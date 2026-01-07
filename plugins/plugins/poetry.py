"""Poetry update plugin.

This plugin updates Poetry itself to the latest version.

Official documentation:
- Poetry: https://python-poetry.org/
- Self update: https://python-poetry.org/docs/cli/#self-update

Update mechanism:
- poetry self update - Updates Poetry to the latest version

Version API:
- PyPI JSON API: https://pypi.org/pypi/poetry/json
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import warnings
from typing import TYPE_CHECKING

import aiohttp

from core.models import UpdateEstimate
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class PoetryPlugin(BasePlugin):
    """Plugin for updating Poetry."""

    # PyPI API URL for Poetry package info
    PYPI_API_URL = "https://pypi.org/pypi/poetry/json"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "poetry"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "poetry"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Poetry dependency manager"

    def is_available(self) -> bool:
        """Check if Poetry is installed."""
        return shutil.which("poetry") is not None

    async def check_available(self) -> bool:
        """Check if Poetry is available for updates."""
        return self.is_available()

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Poetry version.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Version string or None if Poetry is not installed.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "poetry",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Parse version from output like "Poetry (version 1.8.0)"
                output = stdout.decode().strip()
                if "version" in output.lower():
                    # Extract version number
                    parts = output.split()
                    for i, part in enumerate(parts):
                        if part.lower() == "version" and i + 1 < len(parts):
                            version = parts[i + 1].rstrip(")").rstrip(")")
                            return version
                # Alternative format: "Poetry version 1.8.0"
                if output.startswith("Poetry"):
                    parts = output.split()
                    if len(parts) >= 3:
                        return parts[-1].rstrip(")")
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest Poetry version from PyPI.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Latest version string or None if unable to fetch.
        """
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.PYPI_API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                if response.status == 200:
                    data = await response.json()
                    return data.get("info", {}).get("version")
        except (aiohttp.ClientError, TimeoutError, KeyError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Poetry needs to be updated.

        This is the new async API method (Version Checking Protocol).

        Returns:
            True if remote version is newer than local version,
            False if up-to-date, None if unable to determine.
        """
        from core.version import needs_update as version_needs_update

        local = await self.get_installed_version()
        remote = await self.get_available_version()

        if not local or not remote:
            return None

        return version_needs_update(local, remote)

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Estimate download size and time for Poetry update.

        This is the new async API method (Version Checking Protocol).
        Poetry is a Python package, so we fetch size from PyPI.

        Returns:
            UpdateEstimate with download size, or None if no update needed.
        """
        if not await self.needs_update():
            return None

        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        # Try to get package size from PyPI
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.PYPI_API_URL, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                if response.status == 200:
                    data = await response.json()
                    # Get the wheel or sdist size
                    urls = data.get("urls", [])
                    total_size = 0
                    for url_info in urls:
                        if url_info.get("packagetype") == "bdist_wheel":
                            total_size = url_info.get("size", 0)
                            break
                    if total_size == 0:
                        for url_info in urls:
                            if url_info.get("packagetype") == "sdist":
                                total_size = url_info.get("size", 0)
                                break

                    if total_size > 0:
                        # Poetry self-update downloads and installs
                        estimated_seconds = max(30, int(total_size / 500_000))  # ~500KB/s
                        return UpdateEstimate(
                            download_bytes=total_size,
                            package_count=1,
                            packages=[f"poetry-{remote_version}"],
                            estimated_seconds=estimated_seconds,
                            confidence=0.7,
                        )
        except (aiohttp.ClientError, TimeoutError, KeyError):
            pass

        # Return estimate without download size if API request fails
        return UpdateEstimate(
            download_bytes=None,
            package_count=1,
            packages=[f"poetry-{remote_version}"],
            estimated_seconds=60,  # Conservative estimate
            confidence=0.3,
        )

    # Backward compatibility alias (deprecated)
    def get_local_version(self) -> str | None:
        """Get the currently installed Poetry version.

        .. deprecated::
            Use :meth:`get_installed_version` instead.

        Returns:
            Version string or None if Poetry is not installed.
        """
        warnings.warn(
            "get_local_version() is deprecated, use get_installed_version() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["poetry", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output like "Poetry (version 1.8.0)"
                output = result.stdout.strip()
                if "version" in output.lower():
                    # Extract version number
                    parts = output.split()
                    for i, part in enumerate(parts):
                        if part.lower() == "version" and i + 1 < len(parts):
                            version = parts[i + 1].rstrip(")").rstrip(")")
                            return version
                # Alternative format: "Poetry version 1.8.0"
                if output.startswith("Poetry"):
                    parts = output.split()
                    if len(parts) >= 3:
                        return parts[-1].rstrip(")")
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        output_lower = output.lower()

        # Check for successful update
        if "updating" in output_lower and "->" in output:
            return 1

        # Check for already up-to-date
        if "already" in output_lower and "latest" in output_lower:
            return 0

        if "up to date" in output_lower:
            return 0

        # Check for successful update message
        if "updated" in output_lower:
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Poetry update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["poetry", "--version"]
        return ["poetry", "self", "update"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Poetry update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Poetry is installed
        if not self.is_available():
            return "Poetry not installed, skipping update", None

        # Get version using new async API
        local_version = await self.get_installed_version()
        output_lines.append(f"Current Poetry version: {local_version}")
        output_lines.append("Updating Poetry...")

        # Run the update command
        return_code, stdout, stderr = await self._run_command(
            ["poetry", "self", "update"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"Update failed: {stderr}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Poetry update with streaming output.

        Yields:
            StreamEvent objects as the update executes.
        """
        from datetime import UTC, datetime

        from core.models import PluginConfig
        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
        )

        # Check if Poetry is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Poetry not installed, skipping update",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
                packages_updated=0,
            )
            return

        # Get version using new async API
        local_version = await self.get_installed_version()
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Current Poetry version: {local_version}",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Poetry...",
            stream="stdout",
        )

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        async for event in self._run_command_streaming(
            ["poetry", "self", "update"],
            timeout=config.timeout_seconds,
            sudo=False,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
            yield event

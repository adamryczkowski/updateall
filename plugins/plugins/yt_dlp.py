"""yt-dlp update plugin.

This plugin updates yt-dlp video downloader.

yt-dlp is a youtube-dl fork with additional features and more active development.
It is the recommended video downloader as youtube-dl development has slowed.

Official documentation:
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- PyPI: https://pypi.org/project/yt-dlp/

Update mechanism:
- For standalone installations (/usr/local/bin): uses -U flag for self-update
- For pip/pipx installations: uses pip/pipx upgrade
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import TYPE_CHECKING

import aiohttp

from core.models import UpdateEstimate
from core.version import compare_versions
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class YtDlpPlugin(BasePlugin):
    """Plugin for updating yt-dlp."""

    PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "yt-dlp"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "yt-dlp"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update yt-dlp video downloader (youtube-dl fork)"

    def _get_tool_path(self) -> str | None:
        """Get the path to yt-dlp executable.

        Returns:
            Path to yt-dlp or None if not installed.
        """
        return shutil.which("yt-dlp")

    # =========================================================================
    # Version Checking Protocol Implementation
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed yt-dlp version.

        Returns:
            Version string (e.g., "2024.01.01") or None if not installed.
        """
        path = self._get_tool_path()
        if not path:
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Version is typically just the date like "2024.01.01"
                version = stdout.decode().strip().split("\n")[0]
                return version
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available yt-dlp version from PyPI.

        Returns:
            Version string or None if cannot determine.
        """
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.PYPI_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("info", {}).get("version")
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if yt-dlp needs an update.

        Returns:
            True if update available, False if up-to-date, None if cannot determine.
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed and available:
            # yt-dlp versions are date-based (e.g., "2024.01.01")
            # Compare as strings since they're lexicographically ordered
            return compare_versions(installed, available) < 0

        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for yt-dlp update.

        Returns:
            UpdateEstimate or None if no update needed.
        """
        needs = await self.needs_update()
        if not needs:
            return None

        # Try to get package size from PyPI
        download_bytes = 3 * 1024 * 1024  # Default ~3MB

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.PYPI_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    # Get size from the latest wheel
                    urls = data.get("urls", [])
                    for url_info in urls:
                        if url_info.get("packagetype") == "bdist_wheel":
                            size = url_info.get("size", 0)
                            if size > 0:
                                download_bytes = size
                                break
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass

        return UpdateEstimate(
            download_bytes=download_bytes,
            package_count=1,
            packages=["yt-dlp"],
            estimated_seconds=30,  # 30 seconds typical
            confidence=0.8,  # High confidence from PyPI
        )

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    def _get_version(self, tool_path: str) -> str | None:
        """Get the version of yt-dlp (sync version).

        Deprecated: Use get_installed_version() instead.

        Args:
            tool_path: Path to the tool executable.

        Returns:
            Version string or None if unable to determine.
        """
        import subprocess

        try:
            result = subprocess.run(
                [tool_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Version is typically just the date like "2023.03.04"
                version = result.stdout.strip().split("\n")[0]
                return version
        except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
            pass
        return None

    def _is_standalone_install(self, path: str) -> bool:
        """Check if the tool is a standalone installation.

        Standalone installations can self-update with -U flag.
        pip/pipx installations should be updated through those tools.

        Args:
            path: Path to the tool executable.

        Returns:
            True if standalone installation, False otherwise.
        """
        # Resolve symlinks to get the real path
        try:
            real_path = os.path.realpath(path)
        except OSError:
            real_path = path

        # Check if it's in /usr/local/bin (standalone)
        if real_path.startswith("/usr/local/bin/"):
            return True

        # Check if it's NOT in a pip/pipx location
        pip_indicators = [
            ".local/bin",
            "site-packages",
            ".venv",
            "virtualenv",
            "pipx",
        ]

        return not any(indicator in real_path for indicator in pip_indicators)

    def is_available(self) -> bool:
        """Check if yt-dlp is installed."""
        return self._get_tool_path() is not None

    async def check_available(self) -> bool:
        """Check if yt-dlp is available for updates."""
        return self.is_available()

    def get_local_version(self) -> str | None:
        """Get the currently installed version.

        Returns:
            Version string or None if not installed.
        """
        path = self._get_tool_path()
        if path:
            return self._get_version(path)
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated.
        """
        output_lower = output.lower()

        # Check for update indicators
        update_patterns = [
            r"updating to version",
            r"updated successfully",
            r"successfully installed",
            r"upgrading.*->",
            r"updated.*to",
            r"current version",  # yt-dlp shows this when updating
        ]

        for pattern in update_patterns:
            if re.search(pattern, output_lower):
                return 1

        if "yt-dlp" in output_lower and ("update" in output_lower or "updated" in output_lower):
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for yt-dlp update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        path = self._get_tool_path()

        if not path:
            return ["echo", "yt-dlp is not installed"]

        if dry_run:
            return ["yt-dlp", "--version"]

        if self._is_standalone_install(path):
            return ["sudo", "yt-dlp", "-U"]

        return ["pipx", "upgrade", "yt-dlp"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:  # noqa: ARG002
        """Execute the yt-dlp update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []
        path = self._get_tool_path()

        if not path:
            return "yt-dlp is not installed, skipping update", None

        version = self._get_version(path)
        output_lines.append(f"Found yt-dlp at {path}")
        output_lines.append(f"Current version: {version}")

        if self._is_standalone_install(path):
            # Use self-update
            output_lines.append("Updating yt-dlp using self-update...")

            return_code, stdout, stderr = await self._run_command(
                ["yt-dlp", "-U"],
                timeout=120,
                sudo=True,
            )

            if stdout:
                output_lines.append(stdout)
            if stderr:
                output_lines.append(stderr)

            if return_code != 0:
                return "\n".join(output_lines), f"Failed to update yt-dlp: {stderr}"

            # Get new version
            new_version = self._get_version(path)
            if new_version and new_version != version:
                output_lines.append(f"yt-dlp updated: {version} -> {new_version}")
            else:
                output_lines.append("yt-dlp is already up to date")
        else:
            # Try pipx first, then pip
            output_lines.append("Updating yt-dlp using pipx...")

            if shutil.which("pipx"):
                return_code, stdout, stderr = await self._run_command(
                    ["pipx", "upgrade", "yt-dlp"],
                    timeout=120,
                )

                if stdout:
                    output_lines.append(stdout)
                if stderr and return_code != 0:
                    output_lines.append(stderr)

                if return_code == 0:
                    output_lines.append("yt-dlp updated via pipx")
                else:
                    # pipx failed, try pip
                    output_lines.append("pipx failed, trying pip...")
                    return_code, stdout, stderr = await self._run_command(
                        ["python", "-m", "pip", "install", "--upgrade", "yt-dlp"],
                        timeout=120,
                    )

                    if stdout:
                        output_lines.append(stdout)
                    if stderr and return_code != 0:
                        output_lines.append(stderr)

                    if return_code != 0:
                        return "\n".join(output_lines), f"Failed to update yt-dlp: {stderr}"
                    output_lines.append("yt-dlp updated via pip")
            else:
                # No pipx, use pip directly
                return_code, stdout, stderr = await self._run_command(
                    ["python", "-m", "pip", "install", "--upgrade", "yt-dlp"],
                    timeout=120,
                )

                if stdout:
                    output_lines.append(stdout)
                if stderr and return_code != 0:
                    output_lines.append(stderr)

                if return_code != 0:
                    return "\n".join(output_lines), f"Failed to update yt-dlp: {stderr}"
                output_lines.append("yt-dlp updated via pip")

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute yt-dlp update with streaming output.

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

        config = PluginConfig(name=self.name)
        output, error = await self._execute_update(config)

        for line in output.split("\n"):
            if line.strip():
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line,
                    stream="stdout",
                )

        if error:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Error: {error}",
                stream="stderr",
            )

        updated_count = self._count_updated_packages(output)

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=error is None,
            exit_code=0 if error is None else 1,
            packages_updated=updated_count,
        )

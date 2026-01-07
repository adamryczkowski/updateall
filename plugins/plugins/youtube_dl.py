"""YouTube-DL update plugin.

This plugin updates youtube-dl video downloader.

youtube-dl is a command-line program to download videos from YouTube
and other video platforms.

Note: youtube-dl development has slowed significantly. Consider using
yt-dlp instead, which is a more actively maintained fork.

Official documentation:
- youtube-dl: https://github.com/ytdl-org/youtube-dl
- PyPI: https://pypi.org/project/youtube-dl/

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


class YoutubeDlPlugin(BasePlugin):
    """Plugin for updating youtube-dl."""

    PYPI_URL = "https://pypi.org/pypi/youtube-dl/json"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "youtube-dl"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "youtube-dl"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update youtube-dl video downloader"

    def _get_tool_path(self) -> str | None:
        """Get the path to youtube-dl executable.

        Returns:
            Path to youtube-dl or None if not installed.
        """
        return shutil.which("youtube-dl")

    # =========================================================================
    # Version Checking Protocol Implementation
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed youtube-dl version.

        Returns:
            Version string (e.g., "2021.12.17") or None if not installed.
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
                # Version is typically just the date like "2021.12.17"
                version = stdout.decode().strip().split("\n")[0]
                return version
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available youtube-dl version from PyPI.

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
        """Check if youtube-dl needs an update.

        Returns:
            True if update available, False if up-to-date, None if cannot determine.
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed and available:
            # youtube-dl versions are date-based (e.g., "2021.12.17")
            return compare_versions(installed, available) < 0

        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for youtube-dl update.

        Returns:
            UpdateEstimate or None if no update needed.
        """
        needs = await self.needs_update()
        if not needs:
            return None

        # Try to get package size from PyPI
        download_bytes = 2 * 1024 * 1024  # Default ~2MB

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.PYPI_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    # Get size from the latest wheel or tarball
                    urls = data.get("urls", [])
                    for url_info in urls:
                        if url_info.get("packagetype") in ("bdist_wheel", "sdist"):
                            size = url_info.get("size", 0)
                            if size > 0:
                                download_bytes = size
                                break
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass

        return UpdateEstimate(
            download_bytes=download_bytes,
            package_count=1,
            packages=["youtube-dl"],
            estimated_seconds=30,  # 30 seconds typical
            confidence=0.8,  # High confidence from PyPI
        )

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    def _get_version(self, tool_path: str) -> str | None:
        """Get the version of youtube-dl (sync version).

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
        """Check if youtube-dl is installed."""
        return self._get_tool_path() is not None

    async def check_available(self) -> bool:
        """Check if youtube-dl is available for updates."""
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
        ]

        for pattern in update_patterns:
            if re.search(pattern, output_lower):
                return 1

        if "youtube-dl" in output_lower and ("update" in output_lower or "updated" in output_lower):
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for youtube-dl update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        path = self._get_tool_path()

        if not path:
            return ["echo", "youtube-dl is not installed"]

        if dry_run:
            return ["youtube-dl", "--version"]

        if self._is_standalone_install(path):
            return ["sudo", "youtube-dl", "-U"]

        return ["pipx", "upgrade", "youtube-dl"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:  # noqa: ARG002
        """Execute the youtube-dl update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []
        path = self._get_tool_path()

        if not path:
            return "youtube-dl is not installed, skipping update", None

        version = self._get_version(path)
        output_lines.append(f"Found youtube-dl at {path}")
        output_lines.append(f"Current version: {version}")

        if self._is_standalone_install(path):
            # Use self-update
            output_lines.append("Updating youtube-dl using self-update...")

            return_code, stdout, stderr = await self._run_command(
                ["youtube-dl", "-U"],
                timeout=120,
                sudo=True,
            )

            if stdout:
                output_lines.append(stdout)
            if stderr:
                output_lines.append(stderr)

            if return_code != 0:
                return "\n".join(output_lines), f"Failed to update youtube-dl: {stderr}"

            # Get new version
            new_version = self._get_version(path)
            if new_version and new_version != version:
                output_lines.append(f"youtube-dl updated: {version} -> {new_version}")
            else:
                output_lines.append("youtube-dl is already up to date")
        else:
            # Try pipx first, then pip
            output_lines.append("Updating youtube-dl using pipx...")

            if shutil.which("pipx"):
                return_code, stdout, stderr = await self._run_command(
                    ["pipx", "upgrade", "youtube-dl"],
                    timeout=120,
                )

                if stdout:
                    output_lines.append(stdout)
                if stderr and return_code != 0:
                    output_lines.append(stderr)

                if return_code == 0:
                    output_lines.append("youtube-dl updated via pipx")
                else:
                    # pipx failed, try pip
                    output_lines.append("pipx failed, trying pip...")
                    return_code, stdout, stderr = await self._run_command(
                        ["python", "-m", "pip", "install", "--upgrade", "youtube-dl"],
                        timeout=120,
                    )

                    if stdout:
                        output_lines.append(stdout)
                    if stderr and return_code != 0:
                        output_lines.append(stderr)

                    if return_code != 0:
                        return "\n".join(output_lines), f"Failed to update youtube-dl: {stderr}"
                    output_lines.append("youtube-dl updated via pip")
            else:
                # No pipx, use pip directly
                return_code, stdout, stderr = await self._run_command(
                    ["python", "-m", "pip", "install", "--upgrade", "youtube-dl"],
                    timeout=120,
                )

                if stdout:
                    output_lines.append(stdout)
                if stderr and return_code != 0:
                    output_lines.append(stderr)

                if return_code != 0:
                    return "\n".join(output_lines), f"Failed to update youtube-dl: {stderr}"
                output_lines.append("youtube-dl updated via pip")

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute youtube-dl update with streaming output.

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

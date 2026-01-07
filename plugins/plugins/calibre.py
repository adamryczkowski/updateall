"""Calibre e-book management software update plugin.

This plugin uses the Centralized Download Manager API (Proposal 2) for:
- Automatic retry with exponential backoff
- Bandwidth limiting
- Download caching
- Progress reporting

Note: Calibre uses a shell installer script that downloads the actual binary.
The DownloadManager is used to download the installer script with retry logic.

Version API:
- Calibre download page: https://calibre-ebook.com/download_linux
- Version can be extracted from the download page
"""

from __future__ import annotations

import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from core.models import DownloadSpec, UpdateEstimate
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    StreamEvent,
)
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig


class CalibrePlugin(BasePlugin):
    """Plugin for updating Calibre e-book management software.

    Calibre is a free and open source e-book library management application.
    This plugin updates Calibre using the official binary installer from
    calibre-ebook.com.

    The official recommendation is to NOT use distribution packages as they
    are often buggy/outdated. Instead, use the binary installer which includes
    private versions of all dependencies.

    Executes:
    1. Checks current version with `calibre --version`
    2. Downloads and runs the official installer script from
       https://download.calibre-ebook.com/linux-installer.sh

    Note: The installer requires sudo privileges and downloads a large binary
    (~100MB). The installer handles both fresh installs and upgrades.

    Sources:
    - https://calibre-ebook.com/download_linux
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "calibre"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "calibre"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Calibre e-book management software"

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Calibre installer runs a shell script with sudo that installs
        the binary to /opt/calibre. The installer script uses sh.
        """
        return ["/bin/sh"]

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Returns:
            True - Calibre plugin supports separate download (installer script).
        """
        return True

    # Installer script URL
    INSTALLER_URL = "https://download.calibre-ebook.com/linux-installer.sh"
    # Version check URL (download page contains version info)
    VERSION_URL = "https://calibre-ebook.com/download_linux"
    # Approximate download size for Calibre binary (~180MB for Linux x64)
    APPROX_DOWNLOAD_SIZE = 180_000_000

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Calibre version.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Version string or None if not installed.
        """
        return_code, stdout, _ = await self._run_command(
            ["calibre", "--version"],
            timeout=30,
            sudo=False,
        )

        if return_code != 0:
            return None

        # Parse version from output like "calibre (calibre 8.16.2)"
        match = re.search(r"calibre[^\d]*(\d+\.\d+(?:\.\d+)?)", stdout)
        if match:
            return match.group(1)
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest Calibre version from the download page.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Latest version string or None if unable to fetch.
        """
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.VERSION_URL, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                if response.status == 200:
                    html = await response.text()
                    # Look for version in the download page (e.g., calibre-X.Y.Z)
                    match = re.search(r"calibre[- ](\d+\.\d+(?:\.\d+)?)", html, re.IGNORECASE)
                    if match:
                        return match.group(1)
        except (aiohttp.ClientError, TimeoutError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Calibre needs to be updated.

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
        """Estimate download size and time for Calibre update.

        This is the new async API method (Version Checking Protocol).
        Calibre binary is approximately 180MB.

        Returns:
            UpdateEstimate with download size, or None if no update needed.
        """
        if not await self.needs_update():
            return None

        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        # Calibre binary is approximately 180MB
        # Estimate ~3 minutes for download + installation
        return UpdateEstimate(
            download_bytes=self.APPROX_DOWNLOAD_SIZE,
            package_count=1,
            packages=[f"calibre-{remote_version}"],
            estimated_seconds=180,  # 3 minutes
            confidence=0.6,  # Approximate size
        )

    async def get_download_spec(self) -> DownloadSpec | None:
        """Get the download specification for Calibre installer.

        This method uses the Centralized Download Manager API to download
        the installer script with retry logic and progress reporting.

        Returns:
            DownloadSpec for the installer script.
        """
        # Calibre always downloads the installer - it checks for updates internally
        download_path = Path(tempfile.gettempdir()) / "calibre-installer.sh"

        return DownloadSpec(
            url=self.INSTALLER_URL,
            destination=download_path,
            extract=False,  # It's a shell script, not an archive
            timeout_seconds=120,  # 2 minutes for the small installer script
        )

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs the Calibre installer, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that shows current version.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # In dry-run mode, just show current version
            return ["calibre", "--version"]
        # The installer script needs to be downloaded and piped to sh
        # For interactive mode, we use a shell command
        return [
            "sh",
            "-c",
            "wget -nv -O- https://download.calibre-ebook.com/linux-installer.sh | sudo sh /dev/stdin",
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute Calibre update using the official installer.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        output_parts: list[str] = []

        # First, get current version (using new async API)
        current_version = await self.get_installed_version()
        if current_version:
            output_parts.append(f"Current Calibre version: {current_version}")
        else:
            output_parts.append("Calibre not currently installed or version unknown")

        # Download the installer script
        output_parts.append("\n=== Downloading Calibre installer ===")

        # Download installer script
        return_code, stdout, stderr = await self._run_command(
            [
                "wget",
                "-nv",
                "-O",
                "/tmp/calibre-installer.sh",
                "https://download.calibre-ebook.com/linux-installer.sh",
            ],
            timeout=120,  # 2 minutes for download
            sudo=False,
        )

        if return_code != 0:
            output_parts.append(stdout)
            return "\n".join(output_parts), f"Failed to download installer: {stderr}"

        output_parts.append("Installer downloaded successfully")

        # Run the installer with sudo
        output_parts.append("\n=== Running Calibre installer ===")

        return_code, stdout, stderr = await self._run_command(
            ["sh", "/tmp/calibre-installer.sh"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"Calibre installer failed: {stderr}"

        # Get new version (using new async API)
        new_version = await self.get_installed_version()
        if new_version:
            output_parts.append(f"\nNew Calibre version: {new_version}")
            if current_version and current_version != new_version:
                output_parts.append(f"Updated from {current_version} to {new_version}")
            elif current_version == new_version:
                output_parts.append("Already at latest version")

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from Calibre output.

        Calibre is a single application, so we return 1 if an update occurred.

        Args:
            output: Command output.

        Returns:
            1 if Calibre was updated, 0 otherwise.
        """
        # Check for successful update indicators
        if "Updated from" in output:
            return 1
        output_lower = output.lower()
        if "successfully installed" in output_lower:
            return 1
        if "calibre installed" in output_lower:
            return 1
        return 0

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Calibre update with streaming output.

        This method provides real-time output during Calibre update.

        Yields:
            StreamEvent objects as Calibre updates.
        """
        from core.models import PluginConfig

        config = PluginConfig(name=self.name)
        collected_output: list[str] = []

        # Get current version first (using new async API)
        current_version = await self.get_installed_version()
        version_msg = (
            f"Current Calibre version: {current_version}"
            if current_version
            else "Calibre not currently installed or version unknown"
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=version_msg,
            stream="stdout",
        )
        collected_output.append(version_msg)

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== Downloading Calibre installer ===",
            stream="stdout",
        )

        # Download installer
        return_code, _stdout, stderr = await self._run_command(
            [
                "wget",
                "-nv",
                "-O",
                "/tmp/calibre-installer.sh",
                "https://download.calibre-ebook.com/linux-installer.sh",
            ],
            timeout=120,
            sudo=False,
        )

        if return_code != 0:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Download failed: {stderr}",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=return_code,
                packages_updated=0,
                error_message=f"Failed to download installer: {stderr}",
            )
            return

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Installer downloaded successfully",
            stream="stdout",
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== Running Calibre installer ===",
            stream="stdout",
        )

        # Run installer with streaming
        async for event in self._run_command_streaming(
            ["sh", "/tmp/calibre-installer.sh"],
            timeout=config.timeout_seconds,
            sudo=True,
            phase=Phase.EXECUTE,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)

            if isinstance(event, CompletionEvent):
                # Get new version (using new async API)
                new_version = await self.get_installed_version()
                packages_updated = 0

                if new_version:
                    if current_version and current_version != new_version:
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=f"Updated from {current_version} to {new_version}",
                            stream="stdout",
                        )
                        packages_updated = 1
                    elif current_version == new_version:
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line="Already at latest version",
                            stream="stdout",
                        )

                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=event.success,
                    exit_code=event.exit_code,
                    packages_updated=packages_updated,
                    error_message=event.error_message,
                )
                return

            yield event

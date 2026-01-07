"""Waterfox update plugin.

This plugin updates Waterfox browser by downloading from GitHub releases.

Waterfox is a Firefox fork focused on privacy and performance.

Official documentation:
- Waterfox: https://www.waterfox.net/
- GitHub: https://github.com/MrAlex94/Waterfox

Update mechanism:
- Get local version via `waterfox --version`
- Get remote version from GitHub API (MrAlex94/Waterfox releases)
- Download and extract tarball to /opt/waterfox

This plugin uses the Centralized Download Manager API (Proposal 2) for:
- Automatic retry with exponential backoff
- Bandwidth limiting
- Download caching with checksum verification
- Archive extraction (tar.bz2)
- Progress reporting
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from core.models import DownloadSpec, UpdateEstimate
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class WaterfoxPlugin(BasePlugin):
    """Plugin for updating Waterfox browser."""

    GITHUB_API_URL = "https://api.github.com/repos/MrAlex94/Waterfox/releases/latest"
    INSTALL_PATH = "/opt/waterfox"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "waterfox"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "waterfox"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Waterfox browser from GitHub releases"

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        Waterfox installation requires sudo for:
        - rm: Removing old installation from /opt/waterfox
        - mv: Moving new installation to /opt/waterfox
        - chown: Setting ownership to root:root
        """
        return ["/bin/rm", "/bin/mv", "/bin/chown"]

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Returns:
            True - Waterfox plugin supports separate download.
        """
        return True

    # Cache for remote version to avoid multiple API calls
    _cached_remote_version: str | None = None

    def _get_waterfox_path(self) -> str | None:
        """Get the path to the Waterfox executable.

        Returns:
            Path to waterfox executable or None if not found.
        """
        # Check if waterfox is in PATH
        waterfox_path = shutil.which("waterfox")
        if waterfox_path:
            return waterfox_path

        # Check common installation location
        install_path = Path(f"{self.INSTALL_PATH}/waterfox")
        if install_path.is_file():
            return str(install_path)

        return None

    def is_available(self) -> bool:
        """Check if Waterfox is installed."""
        return self._get_waterfox_path() is not None

    async def check_available(self) -> bool:
        """Check if Waterfox is available for updates."""
        return self.is_available()

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Waterfox version.

        Returns:
            Version string or None if Waterfox is not installed.
        """
        waterfox_path = self._get_waterfox_path()
        if not waterfox_path:
            return None

        try:
            result = subprocess.run(
                [waterfox_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Parse version from output like "Mozilla Waterfox 6.0.18"
                output = result.stdout.strip()
                pattern = r"Mozilla Waterfox ([0-9.]+)"
                match = re.search(pattern, output)
                if match:
                    return match.group(1)
                # Fallback: return first line
                if output:
                    return output.split("\n")[0]
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest Waterfox version from GitHub.

        Returns:
            Latest version string or None if unable to fetch.
        """
        try:
            request = urllib.request.Request(
                self.GITHUB_API_URL,
                headers={"User-Agent": "update-all-plugin"},
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode())
                # Cache the response for get_update_estimate
                self._cached_release_data = data
                tag_name = str(data.get("tag_name", ""))
                # Tag format is like "6.0.18-1" or just "6.0.18"
                pattern = r"^([0-9.]+)"
                match = re.match(pattern, tag_name)
                if match:
                    return match.group(1)
                return tag_name if tag_name else None
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, OSError):
            pass
        except Exception:
            # Catch any other unexpected errors
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Waterfox needs an update.

        Returns:
            True if an update is available, False if up-to-date,
            None if cannot determine.
        """
        local_version = await self.get_installed_version()
        remote_version = await self.get_available_version()

        if not local_version or not remote_version:
            return None

        # Use version comparison from core
        from core.version import needs_update as version_needs_update

        return version_needs_update(local_version, remote_version)

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for Waterfox update.

        Returns:
            UpdateEstimate with download size from GitHub API, or None
            if no update is needed or size cannot be determined.
        """
        # Check if update is needed
        if not await self.needs_update():
            return None

        # Try to get size from cached release data
        release_data = getattr(self, "_cached_release_data", None)
        if not release_data:
            # Fetch release data if not cached
            try:
                request = urllib.request.Request(
                    self.GITHUB_API_URL,
                    headers={"User-Agent": "update-all-plugin"},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    release_data = json.loads(response.read().decode())
            except Exception:
                return None

        # Find the Linux tarball asset
        assets = release_data.get("assets", [])
        for asset in assets:
            name = asset.get("name", "").lower()
            if "linux" in name and ("tar.bz2" in name or "tar.gz" in name):
                size = asset.get("size")
                if size:
                    version = await self.get_available_version()
                    return UpdateEstimate(
                        download_bytes=size,
                        package_count=1,
                        packages=[f"waterfox-{version}"] if version else ["waterfox"],
                    )

        return None

    # Backward compatibility aliases
    def get_local_version(self) -> str | None:
        """Deprecated: Use get_installed_version() instead."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self.get_installed_version())

    def get_remote_version(self) -> str | None:
        """Deprecated: Use get_available_version() instead."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(self.get_available_version())

    def _get_download_url(self, version: str) -> str:
        """Get the download URL for a specific version.

        Args:
            version: Version string.

        Returns:
            Download URL for the tarball.
        """
        # Note: The URL format may vary. This is based on the original script.
        return (
            f"https://storage-waterfox.netdna-ssl.com/releases/linux64/installer/"
            f"waterfox-classic-{version}.en-US.linux-x86_64.tar.bz2"
        )

    async def get_download_spec(self) -> DownloadSpec | None:
        """Get the download specification for Waterfox.

        This method uses the Centralized Download Manager API to specify
        the download URL, destination, and extraction settings.

        Returns:
            DownloadSpec with URL and extraction settings, or None if
            no update is needed.
        """
        # Check if update is needed
        if not await self.needs_update():
            return None

        # Get the remote version
        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        # Get download URL
        download_url = self._get_download_url(remote_version)

        # Create a temporary directory for the download
        # The DownloadManager will handle extraction
        download_path = Path(tempfile.gettempdir()) / f"waterfox-{remote_version}.tar.bz2"

        return DownloadSpec(
            url=download_url,
            destination=download_path,
            extract=True,
            extract_format="tar.bz2",
            headers={"User-Agent": "update-all-plugin"},
            timeout_seconds=600,  # 10 minutes for large download
        )

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of packages updated (0 or 1 for Waterfox).
        """
        output_lower = output.lower()

        # Check for successful update indicators
        if any(
            indicator in output_lower
            for indicator in [
                "updated successfully",
                "update complete",
                "installed successfully",
                "extracted to",
                "-> ",  # Version change indicator
            ]
        ):
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Waterfox update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        waterfox_path = self._get_waterfox_path()
        if dry_run:
            if waterfox_path:
                return [waterfox_path, "--version"]
            return ["echo", "Waterfox not installed"]
        # For actual update, we'd need a more complex script
        # Return version check for now
        if waterfox_path:
            return [waterfox_path, "--version"]
        return ["echo", "Waterfox not installed"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:  # noqa: ARG002
        """Execute the Waterfox update.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Waterfox is installed
        waterfox_path = self._get_waterfox_path()
        if not waterfox_path:
            return "Waterfox not installed, skipping update", None

        local_version = await self.get_installed_version()
        output_lines.append(f"Current Waterfox version: {local_version}")

        # Get remote version
        remote_version = await self.get_available_version()
        if not remote_version:
            return "\n".join(output_lines), "Failed to get remote version from GitHub"

        output_lines.append(f"Latest Waterfox version: {remote_version}")

        # Check if update is needed using version comparison
        from core.version import needs_update as version_needs_update

        if not version_needs_update(local_version, remote_version):
            output_lines.append("Waterfox is already up to date")
            return "\n".join(output_lines), None

        output_lines.append(f"Updating Waterfox: {local_version} -> {remote_version}")

        # Download the tarball
        download_url = self._get_download_url(remote_version)
        output_lines.append(f"Downloading from: {download_url}")

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tarball_path = Path(tmpdir) / f"waterfox-{remote_version}.tar.bz2"

                # Download
                request = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": "update-all-plugin"},
                )
                with (
                    urllib.request.urlopen(request, timeout=300) as response,
                    tarball_path.open("wb") as f,
                ):
                    f.write(response.read())

                output_lines.append("Download complete")

                # Extract using tar
                extract_dir = Path(tmpdir) / "extract"
                extract_dir.mkdir()

                return_code, _stdout_tar, stderr = await self._run_command(
                    ["tar", "-xjf", str(tarball_path), "-C", str(extract_dir)],
                    timeout=120,
                )

                if return_code != 0:
                    return "\n".join(output_lines), f"Failed to extract tarball: {stderr}"

                output_lines.append("Extraction complete")

                # Find the extracted directory
                extracted_dirs = list(extract_dir.iterdir())
                if not extracted_dirs:
                    return "\n".join(output_lines), "No directory found after extraction"

                extracted_dir = extracted_dirs[0]

                # Move to installation location (requires sudo)
                output_lines.append(f"Installing to {self.INSTALL_PATH}")

                # Remove old installation
                return_code, _stdout_rm, stderr = await self._run_command(
                    ["rm", "-rf", self.INSTALL_PATH],
                    timeout=30,
                    sudo=True,
                )

                if return_code != 0:
                    output_lines.append(f"Warning: Failed to remove old installation: {stderr}")

                # Move new installation
                return_code, _stdout2, stderr = await self._run_command(
                    ["mv", str(extracted_dir), self.INSTALL_PATH],
                    timeout=30,
                    sudo=True,
                )

                if return_code != 0:
                    return "\n".join(output_lines), f"Failed to install: {stderr}"

                # Set ownership
                return_code, _stdout, stderr = await self._run_command(
                    ["chown", "-R", "root:root", self.INSTALL_PATH],
                    timeout=30,
                    sudo=True,
                )

                if return_code != 0:
                    output_lines.append(f"Warning: Failed to set ownership: {stderr}")

                output_lines.append(
                    f"Waterfox updated successfully: {local_version} -> {remote_version}"
                )

        except urllib.error.URLError as e:
            return "\n".join(output_lines), f"Download failed: {e}"
        except OSError as e:
            return "\n".join(output_lines), f"File operation failed: {e}"

        return "\n".join(output_lines), None

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Waterfox update with streaming output.

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

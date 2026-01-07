"""Go runtime update plugin.

This plugin updates the Go programming language runtime by downloading
the latest release from go.dev.

Official download: https://go.dev/dl/
Version API: https://golang.org/VERSION?m=text

Note: This plugin installs Go to ~/apps/go with version-specific directories.

This plugin uses the Centralized Download Manager API (Proposal 2) for:
- Automatic retry with exponential backoff
- Bandwidth limiting
- Download caching with checksum verification
- Archive extraction (tar.gz)
- Progress reporting
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import tempfile
import urllib.request
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from core.models import DownloadSpec, UpdateEstimate
from core.streaming import CompletionEvent, EventType, OutputEvent
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class GoRuntimePlugin(BasePlugin):
    """Plugin for updating Go programming language runtime."""

    # Default paths
    DEFAULT_APPS_DIR = "~/apps"
    VERSION_URL = "https://golang.org/VERSION?m=text"
    DOWNLOAD_BASE_URL = "https://go.dev/dl"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "go-runtime"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "go"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Go programming language runtime"

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Returns:
            True - Go runtime plugin supports separate download.
        """
        return True

    def is_available(self) -> bool:
        """Check if Go is installed."""
        return shutil.which("go") is not None

    async def check_available(self) -> bool:
        """Check if Go is available for updates."""
        return self.is_available()

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Go version.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Version string (e.g., "go1.21.5") or None if Go is not installed.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "go",
                "version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Output format: "go version go1.21.5 linux/amd64"
                parts = stdout.decode().strip().split()
                if len(parts) >= 3:
                    return parts[2]  # e.g., "go1.21.5"
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest Go version from golang.org.

        This is the new async API method (Version Checking Protocol).

        Returns:
            Latest version string (e.g., "go1.21.5") or None if unable to fetch.
        """
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(self.VERSION_URL, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                if response.status == 200:
                    # Response format: "go1.21.5\ntime ..."
                    content = await response.text()
                    first_line = content.strip().split("\n")[0]
                    return str(first_line)
        except (aiohttp.ClientError, TimeoutError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Go needs to be updated.

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
        """Estimate download size and time for Go update.

        This is the new async API method (Version Checking Protocol).
        Fetches the Content-Length header from the download URL.

        Returns:
            UpdateEstimate with download size, or None if no update needed.
        """
        if not await self.needs_update():
            return None

        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        download_url = self._get_download_url(remote_version)

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.head(download_url, timeout=aiohttp.ClientTimeout(total=30)) as response,
            ):
                if response.status == 200:
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        download_bytes = int(content_length)
                        # Estimate ~60 seconds per 100MB download + extraction
                        estimated_seconds = max(30, int(download_bytes / 1_000_000 * 0.6))
                        return UpdateEstimate(
                            download_bytes=download_bytes,
                            package_count=1,
                            packages=[f"go-{remote_version}"],
                            estimated_seconds=estimated_seconds,
                            confidence=0.8,
                        )
        except (aiohttp.ClientError, TimeoutError):
            pass

        # Return estimate without download size if HEAD request fails
        return UpdateEstimate(
            download_bytes=None,
            package_count=1,
            packages=[f"go-{remote_version}"],
            estimated_seconds=120,  # Conservative estimate
            confidence=0.3,
        )

    # Backward compatibility aliases (deprecated)
    def get_local_version(self) -> str | None:
        """Get the currently installed Go version.

        .. deprecated::
            Use :meth:`get_installed_version` instead.

        Returns:
            Version string (e.g., "go1.21.5") or None if Go is not installed.
        """
        warnings.warn(
            "get_local_version() is deprecated, use get_installed_version() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        import subprocess

        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["go", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Output format: "go version go1.21.5 linux/amd64"
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    return parts[2]  # e.g., "go1.21.5"
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def get_remote_version(self) -> str | None:
        """Get the latest Go version from golang.org.

        .. deprecated::
            Use :meth:`get_available_version` instead.

        Returns:
            Latest version string (e.g., "go1.21.5") or None if unable to fetch.
        """
        warnings.warn(
            "get_remote_version() is deprecated, use get_available_version() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        try:
            with urllib.request.urlopen(self.VERSION_URL, timeout=30) as response:
                # Response format: "go1.21.5\ntime ..."
                content = response.read().decode().strip()
                first_line = content.split("\n")[0]
                return str(first_line)
        except Exception:
            pass
        return None

    def _get_download_url(self, version: str) -> str:
        """Get the download URL for a specific Go version.

        Args:
            version: Go version string (e.g., "go1.21.5").

        Returns:
            Full download URL for the tarball.
        """
        # Detect architecture
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch = "amd64"
        elif machine in ("aarch64", "arm64"):
            arch = "arm64"
        elif machine.startswith("arm"):
            arch = "armv6l"
        else:
            arch = "amd64"  # Default fallback

        filename = f"{version}.linux-{arch}.tar.gz"
        return f"{self.DOWNLOAD_BASE_URL}/{filename}"

    async def get_download_spec(self) -> DownloadSpec | None:
        """Get the download specification for Go runtime.

        This method uses the Centralized Download Manager API to specify
        the download URL, destination, and extraction settings.

        Returns:
            DownloadSpec with URL and extraction settings, or None if
            no update is needed.
        """
        # Check if update is needed (using new async API)
        if not await self.needs_update():
            return None

        # Get the remote version (using new async API)
        remote_version = await self.get_available_version()
        if not remote_version:
            return None

        # Get download URL
        download_url = self._get_download_url(remote_version)

        # Create a temporary directory for the download
        download_path = Path(tempfile.gettempdir()) / f"{remote_version}.linux-amd64.tar.gz"

        return DownloadSpec(
            url=download_url,
            destination=download_path,
            extract=True,
            extract_format="tar.gz",
            timeout_seconds=600,  # 10 minutes for large download
        )

    def _count_updated_packages(self, output: str) -> int:
        """Count updated items from output.

        Args:
            output: Command output to parse.

        Returns:
            Number of items updated.
        """
        output_lower = output.lower()

        # Check for successful Go update
        if "now, local go version is" in output_lower:
            return 1

        # Check for already up-to-date
        if "is up-to-date" in output_lower or "up to date" in output_lower:
            return 0

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Go update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["go", "version"]
        return ["go", "version"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Go runtime update.

        This operation:
        1. Checks if update is needed
        2. Downloads the latest Go tarball
        3. Extracts to ~/apps with version-specific directory
        4. Creates symlink ~/apps/go -> ~/apps/goX.Y.Z

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Check if Go is installed
        if not self.is_available():
            return "Go not installed, skipping update", None

        # Get versions (using new async API)
        local_version = await self.get_installed_version()
        remote_version = await self.get_available_version()

        output_lines.append(f"Local Go version: {local_version}")
        output_lines.append(f"Remote Go version: {remote_version}")

        if not remote_version:
            return "\n".join(output_lines), "Failed to fetch remote version"

        if local_version == remote_version:
            output_lines.append(f"Go is up-to-date ({local_version})")
            return "\n".join(output_lines), None

        output_lines.append(f"Updating Go from {local_version} to {remote_version}...")

        # Build the update script
        apps_dir = str(Path(self.DEFAULT_APPS_DIR).expanduser())
        download_url = self._get_download_url(remote_version)

        # Detect architecture for filename
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch = "amd64"
        elif machine in ("aarch64", "arm64"):
            arch = "arm64"
        elif machine.startswith("arm"):
            arch = "armv6l"
        else:
            arch = "amd64"

        release_file = f"{remote_version}.linux-{arch}.tar.gz"

        update_script = f"""
set -euo pipefail

# Create temp directory
tmp=$(mktemp -d)
cd "$tmp"

# Download Go
echo "Downloading {download_url}..."
curl -OL "{download_url}"

# Prepare apps directory
mkdir -p "{apps_dir}"
rm -f "{apps_dir}/go" 2>/dev/null || true

# Extract
tar -C "{apps_dir}" -xzf "{release_file}"

# Rename and create symlink
mv "{apps_dir}/go" "{apps_dir}/{remote_version}"
ln -sf "{apps_dir}/{remote_version}" "{apps_dir}/go"

# Cleanup
cd /
rm -rf "$tmp"

echo "Now, local Go version is {remote_version}"
"""

        try:
            process = await asyncio.create_subprocess_shell(
                update_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            build_output = stdout.decode() if stdout else ""
            output_lines.append(build_output)

            if process.returncode == 0:
                output_lines.append("Go runtime updated successfully")
                return "\n".join(output_lines), None
            else:
                return "\n".join(output_lines), f"Update failed with exit code {process.returncode}"
        except TimeoutError:
            return "\n".join(output_lines), "Update timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error during update: {e}"

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Go runtime update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Check if Go is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Go not installed, skipping update",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Get versions (using new async API)
        local_version = await self.get_installed_version()
        remote_version = await self.get_available_version()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Local Go version: {local_version}",
            stream="stdout",
        )
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Remote Go version: {remote_version}",
            stream="stdout",
        )

        if not remote_version:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Failed to fetch remote version from golang.org",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message="Failed to fetch remote version",
            )
            return

        if local_version == remote_version:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Go is up-to-date ({local_version})",
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

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Updating Go from {local_version} to {remote_version}...",
            stream="stdout",
        )

        # Build the update script
        apps_dir = str(Path(self.DEFAULT_APPS_DIR).expanduser())
        download_url = self._get_download_url(remote_version)

        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch = "amd64"
        elif machine in ("aarch64", "arm64"):
            arch = "arm64"
        elif machine.startswith("arm"):
            arch = "armv6l"
        else:
            arch = "amd64"

        release_file = f"{remote_version}.linux-{arch}.tar.gz"

        update_script = f"""
set -euo pipefail
tmp=$(mktemp -d)
cd "$tmp"
echo "Downloading {download_url}..."
curl -OL "{download_url}"
mkdir -p "{apps_dir}"
rm -f "{apps_dir}/go" 2>/dev/null || true
tar -C "{apps_dir}" -xzf "{release_file}"
mv "{apps_dir}/go" "{apps_dir}/{remote_version}"
ln -sf "{apps_dir}/{remote_version}" "{apps_dir}/go"
cd /
rm -rf "$tmp"
echo "Now, local Go version is {remote_version}"
"""

        collected_output: list[str] = []

        try:
            process = await asyncio.create_subprocess_shell(
                update_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            if process.stdout:
                async for raw_line in process.stdout:
                    line_str = raw_line.decode().rstrip()
                    collected_output.append(line_str)
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=line_str,
                        stream="stdout",
                    )

            await process.wait()

            full_output = "\n".join(collected_output)
            if process.returncode != 0:
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=False,
                    exit_code=process.returncode or 1,
                    error_message=f"Update failed with exit code {process.returncode}",
                )
            else:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line="Go runtime updated successfully",
                    stream="stdout",
                )
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=True,
                    exit_code=0,
                    packages_updated=self._count_updated_packages(full_output),
                )
        except Exception as e:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Error during update: {e}",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=str(e),
            )

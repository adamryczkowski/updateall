"""Julia runtime update plugin using juliaup.

This plugin updates the Julia programming language runtime using juliaup.
Juliaup is a cross-platform Julia version manager written in Rust.

Official documentation:
- Juliaup: https://github.com/JuliaLang/juliaup
- Julia releases: https://julialang.org/downloads/

Three-phase update mechanism:
- CHECK: juliaup status - Shows installed channels and available updates
- DOWNLOAD: Direct download from julialang.org - Downloads Julia tarball
- EXECUTE: juliaup update - Installs the update (uses cached download if available)

Auto-installation:
- If juliaup is not installed but pipx is available, juliaup will be
  automatically installed via `pipx install juliaup`.
- If neither juliaup nor pipx is available, an error is returned with
  instructions on how to install them.

Note: This plugin should run after the cargo plugin since juliaup can also
be installed via cargo (cargo install juliaup).
"""

from __future__ import annotations

import asyncio
import platform
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

from core.models import DownloadSpec, UpdateEstimate
from core.streaming import CompletionEvent, EventType, OutputEvent, Phase
from core.version import compare_versions
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig
    from core.streaming import StreamEvent


class JuliaRuntimePlugin(BasePlugin):
    """Plugin for updating Julia runtime via juliaup.

    Three-phase execution:
    1. CHECK: juliaup status - detect available updates
    2. DOWNLOAD: Direct download from julialang.org
    3. EXECUTE: juliaup update - install the update

    Auto-installation:
    - If juliaup is missing and pipx is available, installs juliaup via pipx
    - If neither is available, returns an error with installation instructions
    """

    GITHUB_RELEASES_URL = "https://api.github.com/repos/JuliaLang/julia/releases/latest"
    DOWNLOAD_BASE_URL = "https://julialang-s3.julialang.org/bin"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "julia-runtime"

    @property
    def command(self) -> str:
        """Return the update command."""
        return "juliaup"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        return "Update Julia runtime via juliaup"

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Returns:
            True - Julia runtime plugin supports separate download.
        """
        return True

    def is_available(self) -> bool:
        """Check if juliaup is installed."""
        return shutil.which("juliaup") is not None

    def _is_pipx_available(self) -> bool:
        """Check if pipx is installed."""
        return shutil.which("pipx") is not None

    async def _ensure_juliaup_installed(self) -> tuple[bool, str]:
        """Ensure juliaup is installed, installing via pipx if needed.

        Returns:
            Tuple of (success, message).
            - If juliaup is already installed: (True, "juliaup is available")
            - If installed via pipx: (True, "Installed juliaup via pipx")
            - If installation failed: (False, error_message)
        """
        if self.is_available():
            return True, "juliaup is available"

        if not self._is_pipx_available():
            return False, (
                "juliaup is not installed and pipx is not available.\n"
                "Please install juliaup using one of the following methods:\n"
                "  1. Install pipx first: sudo apt install pipx\n"
                "     Then run: pipx install juliaup\n"
                "  2. Install via cargo: cargo install juliaup\n"
                "  3. Install via curl: curl -fsSL https://install.julialang.org | sh\n"
                "For more information, visit: https://github.com/JuliaLang/juliaup"
            )

        # Install juliaup via pipx
        try:
            process = await asyncio.create_subprocess_exec(
                "pipx",
                "install",
                "juliaup",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=120)
            output = stdout.decode() if stdout else ""

            if process.returncode == 0:
                return True, f"Installed juliaup via pipx\n{output}"
            else:
                return False, f"Failed to install juliaup via pipx:\n{output}"
        except TimeoutError:
            return False, "Timeout while installing juliaup via pipx"
        except Exception as e:
            return False, f"Error installing juliaup via pipx: {e}"

    async def check_available(self) -> bool:
        """Check if juliaup is available for updates.

        This method will attempt to install juliaup via pipx if it's not
        already installed.
        """
        success, _ = await self._ensure_juliaup_installed()
        return success

    # =========================================================================
    # Version Checking Protocol Implementation
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Julia version.

        Returns:
            Version string (e.g., "1.10.0") or None if Julia is not installed.
        """
        if not shutil.which("julia"):
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "julia",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Output format: "julia version 1.10.0"
                output = stdout.decode().strip()
                parts = output.split()
                if len(parts) >= 3:
                    return parts[2]  # e.g., "1.10.0"
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available Julia version from GitHub releases.

        Returns:
            Version string or None if cannot determine.
        """
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Accept": "application/vnd.github.v3+json"}
                async with session.get(
                    self.GITHUB_RELEASES_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        tag = data.get("tag_name", "")
                        # Tag format: "v1.10.0"
                        return tag.lstrip("v")
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Julia needs an update.

        Returns:
            True if update available, False if up-to-date, None if cannot determine.
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed and available:
            return compare_versions(installed, available) < 0

        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for Julia update.

        Fetches the Content-Length header from the download URL for accurate size.

        Returns:
            UpdateEstimate or None if no update needed.
        """
        needs = await self.needs_update()
        if not needs:
            return None

        available = await self.get_available_version()
        if not available:
            # Return estimate without download size
            return UpdateEstimate(
                download_bytes=120 * 1024 * 1024,  # ~120MB estimate
                package_count=1,
                packages=["julia"],
                estimated_seconds=90,
                confidence=0.6,
            )

        # Try to get actual download size from HEAD request
        download_url = self._get_download_url(available)
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.head(
                    download_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp,
            ):
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        download_bytes = int(content_length)
                        # Estimate ~60 seconds per 100MB
                        estimated_seconds = max(30, int(download_bytes / 1_000_000 * 0.6))
                        return UpdateEstimate(
                            download_bytes=download_bytes,
                            package_count=1,
                            packages=[f"julia-{available}"],
                            estimated_seconds=estimated_seconds,
                            confidence=0.8,
                        )
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass

        # Fallback estimate
        return UpdateEstimate(
            download_bytes=120 * 1024 * 1024,  # ~120MB estimate
            package_count=1,
            packages=["julia"],
            estimated_seconds=90,
            confidence=0.6,
        )

    # =========================================================================
    # Download URL Construction
    # =========================================================================

    def _get_download_url(self, version: str) -> str:
        """Get the download URL for a specific Julia version.

        Args:
            version: Julia version string (e.g., "1.10.0").

        Returns:
            Full download URL for the tarball.
        """
        # Detect OS
        system = platform.system().lower()
        if system == "darwin":
            os_name = "mac"
        elif system == "linux":
            os_name = "linux"
        elif system == "windows":
            os_name = "winnt"
        else:
            os_name = "linux"  # Default fallback

        # Detect architecture
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch = "x64"
        elif machine in ("aarch64", "arm64"):
            arch = "aarch64"
        elif machine.startswith("arm"):
            arch = "armv7l"
        elif machine in ("i386", "i686"):
            arch = "x86"
        else:
            arch = "x64"  # Default fallback

        # Extract major.minor for URL path
        version_parts = version.split(".")
        if len(version_parts) >= 2:
            major_minor = f"{version_parts[0]}.{version_parts[1]}"
        else:
            major_minor = version

        # Construct filename based on OS
        if os_name == "mac":
            if arch == "aarch64":
                filename = f"julia-{version}-macaarch64.tar.gz"
            else:
                filename = f"julia-{version}-mac64.tar.gz"
        elif os_name == "winnt":
            filename = f"julia-{version}-win64.tar.gz"
        else:
            filename = f"julia-{version}-linux-{arch}.tar.gz"

        return f"{self.DOWNLOAD_BASE_URL}/{os_name}/{arch}/{major_minor}/{filename}"

    # =========================================================================
    # Three-Phase Execution
    # =========================================================================

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        Julia phases:
        - CHECK: juliaup status - shows installed channels and available updates
        - DOWNLOAD: Handled via get_download_spec() for direct download
        - EXECUTE: juliaup update - installs the update

        Args:
            dry_run: If True, return commands that simulate the update.

        Returns:
            Dict mapping Phase to command list.
        """
        if dry_run:
            return {
                Phase.CHECK: ["juliaup", "status"],
            }

        return {
            Phase.CHECK: ["juliaup", "status"],
            # DOWNLOAD phase handled via get_download_spec()
            Phase.EXECUTE: ["juliaup", "update"],
        }

    async def get_download_spec(self) -> DownloadSpec | None:
        """Get the download specification for Julia runtime.

        This method uses the Centralized Download Manager API to specify
        the download URL, destination, and extraction settings.

        Returns:
            DownloadSpec with URL and settings, or None if no update needed.
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
        download_path = Path(tempfile.gettempdir()) / f"julia-{remote_version}.tar.gz"

        # Try to get expected size
        expected_size = None
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.head(
                    download_url,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp,
            ):
                if resp.status == 200:
                    content_length = resp.headers.get("Content-Length")
                    if content_length:
                        expected_size = int(content_length)
        except (TimeoutError, aiohttp.ClientError, OSError):
            pass

        return DownloadSpec(
            url=download_url,
            destination=download_path,
            expected_size=expected_size,
            extract=False,  # Let juliaup handle extraction
            timeout_seconds=600,  # 10 minutes for large download
        )

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Download Julia runtime update.

        This method handles the download phase. If no update is needed,
        it reports success without downloading anything.

        Yields:
            StreamEvent objects with download progress.
        """
        # Check if update is needed
        needs = await self.needs_update()

        if needs is None:
            # Cannot determine if update is needed
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Cannot determine if Julia update is needed",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message="Cannot determine if Julia update is needed",
            )
            return

        if not needs:
            # No update needed
            installed = await self.get_installed_version()
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Julia is up-to-date (version {installed})",
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

        # Get download spec and use the download manager
        spec = await self.get_download_spec()
        if not spec:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Failed to get download specification",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message="Failed to get download specification",
            )
            return

        # Use the download manager for actual download
        from core.download_manager import get_download_manager

        download_manager = get_download_manager()
        async for event in download_manager.download_streaming(spec, plugin_name=self.name):
            yield event

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    def get_local_version(self) -> str | None:
        """Get the currently installed Julia version (sync version).

        Deprecated: Use get_installed_version() instead.

        Returns:
            Version string (e.g., "1.10.0") or None if Julia is not installed.
        """
        import subprocess

        if not shutil.which("julia"):
            return None

        try:
            result = subprocess.run(
                ["julia", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Output format: "julia version 1.10.0"
                parts = result.stdout.strip().split()
                if len(parts) >= 3:
                    return parts[2]  # e.g., "1.10.0"
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated items from juliaup output.

        Args:
            output: Command output to parse.

        Returns:
            Number of items updated.
        """
        output_lower = output.lower()

        # Check for juliaup updates
        count = 0
        if "updated" in output_lower:
            # Count lines with "updated" for juliaup
            for line in output.split("\n"):
                if "updated" in line.lower():
                    count += 1

        return count

    def _parse_status_for_updates(self, output: str) -> list[str]:
        """Parse juliaup status output to find available updates.

        Args:
            output: Output from juliaup status command.

        Returns:
            List of channels with available updates.
        """
        updates = []
        for line in output.split("\n"):
            # Look for "Update to X.Y.Z available" pattern
            if "update" in line.lower() and "available" in line.lower():
                # Extract channel name from the line
                match = re.search(r"^[*\s]*(\S+)", line)
                if match:
                    updates.append(match.group(1))
        return updates

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for Julia runtime update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if dry_run:
            return ["juliaup", "status"]
        return ["juliaup", "update"]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the Julia runtime update via juliaup.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []

        # Ensure juliaup is installed (auto-install via pipx if needed)
        success, message = await self._ensure_juliaup_installed()
        output_lines.append(message)

        if not success:
            return "\n".join(output_lines), message

        local_version = self.get_local_version()
        if local_version:
            output_lines.append(f"Current Julia version: {local_version}")

        output_lines.append("Updating Julia via juliaup...")

        try:
            process = await asyncio.create_subprocess_exec(
                "juliaup",
                "update",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=config.timeout_seconds,
            )
            juliaup_output = stdout.decode() if stdout else ""
            output_lines.append(juliaup_output)

            if process.returncode != 0:
                error_msg = f"juliaup update failed with exit code {process.returncode}"
                output_lines.append(error_msg)
                return "\n".join(output_lines), error_msg

            output_lines.append("Julia runtime updated successfully")
            return "\n".join(output_lines), None

        except TimeoutError:
            return "\n".join(output_lines), "juliaup update timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error running juliaup: {e}"

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute Julia runtime update with streaming output.

        Yields:
            StreamEvent objects from the update process.
        """
        # Ensure juliaup is installed (auto-install via pipx if needed)
        success, message = await self._ensure_juliaup_installed()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=message,
            stream="stdout" if success else "stderr",
        )

        if not success:
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=message,
            )
            return

        local_version = self.get_local_version()
        if local_version:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Current Julia version: {local_version}",
                stream="stdout",
            )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="Updating Julia via juliaup...",
            stream="stdout",
        )

        collected_output: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                "juliaup",
                "update",
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

            if process.returncode != 0:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"juliaup update failed with exit code {process.returncode}",
                    stream="stderr",
                )
                yield CompletionEvent(
                    event_type=EventType.COMPLETION,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    success=False,
                    exit_code=process.returncode or 1,
                )
            else:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line="Julia runtime updated successfully",
                    stream="stdout",
                )
                full_output = "\n".join(collected_output)
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
                line=f"Error running juliaup: {e}",
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

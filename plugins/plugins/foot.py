"""Foot terminal emulator update plugin.

Foot is a fast, lightweight Wayland terminal emulator. This plugin updates
foot using the appropriate method based on how it was installed:

1. Distribution package (apt): Uses apt to update foot
2. Source build (/usr/local): Builds from source from the official Codeberg repository

Official repository: https://codeberg.org/dnkl/foot
ArchWiki: https://wiki.archlinux.org/title/Foot

Detection logic:
- If foot is installed in /usr/bin, it's assumed to be a distribution package
- If foot is installed in /usr/local/bin, it's assumed to be built from source
- Other locations default to source build behavior

Note: Source builds require sudo access for installation to /usr/local.
Build dependencies must be installed separately (meson, ninja, wayland-dev, etc.)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    StreamEvent,
)

from .base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig


class FootPlugin(BasePlugin):
    """Plugin for updating Foot terminal emulator.

    Supports both distribution package updates (apt) and source builds.
    """

    # Default paths for source builds
    DEFAULT_SRC_DIR = "~/src/foot"
    DEFAULT_INSTALL_PREFIX = "/usr/local"
    CODEBERG_API_URL = "https://codeberg.org/api/v1/repos/dnkl/foot/releases?limit=1"
    CODEBERG_REPO_URL = "https://codeberg.org/dnkl/foot.git"

    # Distribution package paths
    DISTRO_BIN_PATH = "/usr/bin/foot"
    SOURCE_BIN_PATH = "/usr/local/bin/foot"

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "foot"

    @property
    def command(self) -> str:
        """Return the update command.

        Note: Foot updates require different methods based on installation type.
        """
        return "foot"

    @property
    def description(self) -> str:
        """Return the plugin description."""
        if self._is_distro_package():
            return "Update Foot terminal emulator via apt"
        return "Update Foot terminal emulator from source (Codeberg)"

    def is_available(self) -> bool:
        """Check if foot is installed."""
        return shutil.which("foot") is not None

    async def check_available(self) -> bool:
        """Check if foot is available for updates."""
        return self.is_available()

    def _get_foot_path(self) -> str | None:
        """Get the full path to the foot binary.

        Returns:
            Full path to foot binary or None if not found.
        """
        return shutil.which("foot")

    def _is_distro_package(self) -> bool:
        """Check if foot is installed via distribution package manager.

        Detection logic:
        - If foot is in /usr/bin, it's a distribution package
        - If foot is in /usr/local/bin, it's a source build
        - Other paths are treated as source builds

        Returns:
            True if foot appears to be installed via apt/distribution package.
        """
        foot_path = self._get_foot_path()
        if not foot_path:
            return False

        # Check if it's in the standard distribution path
        foot_path_obj = Path(foot_path).resolve()

        # Distribution packages install to /usr/bin
        if str(foot_path_obj).startswith("/usr/bin"):
            return True

        # Source builds typically install to /usr/local/bin
        if str(foot_path_obj).startswith("/usr/local"):
            return False

        # Default to source build for other paths
        return False

    def get_local_version(self) -> str | None:
        """Get the currently installed foot version.

        Returns:
            Version string or None if foot is not installed.
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                ["foot", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                # Output format: "foot version: X.Y.Z ..."
                first_line = result.stdout.strip().split("\n")[0]
                if "version:" in first_line.lower():
                    # Extract version number
                    parts = first_line.split(":")
                    if len(parts) >= 2:
                        version_part = parts[1].strip().split()[0]
                        return version_part
                # Fallback: try to extract version from first line
                return first_line.split()[0] if first_line else None
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            pass
        return None

    def get_remote_version(self) -> str | None:
        """Get the latest release version from Codeberg.

        Only used for source builds.

        Returns:
            Latest version tag or None if unable to fetch.
        """
        try:
            with urllib.request.urlopen(self.CODEBERG_API_URL, timeout=30) as response:
                data = json.loads(response.read().decode())
                if data and len(data) > 0:
                    tag_name = data[0].get("tag_name")
                    return str(tag_name) if tag_name else None
        except Exception:
            # Catch all exceptions including URLError, JSONDecodeError, network errors, etc.
            pass
        return None

    def needs_update(self) -> bool:
        """Check if foot needs to be updated.

        For distribution packages, we can't easily check without running apt.
        For source builds, we compare local and remote versions.

        Returns:
            True if remote version is newer than local version.
        """
        if self._is_distro_package():
            # For apt packages, we can't easily determine this
            # Return True to let apt check
            return True

        local = self.get_local_version()
        remote = self.get_remote_version()

        if not local or not remote:
            return False

        # Simple version comparison (assumes semantic versioning)
        return local != remote

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from build output.

        For foot, we count 1 if the update was successful.

        Args:
            output: Command output to parse.

        Returns:
            1 if update successful, 0 if already up-to-date.
        """
        output_lower = output.lower()

        # Check for successful update
        if "updated successfully" in output_lower:
            return 1

        # Check for already up-to-date
        if "is up-to-date" in output_lower or "up to date" in output_lower:
            return 0

        # Check for apt upgrade indicators
        if "0 upgraded" in output_lower:
            return 0
        if "1 upgraded" in output_lower or "upgraded" in output_lower:
            return 1

        # Check for successful build/install
        if "installing" in output_lower and "foot" in output_lower:
            return 1

        return 0

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the interactive command for foot update.

        Args:
            dry_run: If True, only check for updates without applying.

        Returns:
            Command list for interactive execution.
        """
        if self._is_distro_package():
            if dry_run:
                return ["apt", "list", "--upgradable", "foot"]
            return ["sudo", "apt", "update", "&&", "sudo", "apt", "upgrade", "-y", "foot"]

        if dry_run:
            # Just check versions
            return ["bash", "-c", "foot --version && echo 'Checking for updates...'"]
        # For interactive mode, we'd run the full build script
        return ["bash", "-c", "foot --version"]

    @property
    def supports_streaming(self) -> bool:
        """This plugin supports streaming output."""
        return True

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute foot update with streaming output.

        Args:
            dry_run: If True, only check for updates without applying.

        Yields:
            StreamEvent objects with progress and output information.
        """
        import asyncio

        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        # Check if foot is installed
        if not self.is_available():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="foot not installed, skipping update",
                stream="stdout",
            )
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                success=True,
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

        foot_path = self._get_foot_path()
        is_distro = self._is_distro_package()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Foot binary location: {foot_path}",
            stream="stdout",
        )
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Installation type: {'distribution package (apt)' if is_distro else 'source build'}",
            stream="stdout",
        )

        overall_success = True
        packages_updated = 0
        error_message = None

        if is_distro:
            # Use apt for distribution packages
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="\n=== Updating via apt ===",
                stream="stdout",
            )

            local_version = self.get_local_version()
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Current foot version: {local_version}",
                stream="stdout",
            )

            if dry_run:
                # Just check for updates
                return_code, stdout, stderr = await self._run_command(
                    ["apt", "list", "--upgradable", "foot"],
                    timeout=60,
                )
                for line in (stdout + stderr).splitlines():
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=line,
                        stream="stdout",
                    )
            else:
                # Run apt update
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line="\n=== Running apt update ===",
                    stream="stdout",
                )

                return_code, stdout, stderr = await self._run_command(
                    ["apt", "update"],
                    timeout=300,
                    sudo=True,
                )
                for line in (stdout + stderr).splitlines():
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=line,
                        stream="stdout",
                    )

                if return_code != 0:
                    overall_success = False
                    error_message = f"apt update failed: {stderr}"
                else:
                    # Run apt upgrade for foot
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line="\n=== Running apt upgrade foot ===",
                        stream="stdout",
                    )

                    return_code, stdout, stderr = await self._run_command(
                        ["apt", "upgrade", "-y", "foot"],
                        timeout=600,
                        sudo=True,
                    )
                    for line in (stdout + stderr).splitlines():
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=line,
                            stream="stdout",
                        )

                    if return_code != 0:
                        overall_success = False
                        error_message = f"apt upgrade failed: {stderr}"
                    else:
                        new_version = self.get_local_version()
                        yield OutputEvent(
                            event_type=EventType.OUTPUT,
                            plugin_name=self.name,
                            timestamp=datetime.now(tz=UTC),
                            line=f"\nNew foot version: {new_version}",
                            stream="stdout",
                        )

                        if local_version != new_version:
                            packages_updated = 1
                            yield OutputEvent(
                                event_type=EventType.OUTPUT,
                                plugin_name=self.name,
                                timestamp=datetime.now(tz=UTC),
                                line=f"foot updated successfully: {local_version} -> {new_version}",
                                stream="stdout",
                            )
                        else:
                            yield OutputEvent(
                                event_type=EventType.OUTPUT,
                                plugin_name=self.name,
                                timestamp=datetime.now(tz=UTC),
                                line="foot is already up-to-date",
                                stream="stdout",
                            )
        else:
            # Build from source
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="\n=== Updating from source ===",
                stream="stdout",
            )

            local_version = self.get_local_version()
            remote_version = self.get_remote_version()

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Local foot version: {local_version}",
                stream="stdout",
            )
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Remote foot version: {remote_version}",
                stream="stdout",
            )

            if not remote_version:
                overall_success = False
                error_message = "Failed to fetch remote version from Codeberg"
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=error_message,
                    stream="stderr",
                )
            elif local_version == remote_version:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"foot is up-to-date ({local_version})",
                    stream="stdout",
                )
            elif dry_run:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Would update foot from {local_version} to {remote_version}",
                    stream="stdout",
                )
            else:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Updating foot from {local_version} to {remote_version}...",
                    stream="stdout",
                )

                # Build the update script
                src_dir = self.DEFAULT_SRC_DIR.replace("~", "$HOME")
                build_dir = f"{src_dir}/build"

                build_script = f"""
set -euo pipefail
FOOT_SRC_DIR="{src_dir}"
FOOT_BUILD_DIR="{build_dir}"
INSTALL_PREFIX="{self.DEFAULT_INSTALL_PREFIX}"

rm -rf "$FOOT_SRC_DIR"
mkdir -p "$(dirname "$FOOT_SRC_DIR")"
git clone --depth 1 --branch "{remote_version}" {self.CODEBERG_REPO_URL} "$FOOT_SRC_DIR"
cd "$FOOT_SRC_DIR"
git submodule update --init --recursive --depth 1
meson setup "$FOOT_BUILD_DIR" --prefix="$INSTALL_PREFIX" --buildtype=release -Dime=true -Dgrapheme-clustering=enabled
ninja -C "$FOOT_BUILD_DIR"
sudo ninja -C "$FOOT_BUILD_DIR" install
if command -v update-desktop-database >/dev/null; then
    sudo update-desktop-database
fi
echo "foot updated successfully: {local_version} -> {remote_version}"
"""

                try:
                    process = await asyncio.create_subprocess_shell(
                        build_script,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )

                    if process.stdout:
                        async for raw_line in process.stdout:
                            yield OutputEvent(
                                event_type=EventType.OUTPUT,
                                plugin_name=self.name,
                                timestamp=datetime.now(tz=UTC),
                                line=raw_line.decode().rstrip(),
                                stream="stdout",
                            )

                    await process.wait()

                    if process.returncode != 0:
                        overall_success = False
                        error_message = f"Build failed with exit code {process.returncode}"
                    else:
                        packages_updated = 1
                except Exception as e:
                    overall_success = False
                    error_message = f"Error during build: {e}"

        # Emit phase end
        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=overall_success,
            error_message=error_message,
        )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=overall_success,
            exit_code=0 if overall_success else 1,
            packages_updated=packages_updated,
            error_message=error_message,
        )

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the foot update (legacy API).

        Automatically detects whether to use apt or source build based on
        the installation location.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        # Check if foot is installed
        if not self.is_available():
            return "foot not installed, skipping update", None

        # Choose update method based on installation type
        if self._is_distro_package():
            return await self._execute_apt_update(config)
        else:
            return await self._execute_source_update(config)

    async def _execute_apt_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute foot update via apt.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        output_lines: list[str] = []
        output_lines.append("Foot is installed via distribution package (apt)")
        output_lines.append(f"Foot binary location: {self._get_foot_path()}")

        local_version = self.get_local_version()
        output_lines.append(f"Current foot version: {local_version}")

        # Run apt update first
        output_lines.append("\n=== Running apt update ===")
        return_code, stdout, stderr = await self._run_command(
            ["apt", "update"],
            timeout=config.timeout_seconds // 2,
            sudo=True,
        )
        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"apt update failed: {stderr}"

        # Run apt upgrade for foot
        output_lines.append("\n=== Running apt upgrade foot ===")
        return_code, stdout, stderr = await self._run_command(
            ["apt", "upgrade", "-y", "foot"],
            timeout=config.timeout_seconds,
            sudo=True,
        )
        output_lines.append(stdout)

        if return_code != 0:
            return "\n".join(output_lines), f"apt upgrade failed: {stderr}"

        # Check new version
        new_version = self.get_local_version()
        output_lines.append(f"\nNew foot version: {new_version}")

        if local_version != new_version:
            output_lines.append(f"foot updated successfully: {local_version} -> {new_version}")
        else:
            output_lines.append("foot is already up-to-date")

        return "\n".join(output_lines), None

    async def _execute_source_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute foot update by building from source.

        Args:
            config: Plugin configuration with timeout and options.

        Returns:
            Tuple of (output, error_message). error_message is None on success.
        """
        import asyncio

        output_lines: list[str] = []
        output_lines.append("Foot is installed from source")
        output_lines.append(f"Foot binary location: {self._get_foot_path()}")

        # Get versions
        local_version = self.get_local_version()
        remote_version = self.get_remote_version()

        output_lines.append(f"Local foot version: {local_version}")
        output_lines.append(f"Remote foot version: {remote_version}")

        if not remote_version:
            return "\n".join(output_lines), "Failed to fetch remote version"

        if local_version == remote_version:
            output_lines.append(f"foot is up-to-date ({local_version})")
            return "\n".join(output_lines), None

        output_lines.append(f"Updating foot from {local_version} to {remote_version}...")

        # Build commands for the update process
        src_dir = self.DEFAULT_SRC_DIR.replace("~", "$HOME")
        build_dir = f"{src_dir}/build"

        build_script = f"""
set -euo pipefail
FOOT_SRC_DIR="{src_dir}"
FOOT_BUILD_DIR="{build_dir}"
INSTALL_PREFIX="{self.DEFAULT_INSTALL_PREFIX}"

# Remove existing source for fresh clone
rm -rf "$FOOT_SRC_DIR"

# Clone shallow copy of the release tag
mkdir -p "$(dirname "$FOOT_SRC_DIR")"
git clone --depth 1 --branch "{remote_version}" {self.CODEBERG_REPO_URL} "$FOOT_SRC_DIR"
cd "$FOOT_SRC_DIR"

# Update submodules
git submodule update --init --recursive --depth 1

# Configure with meson
meson setup "$FOOT_BUILD_DIR" --prefix="$INSTALL_PREFIX" --buildtype=release -Dime=true -Dgrapheme-clustering=enabled

# Build
ninja -C "$FOOT_BUILD_DIR"

# Install (requires sudo)
sudo ninja -C "$FOOT_BUILD_DIR" install

# Update desktop database
if command -v update-desktop-database >/dev/null; then
    sudo update-desktop-database
fi

echo "foot updated successfully: {local_version} -> {remote_version}"
"""

        try:
            process = await asyncio.create_subprocess_shell(
                build_script,
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
                return "\n".join(output_lines), None
            else:
                return "\n".join(output_lines), f"Build failed with exit code {process.returncode}"
        except TimeoutError:
            return "\n".join(output_lines), "Build timed out"
        except Exception as e:
            return "\n".join(output_lines), f"Error during build: {e}"

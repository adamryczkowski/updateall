"""Rustup (Rust toolchain) manager plugin.

This plugin updates Rust toolchains using rustup.

Official documentation:
- Rustup: https://rust-lang.github.io/rustup/

Update mechanism:
- rustup update - Updates all installed toolchains
- rustup check - Checks for available updates without applying
"""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import TYPE_CHECKING

from core.models import UpdateCommand, UpdateEstimate
from core.version import compare_versions
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class RustupPlugin(BasePlugin):
    """Plugin for Rustup toolchain manager (Rust).

    Executes:
    1. rustup update - update all installed toolchains
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "rustup"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "rustup"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Rust toolchain manager (rustup)"

    def is_available(self) -> bool:
        """Check if rustup is installed."""
        return shutil.which("rustup") is not None

    async def check_available(self) -> bool:
        """Check if rustup is available for updates."""
        return self.is_available()

    # =========================================================================
    # Version Checking Protocol Implementation
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed Rust version.

        Returns:
            Version string (e.g., "1.75.0") or None if not installed.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "rustc",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                # Output format: "rustc 1.75.0 (82e1608df 2023-12-21)"
                output = stdout.decode().strip()
                parts = output.split()
                if len(parts) >= 2:
                    return parts[1]  # e.g., "1.75.0"
        except (TimeoutError, OSError):
            pass
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available Rust version.

        Uses `rustup check` to determine if updates are available.

        Returns:
            Version string or None if cannot determine.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "rustup",
                "check",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode == 0:
                output = stdout.decode()
                # Parse rustup check output for version info (e.g., "1.74.0 -> 1.75.0")
                for line in output.split("\n"):
                    if "stable" in line.lower():
                        # Check for update available
                        if "->" in line:
                            # Extract version after ->
                            match = re.search(r"->\s*(\d+\.\d+\.\d+)", line)
                            if match:
                                return match.group(1)
                        # Check for up to date
                        elif "up to date" in line.lower():
                            match = re.search(r":\s*(\d+\.\d+\.\d+)", line)
                            if match:
                                return match.group(1)
        except (TimeoutError, OSError):
            pass
        return None

    async def needs_update(self) -> bool | None:
        """Check if Rust needs an update.

        Uses `rustup check` to determine if updates are available.

        Returns:
            True if update available, False if up-to-date, None if cannot determine.
        """
        if not self.is_available():
            return None

        try:
            process = await asyncio.create_subprocess_exec(
                "rustup",
                "check",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode == 0:
                output = stdout.decode().lower()
                # Check for "update available" in output
                if "update available" in output:
                    return True
                if "up to date" in output:
                    return False
        except (TimeoutError, OSError):
            pass

        # Fallback to version comparison
        installed = await self.get_installed_version()
        available = await self.get_available_version()
        if installed and available:
            return compare_versions(installed, available) < 0
        return None

    async def get_update_estimate(self) -> UpdateEstimate | None:
        """Get estimated download size for Rust update.

        Rust toolchain updates are typically 200-400MB depending on components.

        Returns:
            UpdateEstimate or None if no update needed.
        """
        needs = await self.needs_update()
        if not needs:
            return None

        # Rust toolchain is typically 200-400MB
        # Estimate based on typical stable toolchain size
        return UpdateEstimate(
            download_bytes=300 * 1024 * 1024,  # ~300MB estimate
            package_count=1,
            packages=["rust-stable"],
            estimated_seconds=120,  # 2 minutes typical
            confidence=0.6,  # Medium confidence - varies by components
        )

    # =========================================================================
    # Declarative Command Execution
    # =========================================================================

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update Rust toolchains.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["rustup", "check"],
                    description="Check for Rust toolchain updates (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["rustup", "update"],
                description="Update Rust toolchains",
                sudo=False,
                success_patterns=("unchanged", "up to date"),
            )
        ]

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute rustup update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["rustup", "update"],
            timeout=config.timeout_seconds,
            sudo=False,  # rustup runs as user
        )

        output = f"=== rustup update ===\n{stdout}"

        if return_code != 0:
            # Check for "already up to date" message
            if "unchanged" in stdout.lower() or "up to date" in stdout.lower():
                return output, None
            return output, f"rustup update failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated toolchains from rustup output.

        Looks for patterns like:
        - "stable-x86_64-unknown-linux-gnu updated"
        - "info: downloading component"
        - Lines with version changes (1.70.0 -> 1.71.0)

        Args:
            output: Command output.

        Returns:
            Number of toolchains/components updated.
        """
        # Count "updated" toolchains
        updated_count = len(re.findall(r"\S+-\S+-\S+-\S+\s+updated", output, re.IGNORECASE))

        if updated_count == 0:
            # Count version change patterns
            updated_count = len(re.findall(r"\d+\.\d+\.\d+\s*->\s*\d+\.\d+\.\d+", output))

        if updated_count == 0:
            # Count "installing component" lines
            updated_count = len(re.findall(r"installing component", output, re.IGNORECASE))

        return updated_count

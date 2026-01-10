"""Cargo (Rust) package manager plugin.

This plugin updates globally installed Rust crates using cargo-update.

Official documentation:
- Cargo: https://doc.rust-lang.org/cargo/
- cargo-update: https://github.com/nabijaczleweli/cargo-update

Prerequisites:
- cargo-update must be installed: cargo install cargo-update

Update mechanism:
- cargo install-update -l: Lists packages with available updates
- cargo install-update -a: Updates all installed crates
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class CargoPlugin(BasePlugin):
    """Plugin for Cargo package manager (Rust).

    Executes:
    1. cargo install-update -a - update all installed crates
       (requires cargo-update: cargo install cargo-update)
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "cargo"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "cargo"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Rust Cargo package manager (requires cargo-update)"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs cargo install-update to update all
        installed crates, showing live output in the terminal.

        Args:
            dry_run: If True, return a command that lists updates without applying.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            return ["cargo", "install-update", "-l"]
        return ["cargo", "install-update", "-a"]

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        Cargo install-update phases:
        - CHECK: List packages with updates available (-l flag)
        - DOWNLOAD: Not supported separately by cargo-update (skipped)
        - EXECUTE: Update all packages (-a flag)

        Args:
            dry_run: If True, return commands that simulate the update.

        Returns:
            Dict mapping Phase to command list.
        """
        if dry_run:
            # In dry-run mode, only show CHECK phase
            return {
                Phase.CHECK: ["cargo", "install-update", "-l"],
            }

        # Normal mode: CHECK to list updates, then EXECUTE to apply them
        # Note: cargo-update doesn't support separate download phase
        return {
            Phase.CHECK: ["cargo", "install-update", "-l"],
            Phase.EXECUTE: ["cargo", "install-update", "-a"],
        }

    async def check_available(self) -> bool:
        """Check if cargo and cargo-update are available."""
        import shutil

        if not shutil.which("cargo"):
            return False

        # Check if cargo-update is installed
        return_code, _stdout, _ = await self._run_command(
            ["cargo", "install-update", "--version"],
            timeout=10,
            sudo=False,
        )
        return return_code == 0

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update Cargo crates.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["cargo", "install-update", "-l"],
                    description="List Cargo crate updates (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["cargo", "install-update", "-a"],
                description="Update all Cargo crates",
                sudo=False,
                success_patterns=("No packages need updating",),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute cargo install-update -a (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["cargo", "install-update", "-a"],
            timeout=config.timeout_seconds,
            sudo=False,  # cargo runs as user
        )

        output = f"=== cargo install-update -a ===\n{stdout}"

        if return_code != 0:
            # Check for "no packages to update" message
            if "No packages need updating" in stdout or "No packages need updating" in stderr:
                return output, None
            return output, f"cargo install-update failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from cargo output.

        Looks for patterns like:
        - "Updating crate-name v1.0.0 -> v1.1.0"
        - "Installing crate-name v1.1.0"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "Updating" lines
        updating_count = len(re.findall(r"Updating\s+\S+", output, re.IGNORECASE))

        if updating_count == 0:
            # Alternative: count "Installing" lines (for fresh installs during update)
            updating_count = len(re.findall(r"Installing\s+\S+", output, re.IGNORECASE))

        return updating_count

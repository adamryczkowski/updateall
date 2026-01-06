"""Cargo (Rust) package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute cargo install-update -a.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["cargo", "install-update", "-a"],
            timeout=config.timeout,
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

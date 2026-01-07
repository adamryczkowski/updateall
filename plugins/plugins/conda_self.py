"""Conda self-update plugin.

This plugin updates conda itself in the base environment.

Uses mamba if available (faster C++ implementation), otherwise falls back to conda.

Sources:
- https://docs.conda.io/projects/conda/en/latest/commands/update.html
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

from core.models import UpdateCommand

from .base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class CondaSelfPlugin(BasePlugin):
    """Plugin for updating conda itself."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "conda-self"

    @property
    def command(self) -> str:
        """Return the primary update command."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    @property
    def description(self) -> str:
        """Return a description of what this plugin updates."""
        return "Updates conda itself in the base environment"

    def is_available(self) -> bool:
        """Check if conda or mamba is available on the system."""
        return shutil.which("conda") is not None or shutil.which("mamba") is not None

    async def check_available(self) -> bool:
        """Check if conda or mamba is available on the system."""
        return self.is_available()

    def _get_package_manager(self) -> str:
        """Get the preferred package manager (mamba or conda)."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update conda itself.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        pkg_manager = self._get_package_manager()

        if dry_run:
            return [
                UpdateCommand(
                    cmd=[pkg_manager, "list", "-n", "base", "conda"],
                    description=f"List conda version (dry run, using {pkg_manager})",
                    sudo=False,
                )
            ]

        return [
            UpdateCommand(
                cmd=[pkg_manager, "update", "conda", "-n", "base", "-y"],
                description=f"Update conda using {pkg_manager}",
                sudo=False,
                success_patterns=(
                    "All requested packages already installed",
                    "# All requested packages already installed",
                ),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the conda self-update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message or None).
        """
        pkg_manager = self._get_package_manager()
        all_output: list[str] = []

        all_output.append(f"Using package manager: {pkg_manager}")
        all_output.append("Updating conda...")

        return_code, stdout, stderr = await self._run_command(
            [pkg_manager, "update", "conda", "-n", "base", "-y"],
            timeout=config.timeout_seconds if config else 300,
        )

        output = stdout + stderr
        all_output.append(output)

        if return_code == 0:
            all_output.append("Conda updated successfully")
            return "\n".join(all_output), None
        else:
            all_output.append("Failed to update conda")
            return "\n".join(all_output), "Failed to update conda"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command for interactive mode."""
        pkg_manager = self._get_package_manager()
        if dry_run:
            return [pkg_manager, "list", "-n", "base", "conda"]
        return [pkg_manager, "update", "conda", "-n", "base"]

    def _count_updated_packages(self, output: str) -> int:
        """Count the number of packages updated from command output."""
        output_lower = output.lower()

        if "all requested packages already installed" in output_lower:
            return 0

        # Count packages being updated
        update_count = len(re.findall(r"updating\s+\w+", output_lower))
        if update_count > 0:
            return update_count

        if "the following packages will be updated:" in output_lower:
            return 1

        return 0

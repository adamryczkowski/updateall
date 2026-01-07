"""Conda-build update plugin.

This plugin updates conda-build in the base environment if installed.

Note: This plugin should run after conda-self to ensure conda is up to date.

Sources:
- https://docs.conda.io/projects/conda-build/en/latest/
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING

from core.models import UpdateCommand

from .base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class CondaBuildPlugin(BasePlugin):
    """Plugin for updating conda-build."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "conda-build"

    @property
    def command(self) -> str:
        """Return the primary update command."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    @property
    def description(self) -> str:
        """Return a description of what this plugin updates."""
        return "Updates conda-build in the base environment"

    def is_available(self) -> bool:
        """Check if conda-build is installed."""
        if not (shutil.which("conda") or shutil.which("mamba")):
            return False
        # Check if conda-build is installed
        return self._check_conda_build_installed_sync()

    def _check_conda_build_installed_sync(self) -> bool:
        """Synchronously check if conda-build is installed."""
        try:
            result = subprocess.run(
                ["conda", "list", "-n", "base", "conda-build", "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                return len(packages) > 0
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
        return False

    async def check_available(self) -> bool:
        """Check if conda-build is installed."""
        return self.is_available()

    def _get_package_manager(self) -> str:
        """Get the preferred package manager (mamba or conda)."""
        if shutil.which("mamba"):
            return "mamba"
        return "conda"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update conda-build.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        pkg_manager = self._get_package_manager()

        if dry_run:
            return [
                UpdateCommand(
                    cmd=[pkg_manager, "list", "-n", "base", "conda-build"],
                    description=f"List conda-build version (dry run, using {pkg_manager})",
                    sudo=False,
                )
            ]

        return [
            UpdateCommand(
                cmd=[pkg_manager, "update", "conda-build", "-n", "base", "-y"],
                description=f"Update conda-build using {pkg_manager}",
                sudo=False,
                success_patterns=(
                    "All requested packages already installed",
                    "# All requested packages already installed",
                ),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the conda-build update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message or None).
        """
        pkg_manager = self._get_package_manager()
        all_output: list[str] = []

        # First check if conda-build is installed
        if not await self.check_available():
            return "conda-build not installed, skipping", None

        all_output.append(f"Using package manager: {pkg_manager}")
        all_output.append("Updating conda-build...")

        return_code, stdout, stderr = await self._run_command(
            [pkg_manager, "update", "conda-build", "-n", "base", "-y"],
            timeout=config.timeout_seconds if config else 300,
        )

        output = stdout + stderr
        all_output.append(output)

        if return_code == 0:
            all_output.append("conda-build updated successfully")
            return "\n".join(all_output), None
        else:
            all_output.append("Failed to update conda-build")
            return "\n".join(all_output), "Failed to update conda-build"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command for interactive mode."""
        pkg_manager = self._get_package_manager()
        if dry_run:
            return [pkg_manager, "list", "-n", "base", "conda-build"]
        return [pkg_manager, "update", "conda-build", "-n", "base"]

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

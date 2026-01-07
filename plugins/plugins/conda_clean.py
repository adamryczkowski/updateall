"""Conda cache cleanup plugin.

This plugin cleans conda cache to free disk space.

Removes:
- Index cache
- Lock files
- Unused cache packages
- Tarballs
- Logfiles

Note: This plugin should run after conda-packages to clean up after updates.

Sources:
- https://docs.conda.io/projects/conda/en/latest/commands/clean.html
"""

from __future__ import annotations

import re
import shutil
from typing import TYPE_CHECKING

from core.models import UpdateCommand

from .base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class CondaCleanPlugin(BasePlugin):
    """Plugin for cleaning conda cache."""

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "conda-clean"

    @property
    def command(self) -> str:
        """Return the primary command."""
        return "conda"

    @property
    def description(self) -> str:
        """Return a description of what this plugin does."""
        return "Cleans conda cache to free disk space"

    def is_available(self) -> bool:
        """Check if conda is available on the system."""
        return shutil.which("conda") is not None

    async def check_available(self) -> bool:
        """Check if conda is available on the system."""
        return self.is_available()

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to clean conda cache.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["conda", "clean", "--all", "--dry-run"],
                    description="Show what would be cleaned (dry run)",
                    sudo=False,
                )
            ]

        return [
            UpdateCommand(
                cmd=["conda", "clean", "--all", "-y"],
                description="Clean conda cache",
                sudo=False,
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute the conda cache cleanup (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message or None).
        """
        all_output: list[str] = []

        all_output.append("Cleaning conda cache...")

        return_code, stdout, stderr = await self._run_command(
            ["conda", "clean", "--all", "-y"],
            timeout=config.timeout_seconds if config else 300,
        )

        output = stdout + stderr
        all_output.append(output)

        if return_code == 0:
            all_output.append("Conda cache cleaned successfully")
            return "\n".join(all_output), None
        else:
            all_output.append("Failed to clean conda cache")
            return "\n".join(all_output), "Failed to clean conda cache"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command for interactive mode."""
        if dry_run:
            return ["conda", "clean", "--all", "--dry-run"]
        return ["conda", "clean", "--all"]

    def _count_updated_packages(self, output: str) -> int:
        """Count the number of items cleaned from command output."""
        # Cleanup doesn't update packages, but we can count removed items
        count = 0
        count += len(re.findall(r"removed\s+\d+", output.lower()))
        count += len(re.findall(r"removing\s+", output.lower()))

        return count

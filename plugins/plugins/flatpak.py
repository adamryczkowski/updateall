"""Flatpak package manager plugin.

This plugin updates Flatpak applications installed on the system.

Official documentation:
- Flatpak: https://flatpak.org/
- flatpak command: https://docs.flatpak.org/en/latest/flatpak-command-reference.html

Update mechanism:
- flatpak update -y: Updates all installed applications and runtimes

Note: Flatpak can run as a regular user (no sudo required).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class FlatpakPlugin(BasePlugin):
    """Plugin for Flatpak application manager.

    Executes:
    1. flatpak update -y - update all installed applications
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "flatpak"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "flatpak"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Flatpak application manager"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs flatpak update, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # Show what would be updated without actually updating
            return ["flatpak", "update", "--no-deploy"]
        return ["flatpak", "update", "-y"]

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update Flatpak applications.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["flatpak", "update", "--no-deploy"],
                    description="Check for Flatpak updates (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["flatpak", "update", "-y", "--noninteractive"],
                description="Update all Flatpak applications",
                sudo=False,
                success_patterns=("Nothing to do",),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute flatpak update (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["flatpak", "update", "-y", "--noninteractive"],
            timeout=config.timeout_seconds,
            sudo=False,  # flatpak can run as user
        )

        output = f"=== flatpak update ===\n{stdout}"

        if return_code != 0:
            # Check for common non-error conditions
            if "Nothing to do" in stdout or "Nothing to do" in stderr:
                return output, None
            return output, f"flatpak update failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from flatpak output.

        Looks for patterns like:
        - "Updating app/org.example.App"
        - Lines with version changes

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "Updating" lines
        updating_count = len(re.findall(r"^Updating\s+", output, re.MULTILINE))

        if updating_count == 0:
            # Alternative: count lines with arrow indicating version change
            updating_count = len(re.findall(r"→", output))

        return updating_count

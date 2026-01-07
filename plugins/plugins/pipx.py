"""Pipx package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class PipxPlugin(BasePlugin):
    """Plugin for pipx Python application manager.

    Executes:
    1. pipx upgrade-all - upgrade all installed applications
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "pipx"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "pipx"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Python application installer (pipx)"

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a command that runs pipx upgrade-all, showing live output
        in the terminal.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            # pipx doesn't have a native dry-run, so just list packages
            return ["pipx", "list"]
        return ["pipx", "upgrade-all"]

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to upgrade pipx applications.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["pipx", "list"],
                    description="List installed applications (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["pipx", "upgrade-all"],
                description="Upgrade all pipx applications",
                sudo=False,
                success_patterns=("No packages to upgrade", "already at latest"),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute pipx upgrade-all (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,  # pipx runs as user
        )

        output = f"=== pipx upgrade-all ===\n{stdout}"

        if return_code != 0:
            # pipx returns non-zero if nothing to upgrade, check stderr
            if "No packages to upgrade" in stderr or "already at latest" in stdout:
                return output, None
            return output, f"pipx upgrade-all failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from pipx output.

        Looks for patterns like:
        - "upgraded package-name from X to Y"
        - "Package 'name' upgraded"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "upgraded" mentions
        upgraded_count = len(re.findall(r"upgraded\s+\S+\s+from", output, re.IGNORECASE))

        if upgraded_count == 0:
            # Alternative pattern
            upgraded_count = len(re.findall(r"Package\s+'\S+'\s+upgraded", output, re.IGNORECASE))

        return upgraded_count

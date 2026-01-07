"""Snap package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class SnapPlugin(BasePlugin):
    """Plugin for Snap package manager (Ubuntu/Canonical).

    Executes:
    1. sudo snap refresh - refresh all snaps
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "snap"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "snap"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Canonical Snap package manager"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to refresh snaps.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["snap", "refresh", "--list"],
                    description="List available snap updates (dry run)",
                    sudo=False,
                )
            ]
        return [
            UpdateCommand(
                cmd=["snap", "refresh"],
                description="Refresh all snaps",
                sudo=True,
                success_patterns=("All snaps up to date",),
            )
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute snap refresh (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["snap", "refresh"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output = f"=== snap refresh ===\n{stdout}"

        if return_code != 0:
            # snap returns non-zero if nothing to refresh
            if "All snaps up to date" in stdout or "All snaps up to date" in stderr:
                return output, None
            return output, f"snap refresh failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from snap output.

        Looks for patterns like:
        - "name X refreshed"
        - Lines with version changes

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Count "refreshed" mentions
        refreshed_count = len(re.findall(r"\S+\s+\S+\s+refreshed", output, re.IGNORECASE))

        if refreshed_count == 0:
            # Alternative: count lines with arrow indicating version change
            refreshed_count = len(re.findall(r"→|->", output))

        return refreshed_count

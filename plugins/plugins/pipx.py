"""Pipx package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

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

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute pipx upgrade-all.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        return_code, stdout, stderr = await self._run_command(
            ["pipx", "upgrade-all"],
            timeout=config.timeout,
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

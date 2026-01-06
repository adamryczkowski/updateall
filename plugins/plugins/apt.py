"""APT package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class AptPlugin(BasePlugin):
    """Plugin for APT package manager (Debian/Ubuntu).

    Executes:
    1. sudo apt update - refresh package lists
    2. sudo apt upgrade -y - upgrade all packages
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "apt"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "apt"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Debian/Ubuntu APT package manager"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute apt update and upgrade.

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        output_parts: list[str] = []

        # Step 1: apt update
        return_code, stdout, stderr = await self._run_command(
            ["apt", "update"],
            timeout=config.timeout_seconds // 2,  # Use half timeout for update
            sudo=True,
        )

        output_parts.append("=== apt update ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"apt update failed: {stderr}"

        # Step 2: apt upgrade
        return_code, stdout, stderr = await self._run_command(
            ["apt", "upgrade", "-y"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output_parts.append("\n=== apt upgrade ===")
        output_parts.append(stdout)

        if return_code != 0:
            return "\n".join(output_parts), f"apt upgrade failed: {stderr}"

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from apt output.

        Looks for patterns like:
        - "X upgraded, Y newly installed"
        - "Unpacking package-name"

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Try to find the summary line
        match = re.search(r"(\d+)\s+upgraded", output)
        if match:
            return int(match.group(1))

        # Fallback: count "Unpacking" lines
        unpacking_count = len(re.findall(r"^Unpacking\s+", output, re.MULTILINE))
        return unpacking_count

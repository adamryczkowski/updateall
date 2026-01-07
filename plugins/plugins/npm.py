"""NPM (Node.js) package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class NpmPlugin(BasePlugin):
    """Plugin for NPM package manager (Node.js global packages).

    Executes:
    1. npm outdated -g - check for outdated packages
    2. npm update -g - update all globally installed packages
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "npm"

    @property
    def command(self) -> str:
        """Return the main command."""
        return "npm"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Node.js NPM global package manager"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update NPM global packages.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["npm", "outdated", "-g"],
                    description="List outdated global packages (dry run)",
                    sudo=False,
                    # npm outdated returns exit code 1 if packages are outdated
                    ignore_exit_codes=(1,),
                )
            ]
        return [
            UpdateCommand(
                cmd=["npm", "outdated", "-g", "--json"],
                description="Check for outdated packages",
                sudo=False,
                step_number=1,
                total_steps=2,
                timeout_seconds=75,  # Quarter of default 300s
                # npm outdated returns exit code 1 if packages are outdated
                ignore_exit_codes=(1,),
            ),
            UpdateCommand(
                cmd=["npm", "update", "-g"],
                description="Update global packages",
                sudo=False,
                step_number=2,
                total_steps=2,
            ),
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute npm update -g (legacy API).

        Args:
            config: Plugin configuration.

        Returns:
            Tuple of (output, error_message).
        """
        # First, check for outdated packages
        return_code, stdout_outdated, _ = await self._run_command(
            ["npm", "outdated", "-g", "--json"],
            timeout=config.timeout_seconds // 4,
            sudo=False,
        )

        output_parts = [f"=== npm outdated -g ===\n{stdout_outdated}"]

        # Run the update
        return_code, stdout, stderr = await self._run_command(
            ["npm", "update", "-g"],
            timeout=config.timeout_seconds,
            sudo=False,  # npm global can be user-owned with nvm/fnm
        )

        output_parts.append(f"\n=== npm update -g ===\n{stdout}")
        output = "\n".join(output_parts)

        if return_code != 0:
            # npm update can fail for various reasons
            if "npm WARN" in stderr and "npm ERR!" not in stderr:
                # Just warnings, not errors
                return output, None
            return output, f"npm update -g failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from npm output.

        Looks for patterns like:
        - "added X packages"
        - "updated X packages"
        - Package names with version changes

        Args:
            output: Command output.

        Returns:
            Number of packages updated.
        """
        # Look for "updated X packages" pattern
        match = re.search(r"updated\s+(\d+)\s+package", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

        # Look for "added X packages" pattern
        match = re.search(r"added\s+(\d+)\s+package", output, re.IGNORECASE)
        if match:
            return int(match.group(1))

        # Count individual package update lines
        update_count = len(re.findall(r"→|->|\+\s+\S+@\d", output))
        return update_count

"""APT package manager plugin."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.models import UpdateCommand
from core.mutex import StandardMutexes
from core.streaming import Phase
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

    @property
    def sudo_commands(self) -> list[str]:
        """Return list of commands that require sudo.

        APT requires sudo for both update and upgrade operations.
        """
        return ["/usr/bin/apt"]

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Return mutexes required for each execution phase.

        APT requires exclusive access to APT and DPKG locks during
        both CHECK and EXECUTE phases to prevent conflicts with
        other package managers.
        """
        return {
            Phase.CHECK: [StandardMutexes.APT_LOCK, StandardMutexes.DPKG_LOCK],
            Phase.EXECUTE: [StandardMutexes.APT_LOCK, StandardMutexes.DPKG_LOCK],
        }

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a bash command that runs apt update followed by apt upgrade,
        showing live output in the terminal.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        if dry_run:
            return [
                "/bin/bash",
                "-c",
                "sudo apt update && sudo apt upgrade --dry-run",
            ]
        return [
            "/bin/bash",
            "-c",
            "sudo apt update && sudo apt upgrade -y",
        ]

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        APT phases:
        - CHECK: Update package lists (apt update)
        - DOWNLOAD: Download packages without installing (apt upgrade --download-only)
        - EXECUTE: Install downloaded packages (apt upgrade -y)

        Args:
            dry_run: If True, return commands that simulate the update.

        Returns:
            Dict mapping Phase to command list.
        """
        if dry_run:
            return {
                Phase.CHECK: ["sudo", "apt", "update"],
                Phase.EXECUTE: ["sudo", "apt", "upgrade", "--dry-run"],
            }

        return {
            Phase.CHECK: ["sudo", "apt", "update"],
            Phase.DOWNLOAD: ["sudo", "apt", "upgrade", "--download-only", "-y"],
            Phase.EXECUTE: ["sudo", "apt", "upgrade", "-y"],
        }

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Get commands to update APT packages.

        Args:
            dry_run: If True, return dry-run commands.

        Returns:
            List of UpdateCommand objects.
        """
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["apt", "update"],
                    description="Update package lists",
                    sudo=True,
                    step_number=1,
                    total_steps=2,
                ),
                UpdateCommand(
                    cmd=["apt", "upgrade", "--dry-run"],
                    description="Show available upgrades (dry run)",
                    sudo=True,
                    step_number=2,
                    total_steps=2,
                ),
            ]
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                description="Update package lists",
                sudo=True,
                step_number=1,
                total_steps=2,
                timeout_seconds=150,  # Half of default 300s
            ),
            UpdateCommand(
                cmd=["apt", "upgrade", "-y"],
                description="Upgrade packages",
                sudo=True,
                step_number=2,
                total_steps=2,
            ),
        ]

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute apt update and upgrade (legacy API).

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

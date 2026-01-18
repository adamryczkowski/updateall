"""APT package manager plugin.

This plugin updates system packages using APT (Advanced Package Tool)
on Debian-based distributions (Debian, Ubuntu, Linux Mint, etc.).

Official documentation:
- APT: https://wiki.debian.org/Apt
- apt command: https://manpages.debian.org/apt
- apt-get man page: https://manpages.debian.org/bookworm/apt/apt-get.8.en.html

Three-phase update mechanism:
- CHECK: apt update - Refreshes package lists from repositories
- DOWNLOAD: apt upgrade --download-only - Downloads packages to /var/cache/apt/archives/
- EXECUTE: apt upgrade --no-download --ignore-missing - Installs only cached packages

Key options (from apt-get man page):
- --download-only (-d): Download only; package files are only retrieved, not unpacked or installed
- --no-download: Disables downloading of packages, uses only cached .deb files
- --ignore-missing (-m): If packages cannot be retrieved, hold them back and continue

Note: Requires sudo privileges for all operations.
"""

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

    Three-phase execution:
    1. CHECK: sudo apt update - refresh package lists
    2. DOWNLOAD: sudo apt upgrade --download-only -y - download packages to cache
    3. EXECUTE: sudo apt upgrade --no-download --ignore-missing -y - install cached packages

    The download size can be obtained by running apt upgrade --dry-run after apt update
    and parsing the "Need to get X MB of archives" line from the output.
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
        CHECK, DOWNLOAD, and EXECUTE phases to prevent conflicts with
        other package managers.
        """
        return {
            Phase.CHECK: [StandardMutexes.APT_LOCK, StandardMutexes.DPKG_LOCK],
            Phase.DOWNLOAD: [StandardMutexes.APT_LOCK, StandardMutexes.DPKG_LOCK],
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
        - DOWNLOAD: Download packages without installing (apt upgrade --download-only -y)
        - EXECUTE: Install only cached packages (apt upgrade --no-download --ignore-missing -y)

        The --no-download flag ensures APT uses only already-downloaded .deb files.
        The --ignore-missing flag allows APT to continue if some packages are missing.

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
            Phase.EXECUTE: [
                "sudo",
                "apt",
                "upgrade",
                "--no-download",
                "--ignore-missing",
                "-y",
            ],
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

    def parse_upgrade_info(self, output: str) -> dict[str, int]:
        """Parse apt upgrade --dry-run output for upgrade information.

        Extracts:
        - Number of packages to upgrade
        - Total download size in bytes
        - Disk space change in bytes

        The output typically contains lines like:
        - "X upgraded, Y newly installed, Z to remove and W not upgraded."
        - "Need to get 45.3 MB of archives."
        - "After this operation, 12.5 MB of additional disk space will be used."

        Args:
            output: Output from apt upgrade --dry-run command.

        Returns:
            Dict with keys: packages_to_upgrade, download_size_bytes, disk_space_change_bytes
        """
        info: dict[str, int] = {
            "packages_to_upgrade": 0,
            "download_size_bytes": 0,
            "disk_space_change_bytes": 0,
        }

        # Match "X upgraded"
        match = re.search(r"(\d+)\s+upgraded", output)
        if match:
            info["packages_to_upgrade"] = int(match.group(1))

        # Match "Need to get X MB of archives" or "Need to get X kB of archives"
        match = re.search(r"Need to get ([\d.,]+)\s*([kKMGT]?B)", output)
        if match:
            size_str = match.group(1).replace(",", ".")
            size = float(size_str)
            unit = match.group(2).upper()
            # APT uses kB (1000 bytes), not KiB (1024 bytes)
            multipliers = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
            info["download_size_bytes"] = int(size * multipliers.get(unit, 1))

        # Match "After this operation, X MB of additional disk space will be used"
        # or "After this operation, X MB disk space will be freed"
        match = re.search(
            r"After this operation,\s*([\d.,]+)\s*([kKMGT]?B).*(?:will be used|will be freed)",
            output,
        )
        if match:
            size_str = match.group(1).replace(",", ".")
            size = float(size_str)
            unit = match.group(2).upper()
            multipliers = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
            disk_change = int(size * multipliers.get(unit, 1))
            # If "freed", make it negative
            if "freed" in output[match.start() : match.end()]:
                disk_change = -disk_change
            info["disk_space_change_bytes"] = disk_change

        return info

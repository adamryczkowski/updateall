"""Mock Alpha plugin for debugging the interactive tabbed UI.

This plugin simulates a long-running update task with three phases:
- CHECK: Simulates checking for updates (light CPU, minimal download)
- DOWNLOAD: Simulates downloading packages (heavy download, light CPU)
- EXECUTE: Simulates installing packages (heavy CPU, minimal download)

Each phase reports download and CPU statistics for testing the stats system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MockAlphaPlugin(BasePlugin):
    """Mock Alpha plugin for debugging interactive mode.

    Simulates a multi-phase update with download and CPU load simulation.
    Uses ASCII art and distinctive markers to make output easily identifiable.
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "mock-alpha"

    @property
    def command(self) -> str:
        """Return the main command (always available for mock)."""
        return "bash"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Mock Alpha - Multi-phase simulated update with stats (debugging)"

    async def check_available(self) -> bool:
        """Mock is always available."""
        return True

    def _build_check_script(self, dry_run: bool = False) -> str:
        """Build the CHECK phase script.

        Simulates checking for updates with light CPU and minimal download.
        Reports estimated download/CPU for subsequent phases.
        """
        iterations = 2 if dry_run else 4
        sleep_time = 1 if dry_run else 2

        return f"""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           MOCK ALPHA - CHECK PHASE (Update)                      ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 [ALPHA] Checking for available updates..."
echo ""

# Simulate light CPU load (checking package metadata)
for i in $(seq 1 {iterations}); do
    echo "  📋 [ALPHA] Scanning repository $i of {iterations}..."

    # Light CPU: simple loop
    for j in $(seq 1 50000); do : ; done

    # Minimal download simulation (reading small amount of data)
    dd if=/dev/zero of=/dev/null bs=1K count=100 2>/dev/null

    sleep {sleep_time}
done

echo ""
echo "┌────────────────────────────────────────────────────────────────┐"
echo "│ 🔷 [ALPHA] CHECK PHASE COMPLETE                                │"
echo "├────────────────────────────────────────────────────────────────┤"
echo "│ Found 12 packages to update                                    │"
echo "│                                                                │"
echo "│ 📊 ESTIMATED RESOURCES FOR REMAINING PHASES:                   │"
echo "│   DOWNLOAD phase: ~50 MB download, ~5% CPU                     │"
echo "│   UPGRADE phase:  ~2 MB download, ~80% CPU for 30s             │"
echo "│                                                                │"
echo "│ Total estimated: 52 MB download, 35s CPU time                  │"
echo "└────────────────────────────────────────────────────────────────┘"
echo ""
"""

    def _build_download_script(self, dry_run: bool = False) -> str:
        """Build the DOWNLOAD phase script.

        Simulates downloading packages with heavy download and light CPU.
        """
        iterations = 2 if dry_run else 5
        sleep_time = 1 if dry_run else 2
        download_size = "1M" if dry_run else "10M"

        return f"""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           MOCK ALPHA - DOWNLOAD PHASE                            ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 [ALPHA] Downloading packages..."
echo ""

total_downloaded=0

for i in $(seq 1 {iterations}); do
    progress=$((i * 100 / {iterations}))
    pkg_size=$((i * 10))
    total_downloaded=$((total_downloaded + pkg_size))

    echo "┌────────────────────────────────────────────────────────────────┐"
    echo "│ 📥 [ALPHA] Downloading package $i of {iterations} (${{pkg_size}} MB)"
    echo "│ Progress: [$progress%] Total: ${{total_downloaded}} MB"
    echo "└────────────────────────────────────────────────────────────────┘"

    # Heavy download simulation (reading larger amount of data)
    dd if=/dev/zero of=/dev/null bs={download_size} count=1 2>/dev/null

    # Light CPU during download
    for j in $(seq 1 10000); do : ; done

    sleep {sleep_time}
done

echo ""
echo "┌────────────────────────────────────────────────────────────────┐"
echo "│ 🔷 [ALPHA] DOWNLOAD PHASE COMPLETE                             │"
echo "├────────────────────────────────────────────────────────────────┤"
echo "│ Downloaded: ${{total_downloaded}} MB                           │"
echo "│ Packages ready for installation: {iterations}                  │"
echo "└────────────────────────────────────────────────────────────────┘"
echo ""
"""

    def _build_execute_script(self, dry_run: bool = False) -> str:
        """Build the EXECUTE phase script.

        Simulates installing packages with heavy CPU and minimal download.
        """
        iterations = 2 if dry_run else 6
        sleep_time = 1 if dry_run else 2
        cpu_iterations = 50000 if dry_run else 500000

        return f"""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║           MOCK ALPHA - EXECUTE PHASE (Upgrade)                   ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 [ALPHA] Installing packages..."
echo ""

for i in $(seq 1 {iterations}); do
    progress=$((i * 100 / {iterations}))

    echo "┌────────────────────────────────────────────────────────────────┐"
    echo "│ 🔧 [ALPHA] Installing package $i of {iterations}"
    echo "│ Progress: [$progress%]"
    echo "└────────────────────────────────────────────────────────────────┘"

    # Heavy CPU simulation (compiling/installing)
    echo "  ⚙️  Compiling alpha-package-$i..."
    for j in $(seq 1 {cpu_iterations}); do : ; done

    echo "  ✅ Installed alpha-package-$i"

    # Minimal download (just config files)
    dd if=/dev/zero of=/dev/null bs=1K count=10 2>/dev/null

    sleep {sleep_time}
done

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                 MOCK ALPHA COMPLETED!                            ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║ 📊 FINAL STATISTICS:                                             ║"
echo "║   Packages updated: {iterations}                                 ║"
echo "║   Total download: ~52 MB                                         ║"
echo "║   CPU time: ~35 seconds                                          ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 Mock Alpha finished successfully!"
"""

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a bash script that runs all three phases sequentially.
        This is used when phase-by-phase execution is not enabled.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        # Combine all phases into one script for backward compatibility
        script = (
            self._build_check_script(dry_run)
            + self._build_download_script(dry_run)
            + self._build_execute_script(dry_run)
        )
        return ["/bin/bash", "-c", script]

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        Mock Alpha phases:
        - CHECK: Simulate checking for updates (light CPU, minimal download)
        - DOWNLOAD: Simulate downloading packages (heavy download, light CPU)
        - EXECUTE: Simulate installing packages (heavy CPU, minimal download)

        Args:
            dry_run: If True, return commands that simulate faster.

        Returns:
            Dict mapping Phase to command list.
        """
        return {
            Phase.CHECK: ["/bin/bash", "-c", self._build_check_script(dry_run)],
            Phase.DOWNLOAD: ["/bin/bash", "-c", self._build_download_script(dry_run)],
            Phase.EXECUTE: ["/bin/bash", "-c", self._build_execute_script(dry_run)],
        }

    async def _execute_update(
        self,
        config: PluginConfig,  # noqa: ARG002
    ) -> tuple[str, str | None]:
        """Execute the mock update.

        Args:
            config: Plugin configuration (unused in mock).

        Returns:
            Tuple of (output, error_message).
        """
        # For non-interactive mode, just return a simple message
        return (
            "Mock Alpha plugin executed successfully.\n"
            "This is a debugging plugin for testing the interactive UI.\n"
            "Use --interactive mode to see the full simulation.",
            None,
        )

    def _count_updated_packages(
        self,
        output: str,  # noqa: ARG002
    ) -> int:
        """Count the number of updated packages from command output.

        Args:
            output: Command output to parse (unused in mock).

        Returns:
            Number of packages updated (simulated).
        """
        # Return a simulated count
        return 12

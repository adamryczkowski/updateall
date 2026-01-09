"""Mock Beta plugin for debugging the interactive tabbed UI.

This plugin simulates a long-running update task with three phases:
- CHECK: Simulates checking for updates (light CPU, minimal download)
- DOWNLOAD: Simulates downloading packages (heavy download, light CPU)
- EXECUTE: Simulates installing packages (heavy CPU, minimal download)

Uses different visual styling than Mock Alpha for easy differentiation.
Each phase reports download and CPU statistics for testing the stats system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MockBetaPlugin(BasePlugin):
    """Mock Beta plugin for debugging interactive mode.

    Simulates a multi-phase update with download and CPU load simulation.
    Uses different ASCII art and markers than Mock Alpha for easy differentiation.
    """

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return "mock-beta"

    @property
    def command(self) -> str:
        """Return the main command (always available for mock)."""
        return "bash"

    @property
    def description(self) -> str:
        """Return plugin description."""
        return "Mock Beta - Multi-phase simulated update with stats (debugging)"

    async def check_available(self) -> bool:
        """Mock is always available."""
        return True

    def _build_check_script(self, dry_run: bool = False) -> str:
        """Build the CHECK phase script.

        Simulates checking for updates with light CPU and minimal download.
        Reports estimated download/CPU for subsequent phases.
        """
        iterations = 2 if dry_run else 5
        sleep_time = 1 if dry_run else 2

        return f"""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│           ★★★ MOCK BETA - CHECK PHASE (Update) ★★★               │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 [BETA] Scanning for available updates..."
echo ""

# Simulate light CPU load (checking package metadata)
for i in $(seq 1 {iterations}); do
    echo "  🌐 [BETA] Querying mirror $i of {iterations}..."

    # Light CPU: simple loop
    for j in $(seq 1 60000); do : ; done

    # Minimal download simulation (reading small amount of data)
    dd if=/dev/zero of=/dev/null bs=2K count=100 2>/dev/null

    sleep {sleep_time}
done

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║ 🔶 [BETA] CHECK PHASE COMPLETE                                 ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║ Found 18 packages to update                                    ║"
echo "║ Found 5 security patches                                       ║"
echo "║                                                                ║"
echo "║ 📊 ESTIMATED RESOURCES FOR REMAINING PHASES:                   ║"
echo "║   DOWNLOAD phase: ~75 MB download, ~8% CPU                     ║"
echo "║   UPGRADE phase:  ~5 MB download, ~90% CPU for 45s             ║"
echo "║                                                                ║"
echo "║ Total estimated: 80 MB download, 50s CPU time                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
"""

    def _build_download_script(self, dry_run: bool = False) -> str:
        """Build the DOWNLOAD phase script.

        Simulates downloading packages with heavy download and light CPU.
        """
        iterations = 2 if dry_run else 6
        sleep_time = 1 if dry_run else 2
        download_size = "2M" if dry_run else "12M"

        return f"""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│           ★★★ MOCK BETA - DOWNLOAD PHASE ★★★                     │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 [BETA] Fetching packages from mirrors..."
echo ""

total_downloaded=0

for i in $(seq 1 {iterations}); do
    progress=$((i * 100 / {iterations}))
    pkg_size=$((i * 12 + 3))
    total_downloaded=$((total_downloaded + pkg_size))

    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║ 📥 [BETA] Downloading package $i of {iterations} (${{pkg_size}} MB)"
    echo "║ Progress: ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ [$progress%]"
    echo "║ Total downloaded: ${{total_downloaded}} MB"
    echo "╚════════════════════════════════════════════════════════════════╝"

    # Heavy download simulation (reading larger amount of data)
    dd if=/dev/zero of=/dev/null bs={download_size} count=1 2>/dev/null

    # Light CPU during download
    for j in $(seq 1 15000); do : ; done

    sleep {sleep_time}
done

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║ 🔶 [BETA] DOWNLOAD PHASE COMPLETE                              ║"
echo "╠════════════════════════════════════════════════════════════════╣"
echo "║ Downloaded: ${{total_downloaded}} MB                           ║"
echo "║ Packages cached: {iterations}                                  ║"
echo "║ Security patches: 5                                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
"""

    def _build_execute_script(self, dry_run: bool = False) -> str:
        """Build the EXECUTE phase script.

        Simulates installing packages with heavy CPU and minimal download.
        """
        iterations = 2 if dry_run else 8
        sleep_time = 1 if dry_run else 2
        cpu_iterations = 60000 if dry_run else 600000

        return f"""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│           ★★★ MOCK BETA - EXECUTE PHASE (Upgrade) ★★★            │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 [BETA] Applying updates..."
echo ""

for i in $(seq 1 {iterations}); do
    progress=$((i * 100 / {iterations}))

    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║ 🔧 [BETA] Installing package $i of {iterations}"
    echo "║ Progress: [$progress%]"
    echo "╚════════════════════════════════════════════════════════════════╝"

    # Heavy CPU simulation (compiling/installing)
    echo "  ⟶ Configuring beta-module-$i..."
    for j in $(seq 1 {cpu_iterations}); do : ; done

    echo "  ⟶ Running post-install hooks..."
    for j in $(seq 1 $((cpu_iterations / 2))); do : ; done

    echo "  ✅ Installed beta-module-$i"

    # Minimal download (just config files)
    dd if=/dev/zero of=/dev/null bs=2K count=10 2>/dev/null

    sleep {sleep_time}
done

echo ""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│              ★★★ MOCK BETA COMPLETED! ★★★                        │"
echo "├──────────────────────────────────────────────────────────────────┤"
echo "│ 📊 FINAL STATISTICS:                                             │"
echo "│   Packages updated: {iterations}                                 │"
echo "│   Security patches applied: 5                                    │"
echo "│   Total download: ~80 MB                                         │"
echo "│   CPU time: ~50 seconds                                          │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 Mock Beta finished successfully!"
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

        Mock Beta phases:
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
            "Mock Beta plugin executed successfully.\n"
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
        # Return a simulated count (different from Alpha)
        return 18

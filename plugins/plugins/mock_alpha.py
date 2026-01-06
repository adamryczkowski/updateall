"""Mock Alpha plugin for debugging the interactive tabbed UI.

This plugin simulates a long-running update task that takes about 2 minutes
to complete, with progress updates every 10 seconds. It's designed to help
verify that the tabbed output system is functioning correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MockAlphaPlugin(BasePlugin):
    """Mock Alpha plugin for debugging interactive mode.

    Simulates a 2-minute update task with progress updates every 10 seconds.
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
        return "Mock Alpha - 2-minute simulated update with progress (debugging)"

    async def check_available(self) -> bool:
        """Mock is always available."""
        return True

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a bash script that simulates a 2-minute update process
        with progress updates every 10 seconds.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list.
        """
        # Total duration: 120 seconds (2 minutes)
        # Updates every 10 seconds = 12 iterations
        total_iterations = 12
        sleep_interval = 10

        if dry_run:
            total_iterations = 3
            sleep_interval = 2

        # Build the bash script inline
        script = f"""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                    MOCK ALPHA PLUGIN                             ║"
echo "║              Long-Running Update Simulation                      ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 Starting Mock Alpha update process..."
echo "🔷 This will take approximately {total_iterations * sleep_interval} seconds"
echo ""

for i in $(seq 1 {total_iterations}); do
    progress=$((i * 100 / {total_iterations}))
    elapsed=$((i * {sleep_interval}))
    remaining=$(({total_iterations * sleep_interval} - elapsed))

    # Create a progress bar
    filled=$((progress / 5))
    empty=$((20 - filled))
    bar=$(printf '█%.0s' $(seq 1 $filled 2>/dev/null) || echo "")
    spaces=$(printf '░%.0s' $(seq 1 $empty 2>/dev/null) || echo "")

    echo ""
    echo "┌────────────────────────────────────────────────────────────────┐"
    echo "│ ALPHA Progress: [$bar$spaces] $progress%"
    echo "│ Step $i of {total_iterations} | Elapsed: ${{elapsed}}s | Remaining: ${{remaining}}s"
    echo "└────────────────────────────────────────────────────────────────┘"

    # Simulate some work being done
    case $((i % 4)) in
        0) echo "  📦 [ALPHA] Checking package dependencies..." ;;
        1) echo "  📥 [ALPHA] Downloading updates..." ;;
        2) echo "  🔧 [ALPHA] Installing packages..." ;;
        3) echo "  ✅ [ALPHA] Verifying installation..." ;;
    esac

    # Show some fake package names
    echo "  → Processing alpha-package-$i..."
    echo "  → Updating alpha-lib-$((i * 2))..."

    sleep {sleep_interval}
done

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                 MOCK ALPHA COMPLETED!                            ║"
echo "║              All simulated updates applied                       ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo "🔷 Mock Alpha finished successfully!"
echo "🔷 Total packages processed: {total_iterations * 2}"
"""

        return ["/bin/bash", "-c", script]

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
        return 24

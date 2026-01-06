"""Mock Beta plugin for debugging the interactive tabbed UI.

This plugin simulates a long-running update task that takes about 2 minutes
to complete, with progress updates every 10 seconds. It uses different
visual styling than Mock Alpha to make it easily distinguishable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig


class MockBetaPlugin(BasePlugin):
    """Mock Beta plugin for debugging interactive mode.

    Simulates a 2-minute update task with progress updates every 10 seconds.
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
        return "Mock Beta - 2-minute simulated update with progress (debugging)"

    async def check_available(self) -> bool:
        """Mock is always available."""
        return True

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode.

        Returns a bash script that simulates a 2-minute update process
        with progress updates every 10 seconds. Uses different styling
        than Mock Alpha.

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

        # Build the bash script inline - using different visual style
        script = f"""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│                    ★★★ MOCK BETA PLUGIN ★★★                      │"
echo "│              Simulated Update Process (Beta)                     │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 Initializing Mock Beta update process..."
echo "🔶 Estimated duration: {total_iterations * sleep_interval} seconds"
echo ""

for i in $(seq 1 {total_iterations}); do
    progress=$((i * 100 / {total_iterations}))
    elapsed=$((i * {sleep_interval}))
    remaining=$(({total_iterations * sleep_interval} - elapsed))

    # Create a different style progress bar
    filled=$((progress / 5))
    empty=$((20 - filled))
    bar=$(printf '▓%.0s' $(seq 1 $filled 2>/dev/null) || echo "")
    spaces=$(printf '▒%.0s' $(seq 1 $empty 2>/dev/null) || echo "")

    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║ BETA Progress: [$bar$spaces] $progress%"
    echo "║ Phase $i of {total_iterations} │ Time: ${{elapsed}}s │ ETA: ${{remaining}}s"
    echo "╚════════════════════════════════════════════════════════════════╝"

    # Simulate different work than Alpha
    case $((i % 4)) in
        0) echo "  🌐 [BETA] Syncing remote repositories..." ;;
        1) echo "  📊 [BETA] Analyzing dependencies..." ;;
        2) echo "  🔄 [BETA] Applying patches..." ;;
        3) echo "  🧪 [BETA] Running post-install tests..." ;;
    esac

    # Show different fake package names
    echo "  ⟶ Updating beta-core-module-$i..."
    echo "  ⟶ Patching beta-security-fix-$((i * 3))..."
    echo "  ⟶ Configuring beta-service-$((i + 100))..."

    sleep {sleep_interval}
done

echo ""
echo "╭──────────────────────────────────────────────────────────────────╮"
echo "│              ★★★ MOCK BETA COMPLETED! ★★★                        │"
echo "│              All Beta updates have been applied                  │"
echo "╰──────────────────────────────────────────────────────────────────╯"
echo ""
echo "🔶 Mock Beta finished successfully!"
echo "🔶 Total modules updated: {total_iterations * 3}"
echo "🔶 Security patches applied: {total_iterations}"
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
        return 36

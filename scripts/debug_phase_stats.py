#!/usr/bin/env python3
"""Debug script to trace phase stats preservation issue.

This script runs the InteractiveTabbedApp with a mock plugin
and allows us to set breakpoints to trace the execution flow.
"""

import asyncio
import sys
from pathlib import Path

# Add the project directories to the path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "ui"))
sys.path.insert(0, str(project_root / "core"))
sys.path.insert(0, str(project_root / "plugins"))
sys.path.insert(0, str(project_root / "cli"))

from unittest.mock import MagicMock  # noqa: E402

from core.streaming import Phase  # noqa: E402
from ui.interactive_tabbed_run import InteractiveTabbedApp  # noqa: E402


def create_mock_plugin(name: str) -> MagicMock:
    """Create a mock plugin for debugging."""
    plugin = MagicMock()
    plugin.name = name
    plugin.supports_interactive = True

    def get_phase_commands(dry_run: bool = False) -> dict[Phase, list[str]]:
        return {
            Phase.CHECK: ["/bin/bash", "-c", f"echo '{name} CHECK' && sleep 0.5"],
            Phase.DOWNLOAD: ["/bin/bash", "-c", f"echo '{name} DOWNLOAD' && sleep 0.5"],
            Phase.EXECUTE: ["/bin/bash", "-c", f"echo '{name} EXECUTE' && sleep 0.5"],
        }

    plugin.get_phase_commands = get_phase_commands
    plugin.get_interactive_command.side_effect = NotImplementedError()
    plugin.check_available = MagicMock(return_value=True)

    return plugin


async def run_debug_session():
    """Run the debug session."""
    plugin = create_mock_plugin("debug-plugin")

    app = InteractiveTabbedApp(
        plugins=[plugin],
        auto_start=True,
        pause_phases=False,
    )

    # This is where we want to set breakpoints
    async with app.run_test():
        pane = app.terminal_panes["debug-plugin"]

        # Wait for first phase to start
        await asyncio.sleep(0.2)

        # Check metrics collector
        collector = pane.metrics_collector
        print("After first phase start:")
        print(f"  collector id: {id(collector)}")
        print(f"  phase_stats: {collector._phase_stats if collector else 'None'}")

        # Wait for first phase to complete and second to start
        await asyncio.sleep(0.8)

        # Check again
        collector2 = pane.metrics_collector
        print("\nAfter second phase start:")
        print(f"  collector id: {id(collector2)}")
        print(f"  same instance: {collector is collector2}")
        print(f"  phase_stats: {collector2._phase_stats if collector2 else 'None'}")

        # Wait for all phases
        await asyncio.sleep(1.5)

        collector3 = pane.metrics_collector
        print("\nAfter all phases:")
        print(f"  collector id: {id(collector3)}")
        print(f"  same instance: {collector is collector3}")
        print(f"  phase_stats: {collector3._phase_stats if collector3 else 'None'}")


if __name__ == "__main__":
    asyncio.run(run_debug_session())

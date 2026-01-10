#!/usr/bin/env python3
"""POC script to verify bugs in the Textual GUI.

This script runs the actual Textual app and verifies:
1. Bug 1 & 2: Statistics are zeroed after each phase
2. Bug 3: Scrolling doesn't change the visible content

Run with: cd ui && poetry run python ../scripts/poc_bug_verification.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add the ui package to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))

from ui.interactive_tabbed_run import InteractiveTabbedApp


def create_mock_plugin(
    name: str,
    *,
    command: list[str] | None = None,
) -> MagicMock:
    """Create a mock plugin for testing."""
    plugin = MagicMock()
    plugin.name = name
    plugin.supports_interactive = True

    if command is None:
        command = ["/bin/bash", "-c", "echo 'Hello from plugin'"]

    plugin.get_interactive_command.return_value = command
    plugin.check_available = AsyncMock(return_value=True)
    plugin.pre_execute = AsyncMock()
    plugin.post_execute = AsyncMock()

    return plugin


async def test_statistics_preserved_across_phases() -> bool:
    """Test that statistics are preserved when phases transition.

    This test:
    1. Creates a plugin that runs a CPU-intensive task
    2. Starts the phase and collects metrics
    3. Completes the phase
    4. Starts a new phase
    5. Verifies that the previous phase's statistics are preserved

    Returns:
        True if the bug is FIXED (statistics preserved), False if bug exists.
    """
    print("\n" + "=" * 60)
    print("TEST: Statistics preserved across phases")
    print("=" * 60)

    # Create a plugin that does some CPU work
    plugin = create_mock_plugin(
        "test_stats",
        command=[
            "/bin/bash",
            "-c",
            "for i in $(seq 1 100000); do echo $i > /dev/null; done; echo 'Done'",
        ],
    )

    app = InteractiveTabbedApp(
        plugins=[plugin],
        auto_start=False,
    )

    bug_exists = False

    async with app.run_test():
        pane = app.terminal_panes["test_stats"]

        # Start the plugin
        await pane.start()
        print(f"Plugin started, state: {pane.state}")

        # Wait for some processing
        await asyncio.sleep(1.0)

        # Get the metrics collector
        collector = pane.metrics_collector
        if collector is None:
            print("ERROR: No metrics collector found!")
            return False

        # Simulate phase transitions
        collector.start_phase("Update")
        print("Started 'Update' phase")

        # Collect metrics during the phase
        collector.collect()
        await asyncio.sleep(0.5)
        collector.collect()

        # Get Update phase stats before completing
        update_stats_before = collector.phase_stats["Update"]
        print("Update phase stats BEFORE completion:")
        print(f"  - wall_time_seconds: {update_stats_before.wall_time_seconds:.2f}")
        print(f"  - cpu_time_seconds: {update_stats_before.cpu_time_seconds:.2f}")
        print(f"  - data_bytes: {update_stats_before.data_bytes}")
        print(f"  - is_running: {update_stats_before.is_running}")
        print(f"  - is_complete: {update_stats_before.is_complete}")

        # Complete the Update phase
        collector.complete_phase("Update")
        print("\nCompleted 'Update' phase")

        # Get Update phase stats after completing
        update_stats_after_complete = collector.phase_stats["Update"]
        print("Update phase stats AFTER completion:")
        print(
            f"  - wall_time_seconds: {update_stats_after_complete.wall_time_seconds:.2f}"
        )
        print(
            f"  - cpu_time_seconds: {update_stats_after_complete.cpu_time_seconds:.2f}"
        )
        print(f"  - data_bytes: {update_stats_after_complete.data_bytes}")
        print(f"  - is_running: {update_stats_after_complete.is_running}")
        print(f"  - is_complete: {update_stats_after_complete.is_complete}")

        # Start a new phase
        collector.start_phase("Download")
        print("\nStarted 'Download' phase")

        # Collect metrics during the new phase
        collector.collect()
        await asyncio.sleep(0.3)
        collector.collect()

        # Get Update phase stats after starting new phase
        update_stats_after_new_phase = collector.phase_stats["Update"]
        print("\nUpdate phase stats AFTER starting new phase:")
        print(
            f"  - wall_time_seconds: {update_stats_after_new_phase.wall_time_seconds:.2f}"
        )
        print(
            f"  - cpu_time_seconds: {update_stats_after_new_phase.cpu_time_seconds:.2f}"
        )
        print(f"  - data_bytes: {update_stats_after_new_phase.data_bytes}")
        print(f"  - is_running: {update_stats_after_new_phase.is_running}")
        print(f"  - is_complete: {update_stats_after_new_phase.is_complete}")

        # Check if stats were preserved
        if update_stats_after_new_phase.wall_time_seconds == 0:
            print("\n❌ BUG: wall_time_seconds was reset to 0!")
            bug_exists = True
        if (
            update_stats_after_new_phase.cpu_time_seconds == 0
            and update_stats_after_complete.cpu_time_seconds > 0
        ):
            print("\n❌ BUG: cpu_time_seconds was reset to 0!")
            bug_exists = True

        if not bug_exists:
            print("\n✅ Statistics were preserved across phases!")

    return not bug_exists


async def test_scrolling_changes_content() -> bool:
    """Test that scrolling actually changes the visible content.

    This test:
    1. Creates a plugin that produces lots of output
    2. Waits for output to be captured
    3. Scrolls up
    4. Verifies that the visible content changed

    Returns:
        True if the bug is FIXED (scrolling works), False if bug exists.
    """
    print("\n" + "=" * 60)
    print("TEST: Scrolling changes visible content")
    print("=" * 60)

    # Create a plugin that produces lots of output
    plugin = create_mock_plugin(
        "test_scroll",
        command=[
            "/bin/bash",
            "-c",
            'for i in $(seq 1 100); do echo "Line $i: This is test output"; done',
        ],
    )

    app = InteractiveTabbedApp(
        plugins=[plugin],
        auto_start=False,
    )

    bug_exists = False

    async with app.run_test():
        pane = app.terminal_panes["test_scroll"]

        # Start the plugin
        await pane.start()
        print(f"Plugin started, state: {pane.state}")

        # Wait for output
        await asyncio.sleep(1.0)

        # Get the terminal view
        terminal_view = pane.terminal_view
        if terminal_view is None:
            print("ERROR: No terminal view found!")
            return False

        # Get the terminal screen
        terminal_screen = terminal_view.terminal_screen

        # Check if there's history to scroll
        history = terminal_screen.get_history()
        print(f"History lines: {len(history)}")

        if len(history) == 0:
            print("WARNING: No history to scroll. Waiting more...")
            await asyncio.sleep(1.0)
            history = terminal_screen.get_history()
            print(f"History lines after waiting: {len(history)}")

        # Get content before scrolling
        content_before = terminal_view.terminal_display
        print("\nContent BEFORE scrolling (first 3 lines):")
        for i, line in enumerate(content_before[:3]):
            print(f"  [{i}]: {line.strip()[:60]}...")

        # Get scroll offset before
        scroll_offset_before = terminal_screen.scroll_offset
        print(f"\nScroll offset BEFORE: {scroll_offset_before}")

        # Scroll up
        terminal_view.scroll_history_up(lines=10)
        print("\nScrolled up 10 lines")

        # Get scroll offset after
        scroll_offset_after = terminal_screen.scroll_offset
        print(f"Scroll offset AFTER: {scroll_offset_after}")

        # Get content after scrolling
        content_after = terminal_view.terminal_display
        print("\nContent AFTER scrolling (first 3 lines):")
        for i, line in enumerate(content_after[:3]):
            print(f"  [{i}]: {line.strip()[:60]}...")

        # Check if content changed
        if content_before == content_after:
            print("\n❌ BUG: Content did NOT change after scrolling!")
            bug_exists = True
        else:
            print("\n✅ Content changed after scrolling!")

        # Also check if scroll offset changed
        if scroll_offset_after == scroll_offset_before:
            print("❌ BUG: Scroll offset did NOT change!")
            bug_exists = True
        else:
            print(
                f"✅ Scroll offset changed from {scroll_offset_before} to {scroll_offset_after}"
            )

        # Now test scrolling down
        terminal_view.scroll_history_down(lines=5)
        print("\nScrolled down 5 lines")

        scroll_offset_after_down = terminal_screen.scroll_offset
        print(f"Scroll offset AFTER down: {scroll_offset_after_down}")

        content_after_down = terminal_view.terminal_display
        print("\nContent AFTER scrolling down (first 3 lines):")
        for i, line in enumerate(content_after_down[:3]):
            print(f"  [{i}]: {line.strip()[:60]}...")

    return not bug_exists


async def test_keyboard_scroll_keys() -> bool:
    """Test that keyboard scroll keys work.

    This test:
    1. Creates a plugin that produces lots of output
    2. Simulates pressing PageUp/PageDown keys
    3. Verifies that scrolling occurred

    Returns:
        True if the bug is FIXED (keyboard scrolling works), False if bug exists.
    """
    print("\n" + "=" * 60)
    print("TEST: Keyboard scroll keys work")
    print("=" * 60)

    # Create a plugin that produces lots of output
    plugin = create_mock_plugin(
        "test_keys",
        command=["/bin/bash", "-c", 'for i in $(seq 1 100); do echo "Line $i"; done'],
    )

    app = InteractiveTabbedApp(
        plugins=[plugin],
        auto_start=False,
    )

    bug_exists = False

    async with app.run_test() as pilot:
        pane = app.terminal_panes["test_keys"]

        # Start the plugin
        await pane.start()
        print(f"Plugin started, state: {pane.state}")

        # Wait for output
        await asyncio.sleep(1.0)

        # Get the terminal view
        terminal_view = pane.terminal_view
        if terminal_view is None:
            print("ERROR: No terminal view found!")
            return False

        terminal_screen = terminal_view.terminal_screen

        # Get scroll offset before
        scroll_offset_before = terminal_screen.scroll_offset
        print(f"Scroll offset BEFORE: {scroll_offset_before}")

        # Get content before
        content_before = terminal_view.terminal_display
        print(f"Content BEFORE (first line): {content_before[0].strip()[:60]}...")

        # Press PageUp
        await pilot.press("pageup")
        print("\nPressed PageUp")

        # Get scroll offset after
        scroll_offset_after = terminal_screen.scroll_offset
        print(f"Scroll offset AFTER: {scroll_offset_after}")

        # Get content after
        content_after = terminal_view.terminal_display
        print(f"Content AFTER (first line): {content_after[0].strip()[:60]}...")

        # Check if scroll offset changed
        if scroll_offset_after == scroll_offset_before:
            print("\n❌ BUG: PageUp did NOT change scroll offset!")
            bug_exists = True
        else:
            print(
                f"\n✅ PageUp changed scroll offset from {scroll_offset_before} to {scroll_offset_after}"
            )

        # Check if content changed
        if content_before == content_after:
            print("❌ BUG: PageUp did NOT change content!")
            bug_exists = True
        else:
            print("✅ PageUp changed content!")

    return not bug_exists


async def main() -> int:
    """Run all bug verification tests."""
    print("=" * 60)
    print("POC Bug Verification Script")
    print("=" * 60)
    print("\nThis script verifies whether the known bugs exist in the")
    print("Textual GUI implementation.")
    print()

    results = {}

    # Test 1: Statistics preserved across phases
    try:
        results[
            "statistics_preserved"
        ] = await test_statistics_preserved_across_phases()
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        results["statistics_preserved"] = False

    # Test 2: Scrolling changes content
    try:
        results["scrolling_works"] = await test_scrolling_changes_content()
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        results["scrolling_works"] = False

    # Test 3: Keyboard scroll keys work
    try:
        results["keyboard_scroll"] = await test_keyboard_scroll_keys()
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback

        traceback.print_exc()
        results["keyboard_scroll"] = False

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results.items():
        status = "✅ FIXED" if passed else "❌ BUG EXISTS"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n✅ All bugs are FIXED!")
        return 0
    else:
        print("\n❌ Some bugs still exist!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

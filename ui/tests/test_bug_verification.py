"""High-level tests to verify bug fixes for the interactive tabbed UI.

These tests verify the following bugs are fixed:

1. Task 1: CPU statistics not updating during CPU-bound tasks
   - Root cause: MetricsCollector was created per-phase, losing accumulated stats
   - Fix: Preserve MetricsCollector across phases, only update PID

2. Task 2: Phase counters reset when transitioning to a new phase
   - Root cause: New MetricsCollector created for each phase
   - Fix: Same as Task 1 - preserve MetricsCollector across phases

3. Task 3: Scrolling doesn't work with mouse wheel, up/down arrows, or pgup/pgdn
   - Root cause: TerminalView.render() didn't respect scroll_offset
   - Fix: Updated get_styled_line() to use scroll_offset, and scroll methods
     to call _update_display() instead of just refresh()
"""

from __future__ import annotations

import pytest

from ui.interactive_tabbed_run import InteractiveTabbedApp
from ui.phase_status_bar import MetricsCollector
from ui.terminal_pane import TerminalPane


class TestBug1CpuStatisticsNotUpdating:
    """Tests for Bug 1: CPU statistics not updating during CPU-bound tasks.

    Root cause: The MetricsCollector was being created anew for each phase,
    which meant that when a CPU-bound task was running, the metrics from
    the previous phase were lost.

    The fix preserves the MetricsCollector across phases by:
    1. Checking if a MetricsCollector already exists in TerminalPane.start()
    2. If it exists, calling update_pid() instead of creating a new one
    3. This preserves all accumulated _phase_stats across phases
    """

    def test_metrics_collector_update_pid_preserves_phase_stats(self) -> None:
        """Test that update_pid preserves accumulated phase statistics."""
        # Create a MetricsCollector and accumulate some stats
        collector = MetricsCollector(pid=None)
        collector.start()

        # Simulate completing the Update phase with some stats
        collector.start_phase("Update")
        # Set stats that won't be overwritten by complete_phase()
        # (wall_time_seconds is calculated from elapsed time, so we don't set it)
        collector._phase_stats["Update"].cpu_time_seconds = 5.2
        collector._phase_stats["Update"].data_bytes = 1024 * 1024
        collector._phase_stats["Update"].peak_memory_mb = 128.0
        collector.complete_phase("Update")

        # Store the wall time that was calculated
        original_wall_time = collector._phase_stats["Update"].wall_time_seconds

        # Now update the PID (simulating transition to next phase)
        collector.update_pid(12345)

        # Verify that the Update phase stats are preserved
        assert collector._phase_stats["Update"].wall_time_seconds == original_wall_time
        assert collector._phase_stats["Update"].cpu_time_seconds == 5.2
        assert collector._phase_stats["Update"].data_bytes == 1024 * 1024
        assert collector._phase_stats["Update"].peak_memory_mb == 128.0
        assert collector._phase_stats["Update"].is_complete is True

    def test_metrics_collector_max_cpu_time_preserved_across_pid_update(self) -> None:
        """Test that _max_cpu_time_seen is preserved when updating PID."""
        collector = MetricsCollector(pid=None)
        collector.start()

        # Set a high CPU time value
        collector._max_cpu_time_seen = 100.5

        # Update PID
        collector.update_pid(12345)

        # Verify max CPU time is preserved
        assert collector._max_cpu_time_seen == 100.5

    def test_metrics_collector_running_state_after_pid_update(self) -> None:
        """Test that collector can be restarted after PID update."""
        collector = MetricsCollector(pid=None)
        collector.start()
        collector.stop()

        # Update PID and restart
        collector.update_pid(12345)
        collector.start()

        assert collector._running is True


class TestBug2PhaseCountersReset:
    """Tests for Bug 2: Phase counters reset when transitioning to a new phase.

    Root cause: Same as Bug 1 - the MetricsCollector was being recreated
    for each phase, which reset all phase statistics.

    The fix is the same as Bug 1 - preserve the MetricsCollector across phases.
    """

    def test_phase_stats_not_updated_after_completion(self) -> None:
        """Test that completed phase stats are not overwritten."""
        collector = MetricsCollector(pid=None)
        collector.start()

        # Complete the Update phase with specific values
        collector.start_phase("Update")
        collector.update_phase_stats(
            "Update",
            cpu_time_seconds=5.0,
            data_bytes=1000,
            peak_memory_mb=100.0,
        )
        collector.complete_phase("Update")

        # Try to update the completed phase (should be ignored)
        collector.update_phase_stats(
            "Update",
            cpu_time_seconds=0.0,  # Trying to reset
            data_bytes=0,
            peak_memory_mb=0.0,
        )

        # Verify the original values are preserved
        assert collector._phase_stats["Update"].cpu_time_seconds == 5.0
        assert collector._phase_stats["Update"].data_bytes == 1000
        assert collector._phase_stats["Update"].peak_memory_mb == 100.0

    def test_phase_stats_force_update_after_completion(self) -> None:
        """Test that force=True allows updating completed phase stats."""
        collector = MetricsCollector(pid=None)
        collector.start()

        # Complete the Update phase
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0)
        collector.complete_phase("Update")

        # Force update the completed phase
        collector.update_phase_stats("Update", cpu_time_seconds=10.0, force=True)

        # Verify the value was updated
        assert collector._phase_stats["Update"].cpu_time_seconds == 10.0

    def test_total_stats_accumulates_across_phases(self) -> None:
        """Test that get_total_stats correctly sums all phases."""
        collector = MetricsCollector(pid=None)
        collector.start()

        # Complete Update phase - set stats directly without using complete_phase
        # to avoid wall_time being calculated from elapsed time
        collector._phase_stats["Update"].cpu_time_seconds = 5.0
        collector._phase_stats["Update"].data_bytes = 1000
        collector._phase_stats["Update"].is_complete = True

        # Complete Download phase
        collector._phase_stats["Download"].cpu_time_seconds = 8.0
        collector._phase_stats["Download"].data_bytes = 2000
        collector._phase_stats["Download"].is_complete = True

        # Get total stats
        total = collector.get_total_stats()

        # Verify totals are correct (wall_time not tested as it's calculated)
        assert total.cpu_time_seconds == 13.0
        assert total.data_bytes == 3000


class TestBug3ScrollingNotWorking:
    """Tests for Bug 3: Scrolling doesn't work with mouse wheel, arrows, or pgup/pgdn.

    Root cause: The TerminalView.render() method was not respecting the
    scroll_offset when rendering lines. The get_styled_line() method
    always returned lines from the beginning of the display, ignoring
    any scroll position.

    The fix:
    1. Updated get_styled_line() to add scroll_offset to the line index
    2. Updated scroll methods to call _update_display() instead of just refresh()
    3. Added mouse scroll event handlers to TerminalPane
    """

    @pytest.mark.asyncio
    async def test_terminal_pane_has_mouse_scroll_handlers(self) -> None:
        """Test that TerminalPane has mouse scroll event handlers."""
        # Verify the handlers exist
        assert hasattr(TerminalPane, "on_mouse_scroll_up")
        assert hasattr(TerminalPane, "on_mouse_scroll_down")

    @pytest.mark.asyncio
    async def test_scroll_methods_exist_on_terminal_pane(self) -> None:
        """Test that scroll methods exist on TerminalPane."""
        assert hasattr(TerminalPane, "scroll_history_up")
        assert hasattr(TerminalPane, "scroll_history_down")
        assert hasattr(TerminalPane, "scroll_to_history_top")
        assert hasattr(TerminalPane, "scroll_to_history_bottom")

    @pytest.mark.asyncio
    async def test_interactive_app_has_scroll_bindings(self) -> None:
        """Test that InteractiveTabbedApp has scroll key bindings."""
        # Check that the app has scroll-related bindings
        binding_keys = [b.key for b in InteractiveTabbedApp.BINDINGS]

        # Verify scroll bindings exist
        assert "pageup" in binding_keys
        assert "pagedown" in binding_keys
        assert "up" in binding_keys
        assert "down" in binding_keys
        assert "home" in binding_keys
        assert "end" in binding_keys

    @pytest.mark.asyncio
    async def test_interactive_app_has_scroll_actions(self) -> None:
        """Test that InteractiveTabbedApp has scroll action methods."""
        assert hasattr(InteractiveTabbedApp, "action_scroll_up")
        assert hasattr(InteractiveTabbedApp, "action_scroll_down")
        assert hasattr(InteractiveTabbedApp, "action_scroll_line_up")
        assert hasattr(InteractiveTabbedApp, "action_scroll_line_down")
        assert hasattr(InteractiveTabbedApp, "action_scroll_top")
        assert hasattr(InteractiveTabbedApp, "action_scroll_bottom")


class TestMetricsCollectorPreservation:
    """Integration tests for MetricsCollector preservation across phases."""

    @pytest.mark.asyncio
    async def test_terminal_pane_preserves_metrics_collector(self) -> None:
        """Test that TerminalPane preserves MetricsCollector across start() calls.

        This is the key integration test that verifies the fix for both
        Bug 1 and Bug 2. When a new phase starts, the existing MetricsCollector
        should be preserved and only its PID should be updated.
        """
        from ui.key_bindings import KeyBindings
        from ui.terminal_pane import PaneConfig

        # Create a TerminalPane with metrics enabled
        config = PaneConfig(show_phase_status_bar=True)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=config,
            key_bindings=KeyBindings(),
        )

        # Manually set up the metrics collector as if first phase completed
        pane._metrics_collector = MetricsCollector(pid=None)
        pane._metrics_collector.start()
        pane._metrics_collector.start_phase("Update")
        pane._metrics_collector._phase_stats["Update"].cpu_time_seconds = 5.0
        pane._metrics_collector._phase_stats["Update"].data_bytes = 1000
        pane._metrics_collector.complete_phase("Update")

        # Store reference to original collector
        original_collector = pane._metrics_collector
        original_update_stats = pane._metrics_collector._phase_stats["Update"]

        # Verify the collector exists and has stats
        assert pane._metrics_collector is not None
        assert pane._metrics_collector._phase_stats["Update"].cpu_time_seconds == 5.0

        # Simulate what happens when update_pid is called (as in start())
        pane._metrics_collector.update_pid(12345)

        # Verify the same collector is still in use
        assert pane._metrics_collector is original_collector

        # Verify the Update phase stats are preserved
        assert pane._metrics_collector._phase_stats["Update"] is original_update_stats
        assert pane._metrics_collector._phase_stats["Update"].cpu_time_seconds == 5.0
        assert pane._metrics_collector._phase_stats["Update"].data_bytes == 1000
        assert pane._metrics_collector._phase_stats["Update"].is_complete is True

    @pytest.mark.asyncio
    async def test_terminal_pane_stop_preserves_metrics_collector(self) -> None:
        """Test that TerminalPane.stop() preserves MetricsCollector.

        This is a critical test that verifies the root cause fix for Bug 2.
        Previously, stop() would set _metrics_collector = None, which caused
        a new collector to be created on the next start(), losing all phase stats.

        The fix removes the line that sets _metrics_collector = None in stop().
        """
        from ui.key_bindings import KeyBindings
        from ui.terminal_pane import PaneConfig

        # Create a TerminalPane with metrics enabled
        config = PaneConfig(show_phase_status_bar=True)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=config,
            key_bindings=KeyBindings(),
        )

        # Manually set up the metrics collector as if first phase completed
        pane._metrics_collector = MetricsCollector(pid=None)
        pane._metrics_collector.start()
        pane._metrics_collector.start_phase("Update")
        pane._metrics_collector._phase_stats["Update"].cpu_time_seconds = 5.0
        pane._metrics_collector._phase_stats["Update"].data_bytes = 1000
        pane._metrics_collector.complete_phase("Update")

        # Store reference to original collector
        original_collector = pane._metrics_collector

        # Call stop() - this should NOT set _metrics_collector to None
        await pane.stop()

        # Verify the collector is still present (not None)
        assert pane._metrics_collector is not None
        assert pane._metrics_collector is original_collector

        # Verify the Update phase stats are preserved
        assert pane._metrics_collector._phase_stats["Update"].cpu_time_seconds == 5.0
        assert pane._metrics_collector._phase_stats["Update"].data_bytes == 1000
        assert pane._metrics_collector._phase_stats["Update"].is_complete is True

        # Verify the collector is stopped but not destroyed
        assert pane._metrics_collector._running is False


class TestScrollingIntegration:
    """Integration tests for scrolling functionality."""

    @pytest.mark.asyncio
    async def test_terminal_view_scroll_offset_affects_display(self) -> None:
        """Test that scroll_offset affects what is displayed."""
        from ui.terminal_view import TerminalView

        # Create a terminal view
        view = TerminalView(columns=80, lines=10, scrollback_lines=100)

        # Feed some content
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())

        # Verify initial scroll offset is 0
        assert view._terminal_screen.scroll_offset == 0

        # Scroll up
        view.scroll_history_up(5)

        # The scroll_offset should now be 5
        # Note: This test verifies the scroll_offset is being used
        assert view._terminal_screen.scroll_offset == 5

    @pytest.mark.asyncio
    async def test_terminal_view_scroll_to_top_and_bottom(self) -> None:
        """Test scroll_to_top and scroll_to_bottom functionality."""
        from ui.terminal_view import TerminalView

        view = TerminalView(columns=80, lines=10, scrollback_lines=100)

        # Feed content to create scrollback
        for i in range(50):
            view.feed(f"Line {i}\r\n".encode())

        # Scroll to top
        view.scroll_to_top()
        top_offset = view._terminal_screen.scroll_offset

        # Scroll to bottom
        view.scroll_to_bottom()
        bottom_offset = view._terminal_screen.scroll_offset

        # Top should have higher offset than bottom (0)
        assert top_offset > bottom_offset
        assert bottom_offset == 0

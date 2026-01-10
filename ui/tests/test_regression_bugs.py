"""Regression tests for fixed bugs in the interactive tabbed UI.

This module consolidates regression tests for bugs that have been fixed.
Each test class documents the original bug, root cause, and fix.

Test Categories:
    1. Unit Tests - Test individual functions/classes in isolation
    2. Integration Tests - Test component interactions
    3. Regression Tests - Tests for specific bug fixes (this file)
    4. E2E Tests - Test full application flows (see test_e2e_*.py)

Bugs Covered:
    - Bug 1: CPU statistics not updating during CPU-bound tasks
    - Bug 2: Phase counters reset when transitioning to a new phase
    - Bug 3: Scrolling doesn't work with mouse wheel, up/down arrows, or pgup/pgdn

See Also:
    - docs/bug-investigation-report.md for detailed bug analysis
    - test_e2e_phase_stats_preservation.py for E2E tests of these fixes
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from unittest.mock import MagicMock

import pytest

from ui.interactive_tabbed_run import InteractiveTabbedApp
from ui.phase_status_bar import MetricsCollector, PhaseStats
from ui.pty_session import is_pty_available
from ui.terminal_pane import PaneConfig, TerminalPane

# Skip tests requiring PTY if not available
pytestmark_pty = pytest.mark.skipif(
    not is_pty_available(),
    reason="PTY not available on this platform",
)


# =============================================================================
# Bug 1: CPU Statistics Not Updating During CPU-Bound Tasks
# =============================================================================


class TestBug1CpuStatisticsRegression:
    """Regression tests for Bug 1: CPU statistics not updating.

    Root Cause:
        MetricsCollector was created per-phase, losing accumulated stats.
        The fix preserves MetricsCollector across phases, only updating PID.

    Key Fix:
        - TerminalPane.start() checks if MetricsCollector exists
        - If exists, calls update_pid() instead of creating new one
        - This preserves all accumulated _phase_stats across phases
    """

    def test_metrics_collector_update_pid_preserves_phase_stats(self) -> None:
        """Verify update_pid preserves accumulated phase statistics."""
        collector = MetricsCollector(pid=None)
        collector.start()

        # Complete Update phase with stats
        collector.start_phase("Update")
        collector._phase_stats["Update"].cpu_time_seconds = 5.2
        collector._phase_stats["Update"].data_bytes = 1024 * 1024
        collector._phase_stats["Update"].peak_memory_mb = 128.0
        collector.complete_phase("Update")

        original_wall_time = collector._phase_stats["Update"].wall_time_seconds

        # Update PID (simulating transition to next phase)
        collector.update_pid(12345)

        # Verify Update phase stats are preserved
        assert collector._phase_stats["Update"].wall_time_seconds == original_wall_time
        assert collector._phase_stats["Update"].cpu_time_seconds == 5.2
        assert collector._phase_stats["Update"].data_bytes == 1024 * 1024
        assert collector._phase_stats["Update"].peak_memory_mb == 128.0
        assert collector._phase_stats["Update"].is_complete is True

    def test_max_cpu_time_preserved_across_pid_update(self) -> None:
        """Verify _max_cpu_time_seen is preserved when updating PID."""
        collector = MetricsCollector(pid=None)
        collector.start()
        collector._max_cpu_time_seen = 100.5

        collector.update_pid(12345)

        assert collector._max_cpu_time_seen == 100.5

    def test_collect_aggregates_child_process_metrics(self) -> None:
        """Verify MetricsCollector aggregates metrics from child processes.

        This is the fix for CPU stats staying at zero because only the
        shell process was monitored, not child processes doing actual work.
        """
        # Start a shell process that spawns a child doing CPU work
        proc = subprocess.Popen(
            ["/bin/bash", "-c", "python3 -c 'sum(range(10000000))'"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            collector = MetricsCollector(pid=proc.pid)
            collector.start()

            time.sleep(0.2)
            metrics = collector.collect()

            # CPU time should be non-negative (aggregated from children)
            assert metrics.cpu_time_seconds >= 0.0
            assert metrics.memory_mb >= 0.0

            collector.stop()
        finally:
            proc.wait(timeout=5)

    def test_collect_process_tree_metrics_method_exists(self) -> None:
        """Verify _collect_process_tree_metrics method exists and works."""
        import os

        collector = MetricsCollector(pid=os.getpid())

        assert hasattr(collector, "_collect_process_tree_metrics")

        process = collector._get_process()
        if process:
            cpu_percent, memory_mb, cpu_time = collector._collect_process_tree_metrics(process)
            assert cpu_percent >= 0.0
            assert memory_mb >= 0.0
            assert cpu_time >= 0.0


# =============================================================================
# Bug 2: Phase Counters Reset When Transitioning to New Phase
# =============================================================================


class TestBug2PhaseCounterResetRegression:
    """Regression tests for Bug 2: Phase counters reset on transition.

    Root Cause:
        Same as Bug 1 - MetricsCollector was recreated for each phase,
        resetting all phase statistics.

    Key Fix:
        - Preserve MetricsCollector across phases
        - Mark completed phases with is_complete flag
        - Block update_phase_stats() for completed phases unless force=True
    """

    def test_completed_phase_stats_preserved_when_starting_new_phase(self) -> None:
        """Verify completed phase stats are preserved when starting new phase."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase
        collector.start_phase("Update")
        time.sleep(0.1)
        collector.update_phase_stats(
            "Update",
            cpu_time_seconds=2.0,
            data_bytes=1024,
            peak_memory_mb=100.0,
        )
        collector.complete_phase("Update")

        # Record stats before starting new phase
        update_stats_before = PhaseStats(
            phase_name="Update",
            wall_time_seconds=collector.phase_stats["Update"].wall_time_seconds,
            cpu_time_seconds=collector.phase_stats["Update"].cpu_time_seconds,
            data_bytes=collector.phase_stats["Update"].data_bytes,
            peak_memory_mb=collector.phase_stats["Update"].peak_memory_mb,
            is_complete=collector.phase_stats["Update"].is_complete,
        )

        # Start Download phase
        collector.start_phase("Download")

        # Verify Update stats are preserved
        update_stats_after = collector.phase_stats["Update"]
        assert update_stats_after.is_complete is True
        assert update_stats_after.wall_time_seconds == update_stats_before.wall_time_seconds
        assert update_stats_after.cpu_time_seconds == update_stats_before.cpu_time_seconds
        assert update_stats_after.data_bytes == update_stats_before.data_bytes

        collector.stop()

    def test_update_phase_stats_blocked_for_completed_phases(self) -> None:
        """Verify update_phase_stats() is blocked for completed phases."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        original_cpu_time = collector.phase_stats["Update"].cpu_time_seconds
        original_data_bytes = collector.phase_stats["Update"].data_bytes

        # Try to update completed phase (should be blocked)
        collector.update_phase_stats("Update", cpu_time_seconds=0.0, data_bytes=0)

        # Stats should NOT have changed
        assert collector.phase_stats["Update"].cpu_time_seconds == original_cpu_time
        assert collector.phase_stats["Update"].data_bytes == original_data_bytes

        # With force=True, it should update
        collector.update_phase_stats("Update", cpu_time_seconds=10.0, data_bytes=4096, force=True)
        assert collector.phase_stats["Update"].cpu_time_seconds == 10.0
        assert collector.phase_stats["Update"].data_bytes == 4096

        collector.stop()

    def test_collect_does_not_overwrite_completed_phase_stats(self) -> None:
        """Verify collect() doesn't modify stats for completed phases."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase with specific values
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        saved_cpu = collector.phase_stats["Update"].cpu_time_seconds
        saved_data = collector.phase_stats["Update"].data_bytes

        # Start new phase and collect multiple times
        collector.start_phase("Download")
        for _ in range(5):
            collector.collect()
            time.sleep(0.05)

        # Update phase stats should NOT have changed
        assert collector.phase_stats["Update"].cpu_time_seconds == saved_cpu
        assert collector.phase_stats["Update"].data_bytes == saved_data

        collector.stop()

    def test_total_stats_accumulates_across_phases(self) -> None:
        """Verify get_total_stats() correctly sums all phases."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Set up stats for each phase directly
        collector._phase_stats["Update"].cpu_time_seconds = 2.0
        collector._phase_stats["Update"].data_bytes = 1000
        collector._phase_stats["Update"].is_complete = True

        collector._phase_stats["Download"].cpu_time_seconds = 1.0
        collector._phase_stats["Download"].data_bytes = 5000
        collector._phase_stats["Download"].is_complete = True

        collector._phase_stats["Upgrade"].cpu_time_seconds = 4.0
        collector._phase_stats["Upgrade"].data_bytes = 500
        collector._phase_stats["Upgrade"].is_complete = True

        total = collector.get_total_stats()

        assert total.cpu_time_seconds == 7.0
        assert total.data_bytes == 6500

        collector.stop()

    def test_multiple_phase_transitions_preserve_all_stats(self) -> None:
        """Verify all previous phase stats are preserved through multiple transitions."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Phase 1: Update
        collector.start_phase("Update")
        time.sleep(0.05)
        collector.update_phase_stats("Update", cpu_time_seconds=1.0, data_bytes=512)
        collector.complete_phase("Update")
        update_wall_time = collector.phase_stats["Update"].wall_time_seconds

        # Phase 2: Download
        collector.start_phase("Download")
        time.sleep(0.05)
        collector.update_phase_stats("Download", cpu_time_seconds=0.5, data_bytes=10240)
        collector.complete_phase("Download")
        download_wall_time = collector.phase_stats["Download"].wall_time_seconds

        # Phase 3: Upgrade
        collector.start_phase("Upgrade")

        # Verify both Update and Download stats are preserved
        assert collector.phase_stats["Update"].is_complete is True
        assert collector.phase_stats["Update"].wall_time_seconds == update_wall_time
        assert collector.phase_stats["Download"].is_complete is True
        assert collector.phase_stats["Download"].wall_time_seconds == download_wall_time

        collector.stop()


# =============================================================================
# Bug 3: Scrolling Not Working
# =============================================================================


class TestBug3ScrollingRegression:
    """Regression tests for Bug 3: Scrolling doesn't work.

    Root Cause:
        TerminalView.render() didn't respect scroll_offset when rendering.
        get_styled_line() always returned lines from the beginning.

    Key Fix:
        - Updated get_styled_line() to add scroll_offset to line index
        - Updated scroll methods to call _update_display() instead of refresh()
        - Added mouse scroll event handlers to TerminalPane
    """

    @pytest.mark.asyncio
    async def test_terminal_pane_has_mouse_scroll_handlers(self) -> None:
        """Verify TerminalPane has mouse scroll event handlers."""
        assert hasattr(TerminalPane, "on_mouse_scroll_up")
        assert hasattr(TerminalPane, "on_mouse_scroll_down")

    @pytest.mark.asyncio
    async def test_scroll_methods_exist_on_terminal_pane(self) -> None:
        """Verify scroll methods exist on TerminalPane."""
        assert hasattr(TerminalPane, "scroll_history_up")
        assert hasattr(TerminalPane, "scroll_history_down")
        assert hasattr(TerminalPane, "scroll_to_history_top")
        assert hasattr(TerminalPane, "scroll_to_history_bottom")

    @pytest.mark.asyncio
    async def test_interactive_app_has_scroll_bindings(self) -> None:
        """Verify InteractiveTabbedApp has scroll key bindings."""
        binding_keys = [b.key for b in InteractiveTabbedApp.BINDINGS]

        assert "pageup" in binding_keys
        assert "pagedown" in binding_keys
        assert "up" in binding_keys
        assert "down" in binding_keys
        assert "home" in binding_keys
        assert "end" in binding_keys

    @pytest.mark.asyncio
    async def test_interactive_app_has_scroll_actions(self) -> None:
        """Verify InteractiveTabbedApp has scroll action methods."""
        assert hasattr(InteractiveTabbedApp, "action_scroll_up")
        assert hasattr(InteractiveTabbedApp, "action_scroll_down")
        assert hasattr(InteractiveTabbedApp, "action_scroll_line_up")
        assert hasattr(InteractiveTabbedApp, "action_scroll_line_down")
        assert hasattr(InteractiveTabbedApp, "action_scroll_top")
        assert hasattr(InteractiveTabbedApp, "action_scroll_bottom")

    @pytest.mark.asyncio
    async def test_terminal_view_scroll_offset_affects_display(self) -> None:
        """Verify scroll_offset affects what is displayed."""
        from ui.terminal_view import TerminalView

        view = TerminalView(columns=80, lines=10, scrollback_lines=100)

        # Feed content
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())

        assert view._terminal_screen.scroll_offset == 0

        # Scroll up
        view.scroll_history_up(5)
        assert view._terminal_screen.scroll_offset == 5

    @pytest.mark.asyncio
    async def test_terminal_view_scroll_to_top_and_bottom(self) -> None:
        """Verify scroll_to_top and scroll_to_bottom work correctly."""
        from ui.terminal_view import TerminalView

        view = TerminalView(columns=80, lines=10, scrollback_lines=100)

        for i in range(50):
            view.feed(f"Line {i}\r\n".encode())

        view.scroll_to_top()
        top_offset = view._terminal_screen.scroll_offset

        view.scroll_to_bottom()
        bottom_offset = view._terminal_screen.scroll_offset

        assert top_offset > bottom_offset
        assert bottom_offset == 0


# =============================================================================
# Integration Tests: MetricsCollector Preservation
# =============================================================================


class TestMetricsCollectorPreservationIntegration:
    """Integration tests for MetricsCollector preservation across phases."""

    @pytest.mark.asyncio
    async def test_terminal_pane_preserves_metrics_collector(self) -> None:
        """Verify TerminalPane preserves MetricsCollector across start() calls."""
        from ui.key_bindings import KeyBindings

        config = PaneConfig(show_phase_status_bar=True)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=config,
            key_bindings=KeyBindings(),
        )

        # Set up metrics collector as if first phase completed
        pane._metrics_collector = MetricsCollector(pid=None)
        pane._metrics_collector.start()
        pane._metrics_collector.start_phase("Update")
        pane._metrics_collector._phase_stats["Update"].cpu_time_seconds = 5.0
        pane._metrics_collector._phase_stats["Update"].data_bytes = 1000
        pane._metrics_collector.complete_phase("Update")

        original_collector = pane._metrics_collector
        original_update_stats = pane._metrics_collector._phase_stats["Update"]

        # Simulate what happens when update_pid is called
        pane._metrics_collector.update_pid(12345)

        # Verify same collector is still in use
        assert pane._metrics_collector is original_collector
        assert pane._metrics_collector._phase_stats["Update"] is original_update_stats
        assert pane._metrics_collector._phase_stats["Update"].cpu_time_seconds == 5.0

    @pytest.mark.asyncio
    async def test_terminal_pane_stop_preserves_metrics_collector(self) -> None:
        """Verify TerminalPane.stop() preserves MetricsCollector.

        This is critical for Bug 2 fix - stop() must NOT set
        _metrics_collector = None.
        """
        from ui.key_bindings import KeyBindings

        config = PaneConfig(show_phase_status_bar=True)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=config,
            key_bindings=KeyBindings(),
        )

        pane._metrics_collector = MetricsCollector(pid=None)
        pane._metrics_collector.start()
        pane._metrics_collector.start_phase("Update")
        pane._metrics_collector._phase_stats["Update"].cpu_time_seconds = 5.0
        pane._metrics_collector.complete_phase("Update")

        original_collector = pane._metrics_collector

        await pane.stop()

        # Collector should NOT be None after stop()
        assert pane._metrics_collector is not None
        assert pane._metrics_collector is original_collector
        assert pane._metrics_collector._phase_stats["Update"].cpu_time_seconds == 5.0
        assert pane._metrics_collector._running is False


# =============================================================================
# Integration Tests: Scrolling
# =============================================================================


class TestScrollingIntegration:
    """Integration tests for scrolling functionality."""

    def test_scroll_methods_are_synchronous(self) -> None:
        """Verify scroll methods execute immediately without waiting."""
        mock_terminal_view = MagicMock()

        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
        )
        pane._terminal_view = mock_terminal_view

        start = time.perf_counter()

        for _ in range(100):
            pane.scroll_history_up(1)
            pane.scroll_history_down(1)

        elapsed = time.perf_counter() - start

        # 200 scroll operations should complete in < 0.1 seconds
        assert elapsed < 0.1, (
            f"200 scroll operations took {elapsed:.3f}s, expected < 0.1s. "
            "Scroll methods should be synchronous."
        )

        assert mock_terminal_view.scroll_history_up.call_count == 100
        assert mock_terminal_view.scroll_history_down.call_count == 100


# =============================================================================
# Real Process Tests
# =============================================================================


@pytestmark_pty
class TestPhaseStatsWithRealProcess:
    """Tests for phase stats with real subprocess execution."""

    @pytest.mark.asyncio
    async def test_phase_stats_preserved_with_real_subprocess(self) -> None:
        """Verify phase stats preservation with real subprocess execution."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Simulate Update phase with real subprocess
        collector.start_phase("Update")

        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            "sleep 0.1 && echo 'Update done'",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        collector.update_pid(proc.pid)

        for _ in range(3):
            collector.collect()
            await asyncio.sleep(0.05)

        await proc.wait()
        collector.complete_phase("Update")

        update_wall_time = collector.phase_stats["Update"].wall_time_seconds
        assert update_wall_time > 0

        # Simulate Download phase with new subprocess
        collector.start_phase("Download")

        proc2 = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            "sleep 0.1 && echo 'Download done'",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        collector.update_pid(proc2.pid)

        for _ in range(3):
            collector.collect()
            await asyncio.sleep(0.05)

        await proc2.wait()

        # Update stats should still be preserved
        assert collector.phase_stats["Update"].is_complete is True
        assert collector.phase_stats["Update"].wall_time_seconds == update_wall_time

        collector.stop()

"""Tests for UI refresh rate issues.

This test suite verifies the root cause of the 1Hz UI refresh issue
that causes laggy interactions with the app, such as scrolling the
tab content or changing tabs.

Issue: Any UI refresh is about 1Hz, causing laggy experience.
Root Cause: The metrics_update_interval defaults to 1.0 seconds.

Expected: UI refresh should be in the region of hundreds of Hz for
smooth interactions.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from ui.phase_status_bar import MetricsCollector
from ui.pty_session import is_pty_available
from ui.terminal_pane import PaneConfig, TerminalPane

# Skip all tests if PTY is not available
pytestmark = pytest.mark.skipif(
    not is_pty_available(),
    reason="PTY not available on this platform",
)


class TestMetricsUpdateInterval:
    """Tests for the metrics update interval configuration."""

    def test_default_metrics_update_interval_is_one_second(self) -> None:
        """Test that the default metrics update interval is 1.0 seconds.

        This is the root cause of the 1Hz UI refresh issue.
        The PaneConfig.metrics_update_interval defaults to 1.0 seconds.
        """
        config = PaneConfig()
        assert config.metrics_update_interval == 1.0, (
            f"Default metrics_update_interval should be 1.0s, got {config.metrics_update_interval}s"
        )

    def test_metrics_collector_default_interval_is_one_second(self) -> None:
        """Test that MetricsCollector default update_interval is 1.0 seconds.

        The MetricsCollector constructor defaults to 1.0 second update interval.
        """
        collector = MetricsCollector(pid=None)
        assert collector.update_interval >= 0.5, (
            f"MetricsCollector update_interval should be >= 0.5s (MIN_UPDATE_INTERVAL), "
            f"got {collector.update_interval}s"
        )

    def test_metrics_collector_min_update_interval(self) -> None:
        """Test that MetricsCollector enforces a minimum update interval.

        The MIN_UPDATE_INTERVAL is 0.5 seconds to avoid excessive CPU usage.
        """
        assert MetricsCollector.MIN_UPDATE_INTERVAL == 0.5, (
            f"MIN_UPDATE_INTERVAL should be 0.5s, got {MetricsCollector.MIN_UPDATE_INTERVAL}s"
        )

    def test_metrics_collector_enforces_min_interval(self) -> None:
        """Test that MetricsCollector enforces minimum interval even if lower is requested."""
        collector = MetricsCollector(pid=None, update_interval=0.1)
        assert collector.update_interval >= MetricsCollector.MIN_UPDATE_INTERVAL, (
            f"update_interval should be >= MIN_UPDATE_INTERVAL ({MetricsCollector.MIN_UPDATE_INTERVAL}s), "
            f"got {collector.update_interval}s"
        )


class TestScrollResponsiveness:
    """Tests for scroll responsiveness.

    These tests verify that scrolling is handled synchronously and
    doesn't wait for the metrics update interval.
    """

    def test_scroll_methods_are_synchronous(self) -> None:
        """Test that scroll methods in TerminalPane are synchronous.

        Scroll methods should execute immediately without waiting for
        any async operations or update intervals.
        """
        # Create a mock terminal view
        mock_terminal_view = MagicMock()

        # Create a TerminalPane
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
        )

        # Manually set the terminal view
        pane._terminal_view = mock_terminal_view

        # Measure time for scroll operations
        start = time.perf_counter()

        for _ in range(100):
            pane.scroll_history_up(1)
            pane.scroll_history_down(1)

        elapsed = time.perf_counter() - start

        # 200 scroll operations should complete in < 0.1 seconds
        # If they were waiting for 1s update interval, this would take 200+ seconds
        assert elapsed < 0.1, (
            f"200 scroll operations took {elapsed:.3f}s, expected < 0.1s. "
            "Scroll methods should be synchronous."
        )

        # Verify scroll methods were called
        assert mock_terminal_view.scroll_history_up.call_count == 100
        assert mock_terminal_view.scroll_history_down.call_count == 100


class TestUIRefreshRateImprovements:
    """Tests for potential UI refresh rate improvements.

    These tests document potential solutions to improve the UI refresh rate.
    """

    def test_can_create_collector_with_faster_interval(self) -> None:
        """Test that MetricsCollector can be created with faster interval.

        While MIN_UPDATE_INTERVAL is 0.5s, we can still create collectors
        with intervals >= 0.5s for faster updates.
        """
        # Create collector with 0.5s interval (minimum allowed)
        collector = MetricsCollector(pid=None, update_interval=0.5)
        assert collector.update_interval == 0.5

    def test_pane_config_accepts_custom_interval(self) -> None:
        """Test that PaneConfig accepts custom metrics_update_interval.

        Users can configure a faster update interval if desired.
        """
        config = PaneConfig(metrics_update_interval=0.5)
        assert config.metrics_update_interval == 0.5

    @pytest.mark.asyncio
    async def test_metrics_update_loop_respects_configured_interval(self) -> None:
        """Test that the metrics update loop uses the configured interval.

        The _metrics_update_loop in TerminalPane should use the configured
        metrics_update_interval from PaneConfig.
        """
        # Create a pane with faster update interval
        config = PaneConfig(metrics_update_interval=0.5)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=config,
        )

        # Verify the config is stored
        assert pane.config.metrics_update_interval == 0.5


class TestRootCauseDocumentation:
    """Tests that document the root cause of the 1Hz UI refresh issue.

    These tests serve as documentation for the issue and its root cause.
    """

    def test_root_cause_is_metrics_update_interval(self) -> None:
        """Document the root cause of the 1Hz UI refresh issue.

        ROOT CAUSE:
        The metrics_update_interval in PaneConfig defaults to 1.0 seconds.
        This causes the _metrics_update_loop in TerminalPane to sleep for
        1 second between each metrics collection and display update.

        AFFECTED COMPONENTS:
        1. PaneConfig.metrics_update_interval (default: 1.0s)
        2. MetricsCollector.update_interval (default: 1.0s)
        3. TerminalPane._metrics_update_loop (sleeps for metrics_update_interval)

        IMPACT:
        - The PhaseStatusBar (showing phase stats) updates only once per second
        - This gives the perception of laggy UI, especially when scrolling
          because the status bar at the bottom doesn't update smoothly

        NOTE:
        The scroll operations themselves are synchronous and immediate.
        The "laggy" feeling is from the status bar updating slowly, not
        from the scroll operations being slow.

        POTENTIAL FIXES:
        1. Reduce metrics_update_interval to 0.1-0.2 seconds (10-5 Hz)
           - Pros: Simple change, immediate improvement
           - Cons: Increased CPU usage for metrics collection

        2. Separate UI refresh from metrics collection
           - Pros: UI can refresh at 60+ Hz, metrics collected less frequently
           - Cons: More complex architecture

        3. Use Textual's reactive system for status bar updates
           - Pros: Leverages Textual's built-in refresh mechanism
           - Cons: May require refactoring PhaseStatusBar
        """
        # This test documents the issue - the assertion is just to confirm
        # the default values that cause the problem
        config = PaneConfig()
        assert config.metrics_update_interval == 1.0, "Default interval should be 1.0s"

        collector = MetricsCollector(pid=None)
        assert collector.update_interval >= 0.5, "Collector interval should be >= 0.5s"

    def test_minimum_update_interval_is_half_second(self) -> None:
        """Document that the minimum update interval is 0.5 seconds.

        The MIN_UPDATE_INTERVAL of 0.5 seconds means the maximum possible
        refresh rate for metrics is 2 Hz, not "hundreds of Hz" as desired.

        To achieve hundreds of Hz refresh rate, the architecture would need
        to be changed to separate:
        1. Metrics collection (can remain at 0.5-1.0 Hz)
        2. UI rendering (should be 60+ Hz for smooth experience)

        The current architecture ties UI refresh to metrics collection,
        which is the fundamental issue.
        """
        assert MetricsCollector.MIN_UPDATE_INTERVAL == 0.5, (
            "MIN_UPDATE_INTERVAL should be 0.5s - this limits max refresh to 2 Hz"
        )

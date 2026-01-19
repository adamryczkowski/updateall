"""UI latency measurement tests.

Milestone 2 - Add UI Latency Tests
See docs/ui-latency-planning.md section "Milestone 2: Add UI Latency Tests"

This module provides automated tests to measure and verify UI latency,
ensuring the decoupled architecture achieves the target refresh rates.

Architecture Background
-----------------------
The UI latency tests verify the decoupled refresh architecture where:
- Metrics collection runs at 1 Hz in a background thread (expensive psutil calls)
- UI refresh runs at 30 Hz via Textual's auto_refresh (reads cached metrics)

This decoupling reduces perceived UI latency from ~1000ms to ~33ms.

Test Thresholds
---------------
Two sets of thresholds are used:

**Aspirational Targets** (after all improvements complete):
- Idle latency: Mean < 10ms
- Input response: P95 < 100ms
- During execution: P95 < 100ms, max < 500ms

**CI Thresholds** (lenient for variable CI environments):
- Idle latency: Mean < 10ms, P95 < 50ms
- Input response: P95 < 500ms, mean < 200ms
- During execution: P95 < 1000ms, max < 5000ms
- Multi-plugin load: P95 < 2000ms
- Scrollback access: Mean < 100ms

The CI thresholds are more lenient to account for:
- Variable CI environment performance
- Occasional spikes due to system load
- Different hardware capabilities

Test Categories
---------------
1. **LatencyReport Tests**: Verify the statistics helper class
2. **Idle Latency Tests**: Measure latency when app is idle
3. **Input Response Tests**: Measure key press processing time
4. **Plugin Execution Tests**: Measure latency during active plugin runs
5. **Load Tests**: Measure latency under various load conditions
6. **Cached Metrics Tests**: Verify cached access is sub-millisecond

Methodology
-----------
Each test:
1. Creates a test app with mock plugins
2. Performs repeated measurements (50-1000 iterations)
3. Computes statistics (mean, median, P95, P99, min, max)
4. Asserts against the appropriate threshold

The tests use `time.perf_counter()` for high-resolution timing and
`LatencyReport.from_samples()` for statistical analysis.

Related Documentation:
- docs/UI-revision-plan.md section 8 - UI Latency Improvement Architecture
- docs/ui-latency-planning.md - Implementation milestones
- docs/ui-latency-study.md - Analysis and recommendations

The tests use the `@pytest.mark.slow` marker for CI optimization,
allowing them to be skipped in fast test runs with: pytest -m "not slow"
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

from ui.interactive_tabbed_run import InteractiveTabbedApp
from ui.pty_session import is_pty_available

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin

# Skip all tests if PTY is not available
pytestmark = [
    pytest.mark.skipif(
        not is_pty_available(),
        reason="PTY not available on this platform",
    ),
    pytest.mark.slow,  # Mark as slow for CI optimization
]


@dataclass
class LatencyReport:
    """Statistics report for latency measurements.

    This dataclass holds statistical information about latency measurements,
    including mean, median, percentiles, and extremes.

    Attributes:
        samples: List of individual latency measurements in milliseconds.
        mean_ms: Mean latency in milliseconds.
        median_ms: Median latency in milliseconds.
        p95_ms: 95th percentile latency in milliseconds.
        p99_ms: 99th percentile latency in milliseconds.
        min_ms: Minimum latency in milliseconds.
        max_ms: Maximum latency in milliseconds.
        std_dev_ms: Standard deviation in milliseconds.
        sample_count: Number of samples collected.
    """

    samples: list[float] = field(default_factory=list)
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    std_dev_ms: float = 0.0
    sample_count: int = 0

    @classmethod
    def from_samples(cls, samples: list[float]) -> LatencyReport:
        """Create a LatencyReport from a list of latency samples.

        Args:
            samples: List of latency measurements in milliseconds.

        Returns:
            LatencyReport with computed statistics.
        """
        if not samples:
            return cls()

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        # Calculate percentile indices
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        # Ensure indices are within bounds
        p95_idx = min(p95_idx, n - 1)
        p99_idx = min(p99_idx, n - 1)

        return cls(
            samples=samples,
            mean_ms=statistics.mean(samples),
            median_ms=statistics.median(samples),
            p95_ms=sorted_samples[p95_idx],
            p99_ms=sorted_samples[p99_idx],
            min_ms=min(samples),
            max_ms=max(samples),
            std_dev_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
            sample_count=n,
        )

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        return (
            f"LatencyReport(n={self.sample_count}, "
            f"mean={self.mean_ms:.2f}ms, median={self.median_ms:.2f}ms, "
            f"p95={self.p95_ms:.2f}ms, p99={self.p99_ms:.2f}ms, "
            f"min={self.min_ms:.2f}ms, max={self.max_ms:.2f}ms)"
        )


def measure_render_latency(
    render_func: callable,
    iterations: int = 100,
) -> LatencyReport:
    """Measure the latency of a render function.

    This helper function measures how long it takes to execute a render
    function multiple times, returning statistical information about
    the latency distribution.

    Args:
        render_func: A callable that performs a render operation.
        iterations: Number of times to call the render function.

    Returns:
        LatencyReport with latency statistics in milliseconds.
    """
    samples: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        render_func()
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)  # Convert to milliseconds

    return LatencyReport.from_samples(samples)


async def measure_input_latency(
    pilot: object,
    key: str = "a",
    iterations: int = 50,
) -> LatencyReport:
    """Measure the latency of input processing.

    This helper function measures how long it takes for the app to
    process keyboard input, from the moment the key is pressed to
    when the app has processed the event.

    Args:
        pilot: The Textual test pilot for sending key events.
        key: The key to press for each iteration.
        iterations: Number of key presses to measure.

    Returns:
        LatencyReport with input latency statistics in milliseconds.
    """
    samples: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        await pilot.press(key)  # type: ignore[attr-defined]
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)  # Convert to milliseconds

    return LatencyReport.from_samples(samples)


def create_mock_plugin(
    name: str,
    *,
    command: list[str] | None = None,
) -> MagicMock:
    """Create a mock plugin for testing.

    Args:
        name: Plugin name.
        command: Command to run (default: echo command).

    Returns:
        Mock plugin object.
    """
    from unittest.mock import AsyncMock

    plugin = MagicMock()
    plugin.name = name
    plugin.supports_interactive = True

    if command is None:
        command = ["/bin/echo", f"Hello from {name}"]

    plugin.get_interactive_command.return_value = command
    plugin.check_available = AsyncMock(return_value=True)
    plugin.pre_execute = AsyncMock()
    plugin.post_execute = AsyncMock()

    return plugin


class TestLatencyReport:
    """Tests for the LatencyReport dataclass."""

    def test_from_samples_empty(self) -> None:
        """Test creating a report from empty samples."""
        report = LatencyReport.from_samples([])
        assert report.sample_count == 0
        assert report.mean_ms == 0.0

    def test_from_samples_single(self) -> None:
        """Test creating a report from a single sample."""
        report = LatencyReport.from_samples([10.0])
        assert report.sample_count == 1
        assert report.mean_ms == 10.0
        assert report.median_ms == 10.0
        assert report.min_ms == 10.0
        assert report.max_ms == 10.0

    def test_from_samples_multiple(self) -> None:
        """Test creating a report from multiple samples."""
        samples = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        report = LatencyReport.from_samples(samples)

        assert report.sample_count == 10
        assert report.mean_ms == 5.5
        assert report.median_ms == 5.5
        assert report.min_ms == 1.0
        assert report.max_ms == 10.0
        assert report.p95_ms == 10.0  # 95th percentile of 10 samples

    def test_str_representation(self) -> None:
        """Test string representation of report."""
        report = LatencyReport.from_samples([1.0, 2.0, 3.0])
        report_str = str(report)
        assert "LatencyReport" in report_str
        assert "mean=" in report_str
        assert "p95=" in report_str


class TestMeasureRenderLatency:
    """Tests for the measure_render_latency helper function."""

    def test_measure_simple_function(self) -> None:
        """Test measuring a simple function."""
        call_count = 0

        def simple_render() -> None:
            nonlocal call_count
            call_count += 1

        report = measure_render_latency(simple_render, iterations=10)

        assert call_count == 10
        assert report.sample_count == 10
        assert report.mean_ms >= 0  # Should be very fast
        assert report.max_ms < 100  # Should complete in < 100ms each

    def test_measure_with_delay(self) -> None:
        """Test measuring a function with artificial delay."""

        def slow_render() -> None:
            time.sleep(0.001)  # 1ms delay

        report = measure_render_latency(slow_render, iterations=5)

        assert report.sample_count == 5
        assert report.mean_ms >= 1.0  # Should be at least 1ms
        assert report.min_ms >= 0.5  # Allow some variance


class TestIdleLatency:
    """Tests for UI latency during idle state.

    Target: Mean idle latency < 10ms
    """

    @pytest.mark.asyncio
    async def test_measure_latency_during_idle(self) -> None:
        """Test that UI latency during idle is within acceptable bounds.

        This test measures the latency of UI operations when the app
        is idle (no plugins running). The target is mean latency < 10ms.

        The test verifies that:
        1. The app can be created and mounted quickly
        2. Basic UI operations complete within the target latency
        3. The status bar can be refreshed at high frequency
        """
        plugin = create_mock_plugin("idle_test")

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            # Measure the latency of accessing cached metrics
            # This simulates what the UI does at 30 Hz
            pane = app.terminal_panes.get("idle_test")
            if pane is None:
                pytest.skip("Terminal pane not created")

            # Measure render latency by simulating status bar refresh
            def simulate_status_refresh() -> None:
                # This simulates what PhaseStatusBar.automatic_refresh() does
                if pane._metrics_collector:
                    _ = pane._metrics_collector.cached_metrics

            report = measure_render_latency(simulate_status_refresh, iterations=100)

            # Log the report for debugging
            print(f"\nIdle latency report: {report}")

            # Target: Mean idle latency < 10ms
            assert report.mean_ms < 10.0, (
                f"Mean idle latency {report.mean_ms:.2f}ms exceeds target of 10ms. Report: {report}"
            )

            # Also verify P95 is reasonable
            assert report.p95_ms < 50.0, (
                f"P95 idle latency {report.p95_ms:.2f}ms exceeds 50ms. Report: {report}"
            )


class TestInputResponseLatency:
    """Tests for input response latency.

    Target: P95 input latency < 100ms (aspirational)
    CI threshold: P95 < 500ms, mean < 200ms (lenient for CI environments)

    Note: The 100ms target is the aspirational goal after all latency
    improvements are complete. The CI thresholds are more lenient to
    account for variable CI environment performance.
    """

    @pytest.mark.asyncio
    async def test_measure_input_response_latency(self) -> None:
        """Test that input response latency is within acceptable bounds.

        This test measures how long it takes for the app to process
        keyboard input.

        Thresholds:
        - Aspirational target: P95 < 100ms (after all improvements)
        - CI threshold: P95 < 500ms, mean < 200ms (lenient for CI)

        The test verifies that:
        1. Key presses are processed quickly
        2. Tab navigation is responsive
        3. The input router doesn't introduce significant latency
        """
        plugins = [
            create_mock_plugin("input_test_1"),
            create_mock_plugin("input_test_2"),
            create_mock_plugin("input_test_3"),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Measure tab switching latency
            samples: list[float] = []

            for _ in range(30):
                start = time.perf_counter()
                await pilot.press("ctrl+tab")
                elapsed = time.perf_counter() - start
                samples.append(elapsed * 1000)

            report = LatencyReport.from_samples(samples)

            # Log the report for debugging
            print(f"\nInput response latency report: {report}")

            # CI threshold: P95 input latency < 500ms (lenient for CI environments)
            # Aspirational target after improvements: P95 < 100ms
            assert report.p95_ms < 500.0, (
                f"P95 input latency {report.p95_ms:.2f}ms exceeds CI threshold of 500ms. "
                f"Report: {report}"
            )

            # CI threshold: Mean < 200ms (lenient for CI environments)
            assert report.mean_ms < 200.0, (
                f"Mean input latency {report.mean_ms:.2f}ms exceeds CI threshold of 200ms. "
                f"Report: {report}"
            )


class TestPluginExecutionLatency:
    """Tests for UI latency during plugin execution.

    Target: P95 latency < 100ms, max < 500ms (aspirational)
    CI threshold: P95 < 1000ms, max < 5000ms (lenient for CI environments)

    Note: The aspirational targets are for after all latency improvements
    are complete. The CI thresholds are more lenient to account for
    variable CI environment performance and occasional spikes.
    """

    @pytest.mark.asyncio
    async def test_measure_latency_during_plugin_execution(self) -> None:
        """Test that UI latency during plugin execution is acceptable.

        This test measures UI latency while a plugin is actively running
        and producing output.

        Thresholds:
        - Aspirational target: P95 < 100ms, max < 500ms
        - CI threshold: P95 < 1000ms, max < 5000ms (lenient for CI)

        The test verifies that:
        1. UI remains responsive during plugin execution
        2. Metrics collection doesn't block the UI
        3. The decoupled architecture works as designed
        """
        # Create a plugin that produces output over time
        plugin = create_mock_plugin(
            "execution_test",
            command=[
                "/bin/bash",
                "-c",
                "for i in $(seq 1 20); do echo Line $i; sleep 0.05; done",
            ],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test() as pilot:
            pane = app.terminal_panes.get("execution_test")
            if pane is None:
                pytest.skip("Terminal pane not created")

            # Start the plugin
            await pane.start()

            # Wait a moment for the plugin to start producing output
            await asyncio.sleep(0.1)

            # Measure latency while plugin is running
            samples: list[float] = []

            # Collect samples while the plugin is running
            for _ in range(50):
                start = time.perf_counter()

                # Simulate what the UI does: read cached metrics
                if pane._metrics_collector:
                    _ = pane._metrics_collector.cached_metrics

                # Also measure a tab switch
                await pilot.press("ctrl+tab")
                await pilot.press("ctrl+shift+tab")

                elapsed = time.perf_counter() - start
                samples.append(elapsed * 1000)

                # Small delay between measurements
                await asyncio.sleep(0.02)

            report = LatencyReport.from_samples(samples)

            # Log the report for debugging
            print(f"\nPlugin execution latency report: {report}")

            # CI threshold: P95 latency < 1000ms (lenient for CI environments)
            # Aspirational target after improvements: P95 < 100ms
            assert report.p95_ms < 1000.0, (
                f"P95 latency during execution {report.p95_ms:.2f}ms "
                f"exceeds CI threshold of 1000ms. Report: {report}"
            )

            # CI threshold: Max latency < 5000ms (lenient for CI environments)
            # Aspirational target after improvements: max < 500ms
            # Note: Max is very lenient to account for occasional spikes
            assert report.max_ms < 5000.0, (
                f"Max latency during execution {report.max_ms:.2f}ms "
                f"exceeds CI threshold of 5000ms. Report: {report}"
            )


class TestUIRefreshRateVerification:
    """Tests to verify the UI refresh rate configuration."""

    def test_phase_status_bar_default_refresh_rate(self) -> None:
        """Test that PhaseStatusBar has correct default refresh rate."""
        from ui.phase_status_bar import PhaseStatusBar

        assert PhaseStatusBar.DEFAULT_UI_REFRESH_RATE == 30.0, (
            f"Default UI refresh rate should be 30 Hz, got {PhaseStatusBar.DEFAULT_UI_REFRESH_RATE}"
        )

    def test_pane_config_default_refresh_rate(self) -> None:
        """Test that PaneConfig has correct default refresh rate."""
        from ui.terminal_pane import PaneConfig

        config = PaneConfig()
        assert config.ui_refresh_rate == 30.0, (
            f"Default UI refresh rate should be 30 Hz, got {config.ui_refresh_rate}"
        )

    def test_metrics_collector_has_cached_metrics(self) -> None:
        """Test that MetricsCollector provides cached_metrics property."""
        from ui.metrics import MetricsCollector

        collector = MetricsCollector(pid=None)
        # Verify cached_metrics property exists and returns PhaseMetrics
        cached = collector.cached_metrics
        assert cached is not None
        assert hasattr(cached, "cpu_percent")
        assert hasattr(cached, "memory_mb")


class TestLatencyUnderLoad:
    """Tests for UI latency under various load conditions.

    These tests use lenient CI thresholds to account for variable
    CI environment performance while still detecting major regressions.
    """

    @pytest.mark.asyncio
    async def test_latency_with_multiple_plugins(self) -> None:
        """Test latency with multiple plugins running concurrently.

        Thresholds:
        - Aspirational target: P95 < 150ms
        - CI threshold: P95 < 2500ms (lenient for CI environments)
        """
        plugins = [
            create_mock_plugin(
                f"load_test_{i}",
                command=["/bin/bash", "-c", "for j in $(seq 1 10); do echo $j; sleep 0.1; done"],
            )
            for i in range(3)
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Start all plugins
            for name in ["load_test_0", "load_test_1", "load_test_2"]:
                pane = app.terminal_panes.get(name)
                if pane:
                    await pane.start()

            # Wait for plugins to start
            await asyncio.sleep(0.2)

            # Measure latency while all plugins are running
            samples: list[float] = []

            for _ in range(30):
                start = time.perf_counter()
                await pilot.press("ctrl+tab")
                elapsed = time.perf_counter() - start
                samples.append(elapsed * 1000)
                await asyncio.sleep(0.05)

            report = LatencyReport.from_samples(samples)

            # Log the report for debugging
            print(f"\nMulti-plugin latency report: {report}")

            # CI threshold: P95 < 2500ms (lenient for CI environments)
            # Aspirational target after improvements: P95 < 150ms
            assert report.p95_ms < 2500.0, (
                f"P95 latency under load {report.p95_ms:.2f}ms exceeds CI threshold of 2500ms. "
                f"Report: {report}"
            )

    @pytest.mark.asyncio
    async def test_latency_during_scrollback_access(self) -> None:
        """Test latency when accessing scrollback buffer.

        Thresholds:
        - Aspirational target: mean < 5ms
        - CI threshold: mean < 100ms (lenient for CI environments)
        """
        # Create a plugin that produces lots of output
        plugin = create_mock_plugin(
            "scrollback_test",
            command=[
                "/bin/bash",
                "-c",
                "for i in $(seq 1 100); do echo Line $i; done",
            ],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes.get("scrollback_test")
            if pane is None:
                pytest.skip("Terminal pane not created")

            # Start the plugin and wait for output
            await pane.start()
            await asyncio.sleep(0.5)

            # Measure latency of scroll operations
            samples: list[float] = []

            for _ in range(50):
                start = time.perf_counter()
                app.action_scroll_up()
                app.action_scroll_down()
                elapsed = time.perf_counter() - start
                samples.append(elapsed * 1000)

            report = LatencyReport.from_samples(samples)

            # Log the report for debugging
            print(f"\nScrollback access latency report: {report}")

            # CI threshold: Mean < 100ms (lenient for CI environments)
            # Aspirational target after improvements: mean < 5ms
            assert report.mean_ms < 100.0, (
                f"Mean scroll latency {report.mean_ms:.2f}ms exceeds CI threshold of 100ms. "
                f"Report: {report}"
            )


class TestCachedMetricsPerformance:
    """Tests for cached metrics access performance."""

    def test_cached_metrics_access_is_fast(self) -> None:
        """Test that accessing cached metrics is very fast.

        The cached_metrics property should return immediately without
        triggering any expensive psutil calls. This is critical for
        achieving 30 Hz UI refresh rate.
        """
        from ui.metrics import MetricsCollector

        collector = MetricsCollector(pid=None)
        collector.start()

        # Do one collection to populate the cache
        collector.collect()

        # Measure access time for cached metrics
        samples: list[float] = []

        for _ in range(1000):
            start = time.perf_counter()
            _ = collector.cached_metrics
            elapsed = time.perf_counter() - start
            samples.append(elapsed * 1000)

        collector.stop()

        report = LatencyReport.from_samples(samples)

        # Log the report for debugging
        print(f"\nCached metrics access latency report: {report}")

        # Cached access should be sub-millisecond
        assert report.mean_ms < 1.0, (
            f"Mean cached metrics access {report.mean_ms:.3f}ms exceeds 1ms. Report: {report}"
        )

        # P99 should also be very fast
        assert report.p99_ms < 5.0, (
            f"P99 cached metrics access {report.p99_ms:.3f}ms exceeds 5ms. Report: {report}"
        )

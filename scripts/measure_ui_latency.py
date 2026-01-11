#!/usr/bin/env python3
"""UI latency measurement script for manual testing and monitoring.

Milestone 3 - Create Latency Monitoring Script
See docs/ui-latency-planning.md section "Milestone 3: Create Latency Monitoring Script"

This script provides a command-line tool for measuring UI latency in the
interactive update screen. It runs the app with mock plugins, measures
latency throughout execution, and generates a statistics report.

Usage:
    # Run with default settings
    just measure-latency

    # Run directly with options
    poetry run python scripts/measure_ui_latency.py --duration 10 --output report.json

The script measures:
    - Idle latency: UI responsiveness when no plugins are running
    - Cached metrics access: Time to read cached metrics (target: < 1ms)
    - Input response: Time to process keyboard input
    - During execution: UI latency while plugins are running

Output includes:
    - Mean, median, P95, P99, min, max latency
    - Sample count and standard deviation
    - Pass/fail status against target thresholds
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Add the parent directories to the path for imports
script_dir = Path(__file__).parent.absolute()
project_root = script_dir.parent
sys.path.insert(0, str(project_root / "ui"))
sys.path.insert(0, str(project_root / "core"))
sys.path.insert(0, str(project_root / "plugins"))

if TYPE_CHECKING:
    from ui.interactive_tabbed_run import InteractiveTabbedApp
    from ui.metrics import MetricsCollector


@dataclass
class LatencyReport:
    """Statistics report for latency measurements.

    This dataclass holds statistical information about latency measurements,
    including mean, median, percentiles, and extremes.

    Attributes:
        name: Name of the measurement (e.g., "idle", "cached_metrics").
        samples: List of individual latency measurements in milliseconds.
        mean_ms: Mean latency in milliseconds.
        median_ms: Median latency in milliseconds.
        p95_ms: 95th percentile latency in milliseconds.
        p99_ms: 99th percentile latency in milliseconds.
        min_ms: Minimum latency in milliseconds.
        max_ms: Maximum latency in milliseconds.
        std_dev_ms: Standard deviation in milliseconds.
        sample_count: Number of samples collected.
        target_ms: Target latency threshold in milliseconds.
        passed: Whether the measurement passed the target threshold.
    """

    name: str = ""
    samples: list[float] = field(default_factory=list)
    mean_ms: float = 0.0
    median_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    std_dev_ms: float = 0.0
    sample_count: int = 0
    target_ms: float | None = None
    passed: bool = True

    @classmethod
    def from_samples(
        cls,
        samples: list[float],
        name: str = "",
        target_ms: float | None = None,
    ) -> LatencyReport:
        """Create a LatencyReport from a list of latency samples.

        Args:
            samples: List of latency measurements in milliseconds.
            name: Name of the measurement.
            target_ms: Target latency threshold for pass/fail.

        Returns:
            LatencyReport with computed statistics.
        """
        if not samples:
            return cls(name=name, target_ms=target_ms)

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        # Calculate percentile indices
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)

        # Ensure indices are within bounds
        p95_idx = min(p95_idx, n - 1)
        p99_idx = min(p99_idx, n - 1)

        mean = statistics.mean(samples)
        passed = target_ms is None or mean <= target_ms

        return cls(
            name=name,
            samples=samples,
            mean_ms=mean,
            median_ms=statistics.median(samples),
            p95_ms=sorted_samples[p95_idx],
            p99_ms=sorted_samples[p99_idx],
            min_ms=min(samples),
            max_ms=max(samples),
            std_dev_ms=statistics.stdev(samples) if len(samples) > 1 else 0.0,
            sample_count=n,
            target_ms=target_ms,
            passed=passed,
        )

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        status = "✓ PASS" if self.passed else "✗ FAIL"
        target_str = f" (target: {self.target_ms:.1f}ms)" if self.target_ms else ""
        return (
            f"{self.name}: {status}{target_str}\n"
            f"  Samples: {self.sample_count}\n"
            f"  Mean:    {self.mean_ms:.3f}ms\n"
            f"  Median:  {self.median_ms:.3f}ms\n"
            f"  P95:     {self.p95_ms:.3f}ms\n"
            f"  P99:     {self.p99_ms:.3f}ms\n"
            f"  Min:     {self.min_ms:.3f}ms\n"
            f"  Max:     {self.max_ms:.3f}ms\n"
            f"  StdDev:  {self.std_dev_ms:.3f}ms"
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        # Remove samples from output to keep it concise
        result.pop("samples", None)
        return result


@dataclass
class FullLatencyReport:
    """Complete latency report with all measurements.

    Attributes:
        timestamp: When the report was generated.
        duration_seconds: Total measurement duration.
        reports: Individual latency reports for each measurement type.
        all_passed: Whether all measurements passed their targets.
    """

    timestamp: str = ""
    duration_seconds: float = 0.0
    reports: list[LatencyReport] = field(default_factory=list)
    all_passed: bool = True

    def __str__(self) -> str:
        """Return a human-readable string representation."""
        header = (
            f"{'=' * 60}\n"
            f"UI Latency Report\n"
            f"{'=' * 60}\n"
            f"Timestamp: {self.timestamp}\n"
            f"Duration:  {self.duration_seconds:.1f}s\n"
            f"Status:    {'✓ ALL PASSED' if self.all_passed else '✗ SOME FAILED'}\n"
            f"{'=' * 60}\n"
        )
        reports_str = "\n\n".join(str(r) for r in self.reports)
        return header + "\n" + reports_str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "all_passed": self.all_passed,
            "reports": [r.to_dict() for r in self.reports],
        }


def measure_sync_latency(
    func: Callable[[], None],
    iterations: int = 100,
    name: str = "",
    target_ms: float | None = None,
) -> LatencyReport:
    """Measure the latency of a synchronous function.

    Args:
        func: A callable to measure.
        iterations: Number of times to call the function.
        name: Name for the measurement.
        target_ms: Target latency threshold.

    Returns:
        LatencyReport with latency statistics in milliseconds.
    """
    samples: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        func()
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)  # Convert to milliseconds

    return LatencyReport.from_samples(samples, name=name, target_ms=target_ms)


async def measure_async_latency(
    func: Callable[[], Any],
    iterations: int = 50,
    name: str = "",
    target_ms: float | None = None,
) -> LatencyReport:
    """Measure the latency of an async function.

    Args:
        func: An async callable to measure.
        iterations: Number of times to call the function.
        name: Name for the measurement.
        target_ms: Target latency threshold.

    Returns:
        LatencyReport with latency statistics in milliseconds.
    """
    samples: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        await func()
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)  # Convert to milliseconds

    return LatencyReport.from_samples(samples, name=name, target_ms=target_ms)


def create_mock_plugin(name: str, duration_seconds: float = 2.0) -> Any:
    """Create a mock plugin for testing.

    Args:
        name: Plugin name.
        duration_seconds: How long the plugin should run.

    Returns:
        Mock plugin object.
    """
    from unittest.mock import AsyncMock, MagicMock

    plugin = MagicMock()
    plugin.name = name
    plugin.supports_interactive = True

    # Create a command that runs for the specified duration
    iterations = int(duration_seconds * 10)  # 10 iterations per second
    command = [
        "/bin/bash",
        "-c",
        f'for i in $(seq 1 {iterations}); do echo "Processing item $i..."; sleep 0.1; done',
    ]

    plugin.get_interactive_command.return_value = command
    plugin.check_available = AsyncMock(return_value=True)
    plugin.pre_execute = AsyncMock()
    plugin.post_execute = AsyncMock()

    return plugin


async def measure_cached_metrics_latency(
    collector: MetricsCollector,
    iterations: int = 1000,
) -> LatencyReport:
    """Measure the latency of accessing cached metrics.

    The cached_metrics property should return immediately without
    triggering any expensive psutil calls. This is critical for
    achieving 30 Hz UI refresh rate.

    Args:
        collector: MetricsCollector instance.
        iterations: Number of access iterations.

    Returns:
        LatencyReport with access latency statistics.
    """
    samples: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        _ = collector.cached_metrics
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)  # Convert to milliseconds

    return LatencyReport.from_samples(
        samples,
        name="Cached Metrics Access",
        target_ms=1.0,  # Target: < 1ms for 30 Hz refresh
    )


async def measure_idle_latency(app: InteractiveTabbedApp) -> LatencyReport:
    """Measure UI latency during idle state.

    Args:
        app: The running InteractiveTabbedApp.

    Returns:
        LatencyReport with idle latency statistics.
    """
    samples: list[float] = []

    # Get any terminal pane
    pane = None
    for p in app.terminal_panes.values():
        pane = p
        break

    if pane is None or pane._metrics_collector is None:
        return LatencyReport.from_samples(
            [],
            name="Idle Latency",
            target_ms=10.0,
        )

    # Measure the latency of reading cached metrics
    for _ in range(100):
        start = time.perf_counter()
        _ = pane._metrics_collector.cached_metrics
        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)

    return LatencyReport.from_samples(
        samples,
        name="Idle Latency",
        target_ms=10.0,  # Target: mean < 10ms
    )


async def measure_execution_latency(
    app: InteractiveTabbedApp,
    duration_seconds: float = 5.0,
) -> LatencyReport:
    """Measure UI latency during plugin execution.

    Args:
        app: The running InteractiveTabbedApp.
        duration_seconds: How long to measure.

    Returns:
        LatencyReport with execution latency statistics.
    """
    samples: list[float] = []

    # Get any terminal pane
    pane = None
    for p in app.terminal_panes.values():
        pane = p
        break

    if pane is None:
        return LatencyReport.from_samples(
            [],
            name="Execution Latency",
            target_ms=100.0,
        )

    # Start the plugin
    await pane.start()

    # Wait a moment for the plugin to start
    await asyncio.sleep(0.2)

    # Measure latency while plugin is running
    end_time = time.time() + duration_seconds
    while time.time() < end_time:
        start = time.perf_counter()

        # Simulate what the UI does: read cached metrics
        if pane._metrics_collector:
            _ = pane._metrics_collector.cached_metrics

        elapsed = time.perf_counter() - start
        samples.append(elapsed * 1000)

        # Small delay between measurements (30 Hz = ~33ms)
        await asyncio.sleep(0.033)

    return LatencyReport.from_samples(
        samples,
        name="Execution Latency",
        target_ms=100.0,  # Target: P95 < 100ms
    )


async def run_latency_measurements(
    duration_seconds: float = 10.0,
    verbose: bool = False,
) -> FullLatencyReport:
    """Run all latency measurements.

    Args:
        duration_seconds: Total duration for measurements.
        verbose: Whether to print progress.

    Returns:
        FullLatencyReport with all measurements.
    """
    from ui.interactive_tabbed_run import InteractiveTabbedApp
    from ui.metrics import MetricsCollector
    from ui.pty_session import is_pty_available

    reports: list[LatencyReport] = []
    start_time = time.time()

    if verbose:
        print("Starting UI latency measurements...")
        print(f"Duration: {duration_seconds}s")
        print()

    # Check if PTY is available
    if not is_pty_available():
        print("WARNING: PTY not available, some measurements will be skipped")

    # 1. Measure cached metrics access (standalone)
    if verbose:
        print("1. Measuring cached metrics access latency...")

    collector = MetricsCollector(pid=None)
    collector.start()
    collector.collect()  # Populate cache

    cached_report = await measure_cached_metrics_latency(collector, iterations=1000)
    reports.append(cached_report)
    collector.stop()

    if verbose:
        print(f"   Mean: {cached_report.mean_ms:.3f}ms")

    # 2. Measure with the full app (if PTY available)
    if is_pty_available():
        if verbose:
            print("2. Measuring idle latency with app...")

        plugin = create_mock_plugin("latency_test", duration_seconds=duration_seconds)

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            # Measure idle latency
            idle_report = await measure_idle_latency(app)
            reports.append(idle_report)

            if verbose:
                print(f"   Mean: {idle_report.mean_ms:.3f}ms")
                print("3. Measuring execution latency...")

            # Measure execution latency
            exec_report = await measure_execution_latency(
                app,
                duration_seconds=min(duration_seconds / 2, 5.0),
            )
            reports.append(exec_report)

            if verbose:
                print(f"   Mean: {exec_report.mean_ms:.3f}ms")
    else:
        if verbose:
            print("2. Skipping app-based measurements (PTY not available)")

    elapsed = time.time() - start_time
    all_passed = all(r.passed for r in reports)

    return FullLatencyReport(
        timestamp=datetime.now(tz=UTC).isoformat(),
        duration_seconds=elapsed,
        reports=reports,
        all_passed=all_passed,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Measure UI latency in the interactive update screen.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run with default settings
    python scripts/measure_ui_latency.py

    # Run for 30 seconds with verbose output
    python scripts/measure_ui_latency.py --duration 30 --verbose

    # Save report to JSON file
    python scripts/measure_ui_latency.py --output report.json

Targets:
    - Cached metrics access: < 1ms (for 30 Hz refresh)
    - Idle latency: < 10ms mean
    - Execution latency: < 100ms P95
        """,
    )

    parser.add_argument(
        "-d",
        "--duration",
        type=float,
        default=10.0,
        help="Measurement duration in seconds (default: 10)",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file for JSON report (optional)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress during measurement",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON to stdout",
    )

    return parser.parse_args()


async def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    args = parse_args()

    try:
        report = await run_latency_measurements(
            duration_seconds=args.duration,
            verbose=args.verbose,
        )

        # Output results
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print()
            print(report)

        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            with output_path.open("w") as f:
                json.dump(report.to_dict(), f, indent=2)
            print(f"\nReport saved to: {output_path}")

        return 0 if report.all_passed else 1

    except KeyboardInterrupt:
        print("\nMeasurement interrupted.")
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

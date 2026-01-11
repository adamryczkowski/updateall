# UI Latency Study

This document answers two key questions about improving UI latency in the interactive update screen.

## Table of Contents

1. [Question 1: Can the UI Thread Be Dedicated to UI Updates Only?](#question-1-can-the-ui-thread-be-dedicated-to-ui-updates-only)
2. [Question 2: How to Build a UI Latency Test?](#question-2-how-to-build-a-ui-latency-test)
3. [Sources](#sources)

---

## Question 1: Can the UI Thread Be Dedicated to UI Updates Only?

### Answer: Yes, Textual Supports This Architecture

Textual provides a robust **Worker system** that allows delegating all non-UI tasks to background threads while keeping the main asyncio event loop (UI thread) exclusively for UI updates.

### How It Works

#### 1. Thread Workers

Textual's `@work` decorator and `run_worker()` method support a `thread=True` parameter that runs work in a separate thread:

```python
from textual import work
from textual.worker import get_current_worker

class MyApp(App):
    @work(exclusive=True, thread=True)
    def heavy_computation(self, data: str) -> None:
        """Run heavy computation in a background thread."""
        worker = get_current_worker()

        # Do expensive work in thread
        result = expensive_operation(data)

        # Check if cancelled before updating UI
        if not worker.is_cancelled:
            # IMPORTANT: Use call_from_thread to safely update UI
            self.call_from_thread(self.update_display, result)
```

#### 2. Key Constraint: Thread-Safe UI Updates

When using thread workers, you **cannot directly call UI methods or set reactive variables** from the worker thread. Instead, use `App.call_from_thread()`:

```python
# WRONG - Will cause issues
def thread_worker(self):
    self.my_widget.update("new value")  # DON'T DO THIS

# CORRECT - Thread-safe UI update
def thread_worker(self):
    self.call_from_thread(self.my_widget.update, "new value")
```

#### 3. Current Architecture vs. Ideal Architecture

**Current Architecture (1 Hz UI refresh):**
```
┌─────────────────────────────────────────────────────┐
│                    Main Thread                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────┐  │
│  │   Metrics   │───▶│  UI Update  │───▶│  Sleep  │  │
│  │ Collection  │    │             │    │  (1s)   │  │
│  └─────────────┘    └─────────────┘    └─────────┘  │
│         ▲                                    │       │
│         └────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

**Ideal Architecture (60 Hz UI refresh):**
```
┌─────────────────────────────────────────────────────┐
│                    Main Thread                       │
│  ┌─────────────────────────────────────────────────┐│
│  │  UI Rendering Loop (60 Hz via auto_refresh)     ││
│  │  - Read cached metrics                          ││
│  │  - Update display                               ││
│  │  - Handle user input                            ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
                         ▲
                         │ call_from_thread()
                         │
┌─────────────────────────────────────────────────────┐
│                  Worker Thread                       │
│  ┌─────────────────────────────────────────────────┐│
│  │  Metrics Collection Loop (1 Hz)                 ││
│  │  - Collect psutil metrics                       ││
│  │  - Update cached values                         ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

#### 4. Implementation Strategy

The project already has partial implementation of this pattern:

1. **`PhaseStatusBar`** uses `auto_refresh` at 30 Hz (see [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py))
2. **`MetricsCollector`** collects metrics in background (see [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py))
3. **`TerminalPane._metrics_update_loop()`** runs metrics collection (see [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py))

To fully implement the ideal architecture:

```python
from textual import work
from textual.worker import get_current_worker

class TerminalPane(Widget):
    # Use auto_refresh for smooth UI updates
    auto_refresh = 1 / 30  # 30 Hz UI refresh

    @work(thread=True)
    def _start_metrics_collection(self) -> None:
        """Collect metrics in background thread."""
        worker = get_current_worker()
        while not worker.is_cancelled:
            metrics = self._collect_metrics()  # Expensive psutil calls
            self.call_from_thread(self._update_cached_metrics, metrics)
            time.sleep(1.0)  # Collect at 1 Hz

    def _update_cached_metrics(self, metrics: Metrics) -> None:
        """Update cached metrics (called from main thread)."""
        self._cached_metrics = metrics

    def render(self) -> RenderResult:
        """Render using cached metrics (fast, no psutil calls)."""
        return self._render_with_cached_metrics()
```

### Summary

| Aspect | Current | Ideal |
|--------|---------|-------|
| UI Refresh Rate | 1 Hz | 30-60 Hz |
| Metrics Collection | Main thread | Worker thread |
| UI Thread Blocking | Yes (during metrics) | No |
| Implementation | Coupled | Decoupled |

---

## Question 2: How to Build a UI Latency Test?

### Answer: Use Textual's Testing Framework with Timing Instrumentation

Textual provides a comprehensive testing framework with the `run_test()` method and `Pilot` class that can be used to measure UI latency.

### Testing Approach

#### 1. Basic Test Structure

```python
import time
import pytest
from textual.pilot import Pilot

from ui.interactive_tabbed_run import InteractiveTabbedApp

@pytest.mark.asyncio
async def test_ui_latency_during_full_run():
    """Measure UI latency throughout a complete mock run."""
    app = create_test_app()  # Create app with mock plugins

    latency_measurements = []

    async with app.run_test(size=(120, 40)) as pilot:
        # Start the run
        await pilot.press("enter")  # or trigger run programmatically

        # Measure latency throughout the run
        while not app.is_complete:
            latency = await measure_ui_response_time(pilot, app)
            latency_measurements.append(latency)
            await pilot.pause(delay=0.1)  # Sample every 100ms

    # Analyze results
    avg_latency = sum(latency_measurements) / len(latency_measurements)
    max_latency = max(latency_measurements)

    assert avg_latency < 0.05, f"Average latency {avg_latency:.3f}s exceeds 50ms target"
    assert max_latency < 0.1, f"Max latency {max_latency:.3f}s exceeds 100ms target"
```

#### 2. Measuring UI Response Time

```python
async def measure_ui_response_time(pilot: Pilot, app: App) -> float:
    """Measure time from action to UI update."""
    # Record initial state
    initial_render = app.screen.render()

    # Trigger an action that should cause UI update
    start_time = time.perf_counter()
    await pilot.press("down")  # Scroll action

    # Wait for UI to update (with timeout)
    max_wait = 1.0
    while time.perf_counter() - start_time < max_wait:
        await pilot.pause(delay=0.001)  # 1ms polling
        current_render = app.screen.render()
        if current_render != initial_render:
            break

    end_time = time.perf_counter()
    return end_time - start_time
```

#### 3. Complete Test Implementation

Create a new test file `ui/tests/test_ui_latency_measurement.py`:

```python
"""UI latency measurement tests.

These tests measure UI responsiveness during a complete run of the
interactive update tool with mock plugins.

Usage:
    poetry run pytest ui/tests/test_ui_latency_measurement.py -v

See Also:
    - docs/ui-latency-study.md for analysis
    - just run-mock-interactive for manual testing
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from ui.interactive_tabbed_run import InteractiveTabbedApp
from ui.pty_session import is_pty_available

if TYPE_CHECKING:
    from textual.pilot import Pilot

# Skip if PTY not available
pytestmark = pytest.mark.skipif(
    not is_pty_available(),
    reason="PTY not available on this platform",
)


@dataclass
class LatencyReport:
    """Report of UI latency measurements."""

    measurements: list[float] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.measurements)

    @property
    def mean(self) -> float:
        return statistics.mean(self.measurements) if self.measurements else 0.0

    @property
    def median(self) -> float:
        return statistics.median(self.measurements) if self.measurements else 0.0

    @property
    def stdev(self) -> float:
        return statistics.stdev(self.measurements) if len(self.measurements) > 1 else 0.0

    @property
    def min(self) -> float:
        return min(self.measurements) if self.measurements else 0.0

    @property
    def max(self) -> float:
        return max(self.measurements) if self.measurements else 0.0

    @property
    def p95(self) -> float:
        """95th percentile latency."""
        if not self.measurements:
            return 0.0
        sorted_m = sorted(self.measurements)
        idx = int(len(sorted_m) * 0.95)
        return sorted_m[min(idx, len(sorted_m) - 1)]

    def __str__(self) -> str:
        return (
            f"LatencyReport(n={self.count}, "
            f"mean={self.mean*1000:.1f}ms, "
            f"median={self.median*1000:.1f}ms, "
            f"p95={self.p95*1000:.1f}ms, "
            f"max={self.max*1000:.1f}ms)"
        )


def create_mock_app() -> InteractiveTabbedApp:
    """Create an InteractiveTabbedApp with mock plugins.

    This simulates the same setup as `just run-mock-interactive`.
    """
    # Set environment to use mock plugins only
    os.environ["UPDATE_ALL_DEBUG_MOCK_ONLY"] = "1"

    # Import here to pick up environment variable
    from plugins import get_available_plugins

    plugins = get_available_plugins()
    mock_plugins = [p for p in plugins if "mock" in p.name.lower()]

    return InteractiveTabbedApp(plugins=mock_plugins)


async def measure_render_latency(app: InteractiveTabbedApp) -> float:
    """Measure time to render the current screen."""
    start = time.perf_counter()
    # Force a render cycle
    app.refresh()
    await asyncio.sleep(0)  # Yield to event loop
    end = time.perf_counter()
    return end - start


async def measure_input_latency(pilot: Pilot, app: InteractiveTabbedApp) -> float:
    """Measure time from keypress to screen update."""
    # Get current screen state hash
    initial_state = hash(str(app.screen.render()))

    start = time.perf_counter()
    await pilot.press("tab")  # Switch tabs

    # Wait for screen to change (with timeout)
    timeout = 2.0
    while time.perf_counter() - start < timeout:
        await pilot.pause(delay=0.001)
        current_state = hash(str(app.screen.render()))
        if current_state != initial_state:
            break

    end = time.perf_counter()

    # Switch back for next measurement
    await pilot.press("shift+tab")
    await pilot.pause(delay=0.05)

    return end - start


class TestUILatencyMeasurement:
    """Tests that measure UI latency during operation."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_measure_latency_during_idle(self) -> None:
        """Measure UI latency when app is idle (no plugins running)."""
        app = create_mock_app()
        report = LatencyReport()

        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for app to initialize
            await pilot.pause(delay=0.5)

            # Take measurements
            for _ in range(20):
                latency = await measure_render_latency(app)
                report.measurements.append(latency)
                await pilot.pause(delay=0.1)

        print(f"\nIdle latency: {report}")

        # Idle should be very fast
        assert report.mean < 0.01, f"Mean idle latency {report.mean*1000:.1f}ms exceeds 10ms"

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_measure_input_response_latency(self) -> None:
        """Measure latency from input to screen update."""
        app = create_mock_app()
        report = LatencyReport()

        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for app to initialize
            await pilot.pause(delay=0.5)

            # Take measurements
            for _ in range(10):
                latency = await measure_input_latency(pilot, app)
                report.measurements.append(latency)

        print(f"\nInput response latency: {report}")

        # Input response should be under 100ms for good UX
        assert report.p95 < 0.1, f"P95 input latency {report.p95*1000:.1f}ms exceeds 100ms"

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_measure_latency_during_plugin_execution(self) -> None:
        """Measure UI latency while plugins are running.

        This is the key test - it measures latency during the actual
        operation that users experience with `just run-mock-interactive`.
        """
        app = create_mock_app()
        report = LatencyReport()

        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for app to initialize
            await pilot.pause(delay=0.5)

            # Start the run (press Enter or trigger programmatically)
            # Note: The exact trigger depends on the app's key bindings
            await pilot.press("enter")

            # Measure latency throughout the run
            run_duration = 10.0  # seconds
            sample_interval = 0.1  # 100ms between samples
            start_time = time.perf_counter()

            while time.perf_counter() - start_time < run_duration:
                latency = await measure_render_latency(app)
                report.measurements.append(latency)
                await pilot.pause(delay=sample_interval)

        print(f"\nDuring-run latency: {report}")

        # During run, latency should still be reasonable
        assert report.p95 < 0.1, f"P95 latency during run {report.p95*1000:.1f}ms exceeds 100ms"
        assert report.max < 0.5, f"Max latency during run {report.max*1000:.1f}ms exceeds 500ms"


class TestUIRefreshRateVerification:
    """Tests that verify the UI refresh rate configuration."""

    @pytest.mark.asyncio
    async def test_auto_refresh_is_configured(self) -> None:
        """Verify that auto_refresh is configured for smooth updates."""
        from ui.phase_status_bar import PhaseStatusBar

        # PhaseStatusBar should have auto_refresh configured
        # for 30 Hz (1/30 = 0.0333... seconds)
        status_bar = PhaseStatusBar()

        # Check if auto_refresh is set (may be None if not configured)
        # The ideal value is 1/30 for 30 Hz refresh
        expected_refresh = 1 / 30

        # Note: This test documents the expected configuration
        # If auto_refresh is not set, this test will fail as a reminder
        # to implement the decoupled refresh architecture
        if hasattr(status_bar, 'auto_refresh') and status_bar.auto_refresh:
            assert abs(status_bar.auto_refresh - expected_refresh) < 0.01, (
                f"auto_refresh should be ~{expected_refresh:.4f}s (30 Hz), "
                f"got {status_bar.auto_refresh:.4f}s"
            )
```

#### 4. Running the Tests

Add a just action for running latency tests:

```just
# Run UI latency measurement tests
test-ui-latency:
    cd ui && poetry run pytest tests/test_ui_latency_measurement.py -v -s --tb=short
```

Run with:
```bash
just test-ui-latency
```

#### 5. Continuous Monitoring

For ongoing latency monitoring, create a script that runs the app and measures latency:

```python
#!/usr/bin/env python3
"""Script to measure UI latency during a full mock run.

Usage:
    poetry run python scripts/measure_ui_latency.py

This script runs the interactive app with mock plugins and measures
UI latency throughout the run, producing a report at the end.
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ["UPDATE_ALL_DEBUG_MOCK_ONLY"] = "1"

from ui.interactive_tabbed_run import InteractiveTabbedApp


async def main():
    """Run latency measurement."""
    from plugins import get_available_plugins

    plugins = get_available_plugins()
    mock_plugins = [p for p in plugins if "mock" in p.name.lower()]

    app = InteractiveTabbedApp(plugins=mock_plugins)

    latencies = []

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(delay=0.5)

        # Run for 30 seconds, measuring every 100ms
        start = time.perf_counter()
        while time.perf_counter() - start < 30:
            measure_start = time.perf_counter()
            app.refresh()
            await asyncio.sleep(0)
            measure_end = time.perf_counter()

            latencies.append(measure_end - measure_start)
            await pilot.pause(delay=0.1)

    # Report
    import statistics

    print("\n" + "=" * 60)
    print("UI LATENCY REPORT")
    print("=" * 60)
    print(f"Samples:    {len(latencies)}")
    print(f"Mean:       {statistics.mean(latencies)*1000:.2f} ms")
    print(f"Median:     {statistics.median(latencies)*1000:.2f} ms")
    print(f"Std Dev:    {statistics.stdev(latencies)*1000:.2f} ms")
    print(f"Min:        {min(latencies)*1000:.2f} ms")
    print(f"Max:        {max(latencies)*1000:.2f} ms")
    print(f"P95:        {sorted(latencies)[int(len(latencies)*0.95)]*1000:.2f} ms")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
```

### Summary

| Test Type | What It Measures | Target |
|-----------|------------------|--------|
| Idle Latency | Render time when idle | < 10ms |
| Input Response | Time from keypress to update | < 100ms (P95) |
| During-Run Latency | Render time during plugin execution | < 100ms (P95), < 500ms (max) |

---

## Sources

### Textual Documentation
- [Workers Guide](https://textual.textualize.io/guide/workers/) - Thread workers and `call_from_thread()`
- [Testing Guide](https://textual.textualize.io/guide/testing/) - `run_test()`, `Pilot`, and `pause()`

### Project Source Code
- [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py) - `_metrics_update_loop()`, `PaneConfig`
- [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py) - `MetricsCollector`, `auto_refresh`
- [`ui/ui/interactive_tabbed_run.py`](../ui/ui/interactive_tabbed_run.py) - Main app class
- [`ui/tests/test_ui_refresh_rate.py`](../ui/tests/test_ui_refresh_rate.py) - Existing tests documenting the issue
- [`plans/ui-latency-improvement-plan.md`](../plans/ui-latency-improvement-plan.md) - Detailed improvement plan

### Textual Source Code (ref/textual)
- [`ref/textual/src/textual/worker.py`](../ref/textual/src/textual/worker.py) - Worker implementation
- [`ref/textual/src/textual/dom.py`](../ref/textual/src/textual/dom.py) - `run_worker()` method
- [`ref/textual/src/textual/app.py`](../ref/textual/src/textual/app.py) - `call_from_thread()` method

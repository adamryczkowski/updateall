"""Phase status bar widget with per-tab metrics display.

This module provides a PhaseStatusBar widget that displays runtime metrics
for each terminal pane, including status, ETA, resource usage, and progress.

UI Revision Plan - Phase 3 Status Bar
See docs/UI-revision-plan.md section 3.4
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

from textual.reactive import reactive
from textual.widgets import Static

if TYPE_CHECKING:
    import asyncio

    import psutil


@dataclass
class PhaseMetrics:
    """Metrics for a single phase execution.

    This dataclass holds all metrics displayed in the status bar,
    including status, time estimates, resource usage, and progress.

    Attributes:
        status: Current status text (e.g., "In Progress", "Paused").
        pause_after_phase: Whether pause is enabled after current phase.
        eta_seconds: Estimated time remaining in seconds, or None if unknown.
        eta_error_seconds: Error margin for ETA in seconds, or None.
        cpu_percent: Current CPU usage percentage (0-100).
        memory_mb: Current memory usage in megabytes.
        memory_peak_mb: Peak memory usage in megabytes.
        items_completed: Number of items processed.
        items_total: Total number of items, or None if unknown.
        network_bytes: Cumulative network bytes downloaded.
        disk_io_bytes: Cumulative disk I/O bytes.
        cpu_time_seconds: Cumulative CPU time in seconds.
        error_message: Error message if metrics collection failed.
    """

    # Status
    status: str = "Pending"
    pause_after_phase: bool = False

    # Time estimates
    eta_seconds: float | None = None
    eta_error_seconds: float | None = None

    # Resource usage (current)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_peak_mb: float = 0.0

    # Progress
    items_completed: int = 0
    items_total: int | None = None

    # Cumulative metrics
    network_bytes: int = 0
    disk_io_bytes: int = 0
    cpu_time_seconds: float = 0.0

    # Error state
    error_message: str | None = None


@dataclass
class MetricsSnapshot:
    """A snapshot of system metrics at a point in time.

    Used for calculating deltas in cumulative metrics like network I/O.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0


class MetricsCollector:
    """Collects runtime metrics for a process.

    This class uses psutil to collect CPU, memory, network, and disk I/O
    metrics for a specific process. It handles errors gracefully when
    metrics are unavailable.

    Attributes:
        pid: Process ID to monitor, or None for system-wide metrics.
        update_interval: Interval between metric updates in seconds.
    """

    # Minimum interval between updates to avoid excessive CPU usage
    MIN_UPDATE_INTERVAL: ClassVar[float] = 0.5

    def __init__(
        self,
        pid: int | None = None,
        update_interval: float = 1.0,
    ) -> None:
        """Initialize the metrics collector.

        Args:
            pid: Process ID to monitor, or None for current process.
            update_interval: Interval between metric updates in seconds.
        """
        self.pid = pid
        self.update_interval = max(update_interval, self.MIN_UPDATE_INTERVAL)

        self._process: psutil.Process | None = None
        self._baseline: MetricsSnapshot | None = None
        self._peak_memory_mb: float = 0.0
        self._last_update: datetime | None = None
        self._metrics = PhaseMetrics()
        self._running = False
        self._update_task: asyncio.Task[None] | None = None

    @property
    def metrics(self) -> PhaseMetrics:
        """Get the current metrics."""
        return self._metrics

    def _get_process(self) -> psutil.Process | None:
        """Get or create the psutil Process object.

        Returns:
            The Process object, or None if unavailable.
        """
        try:
            import psutil

            if self._process is None:
                if self.pid is not None:
                    self._process = psutil.Process(self.pid)
                else:
                    self._process = psutil.Process()
            return self._process
        except Exception:
            return None

    def _take_baseline_snapshot(self) -> MetricsSnapshot:
        """Take a baseline snapshot of system metrics.

        Returns:
            A MetricsSnapshot with current system metrics.
        """
        try:
            import psutil

            net_io = psutil.net_io_counters()
            disk_io = psutil.disk_io_counters()

            return MetricsSnapshot(
                timestamp=datetime.now(tz=UTC),
                network_bytes_sent=net_io.bytes_sent if net_io else 0,
                network_bytes_recv=net_io.bytes_recv if net_io else 0,
                disk_read_bytes=disk_io.read_bytes if disk_io else 0,
                disk_write_bytes=disk_io.write_bytes if disk_io else 0,
            )
        except Exception:
            return MetricsSnapshot()

    def start(self) -> None:
        """Start collecting metrics."""
        if self._running:
            return

        self._running = True
        self._baseline = self._take_baseline_snapshot()
        self._peak_memory_mb = 0.0

        # Initialize process for CPU percent calculation
        process = self._get_process()
        if process:
            with contextlib.suppress(Exception):
                process.cpu_percent()  # First call returns 0, primes the counter

    def stop(self) -> None:
        """Stop collecting metrics."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            self._update_task = None

    def collect(self) -> PhaseMetrics:
        """Collect current metrics.

        Returns:
            Updated PhaseMetrics with current values.
        """
        if not self._running:
            return self._metrics

        process = self._get_process()
        if process is None:
            self._metrics.error_message = "Process not accessible"
            return self._metrics

        try:
            import psutil

            # CPU percent (since last call)
            try:
                self._metrics.cpu_percent = process.cpu_percent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._metrics.cpu_percent = 0.0

            # Memory usage
            try:
                mem_info = process.memory_info()
                self._metrics.memory_mb = mem_info.rss / (1024 * 1024)
                self._peak_memory_mb = max(self._peak_memory_mb, self._metrics.memory_mb)
                self._metrics.memory_peak_mb = self._peak_memory_mb
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # CPU time
            try:
                cpu_times = process.cpu_times()
                self._metrics.cpu_time_seconds = cpu_times.user + cpu_times.system
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Network and disk I/O (system-wide, calculate delta from baseline)
            if self._baseline:
                try:
                    net_io = psutil.net_io_counters()
                    if net_io:
                        recv_delta = net_io.bytes_recv - self._baseline.network_bytes_recv
                        self._metrics.network_bytes = max(0, recv_delta)
                except Exception:
                    pass

                try:
                    disk_io = psutil.disk_io_counters()
                    if disk_io:
                        read_delta = disk_io.read_bytes - self._baseline.disk_read_bytes
                        write_delta = disk_io.write_bytes - self._baseline.disk_write_bytes
                        self._metrics.disk_io_bytes = max(0, read_delta + write_delta)
                except Exception:
                    pass

            self._metrics.error_message = None
            self._last_update = datetime.now(tz=UTC)

        except Exception as e:
            self._metrics.error_message = str(e)

        return self._metrics

    def update_progress(self, completed: int, total: int | None = None) -> None:
        """Update progress metrics.

        Args:
            completed: Number of items completed.
            total: Total number of items, or None if unknown.
        """
        self._metrics.items_completed = completed
        self._metrics.items_total = total

    def update_eta(
        self,
        eta_seconds: float | None,
        error_seconds: float | None = None,
    ) -> None:
        """Update ETA metrics.

        Args:
            eta_seconds: Estimated time remaining in seconds.
            error_seconds: Error margin in seconds.
        """
        self._metrics.eta_seconds = eta_seconds
        self._metrics.eta_error_seconds = error_seconds

    def update_status(self, status: str, pause_after_phase: bool = False) -> None:
        """Update status metrics.

        Args:
            status: Current status text.
            pause_after_phase: Whether pause is enabled after current phase.
        """
        self._metrics.status = status
        self._metrics.pause_after_phase = pause_after_phase


# CSS styles for the phase status bar
PHASE_STATUS_BAR_CSS = """
/* Phase Status Bar Styles */
/* See docs/UI-revision-plan.md section 3.4 */

PhaseStatusBar {
    height: 3;
    dock: bottom;
    padding: 0 1;
    background: $surface;
    border-top: solid $primary;
}

PhaseStatusBar.error {
    border-top: solid $error;
}

PhaseStatusBar.paused {
    border-top: solid $warning;
}

PhaseStatusBar .status-line {
    width: 100%;
}

PhaseStatusBar .metrics-line {
    width: 100%;
    color: $text-muted;
}

PhaseStatusBar .error-indicator {
    color: $error;
}
"""


class PhaseStatusBar(Static):
    """Status bar widget showing per-tab metrics.

    This widget displays runtime metrics for a terminal pane in a
    three-line format:
    - Line 1: Status and ETA
    - Line 2: CPU, memory, and progress
    - Line 3: Network, disk I/O, and CPU time

    Example:
        status_bar = PhaseStatusBar(pane_id="apt")
        status_bar.update_metrics(PhaseMetrics(
            status="In Progress",
            cpu_percent=45.0,
            memory_mb=128.0,
        ))
    """

    DEFAULT_CSS = PHASE_STATUS_BAR_CSS

    # Reactive properties for automatic refresh
    metrics: reactive[PhaseMetrics] = reactive(PhaseMetrics, always_update=True)

    def __init__(
        self,
        pane_id: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the status bar.

        Args:
            pane_id: ID of the associated terminal pane.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id or f"status-bar-{pane_id}", classes=classes)
        self.pane_id = pane_id
        self._metrics_collector: MetricsCollector | None = None

    def watch_metrics(self, metrics: PhaseMetrics) -> None:
        """React to metrics changes.

        Args:
            metrics: New metrics to display.
        """
        self._refresh_display()

        # Update CSS classes based on state
        self.remove_class("error", "paused")
        if metrics.error_message:
            self.add_class("error")
        if metrics.pause_after_phase:
            self.add_class("paused")

    def update_metrics(self, metrics: PhaseMetrics) -> None:
        """Update the displayed metrics.

        Args:
            metrics: New metrics to display.
        """
        self.metrics = metrics

    def set_metrics_collector(self, collector: MetricsCollector) -> None:
        """Set the metrics collector for automatic updates.

        Args:
            collector: MetricsCollector instance to use.
        """
        self._metrics_collector = collector

    def collect_and_update(self) -> None:
        """Collect metrics from the collector and update display."""
        if self._metrics_collector:
            self.metrics = self._metrics_collector.collect()

    def _refresh_display(self) -> None:
        """Refresh the status bar content."""
        m = self.metrics

        # Line 1: Status and ETA
        pause_indicator = " [⏸ Pause after phase]" if m.pause_after_phase else ""
        eta_str = self._format_eta(m.eta_seconds, m.eta_error_seconds)
        line1 = f"Status: {m.status}{pause_indicator} | ETA: {eta_str}"

        # Line 2: Resource usage
        items_str = self._format_items(m.items_completed, m.items_total)
        line2 = (
            f"CPU: {m.cpu_percent:.0f}% | "
            f"Mem: {m.memory_mb:.0f}/{m.memory_peak_mb:.0f}MB (peak) | "
            f"{items_str}"
        )

        # Line 3: Cumulative metrics
        net_str = self._format_bytes(m.network_bytes)
        disk_str = self._format_bytes(m.disk_io_bytes)
        cpu_time_str = self._format_duration(m.cpu_time_seconds)
        line3 = f"Network: {net_str} ↓ | Disk I/O: {disk_str} | CPU Time: {cpu_time_str}"

        # Add error indicator if needed
        if m.error_message:
            line3 += f" | [red]⚠ {m.error_message}[/red]"

        self.update(f"{line1}\n{line2}\n{line3}")

    def _format_eta(
        self,
        eta_seconds: float | None,
        error_seconds: float | None,
    ) -> str:
        """Format ETA with optional error margin.

        Args:
            eta_seconds: ETA in seconds, or None.
            error_seconds: Error margin in seconds, or None.

        Returns:
            Formatted ETA string.
        """
        if eta_seconds is None:
            return "N/A"

        eta_str = self._format_duration(eta_seconds)
        if error_seconds is not None:
            error_str = self._format_duration(error_seconds)
            return f"{eta_str} (±{error_str})"
        return eta_str

    def _format_items(self, completed: int, total: int | None) -> str:
        """Format items progress.

        Args:
            completed: Number of items completed.
            total: Total number of items, or None.

        Returns:
            Formatted items string.
        """
        if total is not None:
            return f"Items: {completed}/{total}"
        if completed > 0:
            return f"Items: {completed}"
        return "Items: --"

    def _format_bytes(self, byte_count: int) -> str:
        """Format byte count with appropriate unit.

        Args:
            byte_count: Number of bytes.

        Returns:
            Formatted string with unit (B, KB, MB, GB).
        """
        if byte_count < 1024:
            return f"{byte_count} B"
        if byte_count < 1024 * 1024:
            return f"{byte_count / 1024:.1f} KB"
        if byte_count < 1024 * 1024 * 1024:
            return f"{byte_count / (1024 * 1024):.1f} MB"
        return f"{byte_count / (1024 * 1024 * 1024):.2f} GB"

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted duration string (e.g., "2m 30s").
        """
        if seconds < 0:
            return "N/A"
        if seconds < 60:
            return f"{seconds:.0f}s"
        if seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def create_metrics_collector_for_pid(pid: int | None = None) -> MetricsCollector:
    """Create a MetricsCollector for a process.

    Factory function to create a properly configured MetricsCollector.

    Args:
        pid: Process ID to monitor, or None for current process.

    Returns:
        Configured MetricsCollector instance.
    """
    return MetricsCollector(pid=pid, update_interval=1.0)

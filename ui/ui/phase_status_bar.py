"""Phase status bar widget with per-tab metrics display.

This module provides a PhaseStatusBar widget that displays runtime metrics
for each terminal pane, including status, ETA, resource usage, and progress.

UI Revision Plan - Phase 3 Status Bar
See docs/UI-revision-plan.md section 3.4

Enhanced to 5-line display with statistics table showing:
- Phase rows: Update, Download, Upgrade, Total
- Columns: Phase, Time, Data, CPU Time, Wall Time, Packages, Peak Memory
- Running progress summary with predictions
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
        projected_download_bytes: Projected download size from stats (update phase).
        projected_upgrade_bytes: Projected download size from stats (upgrade phase).
        actual_download_bytes: Actual download size during update phase.
        actual_upgrade_bytes: Actual download size during upgrade phase.
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

    # Projected download sizes from stats module
    projected_download_bytes: int | None = None
    projected_upgrade_bytes: int | None = None

    # Actual download sizes (tracked during execution)
    actual_download_bytes: int = 0
    actual_upgrade_bytes: int = 0

    # Error state
    error_message: str | None = None


@dataclass
class PhaseStats:
    """Statistics for a single phase (Update/Download/Upgrade).

    Attributes:
        phase_name: Name of the phase.
        wall_time_seconds: Wall clock time in seconds.
        data_bytes: Data downloaded in bytes.
        cpu_time_seconds: CPU time in seconds.
        packages: Number of packages processed.
        peak_memory_mb: Peak memory usage in MB.
        is_complete: Whether the phase is complete.
        is_running: Whether the phase is currently running.
    """

    phase_name: str
    wall_time_seconds: float = 0.0
    data_bytes: int = 0
    cpu_time_seconds: float = 0.0
    packages: int = 0
    peak_memory_mb: float = 0.0
    is_complete: bool = False
    is_running: bool = False


@dataclass
class RunningProgress:
    """Running progress summary with predictions.

    Attributes:
        predicted_wall_time_left: Predicted wall time remaining in seconds.
        predicted_download_left: Predicted download size remaining in bytes.
        cpu_time_so_far: CPU time consumed so far in seconds.
        peak_memory_so_far: Peak memory usage so far in MB.
    """

    predicted_wall_time_left: float | None = None
    predicted_download_left: int | None = None
    cpu_time_so_far: float = 0.0
    peak_memory_so_far: float = 0.0


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

        # Per-phase statistics
        self._phase_stats: dict[str, PhaseStats] = {
            "Update": PhaseStats("Update"),
            "Download": PhaseStats("Download"),
            "Upgrade": PhaseStats("Upgrade"),
        }
        self._current_phase: str | None = None
        self._phase_start_time: datetime | None = None

    @property
    def metrics(self) -> PhaseMetrics:
        """Get the current metrics."""
        return self._metrics

    @property
    def phase_stats(self) -> dict[str, PhaseStats]:
        """Get per-phase statistics."""
        return self._phase_stats

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

    def start_phase(self, phase_name: str) -> None:
        """Start tracking a new phase.

        Args:
            phase_name: Name of the phase (Update, Download, Upgrade).
        """
        if phase_name in self._phase_stats:
            self._current_phase = phase_name
            self._phase_start_time = datetime.now(tz=UTC)
            self._phase_stats[phase_name].is_running = True
            self._phase_stats[phase_name].is_complete = False

    def complete_phase(self, phase_name: str) -> None:
        """Mark a phase as complete.

        Args:
            phase_name: Name of the phase (Update, Download, Upgrade).
        """
        if phase_name in self._phase_stats:
            stats = self._phase_stats[phase_name]
            stats.is_running = False
            stats.is_complete = True
            if self._phase_start_time:
                elapsed = (datetime.now(tz=UTC) - self._phase_start_time).total_seconds()
                stats.wall_time_seconds = elapsed
            self._current_phase = None
            self._phase_start_time = None

    def update_phase_stats(
        self,
        phase_name: str,
        *,
        data_bytes: int | None = None,
        cpu_time_seconds: float | None = None,
        packages: int | None = None,
        peak_memory_mb: float | None = None,
    ) -> None:
        """Update statistics for a specific phase.

        Args:
            phase_name: Name of the phase.
            data_bytes: Data downloaded in bytes.
            cpu_time_seconds: CPU time in seconds.
            packages: Number of packages processed.
            peak_memory_mb: Peak memory usage in MB.
        """
        if phase_name not in self._phase_stats:
            return

        stats = self._phase_stats[phase_name]
        if data_bytes is not None:
            stats.data_bytes = data_bytes
        if cpu_time_seconds is not None:
            stats.cpu_time_seconds = cpu_time_seconds
        if packages is not None:
            stats.packages = packages
        if peak_memory_mb is not None:
            stats.peak_memory_mb = max(stats.peak_memory_mb, peak_memory_mb)

        # Update wall time if phase is running
        if stats.is_running and self._phase_start_time:
            stats.wall_time_seconds = (
                datetime.now(tz=UTC) - self._phase_start_time
            ).total_seconds()

    def get_total_stats(self) -> PhaseStats:
        """Get aggregated statistics across all phases.

        Returns:
            PhaseStats with totals (sum for most, max for peak memory).
        """
        total = PhaseStats("Total")
        for stats in self._phase_stats.values():
            total.wall_time_seconds += stats.wall_time_seconds
            total.data_bytes += stats.data_bytes
            total.cpu_time_seconds += stats.cpu_time_seconds
            total.packages += stats.packages
            total.peak_memory_mb = max(total.peak_memory_mb, stats.peak_memory_mb)
        return total

    def get_running_progress(self) -> RunningProgress:
        """Get running progress summary with predictions.

        Returns:
            RunningProgress with current predictions.
        """
        total = self.get_total_stats()
        return RunningProgress(
            predicted_wall_time_left=self._metrics.eta_seconds,
            predicted_download_left=(
                self._metrics.projected_download_bytes - self._metrics.actual_download_bytes
                if self._metrics.projected_download_bytes
                else None
            ),
            cpu_time_so_far=total.cpu_time_seconds,
            peak_memory_so_far=total.peak_memory_mb,
        )

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

            # Update current phase stats
            if self._current_phase:
                self.update_phase_stats(
                    self._current_phase,
                    cpu_time_seconds=self._metrics.cpu_time_seconds,
                    peak_memory_mb=self._metrics.memory_peak_mb,
                    data_bytes=self._metrics.network_bytes,
                )

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


# CSS styles for the phase status bar (5 lines)
PHASE_STATUS_BAR_CSS = """
/* Phase Status Bar Styles - 5 lines with statistics table */
/* See docs/UI-revision-plan.md section 3.4 */

PhaseStatusBar {
    height: 6;
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

PhaseStatusBar .table-header {
    color: $text;
    text-style: bold;
}

PhaseStatusBar .phase-running {
    color: $warning;
}

PhaseStatusBar .phase-complete {
    color: $success;
}
"""


class PhaseStatusBar(Static):
    """Status bar widget showing per-tab metrics in a 5-line table format.

    This widget displays runtime metrics for a terminal pane in a
    five-line format with a statistics table:
    - Line 1: Table header (Phase | Time | Data | CPU | Wall | Pkgs | Mem)
    - Line 2: Update phase row
    - Line 3: Download phase row
    - Line 4: Upgrade phase row
    - Line 5: Total row + Running progress summary

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
        """Refresh the status bar content with 5-line table format."""
        m = self.metrics

        # Get phase stats from collector if available
        if self._metrics_collector:
            phase_stats = self._metrics_collector.phase_stats
            total_stats = self._metrics_collector.get_total_stats()
            progress = self._metrics_collector.get_running_progress()
        else:
            # Default empty stats
            phase_stats = {
                "Update": PhaseStats("Update"),
                "Download": PhaseStats("Download"),
                "Upgrade": PhaseStats("Upgrade"),
            }
            total_stats = PhaseStats("Total")
            progress = RunningProgress()

        # Column widths for consistent alignment
        # Phase: 10 chars (includes 2-char status indicator space)
        # Time: 8 chars, Data: 10 chars, CPU: 8 chars, Wall: 8 chars, Pkgs: 6 chars, Mem: 8 chars
        col_phase = 10
        col_time = 8
        col_data = 10
        col_cpu = 8
        col_wall = 8
        col_pkgs = 6
        col_mem = 8

        # Build table header with column widths for alignment
        header = (
            f"{'Phase':<{col_phase}} │ {'Time':>{col_time}} │ {'Data':>{col_data}} │ "
            f"{'CPU':>{col_cpu}} │ {'Wall':>{col_wall}} │ {'Pkgs':>{col_pkgs}} │ {'Mem':>{col_mem}}"
        )

        # Format each phase row
        def format_phase_row(stats: PhaseStats) -> str:
            # Status indicator: 2 chars (indicator + space, or 2 spaces)
            if stats.is_running:
                status_indicator = "▶ "
            elif stats.is_complete:
                status_indicator = "✓ "
            else:
                status_indicator = "  "

            # Phase name: remaining chars after status indicator
            phase_width = col_phase - 2
            phase_cell = f"{status_indicator}{stats.phase_name:<{phase_width}}"

            # Format memory with consistent width
            mem_str = f"{stats.peak_memory_mb:.0f}MB"

            return (
                f"{phase_cell} │ "
                f"{self._format_duration(stats.wall_time_seconds):>{col_time}} │ "
                f"{self._format_bytes(stats.data_bytes):>{col_data}} │ "
                f"{self._format_duration(stats.cpu_time_seconds):>{col_cpu}} │ "
                f"{self._format_duration(stats.wall_time_seconds):>{col_wall}} │ "
                f"{stats.packages:>{col_pkgs}} │ "
                f"{mem_str:>{col_mem}}"
            )

        update_row = format_phase_row(phase_stats["Update"])
        download_row = format_phase_row(phase_stats["Download"])
        upgrade_row = format_phase_row(phase_stats["Upgrade"])

        # Total row with running progress summary
        total_row = format_phase_row(total_stats)

        # Running progress summary (appended to display)
        progress_parts = []
        if progress.predicted_wall_time_left is not None:
            progress_parts.append(
                f"ETA: {self._format_duration(progress.predicted_wall_time_left)}"
            )
        if progress.predicted_download_left is not None and progress.predicted_download_left > 0:
            progress_parts.append(
                f"DL Left: {self._format_bytes(progress.predicted_download_left)}"
            )
        progress_parts.append(f"CPU: {self._format_duration(progress.cpu_time_so_far)}")
        progress_parts.append(f"Peak: {progress.peak_memory_so_far:.0f}MB")

        progress_summary = " │ ".join(progress_parts)

        # Add error indicator if needed
        if m.error_message:
            progress_summary += f" │ [red]⚠ {m.error_message}[/red]"

        # Pause indicator
        if m.pause_after_phase:
            progress_summary += " │ [yellow]⏸ Pause[/yellow]"

        # Combine all lines
        content = f"{header}\n{update_row}\n{download_row}\n{upgrade_row}\n{total_row} │ {progress_summary}"

        self.update(content)

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

"""Metrics collection and storage for the UI module.

This module provides metrics-related classes for tracking and displaying
runtime metrics during plugin execution:

- MetricsStore: Persistent storage for metrics across phase transitions
- MetricsCollector: Real-time metrics collection using psutil
- PhaseMetrics: Metrics for display in the status bar
- PhaseStats: Statistics for a single phase
- MetricsSnapshot: Point-in-time snapshot of system metrics
- RunningProgress: Running progress summary with predictions

This module is for **UI display** - collecting and displaying real-time
metrics in the terminal UI status bar during plugin execution.

Key differences from core.metrics:
    - Purpose: UI display vs. production monitoring
    - Scope: Per-process runtime stats vs. system-wide health
    - Data: CPU, memory, network, disk I/O vs. alert thresholds
    - Usage: Status bar display vs. backend monitoring

Use this module when:
    - Displaying runtime metrics in the UI
    - Tracking per-phase statistics (Update, Download, Upgrade)
    - Persisting metrics across PTY session restarts
    - Calculating ETAs and progress predictions

See Also:
    core.metrics: For production observability metrics with alert
        thresholds (memory limits, latency targets, queue depth).

Milestone 3 - Textual Library Usage Review and Fixes
See docs/cleanup-and-refactoring-plan.md section 3.3.1

Milestone 4 - UI Module Architecture Refactoring
See docs/cleanup-and-refactoring-plan.md section 4.3.2
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

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


@dataclass
class PhaseSnapshot:
    """Immutable snapshot of metrics at phase completion.

    This snapshot is taken when a phase completes and is preserved
    even if the PTY session is restarted or the MetricsCollector is reset.

    Attributes:
        phase_name: Name of the phase (Update, Download, Upgrade).
        wall_time_seconds: Wall clock time spent in this phase.
        cpu_time_seconds: CPU time consumed in this phase.
        data_bytes: Network data transferred in this phase.
        packages: Number of packages processed.
        peak_memory_mb: Peak memory usage during this phase.
        start_time: When the phase started.
        end_time: When the phase completed.
        success: Whether the phase completed successfully.
    """

    phase_name: str
    wall_time_seconds: float = 0.0
    cpu_time_seconds: float = 0.0
    data_bytes: int = 0
    packages: int = 0
    peak_memory_mb: float = 0.0
    start_time: datetime | None = None
    end_time: datetime | None = None
    success: bool = True


@dataclass
class AccumulatedMetrics:
    """Accumulated metrics across all phases.

    These metrics are accumulated over time and never decrease,
    even when child processes exit or PTY sessions restart.

    Attributes:
        total_cpu_time_seconds: Total CPU time across all phases.
        total_data_bytes: Total network data across all phases.
        total_wall_time_seconds: Total wall clock time across all phases.
        total_packages: Total packages processed across all phases.
        peak_memory_mb: Peak memory usage across all phases.
    """

    total_cpu_time_seconds: float = 0.0
    total_data_bytes: int = 0
    total_wall_time_seconds: float = 0.0
    total_packages: int = 0
    peak_memory_mb: float = 0.0


class MetricsStore:
    """Persistent storage for metrics across phase transitions.

    This class provides a central location for storing and retrieving
    metrics that must persist across PTY session restarts and phase
    transitions. It solves the problem where MetricsCollector was tied
    to ephemeral PTY sessions, causing metrics to be lost.

    The MetricsStore:
    1. Takes snapshots of phase metrics when phases complete
    2. Accumulates total metrics across all phases
    3. Provides access to historical phase data
    4. Survives PTY session restarts

    Example:
        store = MetricsStore()

        # When a phase completes, snapshot its metrics
        store.snapshot_phase("Update", phase_stats)

        # Get accumulated totals
        totals = store.get_accumulated_metrics()

        # Get a specific phase snapshot
        update_snapshot = store.get_phase_snapshot("Update")
    """

    def __init__(self) -> None:
        """Initialize the metrics store."""
        self._phase_snapshots: dict[str, PhaseSnapshot] = {}
        self._accumulated = AccumulatedMetrics()
        self._current_phase: str | None = None
        self._phase_start_time: datetime | None = None

        # Track the baseline values at the start of each phase
        # to calculate per-phase deltas correctly
        self._phase_start_cpu_time: float = 0.0
        self._phase_start_data_bytes: int = 0

    def start_phase(self, phase_name: str) -> None:
        """Mark the start of a new phase.

        Args:
            phase_name: Name of the phase starting (Update, Download, Upgrade).
        """
        self._current_phase = phase_name
        self._phase_start_time = datetime.now(tz=UTC)

        # Record baseline values for delta calculation
        self._phase_start_cpu_time = self._accumulated.total_cpu_time_seconds
        self._phase_start_data_bytes = self._accumulated.total_data_bytes

    def snapshot_phase(
        self,
        phase_name: str,
        stats: PhaseStats,
        *,
        success: bool = True,
    ) -> PhaseSnapshot:
        """Take a snapshot of phase metrics when the phase completes.

        This method creates an immutable snapshot of the phase's final
        metrics and stores it. The snapshot is preserved even if the
        PTY session is restarted.

        Args:
            phase_name: Name of the phase (Update, Download, Upgrade).
            stats: The PhaseStats object with final metrics.
            success: Whether the phase completed successfully.

        Returns:
            The created PhaseSnapshot.
        """
        snapshot = PhaseSnapshot(
            phase_name=phase_name,
            wall_time_seconds=stats.wall_time_seconds,
            cpu_time_seconds=stats.cpu_time_seconds,
            data_bytes=stats.data_bytes,
            packages=stats.packages,
            peak_memory_mb=stats.peak_memory_mb,
            start_time=self._phase_start_time,
            end_time=datetime.now(tz=UTC),
            success=success,
        )

        self._phase_snapshots[phase_name] = snapshot

        # Update accumulated totals
        # Note: We use the snapshot values, not deltas, because the
        # PhaseStats already contains per-phase values
        self._update_accumulated_from_snapshot(snapshot)

        # Clear current phase
        self._current_phase = None
        self._phase_start_time = None

        return snapshot

    def _update_accumulated_from_snapshot(self, _snapshot: PhaseSnapshot) -> None:
        """Update accumulated metrics from a phase snapshot.

        Args:
            _snapshot: The phase snapshot to accumulate (unused, recalculates from all).
        """
        # Recalculate totals from all snapshots to ensure consistency
        total_cpu = 0.0
        total_data = 0
        total_wall = 0.0
        total_packages = 0
        peak_memory = 0.0

        for snap in self._phase_snapshots.values():
            total_cpu += snap.cpu_time_seconds
            total_data += snap.data_bytes
            total_wall += snap.wall_time_seconds
            total_packages += snap.packages
            peak_memory = max(peak_memory, snap.peak_memory_mb)

        self._accumulated.total_cpu_time_seconds = total_cpu
        self._accumulated.total_data_bytes = total_data
        self._accumulated.total_wall_time_seconds = total_wall
        self._accumulated.total_packages = total_packages
        self._accumulated.peak_memory_mb = peak_memory

    def get_phase_snapshot(self, phase_name: str) -> PhaseSnapshot | None:
        """Get the snapshot for a specific phase.

        Args:
            phase_name: Name of the phase.

        Returns:
            The PhaseSnapshot if available, None otherwise.
        """
        return self._phase_snapshots.get(phase_name)

    def get_all_snapshots(self) -> dict[str, PhaseSnapshot]:
        """Get all phase snapshots.

        Returns:
            Dictionary mapping phase names to their snapshots.
        """
        return dict(self._phase_snapshots)

    def get_accumulated_metrics(self) -> AccumulatedMetrics:
        """Get the accumulated metrics across all phases.

        Returns:
            AccumulatedMetrics with totals.
        """
        return self._accumulated

    def update_live_metrics(
        self,
        *,
        cpu_time_seconds: float | None = None,
        data_bytes: int | None = None,
        peak_memory_mb: float | None = None,
    ) -> None:
        """Update live metrics during phase execution.

        This method is called periodically during phase execution to
        update the accumulated metrics with the latest values. It uses
        maximum tracking to ensure values never decrease.

        Args:
            cpu_time_seconds: Current total CPU time.
            data_bytes: Current total data bytes.
            peak_memory_mb: Current peak memory.
        """
        if cpu_time_seconds is not None:
            self._accumulated.total_cpu_time_seconds = max(
                self._accumulated.total_cpu_time_seconds,
                cpu_time_seconds,
            )

        if data_bytes is not None:
            self._accumulated.total_data_bytes = max(
                self._accumulated.total_data_bytes,
                data_bytes,
            )

        if peak_memory_mb is not None:
            self._accumulated.peak_memory_mb = max(
                self._accumulated.peak_memory_mb,
                peak_memory_mb,
            )

    @property
    def current_phase(self) -> str | None:
        """Get the currently running phase name."""
        return self._current_phase

    @property
    def has_completed_phases(self) -> bool:
        """Check if any phases have completed."""
        return len(self._phase_snapshots) > 0

    def reset(self) -> None:
        """Reset all stored metrics.

        This should only be called when starting a completely new
        plugin execution, not between phases.
        """
        self._phase_snapshots.clear()
        self._accumulated = AccumulatedMetrics()
        self._current_phase = None
        self._phase_start_time = None
        self._phase_start_cpu_time = 0.0
        self._phase_start_data_bytes = 0


class MetricsCollector:
    """Collects runtime metrics for a process.

    This class uses psutil to collect CPU, memory, network, and disk I/O
    metrics for a specific process. It handles errors gracefully when
    metrics are unavailable.

    The MetricsCollector now integrates with a MetricsStore for persistent
    storage of phase metrics across PTY session restarts and phase transitions.
    This addresses the architectural issue where metrics were lost when
    child processes exited or PTY sessions were restarted.

    Attributes:
        pid: Process ID to monitor, or None for system-wide metrics.
        update_interval: Interval between metric updates in seconds.
        metrics_store: Optional MetricsStore for persistent metrics storage.
    """

    # Minimum interval between updates to avoid excessive CPU usage
    MIN_UPDATE_INTERVAL: ClassVar[float] = 0.5

    def __init__(
        self,
        pid: int | None = None,
        update_interval: float = 1.0,
        metrics_store: MetricsStore | None = None,
    ) -> None:
        """Initialize the metrics collector.

        Args:
            pid: Process ID to monitor, or None for current process.
            update_interval: Interval between metric updates in seconds.
            metrics_store: Optional MetricsStore for persistent metrics.
                If not provided, a new one will be created.
        """
        self.pid = pid
        self.update_interval = max(update_interval, self.MIN_UPDATE_INTERVAL)

        # Use provided MetricsStore or create a new one
        # The MetricsStore persists across PTY session restarts
        self._metrics_store = metrics_store or MetricsStore()

        self._process: psutil.Process | None = None
        self._baseline: MetricsSnapshot | None = None
        self._peak_memory_mb: float = 0.0
        self._last_update: datetime | None = None
        self._metrics = PhaseMetrics()
        self._cached_metrics = PhaseMetrics()  # Cached copy for fast UI reads
        self._running = False
        self._update_task: asyncio.Task[None] | None = None

        # Track maximum CPU time seen to handle child process exits
        # When child processes exit, their CPU time is lost from the process tree.
        # By tracking the maximum, we ensure CPU time never decreases.
        self._max_cpu_time_seen: float = 0.0

        # Per-phase statistics
        self._phase_stats: dict[str, PhaseStats] = {
            "Update": PhaseStats("Update"),
            "Download": PhaseStats("Download"),
            "Upgrade": PhaseStats("Upgrade"),
        }
        self._current_phase: str | None = None
        self._phase_start_time: datetime | None = None

        # Track CPU time at phase start to calculate per-phase CPU time
        self._phase_start_cpu_time: float = 0.0
        # Track network bytes at phase start for per-phase data
        self._phase_start_network_bytes: int = 0

        # Restore phase stats from MetricsStore if available
        self._restore_from_store()

    @property
    def metrics(self) -> PhaseMetrics:
        """Get the current metrics."""
        return self._metrics

    @property
    def cached_metrics(self) -> PhaseMetrics:
        """Get the cached metrics for fast UI reads.

        This property returns the most recently collected metrics without
        triggering a new collection. It's designed for high-frequency UI
        reads (e.g., 30 Hz) where the actual collection happens at a lower
        frequency (e.g., 1 Hz) in a background thread.

        Returns:
            The cached PhaseMetrics from the last collection.
        """
        return self._cached_metrics

    @property
    def phase_stats(self) -> dict[str, PhaseStats]:
        """Get per-phase statistics."""
        return self._phase_stats

    @property
    def metrics_store(self) -> MetricsStore:
        """Get the underlying MetricsStore for persistent storage."""
        return self._metrics_store

    def _restore_from_store(self) -> None:
        """Restore phase stats from the MetricsStore.

        This method is called during initialization to restore any
        previously completed phase statistics from the MetricsStore.
        This ensures that phase metrics persist across PTY session
        restarts and phase transitions.
        """
        for phase_name, snapshot in self._metrics_store.get_all_snapshots().items():
            if phase_name in self._phase_stats:
                stats = self._phase_stats[phase_name]
                stats.wall_time_seconds = snapshot.wall_time_seconds
                stats.cpu_time_seconds = snapshot.cpu_time_seconds
                stats.data_bytes = snapshot.data_bytes
                stats.packages = snapshot.packages
                stats.peak_memory_mb = snapshot.peak_memory_mb
                stats.is_complete = True
                stats.is_running = False

        # Restore accumulated metrics
        accumulated = self._metrics_store.get_accumulated_metrics()
        self._max_cpu_time_seen = accumulated.total_cpu_time_seconds
        self._peak_memory_mb = accumulated.peak_memory_mb

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

    def update_pid(self, pid: int | None) -> None:
        """Update the process ID to monitor.

        This method allows updating the PID when transitioning between phases.
        Each phase may spawn a new process, but we want to preserve accumulated
        statistics across phases. This method updates the PID while keeping
        all existing phase statistics intact.

        Args:
            pid: New process ID to monitor, or None for current process.
        """
        self.pid = pid
        # Reset the process object so it will be recreated with the new PID
        self._process = None
        # Take a new baseline for network/disk I/O deltas
        # Note: We don't reset _max_cpu_time_seen because we want to preserve
        # the total CPU time accumulated across all phases
        self._baseline = self._take_baseline_snapshot()
        # Prime the CPU percent counter for the new process
        process = self._get_process()
        if process:
            with contextlib.suppress(Exception):
                process.cpu_percent()  # First call returns 0, primes the counter

    def start_phase(self, phase_name: str) -> None:
        """Start tracking a new phase.

        Args:
            phase_name: Name of the phase (Update, Download, Upgrade).
        """
        if phase_name in self._phase_stats:
            # Collect current metrics first to ensure we have up-to-date values
            self.collect()

            self._current_phase = phase_name
            self._phase_start_time = datetime.now(tz=UTC)
            self._phase_stats[phase_name].is_running = True
            self._phase_stats[phase_name].is_complete = False

            # Record starting CPU time and network bytes for per-phase calculation
            # These are now up-to-date after the collect() call above
            self._phase_start_cpu_time = self._metrics.cpu_time_seconds
            self._phase_start_network_bytes = self._metrics.network_bytes

            # Notify the MetricsStore that a new phase is starting
            self._metrics_store.start_phase(phase_name)

    def complete_phase(self, phase_name: str, *, success: bool = True) -> None:
        """Mark a phase as complete and snapshot metrics to the store.

        This method marks the phase as complete and creates an immutable
        snapshot in the MetricsStore. The snapshot is preserved even if
        the PTY session is restarted or the MetricsCollector is reset.

        Args:
            phase_name: Name of the phase (Update, Download, Upgrade).
            success: Whether the phase completed successfully.
        """
        if phase_name in self._phase_stats:
            stats = self._phase_stats[phase_name]
            stats.is_running = False
            stats.is_complete = True
            if self._phase_start_time:
                elapsed = (datetime.now(tz=UTC) - self._phase_start_time).total_seconds()
                stats.wall_time_seconds = elapsed

            # Snapshot the phase metrics to the MetricsStore
            # This creates an immutable record that persists across
            # PTY session restarts and phase transitions
            self._metrics_store.snapshot_phase(phase_name, stats, success=success)

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
        force: bool = False,
    ) -> None:
        """Update statistics for a specific phase.

        Args:
            phase_name: Name of the phase.
            data_bytes: Data downloaded in bytes.
            cpu_time_seconds: CPU time in seconds.
            packages: Number of packages processed.
            peak_memory_mb: Peak memory usage in MB.
            force: If True, update even if phase is complete (default: False).
        """
        if phase_name not in self._phase_stats:
            return

        stats = self._phase_stats[phase_name]

        # Don't update completed phases unless force is True
        # This fixes the issue where phase counters were reset when
        # transitioning to a new phase
        if stats.is_complete and not force:
            return

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

    def _collect_process_tree_metrics(
        self,
        process: psutil.Process,
    ) -> tuple[float, float, float]:
        """Collect aggregated metrics from a process and all its descendants.

        This method recursively collects CPU percent, memory, and CPU time
        from the given process and all its children (grandchildren, etc.).
        This is essential for accurately measuring resource usage when the
        monitored PID is a shell that spawns child processes to do the work.

        Args:
            process: The root psutil.Process to collect metrics from.

        Returns:
            Tuple of (cpu_percent, memory_mb, cpu_time_seconds) aggregated
            from the process and all its descendants.
        """
        import psutil

        total_cpu_percent = 0.0
        total_memory_mb = 0.0
        total_cpu_time = 0.0

        # Collect from the main process
        try:
            total_cpu_percent += process.cpu_percent()
            mem_info = process.memory_info()
            total_memory_mb += mem_info.rss / (1024 * 1024)
            cpu_times = process.cpu_times()
            total_cpu_time += cpu_times.user + cpu_times.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Collect from all child processes recursively
        try:
            children = process.children(recursive=True)
            for child in children:
                try:
                    total_cpu_percent += child.cpu_percent()
                    child_mem = child.memory_info()
                    total_memory_mb += child_mem.rss / (1024 * 1024)
                    child_cpu_times = child.cpu_times()
                    total_cpu_time += child_cpu_times.user + child_cpu_times.system
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Child process may have exited, skip it
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Parent process may have exited
            pass

        return total_cpu_percent, total_memory_mb, total_cpu_time

    def collect(self) -> PhaseMetrics:
        """Collect current metrics.

        This method collects metrics from the monitored process and ALL its
        descendant processes (children, grandchildren, etc.). This is important
        because the monitored PID is typically a shell process that spawns
        child processes to do the actual work. Many upgrade scripts are just
        wrappers that spawn other processes.

        Returns:
            Updated PhaseMetrics with current values.
        """
        if not self._running:
            return self._metrics

        try:
            import psutil

            # Try to get process-specific metrics first
            process = self._get_process()

            # Collect metrics from process tree (parent + all descendants)
            if process:
                try:
                    cpu_percent, memory_mb, cpu_time = self._collect_process_tree_metrics(process)
                    self._metrics.cpu_percent = cpu_percent
                    self._metrics.memory_mb = memory_mb
                    # Use maximum of current and previously seen CPU time.
                    # When child processes exit, their CPU time is lost from the
                    # process tree. By tracking the maximum, we ensure CPU time
                    # never decreases, which fixes the issue where CPU counters
                    # would reset to zero after each action (like "Checking repository...").
                    self._max_cpu_time_seen = max(self._max_cpu_time_seen, cpu_time)
                    self._metrics.cpu_time_seconds = self._max_cpu_time_seen
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # Fall back to system-wide metrics
                    self._metrics.cpu_percent = psutil.cpu_percent()
                    mem = psutil.virtual_memory()
                    self._metrics.memory_mb = mem.used / (1024 * 1024)
                    if self._baseline:
                        elapsed = (datetime.now(tz=UTC) - self._baseline.timestamp).total_seconds()
                        self._metrics.cpu_time_seconds = elapsed * (
                            self._metrics.cpu_percent / 100.0
                        )
            else:
                # No process to monitor, use system-wide metrics
                self._metrics.cpu_percent = psutil.cpu_percent()
                mem = psutil.virtual_memory()
                self._metrics.memory_mb = mem.used / (1024 * 1024)
                if self._baseline:
                    elapsed = (datetime.now(tz=UTC) - self._baseline.timestamp).total_seconds()
                    self._metrics.cpu_time_seconds = elapsed * (self._metrics.cpu_percent / 100.0)

            # Update peak memory
            self._peak_memory_mb = max(self._peak_memory_mb, self._metrics.memory_mb)
            self._metrics.memory_peak_mb = self._peak_memory_mb

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

            # Update current phase stats with per-phase deltas
            if self._current_phase:
                # Calculate per-phase CPU time (delta from phase start)
                phase_cpu_time = max(
                    0.0,
                    self._metrics.cpu_time_seconds - self._phase_start_cpu_time,
                )
                # Calculate per-phase network bytes (delta from phase start)
                phase_data_bytes = max(
                    0,
                    self._metrics.network_bytes - self._phase_start_network_bytes,
                )
                self.update_phase_stats(
                    self._current_phase,
                    cpu_time_seconds=phase_cpu_time,
                    peak_memory_mb=self._metrics.memory_peak_mb,
                    data_bytes=phase_data_bytes,
                )

            self._metrics.error_message = None
            self._last_update = datetime.now(tz=UTC)

        except Exception as e:
            self._metrics.error_message = str(e)

        # Update the cached metrics for fast UI reads
        # This allows the UI to read at high frequency (30 Hz) while
        # actual collection happens at lower frequency (1 Hz)
        self._update_cached_metrics()

        return self._metrics

    def _update_cached_metrics(self) -> None:
        """Update the cached metrics from the current metrics.

        This method copies all fields from _metrics to _cached_metrics.
        The cached metrics are used by the UI for high-frequency reads
        without triggering expensive psutil collection.
        """
        m = self._metrics
        c = self._cached_metrics
        c.status = m.status
        c.pause_after_phase = m.pause_after_phase
        c.eta_seconds = m.eta_seconds
        c.eta_error_seconds = m.eta_error_seconds
        c.cpu_percent = m.cpu_percent
        c.memory_mb = m.memory_mb
        c.memory_peak_mb = m.memory_peak_mb
        c.items_completed = m.items_completed
        c.items_total = m.items_total
        c.network_bytes = m.network_bytes
        c.disk_io_bytes = m.disk_io_bytes
        c.cpu_time_seconds = m.cpu_time_seconds
        c.projected_download_bytes = m.projected_download_bytes
        c.projected_upgrade_bytes = m.projected_upgrade_bytes
        c.actual_download_bytes = m.actual_download_bytes
        c.actual_upgrade_bytes = m.actual_upgrade_bytes
        c.error_message = m.error_message

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


def create_metrics_collector_for_pid(pid: int | None = None) -> MetricsCollector:
    """Create a MetricsCollector for a process.

    Factory function to create a properly configured MetricsCollector.

    Args:
        pid: Process ID to monitor, or None for current process.

    Returns:
        Configured MetricsCollector instance.
    """
    return MetricsCollector(pid=pid, update_interval=1.0)

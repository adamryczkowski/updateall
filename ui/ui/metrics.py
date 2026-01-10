"""Persistent metrics storage for phase transitions.

This module provides a MetricsStore class that maintains metrics across
phase transitions and PTY session restarts. It addresses the architectural
issue where metrics were tied to ephemeral PTY sessions.

Milestone 3 - Textual Library Usage Review and Fixes
See docs/cleanup-and-refactoring-plan.md section 3.3.1
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ui.phase_status_bar import PhaseStats


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

"""Unit tests for the MetricsStore class.

This module contains unit tests for the MetricsStore class, which provides
persistent storage for phase metrics across PTY session lifecycles.

The MetricsStore was introduced as part of the fix for Bug 1 and Bug 2
(CPU statistics not updating, phase counters resetting). It provides a
separate storage layer that persists metrics even when the MetricsCollector
is stopped or recreated.

Test Categories:
    - PhaseSnapshot: Tests for the PhaseSnapshot dataclass
    - AccumulatedMetrics: Tests for the AccumulatedMetrics dataclass
    - MetricsStore: Tests for the MetricsStore class
    - Integration: Integration tests with MetricsCollector

See Also:
    - test_regression_bugs.py for bug fix regression tests
    - docs/cleanup-and-refactoring-plan.md section 3.3.1
    - docs/bug-investigation-report.md
"""

from __future__ import annotations

from ui.metrics import AccumulatedMetrics, MetricsStore, PhaseSnapshot
from ui.phase_status_bar import PhaseStats


class TestPhaseSnapshot:
    """Tests for PhaseSnapshot dataclass."""

    def test_default_values(self) -> None:
        """Test PhaseSnapshot with default values."""
        snapshot = PhaseSnapshot(phase_name="Update")
        assert snapshot.phase_name == "Update"
        assert snapshot.wall_time_seconds == 0.0
        assert snapshot.cpu_time_seconds == 0.0
        assert snapshot.data_bytes == 0
        assert snapshot.packages == 0
        assert snapshot.peak_memory_mb == 0.0
        assert snapshot.start_time is None
        assert snapshot.end_time is None
        assert snapshot.success is True

    def test_custom_values(self) -> None:
        """Test PhaseSnapshot with custom values."""
        snapshot = PhaseSnapshot(
            phase_name="Download",
            wall_time_seconds=10.5,
            cpu_time_seconds=5.2,
            data_bytes=1024000,
            packages=5,
            peak_memory_mb=128.5,
            success=False,
        )
        assert snapshot.phase_name == "Download"
        assert snapshot.wall_time_seconds == 10.5
        assert snapshot.cpu_time_seconds == 5.2
        assert snapshot.data_bytes == 1024000
        assert snapshot.packages == 5
        assert snapshot.peak_memory_mb == 128.5
        assert snapshot.success is False


class TestAccumulatedMetrics:
    """Tests for AccumulatedMetrics dataclass."""

    def test_default_values(self) -> None:
        """Test AccumulatedMetrics with default values."""
        metrics = AccumulatedMetrics()
        assert metrics.total_cpu_time_seconds == 0.0
        assert metrics.total_data_bytes == 0
        assert metrics.total_wall_time_seconds == 0.0
        assert metrics.total_packages == 0
        assert metrics.peak_memory_mb == 0.0


class TestMetricsStore:
    """Tests for MetricsStore class."""

    def test_init(self) -> None:
        """Test MetricsStore initialization."""
        store = MetricsStore()
        assert store.current_phase is None
        assert store.has_completed_phases is False
        assert store.get_all_snapshots() == {}

    def test_start_phase(self) -> None:
        """Test starting a phase."""
        store = MetricsStore()
        store.start_phase("Update")
        assert store.current_phase == "Update"

    def test_snapshot_phase(self) -> None:
        """Test snapshotting a phase."""
        store = MetricsStore()
        store.start_phase("Update")

        stats = PhaseStats(
            phase_name="Update",
            wall_time_seconds=10.0,
            cpu_time_seconds=5.0,
            data_bytes=1024,
            packages=3,
            peak_memory_mb=100.0,
        )

        snapshot = store.snapshot_phase("Update", stats)

        assert snapshot.phase_name == "Update"
        assert snapshot.wall_time_seconds == 10.0
        assert snapshot.cpu_time_seconds == 5.0
        assert snapshot.data_bytes == 1024
        assert snapshot.packages == 3
        assert snapshot.peak_memory_mb == 100.0
        assert snapshot.success is True
        assert store.current_phase is None
        assert store.has_completed_phases is True

    def test_snapshot_phase_failure(self) -> None:
        """Test snapshotting a failed phase."""
        store = MetricsStore()
        store.start_phase("Download")

        stats = PhaseStats(phase_name="Download", wall_time_seconds=5.0)
        snapshot = store.snapshot_phase("Download", stats, success=False)

        assert snapshot.success is False

    def test_get_phase_snapshot(self) -> None:
        """Test retrieving a phase snapshot."""
        store = MetricsStore()
        store.start_phase("Update")
        stats = PhaseStats(phase_name="Update", wall_time_seconds=10.0)
        store.snapshot_phase("Update", stats)

        snapshot = store.get_phase_snapshot("Update")
        assert snapshot is not None
        assert snapshot.phase_name == "Update"

        # Non-existent phase
        assert store.get_phase_snapshot("NonExistent") is None

    def test_get_all_snapshots(self) -> None:
        """Test retrieving all snapshots."""
        store = MetricsStore()

        # Snapshot multiple phases
        for phase in ["Update", "Download", "Upgrade"]:
            store.start_phase(phase)
            stats = PhaseStats(phase_name=phase, wall_time_seconds=10.0)
            store.snapshot_phase(phase, stats)

        snapshots = store.get_all_snapshots()
        assert len(snapshots) == 3
        assert "Update" in snapshots
        assert "Download" in snapshots
        assert "Upgrade" in snapshots

    def test_get_accumulated_metrics(self) -> None:
        """Test accumulated metrics calculation."""
        store = MetricsStore()

        # Snapshot Update phase
        store.start_phase("Update")
        stats1 = PhaseStats(
            phase_name="Update",
            wall_time_seconds=10.0,
            cpu_time_seconds=5.0,
            data_bytes=1000,
            packages=2,
            peak_memory_mb=100.0,
        )
        store.snapshot_phase("Update", stats1)

        # Snapshot Download phase
        store.start_phase("Download")
        stats2 = PhaseStats(
            phase_name="Download",
            wall_time_seconds=20.0,
            cpu_time_seconds=8.0,
            data_bytes=5000,
            packages=3,
            peak_memory_mb=150.0,
        )
        store.snapshot_phase("Download", stats2)

        accumulated = store.get_accumulated_metrics()
        assert accumulated.total_wall_time_seconds == 30.0
        assert accumulated.total_cpu_time_seconds == 13.0
        assert accumulated.total_data_bytes == 6000
        assert accumulated.total_packages == 5
        assert accumulated.peak_memory_mb == 150.0  # Max of 100 and 150

    def test_update_live_metrics(self) -> None:
        """Test updating live metrics."""
        store = MetricsStore()

        # Update with increasing values
        store.update_live_metrics(cpu_time_seconds=5.0, data_bytes=1000)
        accumulated = store.get_accumulated_metrics()
        assert accumulated.total_cpu_time_seconds == 5.0
        assert accumulated.total_data_bytes == 1000

        # Update with higher values
        store.update_live_metrics(cpu_time_seconds=10.0, data_bytes=2000)
        accumulated = store.get_accumulated_metrics()
        assert accumulated.total_cpu_time_seconds == 10.0
        assert accumulated.total_data_bytes == 2000

        # Update with lower values (should not decrease)
        store.update_live_metrics(cpu_time_seconds=3.0, data_bytes=500)
        accumulated = store.get_accumulated_metrics()
        assert accumulated.total_cpu_time_seconds == 10.0  # Still 10
        assert accumulated.total_data_bytes == 2000  # Still 2000

    def test_update_live_metrics_peak_memory(self) -> None:
        """Test peak memory tracking in live metrics."""
        store = MetricsStore()

        store.update_live_metrics(peak_memory_mb=100.0)
        assert store.get_accumulated_metrics().peak_memory_mb == 100.0

        store.update_live_metrics(peak_memory_mb=200.0)
        assert store.get_accumulated_metrics().peak_memory_mb == 200.0

        store.update_live_metrics(peak_memory_mb=50.0)
        assert store.get_accumulated_metrics().peak_memory_mb == 200.0  # Still max

    def test_reset(self) -> None:
        """Test resetting the store."""
        store = MetricsStore()

        # Add some data
        store.start_phase("Update")
        stats = PhaseStats(phase_name="Update", wall_time_seconds=10.0)
        store.snapshot_phase("Update", stats)
        store.update_live_metrics(cpu_time_seconds=5.0)

        # Reset
        store.reset()

        assert store.current_phase is None
        assert store.has_completed_phases is False
        assert store.get_all_snapshots() == {}
        assert store.get_accumulated_metrics().total_cpu_time_seconds == 0.0

    def test_phase_snapshots_preserve_across_multiple_phases(self) -> None:
        """Test that phase snapshots are preserved across multiple phases."""
        store = MetricsStore()

        # Complete Update phase
        store.start_phase("Update")
        update_stats = PhaseStats(
            phase_name="Update",
            wall_time_seconds=10.0,
            cpu_time_seconds=5.0,
        )
        store.snapshot_phase("Update", update_stats)

        # Start and complete Download phase
        store.start_phase("Download")
        download_stats = PhaseStats(
            phase_name="Download",
            wall_time_seconds=20.0,
            cpu_time_seconds=8.0,
        )
        store.snapshot_phase("Download", download_stats)

        # Verify Update phase is still preserved
        update_snapshot = store.get_phase_snapshot("Update")
        assert update_snapshot is not None
        assert update_snapshot.wall_time_seconds == 10.0
        assert update_snapshot.cpu_time_seconds == 5.0

        # Verify Download phase is also preserved
        download_snapshot = store.get_phase_snapshot("Download")
        assert download_snapshot is not None
        assert download_snapshot.wall_time_seconds == 20.0
        assert download_snapshot.cpu_time_seconds == 8.0


class TestMetricsStoreIntegration:
    """Integration tests for MetricsStore with MetricsCollector."""

    def test_metrics_collector_uses_store(self) -> None:
        """Test that MetricsCollector uses MetricsStore."""
        from ui.phase_status_bar import MetricsCollector

        store = MetricsStore()
        collector = MetricsCollector(metrics_store=store)

        assert collector.metrics_store is store

    def test_metrics_collector_creates_store_if_not_provided(self) -> None:
        """Test that MetricsCollector creates a store if not provided."""
        from ui.phase_status_bar import MetricsCollector

        collector = MetricsCollector()
        assert collector.metrics_store is not None

    def test_phase_completion_snapshots_to_store(self) -> None:
        """Test that completing a phase creates a snapshot in the store."""
        from ui.phase_status_bar import MetricsCollector

        store = MetricsStore()
        collector = MetricsCollector(metrics_store=store)
        collector.start()

        # Start and complete a phase
        collector.start_phase("Update")
        # Update stats using the available parameters
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=1024)
        collector.complete_phase("Update")

        # Verify snapshot was created
        snapshot = store.get_phase_snapshot("Update")
        assert snapshot is not None
        assert snapshot.phase_name == "Update"
        assert snapshot.cpu_time_seconds == 5.0
        assert snapshot.data_bytes == 1024

    def test_store_preserves_metrics_across_pid_update(self) -> None:
        """Test that MetricsStore preserves metrics when PID is updated."""
        from ui.phase_status_bar import MetricsCollector

        store = MetricsStore()
        collector = MetricsCollector(pid=None, metrics_store=store)
        collector.start()

        # Complete first phase - set stats before completing
        collector.start_phase("Update")
        # Directly set the stats for testing
        collector._phase_stats["Update"].cpu_time_seconds = 5.0
        collector._phase_stats["Update"].data_bytes = 2048
        collector.complete_phase("Update")

        # Simulate PID update (new PTY session)
        collector.update_pid(12345)

        # Verify Update phase is still preserved in the store
        snapshot = store.get_phase_snapshot("Update")
        assert snapshot is not None
        assert snapshot.cpu_time_seconds == 5.0
        assert snapshot.data_bytes == 2048

    def test_new_collector_restores_from_store(self) -> None:
        """Test that a new MetricsCollector restores from existing store."""
        from ui.phase_status_bar import MetricsCollector

        store = MetricsStore()

        # First collector completes a phase
        collector1 = MetricsCollector(metrics_store=store)
        collector1.start()
        collector1.start_phase("Update")
        # Set stats before completing
        collector1._phase_stats["Update"].cpu_time_seconds = 5.0
        collector1._phase_stats["Update"].data_bytes = 1024
        collector1._phase_stats["Update"].packages = 3
        collector1.complete_phase("Update")
        collector1.stop()

        # Second collector with same store should see the completed phase
        collector2 = MetricsCollector(metrics_store=store)

        # The phase stats should be restored
        assert collector2.phase_stats["Update"].is_complete is True
        assert collector2.phase_stats["Update"].cpu_time_seconds == 5.0
        assert collector2.phase_stats["Update"].data_bytes == 1024
        assert collector2.phase_stats["Update"].packages == 3

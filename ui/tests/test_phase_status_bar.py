"""Tests for phase_status_bar module.

UI Revision Plan - Phase 3 Status Bar
See docs/UI-revision-plan.md section 5.3
"""

from __future__ import annotations

from ui.metrics import (
    MetricsCollector,
    MetricsSnapshot,
    PhaseMetrics,
    create_metrics_collector_for_pid,
)
from ui.phase_status_bar import (
    PHASE_STATUS_BAR_CSS,
    PhaseStatusBar,
)


class TestPhaseMetrics:
    """Tests for PhaseMetrics dataclass."""

    def test_default_values(self) -> None:
        """Test that PhaseMetrics has sensible defaults."""
        metrics = PhaseMetrics()

        assert metrics.status == "Pending"
        assert metrics.pause_after_phase is False
        assert metrics.eta_seconds is None
        assert metrics.eta_error_seconds is None
        assert metrics.cpu_percent == 0.0
        assert metrics.memory_mb == 0.0
        assert metrics.memory_peak_mb == 0.0
        assert metrics.items_completed == 0
        assert metrics.items_total is None
        assert metrics.network_bytes == 0
        assert metrics.disk_io_bytes == 0
        assert metrics.cpu_time_seconds == 0.0
        assert metrics.error_message is None

    def test_custom_values(self) -> None:
        """Test that PhaseMetrics accepts custom values."""
        metrics = PhaseMetrics(
            status="In Progress",
            pause_after_phase=True,
            eta_seconds=150.0,
            eta_error_seconds=15.0,
            cpu_percent=45.5,
            memory_mb=128.0,
            memory_peak_mb=256.0,
            items_completed=15,
            items_total=42,
            network_bytes=157286400,
            disk_io_bytes=48234496,
            cpu_time_seconds=83.5,
        )

        assert metrics.status == "In Progress"
        assert metrics.pause_after_phase is True
        assert metrics.eta_seconds == 150.0
        assert metrics.eta_error_seconds == 15.0
        assert metrics.cpu_percent == 45.5
        assert metrics.memory_mb == 128.0
        assert metrics.memory_peak_mb == 256.0
        assert metrics.items_completed == 15
        assert metrics.items_total == 42
        assert metrics.network_bytes == 157286400
        assert metrics.disk_io_bytes == 48234496
        assert metrics.cpu_time_seconds == 83.5

    def test_error_message(self) -> None:
        """Test error message field."""
        metrics = PhaseMetrics(error_message="Process not accessible")
        assert metrics.error_message == "Process not accessible"


class TestMetricsSnapshot:
    """Tests for MetricsSnapshot dataclass."""

    def test_default_values(self) -> None:
        """Test that MetricsSnapshot has sensible defaults."""
        snapshot = MetricsSnapshot()

        assert snapshot.timestamp is not None
        assert snapshot.network_bytes_sent == 0
        assert snapshot.network_bytes_recv == 0
        assert snapshot.disk_read_bytes == 0
        assert snapshot.disk_write_bytes == 0

    def test_custom_values(self) -> None:
        """Test that MetricsSnapshot accepts custom values."""
        from datetime import UTC, datetime

        now = datetime.now(tz=UTC)
        snapshot = MetricsSnapshot(
            timestamp=now,
            network_bytes_sent=1000,
            network_bytes_recv=2000,
            disk_read_bytes=3000,
            disk_write_bytes=4000,
        )

        assert snapshot.timestamp == now
        assert snapshot.network_bytes_sent == 1000
        assert snapshot.network_bytes_recv == 2000
        assert snapshot.disk_read_bytes == 3000
        assert snapshot.disk_write_bytes == 4000


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_init_default_values(self) -> None:
        """Test MetricsCollector initialization with defaults."""
        collector = MetricsCollector()

        assert collector.pid is None
        assert collector.update_interval >= MetricsCollector.MIN_UPDATE_INTERVAL

    def test_init_with_pid(self) -> None:
        """Test MetricsCollector initialization with PID."""
        collector = MetricsCollector(pid=1234)
        assert collector.pid == 1234

    def test_init_enforces_min_interval(self) -> None:
        """Test that update_interval is at least MIN_UPDATE_INTERVAL."""
        collector = MetricsCollector(update_interval=0.1)
        assert collector.update_interval >= MetricsCollector.MIN_UPDATE_INTERVAL

    def test_metrics_property(self) -> None:
        """Test that metrics property returns PhaseMetrics."""
        collector = MetricsCollector()
        metrics = collector.metrics

        assert isinstance(metrics, PhaseMetrics)

    def test_start_sets_running(self) -> None:
        """Test that start() sets running state."""
        collector = MetricsCollector()
        collector.start()

        assert collector._running is True
        assert collector._baseline is not None

    def test_stop_clears_running(self) -> None:
        """Test that stop() clears running state."""
        collector = MetricsCollector()
        collector.start()
        collector.stop()

        assert collector._running is False

    def test_update_progress(self) -> None:
        """Test update_progress method."""
        collector = MetricsCollector()
        collector.update_progress(15, 42)

        assert collector.metrics.items_completed == 15
        assert collector.metrics.items_total == 42

    def test_update_progress_without_total(self) -> None:
        """Test update_progress without total."""
        collector = MetricsCollector()
        collector.update_progress(10)

        assert collector.metrics.items_completed == 10
        assert collector.metrics.items_total is None

    def test_update_eta(self) -> None:
        """Test update_eta method."""
        collector = MetricsCollector()
        collector.update_eta(150.0, 15.0)

        assert collector.metrics.eta_seconds == 150.0
        assert collector.metrics.eta_error_seconds == 15.0

    def test_update_eta_without_error(self) -> None:
        """Test update_eta without error margin."""
        collector = MetricsCollector()
        collector.update_eta(120.0)

        assert collector.metrics.eta_seconds == 120.0
        assert collector.metrics.eta_error_seconds is None

    def test_update_status(self) -> None:
        """Test update_status method."""
        collector = MetricsCollector()
        collector.update_status("In Progress", pause_after_phase=True)

        assert collector.metrics.status == "In Progress"
        assert collector.metrics.pause_after_phase is True

    def test_collect_when_not_running(self) -> None:
        """Test collect returns current metrics when not running."""
        collector = MetricsCollector()
        collector.update_status("Test Status")

        metrics = collector.collect()

        assert metrics.status == "Test Status"

    def test_collect_with_real_psutil(self) -> None:
        """Test collect with real psutil on current process."""
        import os

        collector = MetricsCollector(pid=os.getpid())
        collector.start()
        metrics = collector.collect()

        # Should have collected some metrics without error
        assert metrics.error_message is None
        # CPU percent should be a valid number (may be 0.0 on first call)
        assert metrics.cpu_percent >= 0.0
        # Memory should be positive for a running process
        assert metrics.memory_mb > 0.0
        # Peak memory should be at least current memory
        assert metrics.memory_peak_mb >= metrics.memory_mb

    def test_collect_handles_process_not_found(self) -> None:
        """Test collect handles missing process gracefully."""
        collector = MetricsCollector(pid=999999999)  # Non-existent PID
        collector.start()
        metrics = collector.collect()

        # Should have error message or default values
        assert metrics is not None


class TestPhaseStatusBar:
    """Tests for PhaseStatusBar widget."""

    def test_init(self) -> None:
        """Test PhaseStatusBar initialization."""
        status_bar = PhaseStatusBar(pane_id="test")

        assert status_bar.pane_id == "test"
        assert status_bar.id == "status-bar-test"

    def test_init_with_custom_id(self) -> None:
        """Test PhaseStatusBar with custom ID."""
        status_bar = PhaseStatusBar(pane_id="test", id="custom-id")

        assert status_bar.id == "custom-id"

    def test_update_metrics(self) -> None:
        """Test update_metrics method."""
        status_bar = PhaseStatusBar(pane_id="test")
        metrics = PhaseMetrics(status="Running", cpu_percent=50.0)

        status_bar.update_metrics(metrics)

        assert status_bar.metrics.status == "Running"
        assert status_bar.metrics.cpu_percent == 50.0

    def test_set_metrics_collector(self) -> None:
        """Test set_metrics_collector method."""
        status_bar = PhaseStatusBar(pane_id="test")
        collector = MetricsCollector()

        status_bar.set_metrics_collector(collector)

        assert status_bar._metrics_collector is collector

    def test_collect_and_update(self) -> None:
        """Test collect_and_update method."""
        status_bar = PhaseStatusBar(pane_id="test")
        collector = MetricsCollector()
        collector.update_status("Collecting")

        status_bar.set_metrics_collector(collector)
        status_bar.collect_and_update()

        assert status_bar.metrics.status == "Collecting"

    def test_format_eta_none(self) -> None:
        """Test _format_eta with None value."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_eta(None, None)
        assert result == "N/A"

    def test_format_eta_with_value(self) -> None:
        """Test _format_eta with value."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_eta(150.0, None)
        assert result == "2m 30s"

    def test_format_eta_with_error(self) -> None:
        """Test _format_eta with error margin."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_eta(150.0, 15.0)
        assert "±" in result
        assert "2m 30s" in result

    def test_format_items_with_total(self) -> None:
        """Test _format_items with total."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_items(15, 42)
        assert result == "Items: 15/42"

    def test_format_items_without_total(self) -> None:
        """Test _format_items without total."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_items(15, None)
        assert result == "Items: 15"

    def test_format_items_zero(self) -> None:
        """Test _format_items with zero completed."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_items(0, None)
        assert result == "Items: --"

    def test_format_bytes_small(self) -> None:
        """Test _format_bytes with small values."""
        status_bar = PhaseStatusBar(pane_id="test")

        assert status_bar._format_bytes(500) == "500 B"
        assert status_bar._format_bytes(0) == "0 B"

    def test_format_bytes_kilobytes(self) -> None:
        """Test _format_bytes with kilobytes."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_bytes(1536)  # 1.5 KB
        assert "KB" in result

    def test_format_bytes_megabytes(self) -> None:
        """Test _format_bytes with megabytes."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_bytes(157286400)  # ~150 MB
        assert "MB" in result

    def test_format_bytes_gigabytes(self) -> None:
        """Test _format_bytes with gigabytes."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_bytes(2147483648)  # 2 GB
        assert "GB" in result

    def test_format_duration_seconds(self) -> None:
        """Test _format_duration with seconds."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_duration(45)
        assert result == "45s"

    def test_format_duration_minutes(self) -> None:
        """Test _format_duration with minutes."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_duration(150)
        assert result == "2m 30s"

    def test_format_duration_hours(self) -> None:
        """Test _format_duration with hours."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_duration(3750)  # 1h 2m 30s
        assert result == "1h 2m"

    def test_format_duration_negative(self) -> None:
        """Test _format_duration with negative value."""
        status_bar = PhaseStatusBar(pane_id="test")
        result = status_bar._format_duration(-5)
        assert result == "N/A"


class TestPhaseStatusBarCss:
    """Tests for PHASE_STATUS_BAR_CSS constant."""

    def test_css_is_valid_string(self) -> None:
        """Test that CSS is a non-empty string."""
        assert isinstance(PHASE_STATUS_BAR_CSS, str)
        assert len(PHASE_STATUS_BAR_CSS) > 0

    def test_css_contains_widget_class(self) -> None:
        """Test that CSS contains PhaseStatusBar class."""
        assert "PhaseStatusBar" in PHASE_STATUS_BAR_CSS

    def test_css_contains_error_class(self) -> None:
        """Test that CSS contains error class."""
        assert ".error" in PHASE_STATUS_BAR_CSS

    def test_css_contains_paused_class(self) -> None:
        """Test that CSS contains paused class."""
        assert ".paused" in PHASE_STATUS_BAR_CSS

    def test_css_contains_color_variables(self) -> None:
        """Test that CSS uses Textual color variables."""
        assert "$surface" in PHASE_STATUS_BAR_CSS
        assert "$primary" in PHASE_STATUS_BAR_CSS
        assert "$error" in PHASE_STATUS_BAR_CSS
        assert "$warning" in PHASE_STATUS_BAR_CSS


class TestCreateMetricsCollectorForPid:
    """Tests for create_metrics_collector_for_pid factory function."""

    def test_creates_collector(self) -> None:
        """Test that factory creates a MetricsCollector."""
        collector = create_metrics_collector_for_pid()
        assert isinstance(collector, MetricsCollector)

    def test_creates_collector_with_pid(self) -> None:
        """Test that factory creates collector with PID."""
        collector = create_metrics_collector_for_pid(pid=1234)
        assert collector.pid == 1234

    def test_creates_collector_with_default_interval(self) -> None:
        """Test that factory uses 1.0s update interval."""
        collector = create_metrics_collector_for_pid()
        assert collector.update_interval == 1.0


class TestPhaseStatusBarIntegration:
    """Integration tests for PhaseStatusBar."""

    def test_displays_status(self) -> None:
        """Test status is displayed."""
        status_bar = PhaseStatusBar(pane_id="test")
        metrics = PhaseMetrics(status="In Progress")
        status_bar.update_metrics(metrics)

        # The status should be in the metrics
        assert status_bar.metrics.status == "In Progress"

    def test_displays_eta_with_error(self) -> None:
        """Test ETA with error margin is displayed."""
        status_bar = PhaseStatusBar(pane_id="test")
        metrics = PhaseMetrics(eta_seconds=150.0, eta_error_seconds=15.0)
        status_bar.update_metrics(metrics)

        assert status_bar.metrics.eta_seconds == 150.0
        assert status_bar.metrics.eta_error_seconds == 15.0

    def test_displays_resource_usage(self) -> None:
        """Test CPU/memory usage is displayed."""
        status_bar = PhaseStatusBar(pane_id="test")
        metrics = PhaseMetrics(cpu_percent=45.0, memory_mb=128.0, memory_peak_mb=256.0)
        status_bar.update_metrics(metrics)

        assert status_bar.metrics.cpu_percent == 45.0
        assert status_bar.metrics.memory_mb == 128.0
        assert status_bar.metrics.memory_peak_mb == 256.0

    def test_handles_unavailable_metrics(self) -> None:
        """Test graceful handling of unavailable metrics."""
        status_bar = PhaseStatusBar(pane_id="test")
        metrics = PhaseMetrics(error_message="Process not accessible")
        status_bar.update_metrics(metrics)

        assert status_bar.metrics.error_message == "Process not accessible"

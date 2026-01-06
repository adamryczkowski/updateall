"""Tests for the metrics module.

Phase 5 - Monitoring Metrics tests.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from core.metrics import (
    MEMORY_ALERT_MB,
    MEMORY_TARGET_MB,
    QUEUE_DEPTH_ALERT,
    QUEUE_DEPTH_TARGET,
    UI_LATENCY_ALERT_MS,
    UI_LATENCY_TARGET_MS,
    LatencyTimer,
    MetricLevel,
    MetricsCollector,
    MetricValue,
    PluginMetrics,
    get_metrics_collector,
    set_metrics_collector,
)


class TestMetricValue:
    """Tests for MetricValue dataclass."""

    def test_metric_value_creation(self) -> None:
        """Test creating a MetricValue."""
        metric = MetricValue(
            name="test_metric",
            value=42.5,
            unit="MB",
            level=MetricLevel.OK,
            labels={"plugin": "apt"},
        )

        assert metric.name == "test_metric"
        assert metric.value == 42.5
        assert metric.unit == "MB"
        assert metric.level == MetricLevel.OK
        assert metric.labels == {"plugin": "apt"}
        assert metric.timestamp is not None

    def test_metric_value_to_dict(self) -> None:
        """Test MetricValue serialization."""
        metric = MetricValue(
            name="test_metric",
            value=100.0,
            unit="ms",
            level=MetricLevel.WARNING,
        )

        d = metric.to_dict()

        assert d["name"] == "test_metric"
        assert d["value"] == 100.0
        assert d["unit"] == "ms"
        assert d["level"] == "warning"
        assert "timestamp" in d


class TestPluginMetrics:
    """Tests for PluginMetrics dataclass."""

    def test_plugin_metrics_creation(self) -> None:
        """Test creating PluginMetrics."""
        pm = PluginMetrics(plugin_name="apt")

        assert pm.plugin_name == "apt"
        assert pm.start_time is not None
        assert pm.end_time is None
        assert pm.memory_peak_mb == 0.0
        assert pm.event_count == 0
        assert pm.error_count == 0

    def test_duration_seconds_property(self) -> None:
        """Test duration_seconds calculation."""
        pm = PluginMetrics(plugin_name="apt")
        pm.end_time = datetime.now(tz=UTC)

        duration = pm.duration_seconds
        assert duration is not None
        assert duration >= 0

    def test_duration_seconds_none_when_not_ended(self) -> None:
        """Test duration_seconds is None when not ended."""
        pm = PluginMetrics(plugin_name="apt")

        assert pm.duration_seconds is None

    def test_events_per_second_property(self) -> None:
        """Test events_per_second calculation."""
        pm = PluginMetrics(plugin_name="apt")
        pm.event_count = 100
        pm.end_time = datetime.now(tz=UTC)

        eps = pm.events_per_second
        assert eps is not None
        assert eps >= 0


class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_record_metric(self) -> None:
        """Test recording a metric."""
        collector = MetricsCollector()
        metric = MetricValue(
            name="test",
            value=1.0,
            unit="count",
        )

        collector.record_metric(metric)

        assert len(collector.metrics) == 1
        assert collector.metrics[0] == metric

    def test_record_memory_usage_ok(self) -> None:
        """Test recording memory usage below target."""
        collector = MetricsCollector()

        metric = collector.record_memory_usage("apt", 30.0)

        assert metric.level == MetricLevel.OK
        assert metric.value == 30.0
        assert metric.labels["plugin"] == "apt"

    def test_record_memory_usage_warning(self) -> None:
        """Test recording memory usage above target but below alert."""
        collector = MetricsCollector()

        metric = collector.record_memory_usage("apt", MEMORY_TARGET_MB + 10)

        assert metric.level == MetricLevel.WARNING

    def test_record_memory_usage_critical(self) -> None:
        """Test recording memory usage above alert threshold."""
        collector = MetricsCollector()

        metric = collector.record_memory_usage("apt", MEMORY_ALERT_MB + 10)

        assert metric.level == MetricLevel.CRITICAL

    def test_record_ui_latency_ok(self) -> None:
        """Test recording UI latency below target."""
        collector = MetricsCollector()

        metric = collector.record_ui_latency(30.0)

        assert metric.level == MetricLevel.OK
        assert metric.value == 30.0

    def test_record_ui_latency_warning(self) -> None:
        """Test recording UI latency above target but below alert."""
        collector = MetricsCollector()

        metric = collector.record_ui_latency(UI_LATENCY_TARGET_MS + 50)

        assert metric.level == MetricLevel.WARNING

    def test_record_ui_latency_critical(self) -> None:
        """Test recording UI latency above alert threshold."""
        collector = MetricsCollector()

        metric = collector.record_ui_latency(UI_LATENCY_ALERT_MS + 50)

        assert metric.level == MetricLevel.CRITICAL

    def test_record_queue_depth_ok(self) -> None:
        """Test recording queue depth below target."""
        collector = MetricsCollector()

        metric = collector.record_queue_depth(50)

        assert metric.level == MetricLevel.OK
        assert metric.value == 50.0

    def test_record_queue_depth_warning(self) -> None:
        """Test recording queue depth above target but below alert."""
        collector = MetricsCollector()

        metric = collector.record_queue_depth(QUEUE_DEPTH_TARGET + 100)

        assert metric.level == MetricLevel.WARNING

    def test_record_queue_depth_critical(self) -> None:
        """Test recording queue depth above alert threshold."""
        collector = MetricsCollector()

        metric = collector.record_queue_depth(QUEUE_DEPTH_ALERT + 100)

        assert metric.level == MetricLevel.CRITICAL

    def test_alert_callback(self) -> None:
        """Test alert callback is invoked on threshold exceeded."""
        alerts: list[MetricValue] = []

        def on_alert(metric: MetricValue) -> None:
            alerts.append(metric)

        collector = MetricsCollector(alert_callback=on_alert)
        collector.record_memory_usage("apt", MEMORY_ALERT_MB + 50)

        assert len(alerts) == 1
        assert alerts[0].level == MetricLevel.CRITICAL

    def test_start_plugin_execution(self) -> None:
        """Test starting plugin execution tracking."""
        collector = MetricsCollector()

        pm = collector.start_plugin_execution("apt")

        assert pm.plugin_name == "apt"
        assert "apt" in collector.plugin_metrics

    def test_end_plugin_execution(self) -> None:
        """Test ending plugin execution tracking."""
        collector = MetricsCollector()
        collector.start_plugin_execution("apt")

        pm = collector.end_plugin_execution("apt")

        assert pm is not None
        assert pm.end_time is not None
        assert pm.duration_seconds is not None

    def test_increment_event_count(self) -> None:
        """Test incrementing event count."""
        collector = MetricsCollector()
        collector.start_plugin_execution("apt")

        collector.increment_event_count("apt")
        collector.increment_event_count("apt")

        pm = collector.plugin_metrics["apt"]
        assert pm.event_count == 2

    def test_increment_error_count(self) -> None:
        """Test incrementing error count."""
        collector = MetricsCollector()
        collector.start_plugin_execution("apt")

        collector.increment_error_count("apt")

        pm = collector.plugin_metrics["apt"]
        assert pm.error_count == 1

    def test_get_average_ui_latency(self) -> None:
        """Test getting average UI latency."""
        collector = MetricsCollector()
        collector.record_ui_latency(10.0)
        collector.record_ui_latency(20.0)
        collector.record_ui_latency(30.0)

        avg = collector.get_average_ui_latency()

        assert avg == 20.0

    def test_get_average_ui_latency_empty(self) -> None:
        """Test getting average UI latency with no samples."""
        collector = MetricsCollector()

        avg = collector.get_average_ui_latency()

        assert avg is None

    def test_get_average_queue_depth(self) -> None:
        """Test getting average queue depth."""
        collector = MetricsCollector()
        collector.record_queue_depth(10)
        collector.record_queue_depth(20)
        collector.record_queue_depth(30)

        avg = collector.get_average_queue_depth()

        assert avg == 20.0

    def test_get_summary(self) -> None:
        """Test getting metrics summary."""
        collector = MetricsCollector()
        collector.start_plugin_execution("apt")
        collector.record_ui_latency(30.0)
        collector.record_memory_usage("apt", MEMORY_ALERT_MB + 10)

        summary = collector.get_summary()

        assert summary["total_metrics_recorded"] == 2
        assert "apt" in summary["plugins_tracked"]
        assert summary["alerts"]["critical"] == 1

    def test_clear(self) -> None:
        """Test clearing all metrics."""
        collector = MetricsCollector()
        collector.start_plugin_execution("apt")
        collector.record_ui_latency(30.0)

        collector.clear()

        assert len(collector.metrics) == 0
        assert len(collector.plugin_metrics) == 0


class TestLatencyTimer:
    """Tests for LatencyTimer context manager."""

    def test_sync_timer(self) -> None:
        """Test synchronous timer usage."""
        with LatencyTimer() as timer:
            # Simulate some work
            total = sum(range(1000))
            _ = total

        assert timer.elapsed_ms > 0
        assert timer.elapsed_seconds > 0

    @pytest.mark.asyncio
    async def test_async_timer(self) -> None:
        """Test asynchronous timer usage."""
        async with LatencyTimer() as timer:
            await asyncio.sleep(0.01)

        assert timer.elapsed_ms >= 10
        assert timer.elapsed_seconds >= 0.01


class TestGlobalCollector:
    """Tests for global metrics collector functions."""

    def test_get_metrics_collector(self) -> None:
        """Test getting global metrics collector."""
        collector = get_metrics_collector()

        assert isinstance(collector, MetricsCollector)

    def test_set_metrics_collector(self) -> None:
        """Test setting global metrics collector."""
        custom_collector = MetricsCollector()
        set_metrics_collector(custom_collector)

        assert get_metrics_collector() is custom_collector


class TestMetricLevel:
    """Tests for MetricLevel enum."""

    def test_metric_level_values(self) -> None:
        """Test MetricLevel enum values."""
        assert MetricLevel.OK.value == "ok"
        assert MetricLevel.WARNING.value == "warning"
        assert MetricLevel.CRITICAL.value == "critical"


class TestThresholdConstants:
    """Tests for threshold constants."""

    def test_memory_thresholds(self) -> None:
        """Test memory threshold values from architecture plan."""
        assert MEMORY_TARGET_MB == 50
        assert MEMORY_ALERT_MB == 100

    def test_ui_latency_thresholds(self) -> None:
        """Test UI latency threshold values from architecture plan."""
        assert UI_LATENCY_TARGET_MS == 50
        assert UI_LATENCY_ALERT_MS == 200

    def test_queue_depth_thresholds(self) -> None:
        """Test queue depth threshold values from architecture plan."""
        assert QUEUE_DEPTH_TARGET == 100
        assert QUEUE_DEPTH_ALERT == 500

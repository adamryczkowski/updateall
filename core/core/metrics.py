"""Monitoring metrics for production observability.

This module provides metrics collection and monitoring for the update-all system.
It tracks key performance indicators as specified in Phase 5 of the architecture
refinement plan.

Metrics tracked:
- Memory usage per plugin (target: < 50 MB, alert: > 100 MB)
- UI update latency (target: < 50 ms, alert: > 200 ms)
- Event queue depth (target: < 100, alert: > 500)
- Plugin execution time
- Streaming event throughput

Phase 5 - Polish, Testing & Documentation (Section 7.5.4)
See docs/update-all-architecture-refinement-plan.md
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class MetricLevel(str, Enum):
    """Severity level for metric alerts."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


# Threshold constants from architecture plan (Appendix B)
MEMORY_TARGET_MB = 50
MEMORY_ALERT_MB = 100
UI_LATENCY_TARGET_MS = 50
UI_LATENCY_ALERT_MS = 200
QUEUE_DEPTH_TARGET = 100
QUEUE_DEPTH_ALERT = 500
TEST_COVERAGE_TARGET = 80
TEST_COVERAGE_ALERT = 70


@dataclass
class MetricValue:
    """A single metric measurement.

    Attributes:
        name: Metric name.
        value: Numeric value.
        unit: Unit of measurement (e.g., "MB", "ms", "count").
        timestamp: When the metric was recorded.
        level: Alert level based on thresholds.
        labels: Additional labels for the metric.
    """

    name: str
    value: float
    unit: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    level: MetricLevel = MetricLevel.OK
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "labels": self.labels,
        }


@dataclass
class PluginMetrics:
    """Metrics for a single plugin execution.

    Attributes:
        plugin_name: Name of the plugin.
        start_time: Execution start time.
        end_time: Execution end time.
        memory_peak_mb: Peak memory usage in MB.
        event_count: Number of streaming events emitted.
        error_count: Number of errors encountered.
    """

    plugin_name: str
    start_time: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    end_time: datetime | None = None
    memory_peak_mb: float = 0.0
    event_count: int = 0
    error_count: int = 0

    @property
    def duration_seconds(self) -> float | None:
        """Calculate execution duration in seconds."""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    @property
    def events_per_second(self) -> float | None:
        """Calculate event throughput."""
        duration = self.duration_seconds
        if duration is None or duration == 0:
            return None
        return self.event_count / duration


class MetricsCollector:
    """Collects and manages metrics for the update-all system.

    This class provides methods to record metrics and check thresholds.
    It can optionally emit metrics to external monitoring systems.

    Attributes:
        metrics: List of recorded metrics.
        plugin_metrics: Metrics per plugin.
        alert_callback: Optional callback for threshold alerts.
    """

    def __init__(
        self,
        alert_callback: Callable[[MetricValue], None] | None = None,
    ) -> None:
        """Initialize the metrics collector.

        Args:
            alert_callback: Optional callback invoked when a metric exceeds thresholds.
        """
        self._metrics: list[MetricValue] = []
        self._plugin_metrics: dict[str, PluginMetrics] = {}
        self._alert_callback = alert_callback
        self._log = logger.bind(component="metrics_collector")

        # UI latency tracking
        self._ui_update_times: list[float] = []
        self._max_ui_latency_samples = 100

        # Queue depth tracking
        self._queue_depth_samples: list[int] = []
        self._max_queue_samples = 100

    @property
    def metrics(self) -> list[MetricValue]:
        """Get all recorded metrics."""
        return self._metrics.copy()

    @property
    def plugin_metrics(self) -> dict[str, PluginMetrics]:
        """Get metrics per plugin."""
        return self._plugin_metrics.copy()

    def record_metric(self, metric: MetricValue) -> None:
        """Record a metric value.

        Args:
            metric: The metric to record.
        """
        self._metrics.append(metric)
        self._log.debug(
            "metric_recorded",
            name=metric.name,
            value=metric.value,
            unit=metric.unit,
            level=metric.level.value,
        )

        # Trigger alert callback if threshold exceeded
        if metric.level != MetricLevel.OK and self._alert_callback:
            self._alert_callback(metric)

    def record_memory_usage(
        self,
        plugin_name: str,
        memory_mb: float,
    ) -> MetricValue:
        """Record memory usage for a plugin.

        Args:
            plugin_name: Name of the plugin.
            memory_mb: Memory usage in megabytes.

        Returns:
            The recorded metric.
        """
        # Determine alert level
        if memory_mb > MEMORY_ALERT_MB:
            level = MetricLevel.CRITICAL
        elif memory_mb > MEMORY_TARGET_MB:
            level = MetricLevel.WARNING
        else:
            level = MetricLevel.OK

        metric = MetricValue(
            name="plugin_memory_usage",
            value=memory_mb,
            unit="MB",
            level=level,
            labels={"plugin": plugin_name},
        )
        self.record_metric(metric)

        # Update plugin metrics
        if plugin_name in self._plugin_metrics:
            pm = self._plugin_metrics[plugin_name]
            pm.memory_peak_mb = max(pm.memory_peak_mb, memory_mb)

        return metric

    def record_ui_latency(self, latency_ms: float) -> MetricValue:
        """Record UI update latency.

        Args:
            latency_ms: Latency in milliseconds.

        Returns:
            The recorded metric.
        """
        # Determine alert level
        if latency_ms > UI_LATENCY_ALERT_MS:
            level = MetricLevel.CRITICAL
        elif latency_ms > UI_LATENCY_TARGET_MS:
            level = MetricLevel.WARNING
        else:
            level = MetricLevel.OK

        metric = MetricValue(
            name="ui_update_latency",
            value=latency_ms,
            unit="ms",
            level=level,
        )
        self.record_metric(metric)

        # Track for averaging
        self._ui_update_times.append(latency_ms)
        if len(self._ui_update_times) > self._max_ui_latency_samples:
            self._ui_update_times.pop(0)

        return metric

    def record_queue_depth(self, depth: int) -> MetricValue:
        """Record event queue depth.

        Args:
            depth: Current queue depth.

        Returns:
            The recorded metric.
        """
        # Determine alert level
        if depth > QUEUE_DEPTH_ALERT:
            level = MetricLevel.CRITICAL
        elif depth > QUEUE_DEPTH_TARGET:
            level = MetricLevel.WARNING
        else:
            level = MetricLevel.OK

        metric = MetricValue(
            name="event_queue_depth",
            value=float(depth),
            unit="count",
            level=level,
        )
        self.record_metric(metric)

        # Track for averaging
        self._queue_depth_samples.append(depth)
        if len(self._queue_depth_samples) > self._max_queue_samples:
            self._queue_depth_samples.pop(0)

        return metric

    def start_plugin_execution(self, plugin_name: str) -> PluginMetrics:
        """Start tracking metrics for a plugin execution.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            PluginMetrics instance for the plugin.
        """
        pm = PluginMetrics(plugin_name=plugin_name)
        self._plugin_metrics[plugin_name] = pm
        self._log.debug("plugin_execution_started", plugin=plugin_name)
        return pm

    def end_plugin_execution(self, plugin_name: str) -> PluginMetrics | None:
        """End tracking metrics for a plugin execution.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            PluginMetrics instance with final values, or None if not found.
        """
        pm = self._plugin_metrics.get(plugin_name)
        if pm:
            pm.end_time = datetime.now(tz=UTC)
            self._log.debug(
                "plugin_execution_ended",
                plugin=plugin_name,
                duration_seconds=pm.duration_seconds,
                event_count=pm.event_count,
            )
        return pm

    def increment_event_count(self, plugin_name: str) -> None:
        """Increment the event count for a plugin.

        Args:
            plugin_name: Name of the plugin.
        """
        pm = self._plugin_metrics.get(plugin_name)
        if pm:
            pm.event_count += 1

    def increment_error_count(self, plugin_name: str) -> None:
        """Increment the error count for a plugin.

        Args:
            plugin_name: Name of the plugin.
        """
        pm = self._plugin_metrics.get(plugin_name)
        if pm:
            pm.error_count += 1

    def get_average_ui_latency(self) -> float | None:
        """Get the average UI update latency.

        Returns:
            Average latency in ms, or None if no samples.
        """
        if not self._ui_update_times:
            return None
        return sum(self._ui_update_times) / len(self._ui_update_times)

    def get_average_queue_depth(self) -> float | None:
        """Get the average queue depth.

        Returns:
            Average depth, or None if no samples.
        """
        if not self._queue_depth_samples:
            return None
        return sum(self._queue_depth_samples) / len(self._queue_depth_samples)

    def get_summary(self) -> dict[str, object]:
        """Get a summary of all metrics.

        Returns:
            Dictionary with metric summaries.
        """
        return {
            "total_metrics_recorded": len(self._metrics),
            "plugins_tracked": list(self._plugin_metrics.keys()),
            "average_ui_latency_ms": self.get_average_ui_latency(),
            "average_queue_depth": self.get_average_queue_depth(),
            "alerts": {
                "warning": sum(1 for m in self._metrics if m.level == MetricLevel.WARNING),
                "critical": sum(1 for m in self._metrics if m.level == MetricLevel.CRITICAL),
            },
        }

    def clear(self) -> None:
        """Clear all recorded metrics."""
        self._metrics.clear()
        self._plugin_metrics.clear()
        self._ui_update_times.clear()
        self._queue_depth_samples.clear()
        self._log.debug("metrics_cleared")


class LatencyTimer:
    """Context manager for measuring operation latency.

    Example:
        async with LatencyTimer() as timer:
            await do_something()
        print(f"Operation took {timer.elapsed_ms} ms")
    """

    def __init__(self) -> None:
        """Initialize the timer."""
        self._start_time: float = 0.0
        self._end_time: float = 0.0

    @property
    def elapsed_ms(self) -> float:
        """Get elapsed time in milliseconds."""
        return (self._end_time - self._start_time) * 1000

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        return self._end_time - self._start_time

    def __enter__(self) -> LatencyTimer:
        """Start the timer."""
        self._start_time = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        """Stop the timer."""
        self._end_time = time.perf_counter()

    async def __aenter__(self) -> LatencyTimer:
        """Start the timer (async)."""
        self._start_time = time.perf_counter()
        return self

    async def __aexit__(self, *args: object) -> None:
        """Stop the timer (async)."""
        self._end_time = time.perf_counter()


# Global metrics collector instance
_global_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance.

    Returns:
        The global MetricsCollector instance.
    """
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def set_metrics_collector(collector: MetricsCollector) -> None:
    """Set the global metrics collector instance.

    Args:
        collector: The MetricsCollector to use globally.
    """
    global _global_collector
    _global_collector = collector

"""Advanced time estimation with statistical modeling.

This module provides time estimation with confidence intervals based on
historical execution data. It uses statistical methods to provide accurate
predictions with uncertainty quantification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean, quantiles, stdev
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


class HistoryStoreProtocol(Protocol):
    """Protocol for history store interface used by TimeEstimator."""

    def get_runs_in_range(
        self,
        start: datetime,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get runs within a date range."""
        ...


@dataclass
class TimeEstimate:
    """Time estimate with confidence interval.

    Provides a point estimate along with lower and upper bounds
    representing the confidence interval.
    """

    point_estimate: float  # seconds
    confidence_interval: tuple[float, float]  # (lower, upper) in seconds
    confidence_level: float  # e.g., 0.5 for 50% confidence (IQR)
    data_points: int  # number of historical data points used

    @property
    def lower_bound(self) -> float:
        """Lower bound of the confidence interval."""
        return self.confidence_interval[0]

    @property
    def upper_bound(self) -> float:
        """Upper bound of the confidence interval."""
        return self.confidence_interval[1]

    @property
    def has_sufficient_data(self) -> bool:
        """Check if there's sufficient data for reliable estimation."""
        return self.data_points >= 5

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format.

        Args:
            seconds: Duration in seconds.

        Returns:
            Formatted duration string.
        """
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"

    def format(self) -> str:
        """Format the estimate as a human-readable string.

        Returns:
            Formatted estimate string.
        """
        point = self.format_duration(self.point_estimate)

        if self.data_points == 0:
            return f"~{point} (no history)"
        elif self.data_points < 5:
            return f"~{point} (limited data)"
        else:
            lower = self.format_duration(self.lower_bound)
            upper = self.format_duration(self.upper_bound)
            return f"{point} ({lower} - {upper})"


@dataclass
class PluginTimeEstimate:
    """Time estimate for a specific plugin."""

    plugin_name: str
    estimate: TimeEstimate
    phase: str = "update"  # estimate, download, or update


class TimeEstimator:
    """Advanced time estimator using statistical modeling.

    Uses historical execution data to predict future execution times
    with confidence intervals. Supports multiple estimation strategies:

    1. Simple average (for limited data)
    2. Outlier-filtered mean with IQR confidence interval
    3. Weighted average favoring recent executions
    """

    # Default estimate when no history is available (5 minutes)
    DEFAULT_ESTIMATE_SECONDS = 300.0

    # Minimum and maximum bounds for default confidence interval
    DEFAULT_MIN_SECONDS = 60.0
    DEFAULT_MAX_SECONDS = 900.0

    # Minimum data points for reliable statistics
    MIN_DATA_POINTS = 5

    # Number of standard deviations for outlier detection
    OUTLIER_THRESHOLD = 2.0

    def __init__(self, history_store: HistoryStoreProtocol) -> None:
        """Initialize the time estimator.

        Args:
            history_store: History store to read execution data from.
        """
        self.history_store = history_store

    def estimate(
        self,
        plugin_name: str,
        phase: str = "update",
        download_size: int | None = None,
    ) -> TimeEstimate:
        """Estimate execution time for a plugin.

        Args:
            plugin_name: Name of the plugin.
            phase: Execution phase (estimate, download, update).
            download_size: Optional download size in bytes for size-based estimation.

        Returns:
            TimeEstimate with point estimate and confidence interval.
        """
        # Get historical execution times
        times = self._get_historical_times(plugin_name, phase)

        if not times:
            return self._default_estimate()

        if len(times) < self.MIN_DATA_POINTS:
            return self._limited_data_estimate(times)

        return self._statistical_estimate(times, download_size)

    def estimate_total(
        self,
        plugin_names: list[str],
        phase: str = "update",
    ) -> TimeEstimate:
        """Estimate total execution time for multiple plugins.

        Args:
            plugin_names: List of plugin names.
            phase: Execution phase.

        Returns:
            Combined TimeEstimate for all plugins.
        """
        if not plugin_names:
            return TimeEstimate(
                point_estimate=0.0,
                confidence_interval=(0.0, 0.0),
                confidence_level=0.5,
                data_points=0,
            )

        estimates = [self.estimate(name, phase) for name in plugin_names]

        # Sum point estimates
        total_point = sum(e.point_estimate for e in estimates)

        # For confidence intervals, we use root-sum-of-squares for independence
        # This is a simplification; real correlation would require more data
        total_lower = sum(e.lower_bound for e in estimates)
        total_upper = sum(e.upper_bound for e in estimates)

        # Use minimum data points across all plugins
        min_data_points = min(e.data_points for e in estimates)

        return TimeEstimate(
            point_estimate=total_point,
            confidence_interval=(total_lower, total_upper),
            confidence_level=0.5,
            data_points=min_data_points,
        )

    def get_plugin_estimates(
        self,
        plugin_names: list[str],
        phase: str = "update",
    ) -> list[PluginTimeEstimate]:
        """Get time estimates for multiple plugins.

        Args:
            plugin_names: List of plugin names.
            phase: Execution phase.

        Returns:
            List of PluginTimeEstimate objects.
        """
        return [
            PluginTimeEstimate(
                plugin_name=name,
                estimate=self.estimate(name, phase),
                phase=phase,
            )
            for name in plugin_names
        ]

    def _get_historical_times(self, plugin_name: str, _phase: str) -> list[float]:
        """Get historical execution times for a plugin.

        Args:
            plugin_name: Name of the plugin.
            _phase: Execution phase (reserved for future use).

        Returns:
            List of execution times in seconds.
        """
        # Get runs from the last 90 days
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=90)
        runs = self.history_store.get_runs_in_range(start, end)

        times: list[float] = []

        for run in runs:
            for plugin in run.get("plugins", []):
                if plugin.get("name") != plugin_name:
                    continue

                # Only include successful runs for estimation
                if plugin.get("status") != "success":
                    continue

                # Calculate duration
                start_str = plugin.get("start_time")
                end_str = plugin.get("end_time")
                if start_str and end_str:
                    try:
                        start_time = datetime.fromisoformat(start_str)
                        end_time = datetime.fromisoformat(end_str)
                        duration = (end_time - start_time).total_seconds()
                        if duration > 0:
                            times.append(duration)
                    except ValueError:
                        continue

        return times

    def _default_estimate(self) -> TimeEstimate:
        """Return default estimate when no history is available.

        Returns:
            Default TimeEstimate.
        """
        return TimeEstimate(
            point_estimate=self.DEFAULT_ESTIMATE_SECONDS,
            confidence_interval=(self.DEFAULT_MIN_SECONDS, self.DEFAULT_MAX_SECONDS),
            confidence_level=0.5,
            data_points=0,
        )

    def _limited_data_estimate(self, times: list[float]) -> TimeEstimate:
        """Estimate with limited historical data.

        Uses simple average with wide confidence interval.

        Args:
            times: List of historical execution times.

        Returns:
            TimeEstimate with wide confidence interval.
        """
        avg = mean(times)

        # Use 50% and 200% of average as bounds
        lower = avg * 0.5
        upper = avg * 2.0

        return TimeEstimate(
            point_estimate=avg,
            confidence_interval=(lower, upper),
            confidence_level=0.7,
            data_points=len(times),
        )

    def _statistical_estimate(
        self,
        times: list[float],
        download_size: int | None = None,  # noqa: ARG002
    ) -> TimeEstimate:
        """Estimate using statistical methods.

        Removes outliers and uses IQR for confidence interval.

        Args:
            times: List of historical execution times.
            download_size: Optional download size (reserved for future use).

        Returns:
            TimeEstimate with statistical confidence interval.
        """
        # Remove outliers using 2-sigma rule
        filtered_times = self._remove_outliers(times)

        if len(filtered_times) < 3:
            # Fall back to limited data estimate if too many outliers
            return self._limited_data_estimate(times)

        # Calculate statistics
        avg = mean(filtered_times)

        # Use quartiles for confidence interval (IQR represents ~50% confidence)
        try:
            q = quantiles(filtered_times, n=4)
            q25, q75 = q[0], q[2]
        except Exception:
            # Fall back if quantiles fail
            std = stdev(filtered_times) if len(filtered_times) > 1 else avg * 0.3
            q25 = max(0, avg - std)
            q75 = avg + std

        return TimeEstimate(
            point_estimate=avg,
            confidence_interval=(q25, q75),
            confidence_level=0.5,
            data_points=len(filtered_times),
        )

    def _remove_outliers(self, times: list[float]) -> list[float]:
        """Remove outliers from execution times.

        Uses 2-sigma rule: values more than 2 standard deviations
        from the mean are considered outliers.

        Args:
            times: List of execution times.

        Returns:
            Filtered list with outliers removed.
        """
        if len(times) < 3:
            return times

        avg = mean(times)
        std = stdev(times)

        if std == 0:
            return times

        threshold = self.OUTLIER_THRESHOLD * std
        return [t for t in times if abs(t - avg) <= threshold]

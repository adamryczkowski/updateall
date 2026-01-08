"""Advanced time estimation with statistical modeling.

This module provides time estimation with confidence intervals based on
historical execution data. It uses statistical methods to provide accurate
predictions with uncertainty quantification.

Two estimator implementations are provided:
1. TimeEstimator: Simple statistical estimator using historical averages
2. DartsTimeEstimator: Advanced estimator using Darts time series models
   with conformal prediction for calibrated confidence intervals
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean, quantiles, stdev
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    from stats.modeling.multi_target import MultiTargetModelManager
    from stats.modeling.trainer import PredictionResult, TrainingConfig
    from stats.retrieval.queries import HistoricalDataQuery

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


@dataclass
class ResourceEstimate:
    """Complete resource estimate for a plugin.

    Provides estimates for wall-clock time, CPU time, memory, and download size
    with confidence intervals for each metric.

    Attributes:
        plugin_name: Name of the plugin (or "total" for aggregated estimates).
        wall_clock: Time estimate for wall-clock duration.
        cpu_time: Time estimate for CPU time (optional).
        memory_peak: Estimate for peak memory usage in bytes (optional).
        download_size: Estimate for download size in bytes (optional).
        model_based: Whether the estimate is based on trained models.
    """

    plugin_name: str
    wall_clock: TimeEstimate
    cpu_time: TimeEstimate | None = None
    memory_peak: TimeEstimate | None = None
    download_size: TimeEstimate | None = None
    model_based: bool = False

    def format_summary(self) -> str:
        """Format a summary of the resource estimate.

        Returns:
            Human-readable summary string.
        """
        parts = [f"Time: {self.wall_clock.format()}"]

        if self.cpu_time:
            parts.append(f"CPU: {self.cpu_time.format()}")

        if self.memory_peak and self.memory_peak.point_estimate > 0:
            mb = self.memory_peak.point_estimate / (1024 * 1024)
            parts.append(f"Memory: {mb:.0f}MB")

        if self.download_size and self.download_size.point_estimate > 0:
            mb = self.download_size.point_estimate / (1024 * 1024)
            parts.append(f"Download: {mb:.0f}MB")

        source = "model" if self.model_based else "historical"
        return f"{self.plugin_name} ({source}): {', '.join(parts)}"


class DartsTimeEstimator:
    """Advanced time estimator using Darts time series models.

    Uses the Darts library for time series forecasting with conformal
    prediction for calibrated confidence intervals. Supports multiple
    target metrics (wall clock, CPU, memory, download size).

    This estimator provides more accurate predictions than the simple
    TimeEstimator when sufficient historical data is available.

    Example:
        >>> from stats.retrieval.queries import HistoricalDataQuery
        >>> query = HistoricalDataQuery()
        >>> estimator = DartsTimeEstimator(query)
        >>> estimator.train_models(["apt", "flatpak"])
        >>> estimate = estimator.estimate("apt")
        >>> print(estimate.format_summary())
    """

    # Default estimate when no model is available (5 minutes)
    DEFAULT_ESTIMATE_SECONDS = 300.0

    # Minimum and maximum bounds for default confidence interval
    DEFAULT_MIN_SECONDS = 60.0
    DEFAULT_MAX_SECONDS = 900.0

    def __init__(
        self,
        query: HistoricalDataQuery,
        model_dir: Path | str | None = None,
        training_days: int = 365,
        training_config: TrainingConfig | None = None,
    ) -> None:
        """Initialize the Darts-based estimator.

        Args:
            query: Query interface for retrieving historical data.
            model_dir: Optional directory for persisting trained models.
            training_days: Number of days of history to use for training.
            training_config: Optional training configuration for models.
        """
        self.query = query
        self.model_dir = Path(model_dir) if model_dir else None
        self.training_days = training_days

        # Lazy import to avoid circular dependencies
        from stats.modeling.multi_target import MultiTargetModelManager

        self.model_manager: MultiTargetModelManager = MultiTargetModelManager(
            training_config=training_config
        )

        # Load existing models if available
        if self.model_dir and self.model_dir.exists():
            self.model_manager.load(self.model_dir)

    def train_models(
        self,
        plugin_names: list[str] | None = None,
    ) -> dict[str, bool]:
        """Train models for specified plugins.

        Args:
            plugin_names: List of plugin names to train. If None, trains
                for all plugins with available data.

        Returns:
            Dictionary mapping plugin names to training success status.
        """
        if plugin_names is None:
            plugin_names = self.query.get_plugin_names(days=self.training_days)

        results: dict[str, bool] = {}

        for plugin_name in plugin_names:
            try:
                # Get training data
                df = self.query.get_training_data_for_plugin(
                    plugin_name,
                    days=self.training_days,
                )

                if len(df) < 10:
                    logger.info(
                        "insufficient_data_for_training",
                        plugin=plugin_name,
                        samples=len(df),
                    )
                    results[plugin_name] = False
                    continue

                # Train models
                result = self.model_manager.train_for_plugin(plugin_name, df)
                results[plugin_name] = result.is_successful

                logger.info(
                    "training_complete",
                    plugin=plugin_name,
                    success=result.is_successful,
                    successful_targets=result.successful_targets,
                    failed_targets=result.failed_targets,
                )

            except Exception as e:
                logger.warning(
                    "training_error",
                    plugin=plugin_name,
                    error=str(e),
                )
                results[plugin_name] = False

        # Save models if directory is configured
        if self.model_dir:
            self.model_manager.save(self.model_dir)

        return results

    def estimate(self, plugin_name: str) -> ResourceEstimate:
        """Estimate resources for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            ResourceEstimate with predictions for all available metrics.
        """
        # Check if we have a trained model
        if self.model_manager.has_models_for_plugin(plugin_name):
            return self._model_based_estimate(plugin_name)
        else:
            return self._fallback_estimate(plugin_name)

    def estimate_total(self, plugin_names: list[str]) -> ResourceEstimate:
        """Estimate total resources for multiple plugins.

        Args:
            plugin_names: List of plugin names.

        Returns:
            Combined ResourceEstimate for all plugins.
        """
        if not plugin_names:
            return ResourceEstimate(
                plugin_name="total",
                wall_clock=TimeEstimate(
                    point_estimate=0.0,
                    confidence_interval=(0.0, 0.0),
                    confidence_level=0.9,
                    data_points=0,
                ),
            )

        estimates = [self.estimate(name) for name in plugin_names]

        # Sum wall clock estimates
        total_point = sum(e.wall_clock.point_estimate for e in estimates)
        total_lower = sum(e.wall_clock.lower_bound for e in estimates)
        total_upper = sum(e.wall_clock.upper_bound for e in estimates)
        min_data_points = min(e.wall_clock.data_points for e in estimates)
        any_model_based = any(e.model_based for e in estimates)

        total_wall_clock = TimeEstimate(
            point_estimate=total_point,
            confidence_interval=(total_lower, total_upper),
            confidence_level=0.9,
            data_points=min_data_points,
        )

        # Sum CPU time if available
        cpu_estimates = [e.cpu_time for e in estimates if e.cpu_time is not None]
        total_cpu = None
        if cpu_estimates:
            total_cpu = TimeEstimate(
                point_estimate=sum(e.point_estimate for e in cpu_estimates),
                confidence_interval=(
                    sum(e.lower_bound for e in cpu_estimates),
                    sum(e.upper_bound for e in cpu_estimates),
                ),
                confidence_level=0.9,
                data_points=min(e.data_points for e in cpu_estimates),
            )

        # Sum download size if available
        download_estimates = [e.download_size for e in estimates if e.download_size is not None]
        total_download = None
        if download_estimates:
            total_download = TimeEstimate(
                point_estimate=sum(e.point_estimate for e in download_estimates),
                confidence_interval=(
                    sum(e.lower_bound for e in download_estimates),
                    sum(e.upper_bound for e in download_estimates),
                ),
                confidence_level=0.9,
                data_points=min(e.data_points for e in download_estimates),
            )

        # Max memory (not sum, since plugins run sequentially)
        memory_estimates = [e.memory_peak for e in estimates if e.memory_peak is not None]
        total_memory = None
        if memory_estimates:
            max_idx = max(
                range(len(memory_estimates)),
                key=lambda i: memory_estimates[i].point_estimate,
            )
            total_memory = memory_estimates[max_idx]

        return ResourceEstimate(
            plugin_name="total",
            wall_clock=total_wall_clock,
            cpu_time=total_cpu,
            memory_peak=total_memory,
            download_size=total_download,
            model_based=any_model_based,
        )

    def _model_based_estimate(self, plugin_name: str) -> ResourceEstimate:
        """Create estimate using trained model.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            ResourceEstimate based on model predictions.
        """
        prediction = self.model_manager.predict_for_plugin(plugin_name)

        # Convert PredictionResult to TimeEstimate
        wall_clock = self._prediction_to_estimate(prediction.wall_clock)
        cpu_time = self._prediction_to_estimate(prediction.cpu_time)
        memory_peak = self._prediction_to_estimate(prediction.memory_peak)
        download_size = self._prediction_to_estimate(prediction.download_size)

        return ResourceEstimate(
            plugin_name=plugin_name,
            wall_clock=wall_clock or self._default_estimate(),
            cpu_time=cpu_time,
            memory_peak=memory_peak,
            download_size=download_size,
            model_based=True,
        )

    def _fallback_estimate(self, plugin_name: str) -> ResourceEstimate:
        """Create estimate using historical statistics.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            ResourceEstimate based on historical averages.
        """
        stats = self.query.get_plugin_stats(plugin_name, days=90)

        if stats is None:
            return ResourceEstimate(
                plugin_name=plugin_name,
                wall_clock=self._default_estimate(),
                model_based=False,
            )

        # Create estimate from historical stats
        wall_clock = TimeEstimate(
            point_estimate=stats.avg_wall_clock_seconds or self.DEFAULT_ESTIMATE_SECONDS,
            confidence_interval=(
                (stats.avg_wall_clock_seconds or self.DEFAULT_ESTIMATE_SECONDS) * 0.5,
                (stats.avg_wall_clock_seconds or self.DEFAULT_ESTIMATE_SECONDS) * 1.5,
            ),
            confidence_level=0.5,
            data_points=stats.execution_count,
        )

        cpu_time = None
        if stats.avg_cpu_seconds is not None:
            cpu_time = TimeEstimate(
                point_estimate=stats.avg_cpu_seconds,
                confidence_interval=(stats.avg_cpu_seconds * 0.5, stats.avg_cpu_seconds * 1.5),
                confidence_level=0.5,
                data_points=stats.execution_count,
            )

        memory_peak = None
        if stats.avg_memory_peak_bytes is not None:
            memory_peak = TimeEstimate(
                point_estimate=stats.avg_memory_peak_bytes,
                confidence_interval=(
                    stats.avg_memory_peak_bytes * 0.5,
                    stats.avg_memory_peak_bytes * 1.5,
                ),
                confidence_level=0.5,
                data_points=stats.execution_count,
            )

        download_size = None
        if stats.avg_download_bytes is not None:
            download_size = TimeEstimate(
                point_estimate=stats.avg_download_bytes,
                confidence_interval=(
                    stats.avg_download_bytes * 0.5,
                    stats.avg_download_bytes * 1.5,
                ),
                confidence_level=0.5,
                data_points=stats.execution_count,
            )

        return ResourceEstimate(
            plugin_name=plugin_name,
            wall_clock=wall_clock,
            cpu_time=cpu_time,
            memory_peak=memory_peak,
            download_size=download_size,
            model_based=False,
        )

    def _prediction_to_estimate(
        self,
        prediction: PredictionResult | None,
    ) -> TimeEstimate | None:
        """Convert a PredictionResult to a TimeEstimate.

        Args:
            prediction: Prediction result from model.

        Returns:
            TimeEstimate or None if prediction is None.
        """
        if prediction is None:
            return None

        return TimeEstimate(
            point_estimate=prediction.point_estimate,
            confidence_interval=(prediction.lower_bound, prediction.upper_bound),
            confidence_level=prediction.confidence_level,
            data_points=10,  # Assume sufficient data if model exists
        )

    def _default_estimate(self) -> TimeEstimate:
        """Return default estimate when no data is available.

        Returns:
            Default TimeEstimate.
        """
        return TimeEstimate(
            point_estimate=self.DEFAULT_ESTIMATE_SECONDS,
            confidence_interval=(self.DEFAULT_MIN_SECONDS, self.DEFAULT_MAX_SECONDS),
            confidence_level=0.5,
            data_points=0,
        )

    def save_models(self, directory: Path | str | None = None) -> None:
        """Save trained models to disk.

        Args:
            directory: Directory to save to. Uses model_dir if None.
        """
        save_dir = Path(directory) if directory else self.model_dir
        if save_dir:
            self.model_manager.save(save_dir)

    def load_models(self, directory: Path | str | None = None) -> None:
        """Load trained models from disk.

        Args:
            directory: Directory to load from. Uses model_dir if None.
        """
        load_dir = Path(directory) if directory else self.model_dir
        if load_dir and load_dir.exists():
            self.model_manager.load(load_dir)

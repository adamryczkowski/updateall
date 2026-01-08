"""Tests for the time estimator module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from stats.estimator import (
    DartsTimeEstimator,
    PluginTimeEstimate,
    ResourceEstimate,
    TimeEstimate,
    TimeEstimator,
)
from stats.history import HistoryStore


class MockHistoryStore:
    """Mock history store for testing."""

    def __init__(self, runs: list[dict[str, Any]] | None = None) -> None:
        """Initialize with optional run data."""
        self._runs = runs or []

    def get_runs_in_range(
        self,
        start: datetime,  # noqa: ARG002
        end: datetime | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Return mock runs."""
        return self._runs


def create_run(
    plugin_name: str,
    duration_seconds: float,
    status: str = "success",
    days_ago: int = 0,
) -> dict[str, Any]:
    """Create a mock run record."""
    end_time = datetime.now(tz=UTC) - timedelta(days=days_ago)
    start_time = end_time - timedelta(seconds=duration_seconds)

    return {
        "id": f"run-{days_ago}",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "plugins": [
            {
                "name": plugin_name,
                "status": status,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "packages_updated": 5,
            }
        ],
    }


class TestTimeEstimate:
    """Tests for TimeEstimate dataclass."""

    def test_lower_bound(self) -> None:
        """Test lower_bound property."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(80.0, 120.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.lower_bound == 80.0

    def test_upper_bound(self) -> None:
        """Test upper_bound property."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(80.0, 120.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.upper_bound == 120.0

    def test_has_sufficient_data_true(self) -> None:
        """Test has_sufficient_data with enough data."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(80.0, 120.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.has_sufficient_data is True

    def test_has_sufficient_data_false(self) -> None:
        """Test has_sufficient_data with insufficient data."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(80.0, 120.0),
            confidence_level=0.5,
            data_points=3,
        )
        assert estimate.has_sufficient_data is False

    def test_format_duration_seconds(self) -> None:
        """Test format_duration for seconds."""
        estimate = TimeEstimate(
            point_estimate=45.0,
            confidence_interval=(30.0, 60.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.format_duration(45.0) == "45s"

    def test_format_duration_minutes(self) -> None:
        """Test format_duration for minutes."""
        estimate = TimeEstimate(
            point_estimate=180.0,
            confidence_interval=(120.0, 240.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.format_duration(180.0) == "3.0m"

    def test_format_duration_hours(self) -> None:
        """Test format_duration for hours."""
        estimate = TimeEstimate(
            point_estimate=7200.0,
            confidence_interval=(3600.0, 10800.0),
            confidence_level=0.5,
            data_points=10,
        )
        assert estimate.format_duration(7200.0) == "2.0h"

    def test_format_no_history(self) -> None:
        """Test format with no history."""
        estimate = TimeEstimate(
            point_estimate=300.0,
            confidence_interval=(60.0, 900.0),
            confidence_level=0.5,
            data_points=0,
        )
        assert "no history" in estimate.format()

    def test_format_limited_data(self) -> None:
        """Test format with limited data."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(50.0, 200.0),
            confidence_level=0.5,
            data_points=3,
        )
        assert "limited data" in estimate.format()

    def test_format_sufficient_data(self) -> None:
        """Test format with sufficient data."""
        estimate = TimeEstimate(
            point_estimate=100.0,
            confidence_interval=(80.0, 120.0),
            confidence_level=0.5,
            data_points=10,
        )
        formatted = estimate.format()
        # Should contain point estimate and range
        assert "1.7m" in formatted  # 100 seconds
        assert "(" in formatted and ")" in formatted


class TestTimeEstimator:
    """Tests for TimeEstimator class."""

    def test_estimate_no_history(self) -> None:
        """Test estimation with no historical data."""
        store = MockHistoryStore([])
        estimator = TimeEstimator(store)

        estimate = estimator.estimate("apt", "update")

        assert estimate.point_estimate == TimeEstimator.DEFAULT_ESTIMATE_SECONDS
        assert estimate.data_points == 0

    def test_estimate_limited_data(self) -> None:
        """Test estimation with limited historical data."""
        runs = [
            create_run("apt", 100.0, days_ago=1),
            create_run("apt", 120.0, days_ago=2),
            create_run("apt", 110.0, days_ago=3),
        ]
        store = MockHistoryStore(runs)
        estimator = TimeEstimator(store)

        estimate = estimator.estimate("apt", "update")

        assert estimate.data_points == 3
        assert 100.0 <= estimate.point_estimate <= 120.0
        # Wide confidence interval for limited data
        assert estimate.lower_bound < estimate.point_estimate
        assert estimate.upper_bound > estimate.point_estimate

    def test_estimate_sufficient_data(self) -> None:
        """Test estimation with sufficient historical data."""
        runs = [
            create_run("apt", 100.0, days_ago=1),
            create_run("apt", 110.0, days_ago=2),
            create_run("apt", 105.0, days_ago=3),
            create_run("apt", 95.0, days_ago=4),
            create_run("apt", 108.0, days_ago=5),
            create_run("apt", 102.0, days_ago=6),
        ]
        store = MockHistoryStore(runs)
        estimator = TimeEstimator(store)

        estimate = estimator.estimate("apt", "update")

        assert estimate.data_points >= 5
        assert estimate.has_sufficient_data
        # Point estimate should be close to mean (~103)
        assert 95.0 <= estimate.point_estimate <= 115.0

    def test_estimate_excludes_failed_runs(self) -> None:
        """Test that failed runs are excluded from estimation."""
        runs = [
            create_run("apt", 100.0, status="success", days_ago=1),
            create_run("apt", 500.0, status="failed", days_ago=2),  # Should be excluded
            create_run("apt", 110.0, status="success", days_ago=3),
        ]
        store = MockHistoryStore(runs)
        estimator = TimeEstimator(store)

        estimate = estimator.estimate("apt", "update")

        # Only 2 successful runs should be counted
        assert estimate.data_points == 2
        # Point estimate should be around 105, not affected by 500
        assert estimate.point_estimate < 200.0

    def test_estimate_removes_outliers(self) -> None:
        """Test that outliers are removed from estimation."""
        runs = [
            create_run("apt", 100.0, days_ago=1),
            create_run("apt", 105.0, days_ago=2),
            create_run("apt", 102.0, days_ago=3),
            create_run("apt", 98.0, days_ago=4),
            create_run("apt", 103.0, days_ago=5),
            create_run("apt", 1000.0, days_ago=6),  # Outlier
        ]
        store = MockHistoryStore(runs)
        estimator = TimeEstimator(store)

        estimate = estimator.estimate("apt", "update")

        # Point estimate should not be heavily affected by outlier
        assert estimate.point_estimate < 200.0

    def test_estimate_total_empty_list(self) -> None:
        """Test total estimation with empty plugin list."""
        store = MockHistoryStore([])
        estimator = TimeEstimator(store)

        estimate = estimator.estimate_total([], "update")

        assert estimate.point_estimate == 0.0
        assert estimate.data_points == 0

    def test_estimate_total_multiple_plugins(self) -> None:
        """Test total estimation for multiple plugins."""
        runs = [
            create_run("apt", 100.0, days_ago=1),
            create_run("flatpak", 50.0, days_ago=1),
        ]
        # Create separate runs for each plugin
        runs[0]["plugins"].append(runs[1]["plugins"][0])
        store = MockHistoryStore([runs[0]])
        estimator = TimeEstimator(store)

        estimate = estimator.estimate_total(["apt", "flatpak"], "update")

        # Total should be sum of individual estimates
        # With limited data, this is approximate
        assert estimate.point_estimate > 0

    def test_get_plugin_estimates(self) -> None:
        """Test getting estimates for multiple plugins."""
        runs = [
            create_run("apt", 100.0, days_ago=1),
        ]
        store = MockHistoryStore(runs)
        estimator = TimeEstimator(store)

        estimates = estimator.get_plugin_estimates(["apt", "flatpak"], "update")

        assert len(estimates) == 2
        assert all(isinstance(e, PluginTimeEstimate) for e in estimates)
        assert estimates[0].plugin_name == "apt"
        assert estimates[1].plugin_name == "flatpak"


class TestTimeEstimatorWithRealStore:
    """Integration tests with real HistoryStore."""

    def test_with_real_history_store(self) -> None:
        """Test estimator with real HistoryStore."""
        with TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            store = HistoryStore(history_file)
            estimator = TimeEstimator(store)

            # Should return default estimate with empty store
            estimate = estimator.estimate("apt", "update")

            assert estimate.point_estimate == TimeEstimator.DEFAULT_ESTIMATE_SECONDS
            assert estimate.data_points == 0


class TestResourceEstimate:
    """Tests for ResourceEstimate dataclass."""

    def test_format_summary_basic(self) -> None:
        """Test format_summary with basic data."""
        estimate = ResourceEstimate(
            plugin_name="apt",
            wall_clock=TimeEstimate(
                point_estimate=60.0,
                confidence_interval=(50.0, 70.0),
                confidence_level=0.9,
                data_points=10,
            ),
        )

        summary = estimate.format_summary()

        assert "apt" in summary
        assert "Time:" in summary
        assert "historical" in summary  # model_based=False by default

    def test_format_summary_model_based(self) -> None:
        """Test format_summary with model-based estimate."""
        estimate = ResourceEstimate(
            plugin_name="apt",
            wall_clock=TimeEstimate(
                point_estimate=60.0,
                confidence_interval=(50.0, 70.0),
                confidence_level=0.9,
                data_points=10,
            ),
            model_based=True,
        )

        summary = estimate.format_summary()

        assert "model" in summary

    def test_format_summary_with_all_metrics(self) -> None:
        """Test format_summary with all metrics."""
        estimate = ResourceEstimate(
            plugin_name="apt",
            wall_clock=TimeEstimate(
                point_estimate=60.0,
                confidence_interval=(50.0, 70.0),
                confidence_level=0.9,
                data_points=10,
            ),
            cpu_time=TimeEstimate(
                point_estimate=30.0,
                confidence_interval=(25.0, 35.0),
                confidence_level=0.9,
                data_points=10,
            ),
            memory_peak=TimeEstimate(
                point_estimate=100 * 1024 * 1024,  # 100MB
                confidence_interval=(80 * 1024 * 1024, 120 * 1024 * 1024),
                confidence_level=0.9,
                data_points=10,
            ),
            download_size=TimeEstimate(
                point_estimate=50 * 1024 * 1024,  # 50MB
                confidence_interval=(40 * 1024 * 1024, 60 * 1024 * 1024),
                confidence_level=0.9,
                data_points=10,
            ),
        )

        summary = estimate.format_summary()

        assert "Time:" in summary
        assert "CPU:" in summary
        assert "Memory:" in summary
        assert "Download:" in summary


class TestDartsTimeEstimator:
    """Tests for DartsTimeEstimator class."""

    @pytest.fixture
    def mock_query(self) -> MagicMock:
        """Create a mock HistoricalDataQuery."""
        query = MagicMock()
        query.get_plugin_names.return_value = ["apt", "flatpak"]
        query.get_plugin_stats.return_value = None
        return query

    @pytest.fixture
    def synthetic_data(self) -> pd.DataFrame:
        """Generate synthetic plugin data for testing."""
        import numpy as np

        rng = np.random.default_rng(42)
        num_samples = 100

        start_date = datetime.now(tz=UTC) - timedelta(days=num_samples)
        timestamps = [start_date + timedelta(days=i) for i in range(num_samples)]

        wall_clock = 60.0 + rng.normal(0, 5, num_samples)
        wall_clock = np.maximum(wall_clock, 1.0)

        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "wall_clock_seconds": wall_clock,
                "cpu_user_seconds": wall_clock * 0.5,
                "memory_peak_bytes": (100 + rng.random(num_samples) * 50) * 1024 * 1024,
                "download_size_bytes": (20 + rng.random(num_samples) * 30) * 1024 * 1024,
                "packages_updated": rng.poisson(5, num_samples),
                "packages_total": 100 + np.arange(num_samples) // 10,
                "status": "success",
            }
        )

    def test_estimate_no_model_no_stats(self, mock_query: MagicMock) -> None:
        """Test estimation when no model and no stats available."""
        estimator = DartsTimeEstimator(mock_query)

        estimate = estimator.estimate("apt")

        assert isinstance(estimate, ResourceEstimate)
        assert estimate.plugin_name == "apt"
        assert estimate.wall_clock.point_estimate == DartsTimeEstimator.DEFAULT_ESTIMATE_SECONDS
        assert estimate.model_based is False

    def test_estimate_with_stats(self, mock_query: MagicMock) -> None:
        """Test estimation using historical stats."""
        from stats.retrieval.queries import PluginStats

        mock_query.get_plugin_stats.return_value = PluginStats(
            plugin_name="apt",
            execution_count=50,
            success_count=48,
            failure_count=2,
            success_rate=0.96,
            avg_wall_clock_seconds=65.0,
            avg_cpu_seconds=30.0,
            avg_download_bytes=50 * 1024 * 1024,
            avg_memory_peak_bytes=100 * 1024 * 1024,
            total_packages_updated=250,
            first_execution=datetime.now(tz=UTC) - timedelta(days=90),
            last_execution=datetime.now(tz=UTC),
        )

        estimator = DartsTimeEstimator(mock_query)

        estimate = estimator.estimate("apt")

        assert estimate.wall_clock.point_estimate == 65.0
        assert estimate.cpu_time is not None
        assert estimate.cpu_time.point_estimate == 30.0
        assert estimate.model_based is False

    def test_estimate_total_empty_list(self, mock_query: MagicMock) -> None:
        """Test total estimation with empty plugin list."""
        estimator = DartsTimeEstimator(mock_query)

        estimate = estimator.estimate_total([])

        assert estimate.plugin_name == "total"
        assert estimate.wall_clock.point_estimate == 0.0

    def test_estimate_total_multiple_plugins(self, mock_query: MagicMock) -> None:
        """Test total estimation for multiple plugins."""
        from stats.retrieval.queries import PluginStats

        def get_stats(plugin_name: str, days: int = 90) -> PluginStats:  # noqa: ARG001
            return PluginStats(
                plugin_name=plugin_name,
                execution_count=50,
                success_count=48,
                failure_count=2,
                success_rate=0.96,
                avg_wall_clock_seconds=60.0 if plugin_name == "apt" else 30.0,
                avg_cpu_seconds=25.0,
                avg_download_bytes=50 * 1024 * 1024,
                avg_memory_peak_bytes=100 * 1024 * 1024,
                total_packages_updated=250,
                first_execution=datetime.now(tz=UTC) - timedelta(days=90),
                last_execution=datetime.now(tz=UTC),
            )

        mock_query.get_plugin_stats.side_effect = get_stats

        estimator = DartsTimeEstimator(mock_query)

        estimate = estimator.estimate_total(["apt", "flatpak"])

        assert estimate.plugin_name == "total"
        # Total should be sum: 60 + 30 = 90
        assert estimate.wall_clock.point_estimate == 90.0

    def test_train_models(self, mock_query: MagicMock, synthetic_data: pd.DataFrame) -> None:
        """Test training models for plugins."""
        from stats.modeling.trainer import ModelType, TrainingConfig

        mock_query.get_training_data_for_plugin.return_value = synthetic_data

        # Use ExponentialSmoothing to avoid LightGBM dependency
        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        estimator = DartsTimeEstimator(mock_query, training_config=config)

        results = estimator.train_models(["apt"])

        assert "apt" in results
        assert results["apt"] is True  # Training should succeed

    def test_train_models_insufficient_data(self, mock_query: MagicMock) -> None:
        """Test training with insufficient data."""
        from stats.modeling.trainer import ModelType, TrainingConfig

        # Return only 5 samples (below minimum)
        mock_query.get_training_data_for_plugin.return_value = pd.DataFrame(
            {
                "timestamp": [datetime.now(tz=UTC) - timedelta(days=i) for i in range(5)],
                "wall_clock_seconds": [60.0] * 5,
            }
        )

        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        estimator = DartsTimeEstimator(mock_query, training_config=config)

        results = estimator.train_models(["apt"])

        assert "apt" in results
        assert results["apt"] is False  # Training should fail

    def test_estimate_with_trained_model(
        self, mock_query: MagicMock, synthetic_data: pd.DataFrame
    ) -> None:
        """Test estimation using trained model."""
        from stats.modeling.trainer import ModelType, TrainingConfig

        mock_query.get_training_data_for_plugin.return_value = synthetic_data

        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )
        estimator = DartsTimeEstimator(mock_query, training_config=config)
        estimator.train_models(["apt"])

        estimate = estimator.estimate("apt")

        assert estimate.model_based is True
        assert estimate.wall_clock.point_estimate > 0

    def test_save_and_load_models(
        self, mock_query: MagicMock, synthetic_data: pd.DataFrame
    ) -> None:
        """Test saving and loading models."""
        from stats.modeling.trainer import ModelType, TrainingConfig

        mock_query.get_training_data_for_plugin.return_value = synthetic_data

        config = TrainingConfig(
            model_type=ModelType.EXPONENTIAL_SMOOTHING,
            auto_select=False,
        )

        with TemporaryDirectory() as tmpdir:
            model_dir = Path(tmpdir) / "models"

            # Train and save
            estimator1 = DartsTimeEstimator(mock_query, model_dir=model_dir, training_config=config)
            estimator1.train_models(["apt"])
            estimator1.save_models()

            # Load in new estimator
            estimator2 = DartsTimeEstimator(mock_query, model_dir=model_dir, training_config=config)
            estimator2.load_models()

            # Should be able to make predictions
            estimate = estimator2.estimate("apt")
            assert estimate.model_based is True

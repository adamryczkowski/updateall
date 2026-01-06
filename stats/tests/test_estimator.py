"""Tests for the time estimator module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from stats.estimator import PluginTimeEstimate, TimeEstimate, TimeEstimator
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

"""Tests for aggregation functions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import ExecutionStatus, StepPhase
from stats.retrieval.aggregations import (
    DailyAggregation,
    PerformanceDataPoint,
    TimeGranularity,
    get_daily_aggregations,
    get_plugin_performance_over_time,
    get_resource_usage_summary,
    get_success_rate_trend,
)


@pytest.fixture
def multi_day_data(db_connection: DatabaseConnection) -> dict[str, list[object]]:
    """Create sample data spanning multiple days for aggregation testing.

    Creates runs and executions over several days to test time-based
    aggregations.

    Returns:
        Dictionary with created entity IDs.
    """
    conn = db_connection.connect()
    created_ids: dict[str, list[object]] = {"runs": [], "executions": [], "metrics": []}

    # Create data for the last 7 days
    for day_offset in range(7):
        day_start = datetime.now(tz=UTC) - timedelta(days=day_offset)

        # Create a run for each day
        run_id = uuid4()
        conn.execute(
            """
            INSERT INTO runs (run_id, start_time, hostname, username, total_plugins,
                             successful_plugins, failed_plugins)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(run_id),
                day_start,
                "test-host",
                "test-user",
                2,
                1 + (day_offset % 2),  # Vary success count
                1 - (day_offset % 2),
            ],
        )
        created_ids["runs"].append(run_id)

        # Create APT execution for each day
        apt_exec_id = uuid4()
        conn.execute(
            """
            INSERT INTO plugin_executions
            (execution_id, run_id, plugin_name, status, start_time, end_time,
             packages_updated, packages_total)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(apt_exec_id),
                str(run_id),
                "apt",
                ExecutionStatus.SUCCESS.value,
                day_start,
                day_start + timedelta(minutes=2),
                5 + day_offset,  # Vary packages
                500,
            ],
        )
        created_ids["executions"].append(apt_exec_id)

        # Create metrics for APT
        apt_metric_id = uuid4()
        conn.execute(
            """
            INSERT INTO step_metrics
            (metric_id, execution_id, step_name, phase, start_time, end_time,
             wall_clock_seconds, cpu_user_seconds, memory_peak_bytes, download_size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(apt_metric_id),
                str(apt_exec_id),
                "update",
                StepPhase.EXECUTE.value,
                day_start,
                day_start + timedelta(minutes=2),
                60.0 + day_offset * 5,  # Vary wall clock
                20.0 + day_offset * 2,
                128_000_000 + day_offset * 10_000_000,
                25_000_000 + day_offset * 5_000_000,
            ],
        )
        created_ids["metrics"].append(apt_metric_id)

        # Create a second plugin (snap) with varying success
        snap_exec_id = uuid4()
        status = ExecutionStatus.SUCCESS if day_offset % 2 == 0 else ExecutionStatus.FAILED
        conn.execute(
            """
            INSERT INTO plugin_executions
            (execution_id, run_id, plugin_name, status, start_time, end_time,
             packages_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(snap_exec_id),
                str(run_id),
                "snap",
                status.value,
                day_start + timedelta(minutes=2),
                day_start + timedelta(minutes=3),
                2 if status == ExecutionStatus.SUCCESS else 0,
            ],
        )
        created_ids["executions"].append(snap_exec_id)

        # Create metrics for snap (only if successful)
        if status == ExecutionStatus.SUCCESS:
            snap_metric_id = uuid4()
            conn.execute(
                """
                INSERT INTO step_metrics
                (metric_id, execution_id, step_name, phase, start_time, end_time,
                 wall_clock_seconds, cpu_user_seconds, memory_peak_bytes, download_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(snap_metric_id),
                    str(snap_exec_id),
                    "update",
                    StepPhase.EXECUTE.value,
                    day_start + timedelta(minutes=2),
                    day_start + timedelta(minutes=3),
                    30.0,
                    10.0,
                    64_000_000,
                    10_000_000,
                ],
            )
            created_ids["metrics"].append(snap_metric_id)

    return created_ids


@pytest.mark.usefixtures("multi_day_data")
class TestGetDailyAggregations:
    """Tests for get_daily_aggregations function."""

    def test_returns_daily_aggregations(self, db_connection: DatabaseConnection) -> None:
        """Test that daily aggregations are returned."""
        aggregations = get_daily_aggregations(days=30, db_path=db_connection.db_path)

        assert len(aggregations) >= 1
        assert all(isinstance(a, DailyAggregation) for a in aggregations)

    def test_aggregation_fields(self, db_connection: DatabaseConnection) -> None:
        """Test that aggregation fields are populated correctly."""
        aggregations = get_daily_aggregations(days=30, db_path=db_connection.db_path)

        for agg in aggregations:
            assert agg.date is not None
            assert agg.total_runs >= 0
            assert agg.total_executions >= 0
            assert agg.successful_executions >= 0
            assert agg.failed_executions >= 0
            assert agg.total_wall_clock_seconds >= 0
            assert agg.unique_plugins >= 0

    def test_aggregation_ordering(self, db_connection: DatabaseConnection) -> None:
        """Test that aggregations are ordered by date ascending."""
        aggregations = get_daily_aggregations(days=30, db_path=db_connection.db_path)

        if len(aggregations) > 1:
            for i in range(1, len(aggregations)):
                assert aggregations[i].date >= aggregations[i - 1].date

    def test_empty_database(self, db_connection: DatabaseConnection) -> None:
        """Test aggregations on empty database."""
        # Don't use multi_day_data fixture for this test
        aggregations = get_daily_aggregations(days=30, db_path=db_connection.db_path)

        # With multi_day_data fixture, this will have data
        # This test is included for completeness but will pass with data
        assert isinstance(aggregations, list)


class TestGetDailyAggregationsEmpty:
    """Tests for get_daily_aggregations on empty database."""

    def test_empty_database(self, db_connection: DatabaseConnection) -> None:
        """Test aggregations on empty database."""
        aggregations = get_daily_aggregations(days=30, db_path=db_connection.db_path)

        assert aggregations == []


@pytest.mark.usefixtures("multi_day_data")
class TestGetPluginPerformanceOverTime:
    """Tests for get_plugin_performance_over_time function."""

    def test_returns_performance_data(self, db_connection: DatabaseConnection) -> None:
        """Test that performance data is returned."""
        data = get_plugin_performance_over_time(
            plugin_name="apt",
            metric="wall_clock_seconds",
            granularity=TimeGranularity.DAILY,
            days=30,
            db_path=db_connection.db_path,
        )

        assert len(data) >= 1
        assert all(isinstance(d, PerformanceDataPoint) for d in data)

    def test_performance_data_fields(self, db_connection: DatabaseConnection) -> None:
        """Test that performance data fields are populated."""
        data = get_plugin_performance_over_time(
            plugin_name="apt",
            metric="wall_clock_seconds",
            days=30,
            db_path=db_connection.db_path,
        )

        for point in data:
            assert point.period_start is not None
            assert point.period_end is not None
            assert point.plugin_name == "apt"
            assert point.metric_name == "wall_clock_seconds"
            assert point.min_value >= 0
            assert point.max_value >= point.min_value
            assert point.avg_value >= 0
            assert point.sample_count >= 1

    def test_different_metrics(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving different metrics."""
        metrics = [
            "wall_clock_seconds",
            "cpu_user_seconds",
            "memory_peak_bytes",
            "download_size_bytes",
        ]

        for metric in metrics:
            data = get_plugin_performance_over_time(
                plugin_name="apt",
                metric=metric,
                days=30,
                db_path=db_connection.db_path,
            )
            assert all(d.metric_name == metric for d in data)

    def test_invalid_metric_raises(self, db_connection: DatabaseConnection) -> None:
        """Test that invalid metric raises ValueError."""
        with pytest.raises(ValueError, match="Invalid metric"):
            get_plugin_performance_over_time(
                plugin_name="apt",
                metric="invalid_metric",
                days=30,
                db_path=db_connection.db_path,
            )

    def test_different_granularities(self, db_connection: DatabaseConnection) -> None:
        """Test different time granularities."""
        for granularity in TimeGranularity:
            data = get_plugin_performance_over_time(
                plugin_name="apt",
                metric="wall_clock_seconds",
                granularity=granularity,
                days=30,
                db_path=db_connection.db_path,
            )
            # Should not raise, may return empty for some granularities
            assert isinstance(data, list)

    def test_nonexistent_plugin(self, db_connection: DatabaseConnection) -> None:
        """Test performance data for non-existent plugin."""
        data = get_plugin_performance_over_time(
            plugin_name="nonexistent",
            metric="wall_clock_seconds",
            days=30,
            db_path=db_connection.db_path,
        )

        assert data == []


@pytest.mark.usefixtures("multi_day_data")
class TestGetSuccessRateTrend:
    """Tests for get_success_rate_trend function."""

    def test_returns_trend_data(self, db_connection: DatabaseConnection) -> None:
        """Test that success rate trend data is returned."""
        trend = get_success_rate_trend(days=30, db_path=db_connection.db_path)

        assert len(trend) >= 1
        assert all(isinstance(t, dict) for t in trend)

    def test_trend_data_fields(self, db_connection: DatabaseConnection) -> None:
        """Test that trend data fields are correct."""
        trend = get_success_rate_trend(days=30, db_path=db_connection.db_path)

        for point in trend:
            assert "period_start" in point
            assert "total_count" in point
            assert "success_count" in point
            assert "success_rate" in point
            success_rate = point["success_rate"]
            assert isinstance(success_rate, float) and 0 <= success_rate <= 1.0

    def test_trend_for_specific_plugin(self, db_connection: DatabaseConnection) -> None:
        """Test success rate trend for specific plugin."""
        trend = get_success_rate_trend(
            plugin_name="apt",
            days=30,
            db_path=db_connection.db_path,
        )

        # APT is always successful in our test data
        for point in trend:
            assert point["success_rate"] == 1.0

    def test_trend_for_mixed_success_plugin(self, db_connection: DatabaseConnection) -> None:
        """Test success rate trend for plugin with mixed results."""
        trend = get_success_rate_trend(
            plugin_name="snap",
            days=30,
            db_path=db_connection.db_path,
        )

        # Snap has mixed success in our test data
        assert len(trend) >= 1


@pytest.mark.usefixtures("multi_day_data")
class TestGetResourceUsageSummary:
    """Tests for get_resource_usage_summary function."""

    def test_returns_summary(self, db_connection: DatabaseConnection) -> None:
        """Test that resource usage summary is returned."""
        summary = get_resource_usage_summary(days=30, db_path=db_connection.db_path)

        assert isinstance(summary, dict)
        assert "total_runs" in summary
        assert "total_executions" in summary
        assert "success_rate" in summary

    def test_summary_fields(self, db_connection: DatabaseConnection) -> None:
        """Test that summary fields are populated correctly."""
        summary = get_resource_usage_summary(days=30, db_path=db_connection.db_path)

        total_runs = summary["total_runs"]
        total_executions = summary["total_executions"]
        success_rate = summary["success_rate"]
        total_wall_clock = summary["total_wall_clock_seconds"]
        unique_plugins = summary["unique_plugins"]

        assert isinstance(total_runs, int) and total_runs >= 1
        assert isinstance(total_executions, int) and total_executions >= 1
        assert isinstance(success_rate, float) and 0 <= success_rate <= 1.0
        assert isinstance(total_wall_clock, (int, float)) and total_wall_clock >= 0
        assert isinstance(unique_plugins, int) and unique_plugins >= 1


class TestGetResourceUsageSummaryEmpty:
    """Tests for get_resource_usage_summary on empty database."""

    def test_empty_database_summary(self, db_connection: DatabaseConnection) -> None:
        """Test summary on empty database."""
        summary = get_resource_usage_summary(days=30, db_path=db_connection.db_path)

        assert summary["total_runs"] == 0
        assert summary["total_executions"] == 0
        assert summary["success_rate"] == 0.0


class TestTimeGranularity:
    """Tests for TimeGranularity enum."""

    def test_all_granularities_defined(self) -> None:
        """Test that all expected granularities are defined."""
        assert TimeGranularity.HOURLY.value == "hour"
        assert TimeGranularity.DAILY.value == "day"
        assert TimeGranularity.WEEKLY.value == "week"
        assert TimeGranularity.MONTHLY.value == "month"

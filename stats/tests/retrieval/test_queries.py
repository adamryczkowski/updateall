"""Tests for query builders."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import ExecutionStatus, StepPhase
from stats.retrieval.queries import HistoricalDataQuery, PluginStats, TimeSeriesPoint


@pytest.fixture
def sample_run_data(db_connection: DatabaseConnection) -> dict[str, object]:
    """Create comprehensive sample data for testing queries.

    Creates a run with multiple plugin executions and step metrics
    to test various query scenarios.

    Returns:
        Dictionary with created entity IDs.
    """
    conn = db_connection.connect()

    # Create a run
    run_id = uuid4()
    run_start = datetime.now(tz=UTC) - timedelta(days=5)
    conn.execute(
        """
        INSERT INTO runs (run_id, start_time, hostname, username, total_plugins,
                         successful_plugins, failed_plugins)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [str(run_id), run_start, "test-host", "test-user", 3, 2, 1],
    )

    # Create plugin executions
    apt_exec_id = uuid4()
    snap_exec_id = uuid4()
    flatpak_exec_id = uuid4()

    # APT - successful
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
            run_start,
            run_start + timedelta(minutes=2),
            10,
            500,
        ],
    )

    # SNAP - successful
    conn.execute(
        """
        INSERT INTO plugin_executions
        (execution_id, run_id, plugin_name, status, start_time, end_time,
         packages_updated, packages_total)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(snap_exec_id),
            str(run_id),
            "snap",
            ExecutionStatus.SUCCESS.value,
            run_start + timedelta(minutes=2),
            run_start + timedelta(minutes=3),
            3,
            20,
        ],
    )

    # Flatpak - failed
    conn.execute(
        """
        INSERT INTO plugin_executions
        (execution_id, run_id, plugin_name, status, start_time, end_time,
         error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(flatpak_exec_id),
            str(run_id),
            "flatpak",
            ExecutionStatus.FAILED.value,
            run_start + timedelta(minutes=3),
            run_start + timedelta(minutes=4),
            "Connection timeout",
        ],
    )

    # Create step metrics for APT
    apt_metric_id = uuid4()
    conn.execute(
        """
        INSERT INTO step_metrics
        (metric_id, execution_id, step_name, phase, start_time, end_time,
         wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
         memory_peak_bytes, download_size_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(apt_metric_id),
            str(apt_exec_id),
            "update",
            StepPhase.EXECUTE.value,
            run_start,
            run_start + timedelta(minutes=2),
            120.5,
            45.2,
            5.3,
            256_000_000,
            50_000_000,
        ],
    )

    # Create step metrics for SNAP
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
            run_start + timedelta(minutes=2),
            run_start + timedelta(minutes=3),
            60.0,
            20.0,
            128_000_000,
            25_000_000,
        ],
    )

    return {
        "run_id": run_id,
        "apt_exec_id": apt_exec_id,
        "snap_exec_id": snap_exec_id,
        "flatpak_exec_id": flatpak_exec_id,
        "apt_metric_id": apt_metric_id,
        "snap_metric_id": snap_metric_id,
    }


@pytest.mark.usefixtures("sample_run_data")
class TestHistoricalDataQuery:
    """Tests for HistoricalDataQuery."""

    def test_get_plugin_stats(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving plugin statistics."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        stats = query.get_plugin_stats("apt", days=90)

        assert stats is not None
        assert stats.plugin_name == "apt"
        assert stats.execution_count >= 1
        assert 0 <= stats.success_rate <= 1.0
        assert stats.success_rate == 1.0  # APT was successful
        assert stats.avg_wall_clock_seconds is not None
        assert stats.avg_wall_clock_seconds > 0

    def test_get_plugin_stats_no_data(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving stats for non-existent plugin."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        stats = query.get_plugin_stats("nonexistent", days=90)

        assert stats is None

    def test_get_plugin_stats_failed_plugin(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving stats for a failed plugin."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        stats = query.get_plugin_stats("flatpak", days=90)

        assert stats is not None
        assert stats.plugin_name == "flatpak"
        assert stats.success_rate == 0.0
        assert stats.failure_count == 1

    def test_get_execution_time_series(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving execution time series."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        series = query.get_execution_time_series("apt", step_name="update", days=90)

        assert len(series) >= 1
        assert all(isinstance(p, TimeSeriesPoint) for p in series)
        assert all(p.value > 0 for p in series)
        assert all(p.plugin_name == "apt" for p in series)

    def test_get_execution_time_series_no_step_filter(
        self, db_connection: DatabaseConnection
    ) -> None:
        """Test retrieving time series without step filter."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        series = query.get_execution_time_series("apt", days=90)

        assert len(series) >= 1

    def test_get_execution_time_series_empty(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving time series for non-existent plugin."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        series = query.get_execution_time_series("nonexistent", days=90)

        assert series == []

    def test_get_training_data_for_plugin(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving training data as DataFrame."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        df = query.get_training_data_for_plugin("apt", days=365)

        assert len(df) >= 1
        assert "timestamp" in df.columns
        assert "wall_clock_seconds" in df.columns
        assert "cpu_user_seconds" in df.columns
        assert "memory_peak_bytes" in df.columns
        assert "download_size_bytes" in df.columns

    def test_get_training_data_only_successful(self, db_connection: DatabaseConnection) -> None:
        """Test that training data only includes successful executions."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        # Flatpak failed, so should have no training data
        df = query.get_training_data_for_plugin("flatpak", days=365)

        assert len(df) == 0

    def test_get_all_plugins_summary(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving summary for all plugins."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        summaries = query.get_all_plugins_summary(days=90)

        assert len(summaries) >= 1
        plugin_names = {s.plugin_name for s in summaries}
        assert "apt" in plugin_names
        assert all(isinstance(s, PluginStats) for s in summaries)

    def test_get_plugin_names(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving list of plugin names."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        names = query.get_plugin_names()

        assert "apt" in names
        assert "snap" in names
        assert "flatpak" in names

    def test_get_plugin_names_with_days_filter(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving plugin names with time filter."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        names = query.get_plugin_names(days=30)

        assert len(names) >= 1

    def test_get_recent_executions(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving recent executions."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        executions = query.get_recent_executions(limit=10)

        assert len(executions) >= 1
        assert all(isinstance(e, dict) for e in executions)
        assert all("plugin_name" in e for e in executions)
        assert all("status" in e for e in executions)

    def test_get_recent_executions_filtered(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving recent executions for specific plugin."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        executions = query.get_recent_executions(plugin_name="apt", limit=10)

        assert len(executions) >= 1
        assert all(e["plugin_name"] == "apt" for e in executions)


@pytest.mark.usefixtures("sample_run_data")
class TestPluginStats:
    """Tests for PluginStats dataclass."""

    def test_success_rate_calculation(self, db_connection: DatabaseConnection) -> None:
        """Test that success rate is calculated correctly."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        # Get all plugins summary to check mixed success/failure
        summaries = query.get_all_plugins_summary(days=90)

        for stats in summaries:
            if stats.execution_count > 0:
                expected_rate = stats.success_count / stats.execution_count
                assert abs(stats.success_rate - expected_rate) < 0.001


@pytest.mark.usefixtures("sample_run_data")
class TestTimeSeriesPoint:
    """Tests for TimeSeriesPoint dataclass."""

    def test_time_series_ordering(self, db_connection: DatabaseConnection) -> None:
        """Test that time series points are ordered by timestamp."""
        query = HistoricalDataQuery(db_path=db_connection.db_path)

        series = query.get_execution_time_series("apt", days=90)

        if len(series) > 1:
            for i in range(1, len(series)):
                assert series[i].timestamp >= series[i - 1].timestamp

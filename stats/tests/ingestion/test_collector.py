"""Tests for metrics collector."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import ExecutionStatus, StepPhase
from stats.ingestion.collector import DuckDBMetricsCollector


class TestDuckDBMetricsCollector:
    """Tests for DuckDBMetricsCollector."""

    def test_start_run_creates_record(self, temp_db_path: Path) -> None:
        """Test that starting a run creates a database record."""
        collector = DuckDBMetricsCollector(temp_db_path)

        run_id = collector.start_run("test-host", "test-user")

        assert run_id is not None

        # Verify record exists in database
        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                "SELECT hostname, username FROM runs WHERE run_id = ?",
                [str(run_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == "test-host"
        assert result[1] == "test-user"

        collector.close()
        db.close()

    def test_start_run_uses_default_hostname(self, temp_db_path: Path) -> None:
        """Test that start_run uses socket.gethostname() by default."""
        import socket

        collector = DuckDBMetricsCollector(temp_db_path)

        run_id = collector.start_run()

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                "SELECT hostname FROM runs WHERE run_id = ?",
                [str(run_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == socket.gethostname()

        collector.close()
        db.close()

    def test_end_run_updates_record(self, temp_db_path: Path) -> None:
        """Test that ending a run updates the record."""
        collector = DuckDBMetricsCollector(temp_db_path)
        run_id = collector.start_run("test-host")

        collector.end_run(total_plugins=3, successful=2, failed=1, skipped=0)

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                """
            SELECT total_plugins, successful_plugins, failed_plugins, end_time
            FROM runs WHERE run_id = ?
            """,
                [str(run_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == 3
        assert result[1] == 2
        assert result[2] == 1
        assert result[3] is not None  # end_time should be set

        collector.close()
        db.close()

    def test_end_run_without_start_raises(self, temp_db_path: Path) -> None:
        """Test that ending a run without starting raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)

        with pytest.raises(RuntimeError, match="No active run"):
            collector.end_run()

        collector.close()

    def test_start_plugin_execution(self, temp_db_path: Path) -> None:
        """Test starting a plugin execution."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        execution_id = collector.start_plugin_execution("apt", packages_total=100)

        assert execution_id is not None

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                """
            SELECT plugin_name, status, packages_total
            FROM plugin_executions WHERE execution_id = ?
            """,
                [str(execution_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == "apt"
        assert result[1] == "running"
        assert result[2] == 100

        collector.close()
        db.close()

    def test_start_plugin_execution_without_run_raises(self, temp_db_path: Path) -> None:
        """Test that starting execution without run raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)

        with pytest.raises(RuntimeError, match="No active run"):
            collector.start_plugin_execution("apt")

        collector.close()

    def test_end_plugin_execution(self, temp_db_path: Path) -> None:
        """Test ending a plugin execution."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        execution_id = collector.start_plugin_execution("apt")

        collector.end_plugin_execution(
            "apt",
            status="success",
            packages_updated=5,
            exit_code=0,
        )

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                """
            SELECT status, packages_updated, exit_code, end_time
            FROM plugin_executions WHERE execution_id = ?
            """,
                [str(execution_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == "success"
        assert result[1] == 5
        assert result[2] == 0
        assert result[3] is not None  # end_time should be set

        collector.close()
        db.close()

    def test_end_plugin_execution_with_enum_status(self, temp_db_path: Path) -> None:
        """Test ending execution with ExecutionStatus enum."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.end_plugin_execution(
            "apt",
            status=ExecutionStatus.FAILED,
            error_message="Something went wrong",
        )

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect().execute("SELECT status, error_message FROM plugin_executions").fetchone()
        )

        assert result is not None
        assert result[0] == "failed"
        assert result[1] == "Something went wrong"

        collector.close()
        db.close()

    def test_end_plugin_execution_not_started_raises(self, temp_db_path: Path) -> None:
        """Test that ending non-existent execution raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        with pytest.raises(RuntimeError, match="No active execution"):
            collector.end_plugin_execution("apt", "success")

        collector.close()

    def test_step_metrics_collection(self, temp_db_path: Path) -> None:
        """Test that step metrics are collected correctly."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.start_step("apt", "update", "EXECUTE")
        # Simulate some work
        time.sleep(0.01)
        collector.end_step("apt", "update", download_size_bytes=1024)

        collector.end_plugin_execution("apt", "success", packages_updated=5)

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                """
            SELECT wall_clock_seconds, download_size_bytes, phase, step_name
            FROM step_metrics
            """
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] > 0  # Wall clock should be positive
        assert result[1] == 1024
        assert result[2] == "EXECUTE"
        assert result[3] == "update"

        collector.close()
        db.close()

    def test_step_metrics_with_enum_phase(self, temp_db_path: Path) -> None:
        """Test step metrics with StepPhase enum."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.start_step("apt", "download", StepPhase.DOWNLOAD)
        collector.end_step("apt", "download", download_size_bytes=2048)

        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute("SELECT phase FROM step_metrics").fetchone()

        assert result is not None
        assert result[0] == "DOWNLOAD"

        collector.close()
        db.close()

    def test_start_step_without_execution_raises(self, temp_db_path: Path) -> None:
        """Test that starting step without execution raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        with pytest.raises(RuntimeError, match="No active execution"):
            collector.start_step("apt", "update", "EXECUTE")

        collector.close()

    def test_end_step_without_start_raises(self, temp_db_path: Path) -> None:
        """Test that ending step without starting raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        with pytest.raises(RuntimeError, match="No active step"):
            collector.end_step("apt", "update")

        collector.close()

    def test_record_estimate(self, temp_db_path: Path) -> None:
        """Test recording plugin estimates."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        estimate_id = collector.record_estimate(
            "apt",
            phase="EXECUTE",
            download_bytes=50_000_000,
            cpu_seconds=30.0,
            wall_seconds=60.0,
            confidence=0.8,
        )

        assert estimate_id is not None

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute(
                """
            SELECT download_bytes_est, cpu_seconds_est, wall_seconds_est, confidence
            FROM estimates WHERE estimate_id = ?
            """,
                [str(estimate_id)],
            )
            .fetchone()
        )

        assert result is not None
        assert result[0] == 50_000_000
        assert result[1] == 30.0
        assert result[2] == 60.0
        assert result[3] == 0.8

        collector.close()
        db.close()

    def test_record_estimate_with_enum_phase(self, temp_db_path: Path) -> None:
        """Test recording estimate with StepPhase enum."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.record_estimate(
            "apt",
            phase=StepPhase.DOWNLOAD,
            download_bytes=1000,
        )

        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute("SELECT phase FROM estimates").fetchone()

        assert result is not None
        assert result[0] == "DOWNLOAD"

        collector.close()
        db.close()

    def test_record_estimate_without_execution_raises(self, temp_db_path: Path) -> None:
        """Test that recording estimate without execution raises RuntimeError."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        with pytest.raises(RuntimeError, match="No active execution"):
            collector.record_estimate("apt", "EXECUTE")

        collector.close()

    def test_current_run_id_property(self, temp_db_path: Path) -> None:
        """Test current_run_id property."""
        collector = DuckDBMetricsCollector(temp_db_path)

        assert collector.current_run_id is None

        run_id = collector.start_run("test-host")
        assert collector.current_run_id == run_id

        collector.end_run()
        assert collector.current_run_id is None

        collector.close()

    def test_get_execution_id(self, temp_db_path: Path) -> None:
        """Test get_execution_id method."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        assert collector.get_execution_id("apt") is None

        execution_id = collector.start_plugin_execution("apt")
        assert collector.get_execution_id("apt") == execution_id

        collector.end_plugin_execution("apt", "success")
        assert collector.get_execution_id("apt") is None

        collector.close()

    def test_multiple_plugins(self, temp_db_path: Path) -> None:
        """Test collecting metrics for multiple plugins."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        # Start multiple plugins
        collector.start_plugin_execution("apt")
        collector.start_plugin_execution("snap")

        # Record steps for each
        collector.start_step("apt", "update", "EXECUTE")
        collector.start_step("snap", "refresh", "EXECUTE")

        time.sleep(0.01)

        collector.end_step("apt", "update", download_size_bytes=1000)
        collector.end_step("snap", "refresh", download_size_bytes=2000)

        collector.end_plugin_execution("apt", "success", packages_updated=3)
        collector.end_plugin_execution("snap", "success", packages_updated=2)

        collector.end_run(total_plugins=2, successful=2, failed=0, skipped=0)

        # Verify both plugins were recorded
        db = DatabaseConnection(temp_db_path)
        conn = db.connect()

        executions = conn.execute(
            "SELECT plugin_name, packages_updated FROM plugin_executions ORDER BY plugin_name"
        ).fetchall()

        assert len(executions) == 2
        assert executions[0][0] == "apt"
        assert executions[0][1] == 3
        assert executions[1][0] == "snap"
        assert executions[1][1] == 2

        metrics = conn.execute(
            "SELECT step_name, download_size_bytes FROM step_metrics ORDER BY step_name"
        ).fetchall()

        assert len(metrics) == 2

        collector.close()
        db.close()

    def test_download_speed_calculation(self, temp_db_path: Path) -> None:
        """Test that download speed is calculated correctly."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.start_step("apt", "download", "DOWNLOAD")
        time.sleep(0.1)  # Sleep for 100ms
        collector.end_step("apt", "download", download_size_bytes=10000)

        db = DatabaseConnection(temp_db_path)
        result = (
            db.connect()
            .execute("SELECT download_speed_bps, wall_clock_seconds FROM step_metrics")
            .fetchone()
        )

        assert result is not None
        download_speed = result[0]
        wall_clock = result[1]

        # Speed should be approximately 10000 / 0.1 = 100000 bps
        # Allow for timing variations
        assert download_speed is not None
        assert download_speed > 0
        assert abs(download_speed - (10000 / wall_clock)) < 1  # Within 1 bps

        collector.close()
        db.close()

    def test_close_is_idempotent(self, temp_db_path: Path) -> None:
        """Test that close() can be called multiple times safely."""
        collector = DuckDBMetricsCollector(temp_db_path)
        collector.start_run("test-host")

        collector.close()
        collector.close()  # Should not raise

    def test_default_db_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Test that default path is used when none provided."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        collector = DuckDBMetricsCollector()

        expected_path = tmp_path / "update-all" / "history.duckdb"
        assert collector.db_path == expected_path

        collector.close()

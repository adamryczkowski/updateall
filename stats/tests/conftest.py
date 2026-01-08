"""Shared test fixtures for stats package tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import ExecutionStatus, PluginExecution, Run, StepMetrics, StepPhase


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for testing.

    The database file will be created in a temporary directory
    that is automatically cleaned up after the test.

    Returns:
        Path to a temporary database file.
    """
    return tmp_path / "test_history.duckdb"


@pytest.fixture
def db_connection(temp_db_path: Path) -> Generator[DatabaseConnection, None, None]:
    """Provide a database connection with initialized schema.

    Creates a new database connection for each test, initializes
    the schema, and ensures proper cleanup after the test.

    Yields:
        A DatabaseConnection instance with initialized schema.
    """
    db = DatabaseConnection(temp_db_path)
    db.connect()  # This also initializes the schema
    yield db
    db.close()


@pytest.fixture
def sample_run(db_connection: DatabaseConnection) -> Run:
    """Create and insert a sample run for testing.

    Returns:
        A Run instance that has been inserted into the database.
    """
    run = Run(
        run_id=uuid4(),
        start_time=datetime.now(tz=UTC),
        hostname="test-host",
        username="test-user",
        total_plugins=5,
    )

    conn = db_connection.connect()
    conn.execute(
        """
        INSERT INTO runs (run_id, start_time, hostname, username, total_plugins)
        VALUES (?, ?, ?, ?, ?)
        """,
        [str(run.run_id), run.start_time, run.hostname, run.username, run.total_plugins],
    )

    return run


@pytest.fixture
def sample_execution(db_connection: DatabaseConnection, sample_run: Run) -> PluginExecution:
    """Create and insert a sample plugin execution for testing.

    Returns:
        A PluginExecution instance that has been inserted into the database.
    """
    execution = PluginExecution(
        execution_id=uuid4(),
        run_id=sample_run.run_id,
        plugin_name="apt",
        status=ExecutionStatus.SUCCESS,
        start_time=datetime.now(tz=UTC),
        packages_updated=10,
    )

    conn = db_connection.connect()
    conn.execute(
        """
        INSERT INTO plugin_executions
        (execution_id, run_id, plugin_name, status, start_time, packages_updated)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            str(execution.execution_id),
            str(execution.run_id),
            execution.plugin_name,
            execution.status.value,
            execution.start_time,
            execution.packages_updated,
        ],
    )

    return execution


@pytest.fixture
def sample_step_metrics(
    db_connection: DatabaseConnection, sample_execution: PluginExecution
) -> StepMetrics:
    """Create and insert sample step metrics for testing.

    Returns:
        A StepMetrics instance that has been inserted into the database.
    """
    metrics = StepMetrics(
        metric_id=uuid4(),
        execution_id=sample_execution.execution_id,
        step_name="update",
        phase=StepPhase.EXECUTE,
        wall_clock_seconds=30.5,
        cpu_user_seconds=15.2,
        download_size_bytes=50_000_000,
    )

    conn = db_connection.connect()
    conn.execute(
        """
        INSERT INTO step_metrics
        (metric_id, execution_id, step_name, phase, wall_clock_seconds,
         cpu_user_seconds, download_size_bytes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(metrics.metric_id),
            str(metrics.execution_id),
            metrics.step_name,
            metrics.phase.value,
            metrics.wall_clock_seconds,
            metrics.cpu_user_seconds,
            metrics.download_size_bytes,
        ],
    )

    return metrics

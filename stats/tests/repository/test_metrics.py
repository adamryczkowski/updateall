"""Tests for metrics repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import PluginExecution, StepMetrics, StepPhase
from stats.repository.metrics import MetricsRepository


class TestMetricsRepository:
    """Tests for MetricsRepository."""

    def test_create_metrics(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test creating new step metrics."""
        repo = MetricsRepository(db_connection.connect())
        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=sample_execution.execution_id,
            step_name="download",
            phase=StepPhase.DOWNLOAD,
            wall_clock_seconds=10.5,
        )

        created = repo.create(metrics)

        assert created.metric_id == metrics.metric_id
        assert created.created_at is not None

    def test_get_by_id(
        self, db_connection: DatabaseConnection, sample_step_metrics: StepMetrics
    ) -> None:
        """Test retrieving metrics by ID."""
        repo = MetricsRepository(db_connection.connect())

        result = repo.get_by_id(sample_step_metrics.metric_id)

        assert result is not None
        assert result.metric_id == sample_step_metrics.metric_id
        assert result.step_name == sample_step_metrics.step_name

    def test_get_by_id_not_found(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving non-existent metrics."""
        repo = MetricsRepository(db_connection.connect())

        result = repo.get_by_id(uuid4())

        assert result is None

    def test_update_metrics(
        self, db_connection: DatabaseConnection, sample_step_metrics: StepMetrics
    ) -> None:
        """Test updating metrics."""
        repo = MetricsRepository(db_connection.connect())
        sample_step_metrics.wall_clock_seconds = 45.0
        sample_step_metrics.memory_peak_bytes = 100_000_000

        updated = repo.update(sample_step_metrics)

        assert updated.wall_clock_seconds == 45.0
        assert updated.memory_peak_bytes == 100_000_000

        # Verify in database
        retrieved = repo.get_by_id(sample_step_metrics.metric_id)
        assert retrieved is not None
        assert retrieved.wall_clock_seconds == 45.0

    def test_update_nonexistent_metrics_raises(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test that updating non-existent metrics raises ValueError."""
        repo = MetricsRepository(db_connection.connect())
        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=sample_execution.execution_id,
            step_name="nonexistent",
            phase=StepPhase.EXECUTE,
        )

        with pytest.raises(ValueError, match="not found"):
            repo.update(metrics)

    def test_delete_metrics(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test deleting metrics."""
        repo = MetricsRepository(db_connection.connect())
        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=sample_execution.execution_id,
            step_name="check",
            phase=StepPhase.CHECK,
        )
        repo.create(metrics)

        result = repo.delete(metrics.metric_id)

        assert result is True
        assert repo.get_by_id(metrics.metric_id) is None

    def test_delete_nonexistent_metrics(self, db_connection: DatabaseConnection) -> None:
        """Test deleting non-existent metrics returns False."""
        repo = MetricsRepository(db_connection.connect())

        result = repo.delete(uuid4())

        assert result is False

    def test_list_by_execution_id(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test listing metrics by execution ID."""
        repo = MetricsRepository(db_connection.connect())

        # Create metrics for different phases
        now = datetime.now(tz=UTC)
        for i, phase in enumerate([StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE]):
            metrics = StepMetrics(
                metric_id=uuid4(),
                execution_id=sample_execution.execution_id,
                step_name=phase.value.lower(),
                phase=phase,
                start_time=now + timedelta(minutes=i),
            )
            repo.create(metrics)

        all_metrics = repo.list_by_execution_id(sample_execution.execution_id)

        assert len(all_metrics) == 3
        phases = {m.phase for m in all_metrics}
        assert phases == {StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE}

    def test_list_by_phase(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test listing metrics by phase."""
        repo = MetricsRepository(db_connection.connect())

        # Create metrics for different phases
        for phase in [StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE]:
            metrics = StepMetrics(
                metric_id=uuid4(),
                execution_id=sample_execution.execution_id,
                step_name=phase.value.lower(),
                phase=phase,
            )
            repo.create(metrics)

        download_metrics = repo.list_by_phase(sample_execution.execution_id, StepPhase.DOWNLOAD)

        assert len(download_metrics) == 1
        assert download_metrics[0].phase == StepPhase.DOWNLOAD

    def test_get_total_wall_clock_for_execution(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting total wall clock time for an execution."""
        repo = MetricsRepository(db_connection.connect())

        # Create metrics with wall clock times
        for phase, wall_clock in [
            (StepPhase.CHECK, 5.0),
            (StepPhase.DOWNLOAD, 15.0),
            (StepPhase.EXECUTE, 30.0),
        ]:
            metrics = StepMetrics(
                metric_id=uuid4(),
                execution_id=sample_execution.execution_id,
                step_name=phase.value.lower(),
                phase=phase,
                wall_clock_seconds=wall_clock,
            )
            repo.create(metrics)

        total = repo.get_total_wall_clock_for_execution(sample_execution.execution_id)

        assert total == 50.0

    def test_get_total_wall_clock_no_metrics(self, db_connection: DatabaseConnection) -> None:
        """Test total wall clock for execution with no metrics."""
        repo = MetricsRepository(db_connection.connect())

        total = repo.get_total_wall_clock_for_execution(uuid4())

        assert total == 0.0

    def test_get_total_download_size_for_execution(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting total download size for an execution."""
        repo = MetricsRepository(db_connection.connect())

        # Create metrics with download sizes
        for i, size in enumerate([10_000_000, 20_000_000, 5_000_000]):
            metrics = StepMetrics(
                metric_id=uuid4(),
                execution_id=sample_execution.execution_id,
                step_name=f"step{i}",
                phase=StepPhase.DOWNLOAD,
                download_size_bytes=size,
            )
            repo.create(metrics)

        total = repo.get_total_download_size_for_execution(sample_execution.execution_id)

        assert total == 35_000_000

    def test_get_peak_memory_for_execution(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting peak memory for an execution."""
        repo = MetricsRepository(db_connection.connect())

        # Create metrics with different memory peaks
        for i, memory in enumerate([100_000_000, 250_000_000, 150_000_000]):
            metrics = StepMetrics(
                metric_id=uuid4(),
                execution_id=sample_execution.execution_id,
                step_name=f"step{i}",
                phase=StepPhase.EXECUTE,
                memory_peak_bytes=memory,
            )
            repo.create(metrics)

        peak = repo.get_peak_memory_for_execution(sample_execution.execution_id)

        assert peak == 250_000_000

    def test_create_with_all_fields(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test creating metrics with all fields populated."""
        repo = MetricsRepository(db_connection.connect())
        now = datetime.now(tz=UTC)

        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=sample_execution.execution_id,
            step_name="full-step",
            phase=StepPhase.EXECUTE,
            start_time=now,
            end_time=now + timedelta(seconds=30),
            wall_clock_seconds=30.0,
            cpu_user_seconds=15.0,
            cpu_kernel_seconds=5.0,
            memory_peak_bytes=500_000_000,
            memory_avg_bytes=300_000_000,
            io_read_bytes=1_000_000,
            io_write_bytes=500_000,
            io_read_ops=100,
            io_write_ops=50,
            network_rx_bytes=50_000_000,
            network_tx_bytes=1_000_000,
            download_size_bytes=50_000_000,
            download_speed_bps=1_666_666.67,
        )

        created = repo.create(metrics)
        retrieved = repo.get_by_id(created.metric_id)

        assert retrieved is not None
        assert retrieved.cpu_user_seconds == 15.0
        assert retrieved.cpu_kernel_seconds == 5.0
        assert retrieved.memory_avg_bytes == 300_000_000
        assert retrieved.io_read_ops == 100
        assert retrieved.network_rx_bytes == 50_000_000
        assert retrieved.download_speed_bps == pytest.approx(1_666_666.67, rel=1e-5)

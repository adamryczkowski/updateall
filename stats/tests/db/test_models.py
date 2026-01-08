"""Tests for data models."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from stats.db.models import (
    Estimate,
    ExecutionStatus,
    PluginExecution,
    Run,
    StepMetrics,
    StepPhase,
)


class TestExecutionStatus:
    """Tests for ExecutionStatus enum."""

    def test_all_statuses_defined(self) -> None:
        """Test that all expected statuses are defined."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.SUCCESS.value == "success"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.SKIPPED.value == "skipped"
        assert ExecutionStatus.TIMEOUT.value == "timeout"

    def test_status_is_string(self) -> None:
        """Test that status values are strings."""
        for status in ExecutionStatus:
            assert isinstance(status.value, str)


class TestStepPhase:
    """Tests for StepPhase enum."""

    def test_all_phases_defined(self) -> None:
        """Test that all expected phases are defined."""
        assert StepPhase.CHECK.value == "CHECK"
        assert StepPhase.DOWNLOAD.value == "DOWNLOAD"
        assert StepPhase.EXECUTE.value == "EXECUTE"

    def test_phase_is_string(self) -> None:
        """Test that phase values are strings."""
        for phase in StepPhase:
            assert isinstance(phase.value, str)


class TestRun:
    """Tests for Run dataclass."""

    def test_create_minimal_run(self) -> None:
        """Test creating a run with minimal required fields."""
        run_id = uuid4()
        start_time = datetime.now(tz=UTC)

        run = Run(
            run_id=run_id,
            start_time=start_time,
            hostname="test-host",
        )

        assert run.run_id == run_id
        assert run.start_time == start_time
        assert run.hostname == "test-host"
        assert run.end_time is None
        assert run.username is None
        assert run.total_plugins == 0

    def test_create_complete_run(self) -> None:
        """Test creating a run with all fields."""
        run_id = uuid4()
        start_time = datetime.now(tz=UTC)
        end_time = datetime.now(tz=UTC)

        run = Run(
            run_id=run_id,
            start_time=start_time,
            hostname="test-host",
            end_time=end_time,
            username="test-user",
            config_hash="abc123",
            total_plugins=10,
            successful_plugins=8,
            failed_plugins=1,
            skipped_plugins=1,
        )

        assert run.run_id == run_id
        assert run.end_time == end_time
        assert run.username == "test-user"
        assert run.config_hash == "abc123"
        assert run.total_plugins == 10
        assert run.successful_plugins == 8
        assert run.failed_plugins == 1
        assert run.skipped_plugins == 1

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        run = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="test-host",
        )

        assert run.total_plugins == 0
        assert run.successful_plugins == 0
        assert run.failed_plugins == 0
        assert run.skipped_plugins == 0
        assert run.created_at is None


class TestPluginExecution:
    """Tests for PluginExecution dataclass."""

    def test_create_minimal_execution(self) -> None:
        """Test creating an execution with minimal required fields."""
        execution_id = uuid4()
        run_id = uuid4()

        execution = PluginExecution(
            execution_id=execution_id,
            run_id=run_id,
            plugin_name="apt",
            status=ExecutionStatus.PENDING,
        )

        assert execution.execution_id == execution_id
        assert execution.run_id == run_id
        assert execution.plugin_name == "apt"
        assert execution.status == ExecutionStatus.PENDING
        assert execution.packages_updated == 0

    def test_create_complete_execution(self) -> None:
        """Test creating an execution with all fields."""
        execution_id = uuid4()
        run_id = uuid4()
        start_time = datetime.now(tz=UTC)
        end_time = datetime.now(tz=UTC)

        execution = PluginExecution(
            execution_id=execution_id,
            run_id=run_id,
            plugin_name="apt",
            status=ExecutionStatus.SUCCESS,
            start_time=start_time,
            end_time=end_time,
            packages_updated=15,
            packages_total=100,
            error_message=None,
            exit_code=0,
        )

        assert execution.start_time == start_time
        assert execution.end_time == end_time
        assert execution.packages_updated == 15
        assert execution.packages_total == 100
        assert execution.exit_code == 0

    def test_failed_execution_with_error(self) -> None:
        """Test creating a failed execution with error message."""
        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=uuid4(),
            plugin_name="apt",
            status=ExecutionStatus.FAILED,
            error_message="Connection timeout",
            exit_code=1,
        )

        assert execution.status == ExecutionStatus.FAILED
        assert execution.error_message == "Connection timeout"
        assert execution.exit_code == 1


class TestStepMetrics:
    """Tests for StepMetrics dataclass."""

    def test_create_minimal_metrics(self) -> None:
        """Test creating metrics with minimal required fields."""
        metric_id = uuid4()
        execution_id = uuid4()

        metrics = StepMetrics(
            metric_id=metric_id,
            execution_id=execution_id,
            step_name="update",
            phase=StepPhase.EXECUTE,
        )

        assert metrics.metric_id == metric_id
        assert metrics.execution_id == execution_id
        assert metrics.step_name == "update"
        assert metrics.phase == StepPhase.EXECUTE
        assert metrics.wall_clock_seconds is None

    def test_create_complete_metrics(self) -> None:
        """Test creating metrics with all fields."""
        metrics = StepMetrics(
            metric_id=uuid4(),
            execution_id=uuid4(),
            step_name="download",
            phase=StepPhase.DOWNLOAD,
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC),
            wall_clock_seconds=30.5,
            cpu_user_seconds=15.2,
            cpu_kernel_seconds=2.1,
            memory_peak_bytes=500_000_000,
            memory_avg_bytes=250_000_000,
            io_read_bytes=1_000_000,
            io_write_bytes=500_000,
            io_read_ops=100,
            io_write_ops=50,
            network_rx_bytes=50_000_000,
            network_tx_bytes=1_000_000,
            download_size_bytes=50_000_000,
            download_speed_bps=5_000_000.0,
        )

        assert metrics.wall_clock_seconds == 30.5
        assert metrics.cpu_user_seconds == 15.2
        assert metrics.memory_peak_bytes == 500_000_000
        assert metrics.download_size_bytes == 50_000_000
        assert metrics.download_speed_bps == 5_000_000.0


class TestEstimate:
    """Tests for Estimate dataclass."""

    def test_create_minimal_estimate(self) -> None:
        """Test creating an estimate with minimal required fields."""
        estimate_id = uuid4()
        execution_id = uuid4()

        estimate = Estimate(
            estimate_id=estimate_id,
            execution_id=execution_id,
            phase=StepPhase.EXECUTE,
        )

        assert estimate.estimate_id == estimate_id
        assert estimate.execution_id == execution_id
        assert estimate.phase == StepPhase.EXECUTE
        assert estimate.download_bytes_est is None
        assert estimate.confidence is None

    def test_create_complete_estimate(self) -> None:
        """Test creating an estimate with all fields."""
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=uuid4(),
            phase=StepPhase.DOWNLOAD,
            download_bytes_est=100_000_000,
            cpu_seconds_est=60.0,
            wall_seconds_est=120.0,
            memory_bytes_est=500_000_000,
            package_count_est=25,
            confidence=0.85,
        )

        assert estimate.download_bytes_est == 100_000_000
        assert estimate.cpu_seconds_est == 60.0
        assert estimate.wall_seconds_est == 120.0
        assert estimate.memory_bytes_est == 500_000_000
        assert estimate.package_count_est == 25
        assert estimate.confidence == 0.85

    def test_confidence_range(self) -> None:
        """Test that confidence can be set to valid range values."""
        # Minimum confidence
        estimate_min = Estimate(
            estimate_id=uuid4(),
            execution_id=uuid4(),
            phase=StepPhase.EXECUTE,
            confidence=0.0,
        )
        assert estimate_min.confidence == 0.0

        # Maximum confidence
        estimate_max = Estimate(
            estimate_id=uuid4(),
            execution_id=uuid4(),
            phase=StepPhase.EXECUTE,
            confidence=1.0,
        )
        assert estimate_max.confidence == 1.0

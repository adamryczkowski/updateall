"""Tests for estimates repository."""

from __future__ import annotations

from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import Estimate, PluginExecution, StepPhase
from stats.repository.estimates import EstimatesRepository


class TestEstimatesRepository:
    """Tests for EstimatesRepository."""

    def test_create_estimate(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test creating a new estimate."""
        repo = EstimatesRepository(db_connection.connect())
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.EXECUTE,
            download_bytes_est=50_000_000,
            confidence=0.8,
        )

        created = repo.create(estimate)

        assert created.estimate_id == estimate.estimate_id
        assert created.created_at is not None

    def test_get_by_id(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test retrieving an estimate by ID."""
        repo = EstimatesRepository(db_connection.connect())
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.DOWNLOAD,
            download_bytes_est=30_000_000,
        )
        repo.create(estimate)

        result = repo.get_by_id(estimate.estimate_id)

        assert result is not None
        assert result.estimate_id == estimate.estimate_id
        assert result.download_bytes_est == 30_000_000

    def test_get_by_id_not_found(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving non-existent estimate."""
        repo = EstimatesRepository(db_connection.connect())

        result = repo.get_by_id(uuid4())

        assert result is None

    def test_update_estimate(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test updating an estimate."""
        repo = EstimatesRepository(db_connection.connect())
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.EXECUTE,
            download_bytes_est=50_000_000,
            confidence=0.7,
        )
        repo.create(estimate)

        estimate.download_bytes_est = 60_000_000
        estimate.confidence = 0.9

        updated = repo.update(estimate)

        assert updated.download_bytes_est == 60_000_000
        assert updated.confidence == 0.9

        # Verify in database
        retrieved = repo.get_by_id(estimate.estimate_id)
        assert retrieved is not None
        assert retrieved.download_bytes_est == 60_000_000

    def test_update_nonexistent_estimate_raises(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test that updating non-existent estimate raises ValueError."""
        repo = EstimatesRepository(db_connection.connect())
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.EXECUTE,
        )

        with pytest.raises(ValueError, match="not found"):
            repo.update(estimate)

    def test_delete_estimate(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test deleting an estimate."""
        repo = EstimatesRepository(db_connection.connect())
        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.CHECK,
        )
        repo.create(estimate)

        result = repo.delete(estimate.estimate_id)

        assert result is True
        assert repo.get_by_id(estimate.estimate_id) is None

    def test_delete_nonexistent_estimate(self, db_connection: DatabaseConnection) -> None:
        """Test deleting non-existent estimate returns False."""
        repo = EstimatesRepository(db_connection.connect())

        result = repo.delete(uuid4())

        assert result is False

    def test_list_by_execution_id(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test listing estimates by execution ID."""
        repo = EstimatesRepository(db_connection.connect())

        # Create estimates for different phases
        for phase in [StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE]:
            estimate = Estimate(
                estimate_id=uuid4(),
                execution_id=sample_execution.execution_id,
                phase=phase,
                download_bytes_est=10_000_000,
            )
            repo.create(estimate)

        estimates = repo.list_by_execution_id(sample_execution.execution_id)

        assert len(estimates) == 3
        phases = {e.phase for e in estimates}
        assert phases == {StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE}

    def test_get_by_execution_and_phase(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting estimate by execution and phase."""
        repo = EstimatesRepository(db_connection.connect())

        # Create estimates for different phases
        for phase in [StepPhase.CHECK, StepPhase.DOWNLOAD, StepPhase.EXECUTE]:
            estimate = Estimate(
                estimate_id=uuid4(),
                execution_id=sample_execution.execution_id,
                phase=phase,
                download_bytes_est=10_000_000 * (phase.value == "DOWNLOAD"),
            )
            repo.create(estimate)

        result = repo.get_by_execution_and_phase(sample_execution.execution_id, StepPhase.DOWNLOAD)

        assert result is not None
        assert result.phase == StepPhase.DOWNLOAD

    def test_get_by_execution_and_phase_not_found(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting non-existent estimate by execution and phase."""
        repo = EstimatesRepository(db_connection.connect())

        result = repo.get_by_execution_and_phase(sample_execution.execution_id, StepPhase.DOWNLOAD)

        assert result is None

    def test_count_by_plugin_name(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test counting estimates by plugin name."""
        repo = EstimatesRepository(db_connection.connect())

        # Create multiple estimates
        for _ in range(3):
            estimate = Estimate(
                estimate_id=uuid4(),
                execution_id=sample_execution.execution_id,
                phase=StepPhase.EXECUTE,
            )
            repo.create(estimate)

        # sample_execution has plugin_name="apt"
        count = repo.count_by_plugin_name("apt")

        assert count == 3

    def test_create_with_all_fields(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test creating an estimate with all fields populated."""
        repo = EstimatesRepository(db_connection.connect())

        estimate = Estimate(
            estimate_id=uuid4(),
            execution_id=sample_execution.execution_id,
            phase=StepPhase.EXECUTE,
            download_bytes_est=100_000_000,
            cpu_seconds_est=60.0,
            wall_seconds_est=120.0,
            memory_bytes_est=500_000_000,
            package_count_est=25,
            confidence=0.85,
        )

        created = repo.create(estimate)
        retrieved = repo.get_by_id(created.estimate_id)

        assert retrieved is not None
        assert retrieved.download_bytes_est == 100_000_000
        assert retrieved.cpu_seconds_est == 60.0
        assert retrieved.wall_seconds_est == 120.0
        assert retrieved.memory_bytes_est == 500_000_000
        assert retrieved.package_count_est == 25
        assert retrieved.confidence == 0.85

    def test_get_average_confidence(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test getting average confidence for a plugin."""
        repo = EstimatesRepository(db_connection.connect())

        # Create estimates with different confidence levels
        for confidence in [0.7, 0.8, 0.9]:
            estimate = Estimate(
                estimate_id=uuid4(),
                execution_id=sample_execution.execution_id,
                phase=StepPhase.EXECUTE,
                confidence=confidence,
            )
            repo.create(estimate)

        avg_confidence = repo.get_average_confidence("apt")

        assert avg_confidence is not None
        assert avg_confidence == pytest.approx(0.8, rel=1e-5)

    def test_get_average_confidence_no_estimates(self, db_connection: DatabaseConnection) -> None:
        """Test average confidence for plugin with no estimates."""
        repo = EstimatesRepository(db_connection.connect())

        avg_confidence = repo.get_average_confidence("nonexistent")

        assert avg_confidence is None

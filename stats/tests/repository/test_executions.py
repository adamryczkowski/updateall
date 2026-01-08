"""Tests for executions repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import ExecutionStatus, PluginExecution, Run
from stats.repository.executions import ExecutionsRepository
from stats.repository.runs import RunsRepository


class TestExecutionsRepository:
    """Tests for ExecutionsRepository."""

    def test_create_execution(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test creating a new plugin execution."""
        repo = ExecutionsRepository(db_connection.connect())
        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=sample_run.run_id,
            plugin_name="apt",
            status=ExecutionStatus.PENDING,
        )

        created = repo.create(execution)

        assert created.execution_id == execution.execution_id
        assert created.created_at is not None

    def test_get_by_id(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test retrieving an execution by ID."""
        repo = ExecutionsRepository(db_connection.connect())

        result = repo.get_by_id(sample_execution.execution_id)

        assert result is not None
        assert result.execution_id == sample_execution.execution_id
        assert result.plugin_name == sample_execution.plugin_name

    def test_get_by_id_not_found(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving non-existent execution."""
        repo = ExecutionsRepository(db_connection.connect())

        result = repo.get_by_id(uuid4())

        assert result is None

    def test_update_execution(
        self, db_connection: DatabaseConnection, sample_execution: PluginExecution
    ) -> None:
        """Test updating an execution."""
        repo = ExecutionsRepository(db_connection.connect())
        sample_execution.status = ExecutionStatus.SUCCESS
        sample_execution.end_time = datetime.now(tz=UTC)
        sample_execution.packages_updated = 15

        updated = repo.update(sample_execution)

        assert updated.status == ExecutionStatus.SUCCESS
        assert updated.packages_updated == 15

        # Verify in database
        retrieved = repo.get_by_id(sample_execution.execution_id)
        assert retrieved is not None
        assert retrieved.status == ExecutionStatus.SUCCESS

    def test_update_nonexistent_execution_raises(
        self, db_connection: DatabaseConnection, sample_run: Run
    ) -> None:
        """Test that updating a non-existent execution raises ValueError."""
        repo = ExecutionsRepository(db_connection.connect())
        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=sample_run.run_id,
            plugin_name="nonexistent",
            status=ExecutionStatus.PENDING,
        )

        with pytest.raises(ValueError, match="not found"):
            repo.update(execution)

    def test_delete_execution(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test deleting an execution."""
        repo = ExecutionsRepository(db_connection.connect())
        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=sample_run.run_id,
            plugin_name="snap",
            status=ExecutionStatus.PENDING,
        )
        repo.create(execution)

        result = repo.delete(execution.execution_id)

        assert result is True
        assert repo.get_by_id(execution.execution_id) is None

    def test_delete_nonexistent_execution(self, db_connection: DatabaseConnection) -> None:
        """Test deleting a non-existent execution returns False."""
        repo = ExecutionsRepository(db_connection.connect())

        result = repo.delete(uuid4())

        assert result is False

    def test_list_by_run_id(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test listing executions by run ID."""
        repo = ExecutionsRepository(db_connection.connect())

        # Create multiple executions for the same run
        for plugin in ["apt", "snap", "flatpak"]:
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=sample_run.run_id,
                plugin_name=plugin,
                status=ExecutionStatus.SUCCESS,
                start_time=datetime.now(tz=UTC),
            )
            repo.create(execution)

        executions = repo.list_by_run_id(sample_run.run_id)

        assert len(executions) == 3
        plugin_names = {e.plugin_name for e in executions}
        assert plugin_names == {"apt", "snap", "flatpak"}

    def test_list_by_plugin_name(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test listing executions by plugin name."""
        repo = ExecutionsRepository(db_connection.connect())
        runs_repo = RunsRepository(db_connection.connect())

        # Create another run
        run2 = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="host2",
        )
        runs_repo.create(run2)

        # Create executions for "apt" in both runs
        for run in [sample_run, run2]:
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=run.run_id,
                plugin_name="apt",
                status=ExecutionStatus.SUCCESS,
                start_time=datetime.now(tz=UTC),
            )
            repo.create(execution)

        executions = repo.list_by_plugin_name("apt")

        assert len(executions) == 2
        assert all(e.plugin_name == "apt" for e in executions)

    def test_list_by_status(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test listing executions by status."""
        repo = ExecutionsRepository(db_connection.connect())

        # Create executions with different statuses
        for status in [
            ExecutionStatus.SUCCESS,
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
        ]:
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=sample_run.run_id,
                plugin_name=f"plugin-{uuid4().hex[:8]}",
                status=status,
                start_time=datetime.now(tz=UTC),
            )
            repo.create(execution)

        successful = repo.list_by_status(ExecutionStatus.SUCCESS)
        failed = repo.list_by_status(ExecutionStatus.FAILED)

        assert len(successful) == 2
        assert len(failed) == 1

    def test_count_by_plugin_name(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test counting executions by plugin name."""
        repo = ExecutionsRepository(db_connection.connect())

        # Create multiple executions for the same plugin
        for _ in range(3):
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=sample_run.run_id,
                plugin_name="pip",
                status=ExecutionStatus.SUCCESS,
            )
            repo.create(execution)

        count = repo.count_by_plugin_name("pip")

        assert count == 3

    def test_get_success_rate(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test calculating success rate for a plugin."""
        repo = ExecutionsRepository(db_connection.connect())

        # Create 4 executions: 3 successful, 1 failed
        for status in [
            ExecutionStatus.SUCCESS,
            ExecutionStatus.SUCCESS,
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
        ]:
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=sample_run.run_id,
                plugin_name="npm",
                status=status,
            )
            repo.create(execution)

        rate = repo.get_success_rate("npm")

        assert rate == 0.75

    def test_get_success_rate_no_executions(self, db_connection: DatabaseConnection) -> None:
        """Test success rate for plugin with no executions."""
        repo = ExecutionsRepository(db_connection.connect())

        rate = repo.get_success_rate("nonexistent")

        assert rate == 0.0

    def test_get_distinct_plugin_names(
        self, db_connection: DatabaseConnection, sample_run: Run
    ) -> None:
        """Test getting distinct plugin names."""
        repo = ExecutionsRepository(db_connection.connect())

        # Create executions for different plugins
        for plugin in ["apt", "snap", "flatpak", "apt"]:  # apt appears twice
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=sample_run.run_id,
                plugin_name=plugin,
                status=ExecutionStatus.SUCCESS,
            )
            repo.create(execution)

        plugins = repo.get_distinct_plugin_names()

        assert len(plugins) == 3
        assert set(plugins) == {"apt", "flatpak", "snap"}

    def test_create_with_all_fields(
        self, db_connection: DatabaseConnection, sample_run: Run
    ) -> None:
        """Test creating an execution with all fields populated."""
        repo = ExecutionsRepository(db_connection.connect())
        now = datetime.now(tz=UTC)

        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=sample_run.run_id,
            plugin_name="full-plugin",
            status=ExecutionStatus.FAILED,
            start_time=now,
            end_time=now + timedelta(minutes=2),
            packages_updated=5,
            packages_total=100,
            error_message="Something went wrong",
            exit_code=1,
        )

        created = repo.create(execution)
        retrieved = repo.get_by_id(created.execution_id)

        assert retrieved is not None
        assert retrieved.packages_total == 100
        assert retrieved.error_message == "Something went wrong"
        assert retrieved.exit_code == 1

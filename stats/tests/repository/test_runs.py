"""Tests for runs repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.models import Run
from stats.repository.runs import RunsRepository


class TestRunsRepository:
    """Tests for RunsRepository."""

    def test_create_run(self, db_connection: DatabaseConnection) -> None:
        """Test creating a new run."""
        repo = RunsRepository(db_connection.connect())
        run = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="test-host",
        )

        created = repo.create(run)

        assert created.run_id == run.run_id
        assert created.created_at is not None

    def test_get_by_id(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test retrieving a run by ID."""
        repo = RunsRepository(db_connection.connect())

        result = repo.get_by_id(sample_run.run_id)

        assert result is not None
        assert result.run_id == sample_run.run_id
        assert result.hostname == sample_run.hostname

    def test_get_by_id_not_found(self, db_connection: DatabaseConnection) -> None:
        """Test retrieving non-existent run."""
        repo = RunsRepository(db_connection.connect())

        result = repo.get_by_id(uuid4())

        assert result is None

    def test_update_run(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test updating a run."""
        repo = RunsRepository(db_connection.connect())
        sample_run.end_time = datetime.now(tz=UTC)
        sample_run.successful_plugins = 5

        updated = repo.update(sample_run)

        assert updated.end_time is not None
        assert updated.successful_plugins == 5

        # Verify in database
        retrieved = repo.get_by_id(sample_run.run_id)
        assert retrieved is not None
        assert retrieved.successful_plugins == 5

    def test_update_nonexistent_run_raises(self, db_connection: DatabaseConnection) -> None:
        """Test that updating a non-existent run raises ValueError."""
        repo = RunsRepository(db_connection.connect())
        run = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="nonexistent",
        )

        with pytest.raises(ValueError, match="not found"):
            repo.update(run)

    def test_delete_run(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test deleting a run."""
        repo = RunsRepository(db_connection.connect())

        result = repo.delete(sample_run.run_id)

        assert result is True
        assert repo.get_by_id(sample_run.run_id) is None

    def test_delete_nonexistent_run(self, db_connection: DatabaseConnection) -> None:
        """Test deleting a non-existent run returns False."""
        repo = RunsRepository(db_connection.connect())

        result = repo.delete(uuid4())

        assert result is False

    def test_list_recent(self, db_connection: DatabaseConnection, sample_run: Run) -> None:
        """Test listing recent runs."""
        repo = RunsRepository(db_connection.connect())

        runs = repo.list_recent(limit=10)

        assert len(runs) >= 1
        assert any(r.run_id == sample_run.run_id for r in runs)

    def test_list_recent_ordering(self, db_connection: DatabaseConnection) -> None:
        """Test that list_recent returns runs in descending order by start_time."""
        repo = RunsRepository(db_connection.connect())

        # Create runs with different start times
        now = datetime.now(tz=UTC)
        run1 = Run(
            run_id=uuid4(),
            start_time=now - timedelta(hours=2),
            hostname="host1",
        )
        run2 = Run(
            run_id=uuid4(),
            start_time=now - timedelta(hours=1),
            hostname="host2",
        )
        run3 = Run(
            run_id=uuid4(),
            start_time=now,
            hostname="host3",
        )

        repo.create(run1)
        repo.create(run2)
        repo.create(run3)

        runs = repo.list_recent(limit=3)

        assert len(runs) == 3
        assert runs[0].run_id == run3.run_id
        assert runs[1].run_id == run2.run_id
        assert runs[2].run_id == run1.run_id

    def test_list_by_hostname(self, db_connection: DatabaseConnection) -> None:
        """Test listing runs by hostname."""
        repo = RunsRepository(db_connection.connect())

        # Create runs for different hosts
        run1 = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="host-a",
        )
        run2 = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="host-b",
        )
        run3 = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="host-a",
        )

        repo.create(run1)
        repo.create(run2)
        repo.create(run3)

        runs = repo.list_by_hostname("host-a")

        assert len(runs) == 2
        assert all(r.hostname == "host-a" for r in runs)

    def test_count_in_date_range(self, db_connection: DatabaseConnection) -> None:
        """Test counting runs in a date range."""
        repo = RunsRepository(db_connection.connect())

        now = datetime.now(tz=UTC)
        yesterday = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        # Create runs at different times
        run1 = Run(
            run_id=uuid4(),
            start_time=two_days_ago,
            hostname="host",
        )
        run2 = Run(
            run_id=uuid4(),
            start_time=yesterday,
            hostname="host",
        )
        run3 = Run(
            run_id=uuid4(),
            start_time=now,
            hostname="host",
        )

        repo.create(run1)
        repo.create(run2)
        repo.create(run3)

        # Count runs from yesterday to now
        count = repo.count_in_date_range(yesterday, now)

        assert count == 2

    def test_create_with_all_fields(self, db_connection: DatabaseConnection) -> None:
        """Test creating a run with all fields populated."""
        repo = RunsRepository(db_connection.connect())
        now = datetime.now(tz=UTC)

        run = Run(
            run_id=uuid4(),
            start_time=now,
            end_time=now + timedelta(minutes=5),
            hostname="full-host",
            username="testuser",
            config_hash="abc123",
            total_plugins=10,
            successful_plugins=8,
            failed_plugins=1,
            skipped_plugins=1,
        )

        created = repo.create(run)
        retrieved = repo.get_by_id(created.run_id)

        assert retrieved is not None
        assert retrieved.username == "testuser"
        assert retrieved.config_hash == "abc123"
        assert retrieved.total_plugins == 10
        assert retrieved.successful_plugins == 8
        assert retrieved.failed_plugins == 1
        assert retrieved.skipped_plugins == 1

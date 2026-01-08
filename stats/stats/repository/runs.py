"""Repository for Run entities.

This module provides CRUD operations for Run records,
representing complete update-all execution sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from stats.db.models import Run
from stats.repository.base import BaseRepository

if TYPE_CHECKING:
    import duckdb


class RunsRepository(BaseRepository[Run]):
    """Repository for managing Run entities.

    Provides CRUD operations and specialized queries for Run records.

    Example:
        >>> repo = RunsRepository(connection)
        >>> run = Run(run_id=uuid4(), start_time=datetime.now(tz=UTC), hostname="host")
        >>> created = repo.create(run)
        >>> retrieved = repo.get_by_id(created.run_id)
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the runs repository.

        Args:
            connection: DuckDB connection for database operations.
        """
        super().__init__(connection)

    def create(self, entity: Run) -> Run:
        """Create a new run record.

        Args:
            entity: Run to create.

        Returns:
            Created run with created_at timestamp populated.
        """
        now = datetime.now(tz=UTC)
        self._conn.execute(
            """
            INSERT INTO runs (
                run_id, start_time, end_time, hostname, username,
                config_hash, total_plugins, successful_plugins,
                failed_plugins, skipped_plugins, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(entity.run_id),
                entity.start_time,
                entity.end_time,
                entity.hostname,
                entity.username,
                entity.config_hash,
                entity.total_plugins,
                entity.successful_plugins,
                entity.failed_plugins,
                entity.skipped_plugins,
                now,
            ],
        )

        entity.created_at = now
        return entity

    def get_by_id(self, entity_id: UUID) -> Run | None:
        """Retrieve a run by its ID.

        Args:
            entity_id: The run's unique identifier.

        Returns:
            The Run if found, None otherwise.
        """
        result = self._conn.execute(
            """
            SELECT run_id, start_time, end_time, hostname, username,
                   config_hash, total_plugins, successful_plugins,
                   failed_plugins, skipped_plugins, created_at
            FROM runs
            WHERE run_id = ?
            """,
            [str(entity_id)],
        ).fetchone()

        if result is None:
            return None

        return Run(
            run_id=UUID(result[0]),
            start_time=result[1],
            end_time=result[2],
            hostname=result[3],
            username=result[4],
            config_hash=result[5],
            total_plugins=result[6],
            successful_plugins=result[7],
            failed_plugins=result[8],
            skipped_plugins=result[9],
            created_at=result[10],
        )

    def update(self, entity: Run) -> Run:
        """Update an existing run record.

        Args:
            entity: Run with updated values.

        Returns:
            The updated run.

        Raises:
            ValueError: If the run does not exist.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity.run_id)
        if existing is None:
            raise ValueError(f"Run with id {entity.run_id} not found")

        # Note: We don't update hostname, username, or config_hash as they are
        # immutable after creation. DuckDB has limitations with foreign key
        # constraints that prevent updating parent records with child records.
        self._conn.execute(
            """
            UPDATE runs SET
                end_time = ?,
                total_plugins = ?,
                successful_plugins = ?,
                failed_plugins = ?,
                skipped_plugins = ?
            WHERE run_id = ?
            """,
            [
                entity.end_time,
                entity.total_plugins,
                entity.successful_plugins,
                entity.failed_plugins,
                entity.skipped_plugins,
                str(entity.run_id),
            ],
        )

        return entity

    def delete(self, entity_id: UUID) -> bool:
        """Delete a run by its ID.

        Note: This will fail if there are related plugin_executions
        due to foreign key constraints. Delete those first.

        Args:
            entity_id: The run's unique identifier.

        Returns:
            True if the run was deleted, False if not found.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity_id)
        if existing is None:
            return False

        self._conn.execute(
            "DELETE FROM runs WHERE run_id = ?",
            [str(entity_id)],
        )

        return True

    def list_recent(self, limit: int = 10) -> list[Run]:
        """List the most recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of runs ordered by start_time descending.
        """
        results = self._conn.execute(
            """
            SELECT run_id, start_time, end_time, hostname, username,
                   config_hash, total_plugins, successful_plugins,
                   failed_plugins, skipped_plugins, created_at
            FROM runs
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

        return [
            Run(
                run_id=UUID(row[0]),
                start_time=row[1],
                end_time=row[2],
                hostname=row[3],
                username=row[4],
                config_hash=row[5],
                total_plugins=row[6],
                successful_plugins=row[7],
                failed_plugins=row[8],
                skipped_plugins=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def list_by_hostname(self, hostname: str, limit: int = 100) -> list[Run]:
        """List runs for a specific hostname.

        Args:
            hostname: The hostname to filter by.
            limit: Maximum number of runs to return.

        Returns:
            List of runs for the specified hostname.
        """
        results = self._conn.execute(
            """
            SELECT run_id, start_time, end_time, hostname, username,
                   config_hash, total_plugins, successful_plugins,
                   failed_plugins, skipped_plugins, created_at
            FROM runs
            WHERE hostname = ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [hostname, limit],
        ).fetchall()

        return [
            Run(
                run_id=UUID(row[0]),
                start_time=row[1],
                end_time=row[2],
                hostname=row[3],
                username=row[4],
                config_hash=row[5],
                total_plugins=row[6],
                successful_plugins=row[7],
                failed_plugins=row[8],
                skipped_plugins=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def list_in_range(
        self,
        start_date: datetime,
        end_date: datetime,
        limit: int = 1000,
    ) -> list[Run]:
        """List runs within a date range.

        Args:
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).
            limit: Maximum number of runs to return.

        Returns:
            List of runs in the date range, ordered by start_time descending.
        """
        results = self._conn.execute(
            """
            SELECT run_id, start_time, end_time, hostname, username,
                   config_hash, total_plugins, successful_plugins,
                   failed_plugins, skipped_plugins, created_at
            FROM runs
            WHERE start_time >= ? AND start_time <= ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [start_date, end_date, limit],
        ).fetchall()

        return [
            Run(
                run_id=UUID(row[0]),
                start_time=row[1],
                end_time=row[2],
                hostname=row[3],
                username=row[4],
                config_hash=row[5],
                total_plugins=row[6],
                successful_plugins=row[7],
                failed_plugins=row[8],
                skipped_plugins=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def count_in_date_range(self, start_date: datetime, end_date: datetime) -> int:
        """Count runs within a date range.

        Args:
            start_date: Start of the date range (inclusive).
            end_date: End of the date range (inclusive).

        Returns:
            Number of runs in the date range.
        """
        result = self._conn.execute(
            """
            SELECT COUNT(*)
            FROM runs
            WHERE start_time >= ? AND start_time <= ?
            """,
            [start_date, end_date],
        ).fetchone()

        return result[0] if result else 0

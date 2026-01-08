"""Repository for PluginExecution entities.

This module provides CRUD operations for PluginExecution records,
representing individual plugin executions within a run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from stats.db.models import ExecutionStatus, PluginExecution
from stats.repository.base import BaseRepository

if TYPE_CHECKING:
    import duckdb


class ExecutionsRepository(BaseRepository[PluginExecution]):
    """Repository for managing PluginExecution entities.

    Provides CRUD operations and specialized queries for plugin execution records.

    Example:
        >>> repo = ExecutionsRepository(connection)
        >>> execution = PluginExecution(
        ...     execution_id=uuid4(),
        ...     run_id=run.run_id,
        ...     plugin_name="apt",
        ...     status=ExecutionStatus.PENDING
        ... )
        >>> created = repo.create(execution)
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the executions repository.

        Args:
            connection: DuckDB connection for database operations.
        """
        super().__init__(connection)

    def create(self, entity: PluginExecution) -> PluginExecution:
        """Create a new plugin execution record.

        Args:
            entity: PluginExecution to create.

        Returns:
            Created execution with created_at timestamp populated.
        """
        now = datetime.now(tz=UTC)
        self._conn.execute(
            """
            INSERT INTO plugin_executions (
                execution_id, run_id, plugin_name, status, start_time,
                end_time, packages_updated, packages_total, error_message,
                exit_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(entity.execution_id),
                str(entity.run_id),
                entity.plugin_name,
                entity.status.value,
                entity.start_time,
                entity.end_time,
                entity.packages_updated,
                entity.packages_total,
                entity.error_message,
                entity.exit_code,
                now,
            ],
        )

        entity.created_at = now
        return entity

    def get_by_id(self, entity_id: UUID) -> PluginExecution | None:
        """Retrieve a plugin execution by its ID.

        Args:
            entity_id: The execution's unique identifier.

        Returns:
            The PluginExecution if found, None otherwise.
        """
        result = self._conn.execute(
            """
            SELECT execution_id, run_id, plugin_name, status, start_time,
                   end_time, packages_updated, packages_total, error_message,
                   exit_code, created_at
            FROM plugin_executions
            WHERE execution_id = ?
            """,
            [str(entity_id)],
        ).fetchone()

        if result is None:
            return None

        return PluginExecution(
            execution_id=UUID(result[0]),
            run_id=UUID(result[1]),
            plugin_name=result[2],
            status=ExecutionStatus(result[3]),
            start_time=result[4],
            end_time=result[5],
            packages_updated=result[6],
            packages_total=result[7],
            error_message=result[8],
            exit_code=result[9],
            created_at=result[10],
        )

    def update(self, entity: PluginExecution) -> PluginExecution:
        """Update an existing plugin execution record.

        Args:
            entity: PluginExecution with updated values.

        Returns:
            The updated execution.

        Raises:
            ValueError: If the execution does not exist.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity.execution_id)
        if existing is None:
            raise ValueError(f"Execution with id {entity.execution_id} not found")

        # Note: We don't update run_id or plugin_name as they are immutable
        # after creation. DuckDB has limitations with foreign key constraints
        # that prevent updating parent records with child records.
        self._conn.execute(
            """
            UPDATE plugin_executions SET
                status = ?,
                start_time = ?,
                end_time = ?,
                packages_updated = ?,
                packages_total = ?,
                error_message = ?,
                exit_code = ?
            WHERE execution_id = ?
            """,
            [
                entity.status.value,
                entity.start_time,
                entity.end_time,
                entity.packages_updated,
                entity.packages_total,
                entity.error_message,
                entity.exit_code,
                str(entity.execution_id),
            ],
        )

        return entity

    def delete(self, entity_id: UUID) -> bool:
        """Delete a plugin execution by its ID.

        Note: This will fail if there are related step_metrics or estimates
        due to foreign key constraints. Delete those first.

        Args:
            entity_id: The execution's unique identifier.

        Returns:
            True if the execution was deleted, False if not found.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity_id)
        if existing is None:
            return False

        self._conn.execute(
            "DELETE FROM plugin_executions WHERE execution_id = ?",
            [str(entity_id)],
        )

        return True

    def list_by_run_id(self, run_id: UUID) -> list[PluginExecution]:
        """List all executions for a specific run.

        Args:
            run_id: The run's unique identifier.

        Returns:
            List of executions for the specified run.
        """
        results = self._conn.execute(
            """
            SELECT execution_id, run_id, plugin_name, status, start_time,
                   end_time, packages_updated, packages_total, error_message,
                   exit_code, created_at
            FROM plugin_executions
            WHERE run_id = ?
            ORDER BY start_time
            """,
            [str(run_id)],
        ).fetchall()

        return [
            PluginExecution(
                execution_id=UUID(row[0]),
                run_id=UUID(row[1]),
                plugin_name=row[2],
                status=ExecutionStatus(row[3]),
                start_time=row[4],
                end_time=row[5],
                packages_updated=row[6],
                packages_total=row[7],
                error_message=row[8],
                exit_code=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def list_by_plugin_name(self, plugin_name: str, limit: int = 100) -> list[PluginExecution]:
        """List executions for a specific plugin.

        Args:
            plugin_name: Name of the plugin.
            limit: Maximum number of executions to return.

        Returns:
            List of executions for the specified plugin, ordered by start_time desc.
        """
        results = self._conn.execute(
            """
            SELECT execution_id, run_id, plugin_name, status, start_time,
                   end_time, packages_updated, packages_total, error_message,
                   exit_code, created_at
            FROM plugin_executions
            WHERE plugin_name = ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [plugin_name, limit],
        ).fetchall()

        return [
            PluginExecution(
                execution_id=UUID(row[0]),
                run_id=UUID(row[1]),
                plugin_name=row[2],
                status=ExecutionStatus(row[3]),
                start_time=row[4],
                end_time=row[5],
                packages_updated=row[6],
                packages_total=row[7],
                error_message=row[8],
                exit_code=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def list_by_status(self, status: ExecutionStatus, limit: int = 100) -> list[PluginExecution]:
        """List executions with a specific status.

        Args:
            status: The execution status to filter by.
            limit: Maximum number of executions to return.

        Returns:
            List of executions with the specified status.
        """
        results = self._conn.execute(
            """
            SELECT execution_id, run_id, plugin_name, status, start_time,
                   end_time, packages_updated, packages_total, error_message,
                   exit_code, created_at
            FROM plugin_executions
            WHERE status = ?
            ORDER BY start_time DESC
            LIMIT ?
            """,
            [status.value, limit],
        ).fetchall()

        return [
            PluginExecution(
                execution_id=UUID(row[0]),
                run_id=UUID(row[1]),
                plugin_name=row[2],
                status=ExecutionStatus(row[3]),
                start_time=row[4],
                end_time=row[5],
                packages_updated=row[6],
                packages_total=row[7],
                error_message=row[8],
                exit_code=row[9],
                created_at=row[10],
            )
            for row in results
        ]

    def count_by_plugin_name(self, plugin_name: str) -> int:
        """Count total executions for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Total number of executions for the plugin.
        """
        result = self._conn.execute(
            "SELECT COUNT(*) FROM plugin_executions WHERE plugin_name = ?",
            [plugin_name],
        ).fetchone()

        return result[0] if result else 0

    def get_success_rate(self, plugin_name: str) -> float:
        """Calculate the success rate for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Success rate as a float between 0.0 and 1.0.
            Returns 0.0 if there are no executions.
        """
        result = self._conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful
            FROM plugin_executions
            WHERE plugin_name = ?
            """,
            [plugin_name],
        ).fetchone()

        if result is None or result[0] == 0:
            return 0.0

        return float(result[1]) / float(result[0])

    def get_distinct_plugin_names(self) -> list[str]:
        """Get all distinct plugin names that have been executed.

        Returns:
            List of unique plugin names.
        """
        results = self._conn.execute(
            "SELECT DISTINCT plugin_name FROM plugin_executions ORDER BY plugin_name"
        ).fetchall()

        return [row[0] for row in results]

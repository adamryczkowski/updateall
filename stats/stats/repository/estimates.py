"""Repository for Estimate entities.

This module provides CRUD operations for Estimate records,
representing plugin-reported estimates for comparison with actuals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from stats.db.models import Estimate, StepPhase
from stats.repository.base import BaseRepository

if TYPE_CHECKING:
    import duckdb


class EstimatesRepository(BaseRepository[Estimate]):
    """Repository for managing Estimate entities.

    Provides CRUD operations and specialized queries for estimate records.

    Example:
        >>> repo = EstimatesRepository(connection)
        >>> estimate = Estimate(
        ...     estimate_id=uuid4(),
        ...     execution_id=execution.execution_id,
        ...     phase=StepPhase.EXECUTE,
        ...     download_bytes_est=50_000_000,
        ...     confidence=0.8
        ... )
        >>> created = repo.create(estimate)
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the estimates repository.

        Args:
            connection: DuckDB connection for database operations.
        """
        super().__init__(connection)

    def create(self, entity: Estimate) -> Estimate:
        """Create a new estimate record.

        Args:
            entity: Estimate to create.

        Returns:
            Created estimate with created_at timestamp populated.
        """
        now = datetime.now(tz=UTC)
        self._conn.execute(
            """
            INSERT INTO estimates (
                estimate_id, execution_id, phase, download_bytes_est,
                cpu_seconds_est, wall_seconds_est, memory_bytes_est,
                package_count_est, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(entity.estimate_id),
                str(entity.execution_id),
                entity.phase.value,
                entity.download_bytes_est,
                entity.cpu_seconds_est,
                entity.wall_seconds_est,
                entity.memory_bytes_est,
                entity.package_count_est,
                entity.confidence,
                now,
            ],
        )

        entity.created_at = now
        return entity

    def get_by_id(self, entity_id: UUID) -> Estimate | None:
        """Retrieve an estimate by its ID.

        Args:
            entity_id: The estimate's unique identifier.

        Returns:
            The Estimate if found, None otherwise.
        """
        result = self._conn.execute(
            """
            SELECT estimate_id, execution_id, phase, download_bytes_est,
                   cpu_seconds_est, wall_seconds_est, memory_bytes_est,
                   package_count_est, confidence, created_at
            FROM estimates
            WHERE estimate_id = ?
            """,
            [str(entity_id)],
        ).fetchone()

        if result is None:
            return None

        return self._row_to_entity(result)

    def update(self, entity: Estimate) -> Estimate:
        """Update an existing estimate record.

        Args:
            entity: Estimate with updated values.

        Returns:
            The updated estimate.

        Raises:
            ValueError: If the estimate does not exist.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity.estimate_id)
        if existing is None:
            raise ValueError(f"Estimate with id {entity.estimate_id} not found")

        self._conn.execute(
            """
            UPDATE estimates SET
                execution_id = ?,
                phase = ?,
                download_bytes_est = ?,
                cpu_seconds_est = ?,
                wall_seconds_est = ?,
                memory_bytes_est = ?,
                package_count_est = ?,
                confidence = ?
            WHERE estimate_id = ?
            """,
            [
                str(entity.execution_id),
                entity.phase.value,
                entity.download_bytes_est,
                entity.cpu_seconds_est,
                entity.wall_seconds_est,
                entity.memory_bytes_est,
                entity.package_count_est,
                entity.confidence,
                str(entity.estimate_id),
            ],
        )

        return entity

    def delete(self, entity_id: UUID) -> bool:
        """Delete an estimate by its ID.

        Args:
            entity_id: The estimate's unique identifier.

        Returns:
            True if the estimate was deleted, False if not found.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity_id)
        if existing is None:
            return False

        self._conn.execute(
            "DELETE FROM estimates WHERE estimate_id = ?",
            [str(entity_id)],
        )

        return True

    def list_by_execution_id(self, execution_id: UUID) -> list[Estimate]:
        """List all estimates for a specific execution.

        Args:
            execution_id: The execution's unique identifier.

        Returns:
            List of estimates for the specified execution.
        """
        results = self._conn.execute(
            """
            SELECT estimate_id, execution_id, phase, download_bytes_est,
                   cpu_seconds_est, wall_seconds_est, memory_bytes_est,
                   package_count_est, confidence, created_at
            FROM estimates
            WHERE execution_id = ?
            ORDER BY created_at
            """,
            [str(execution_id)],
        ).fetchall()

        return [self._row_to_entity(row) for row in results]

    def get_by_execution_and_phase(self, execution_id: UUID, phase: StepPhase) -> Estimate | None:
        """Get estimate for a specific execution and phase.

        Args:
            execution_id: The execution's unique identifier.
            phase: The phase to get estimate for.

        Returns:
            The Estimate if found, None otherwise.
        """
        result = self._conn.execute(
            """
            SELECT estimate_id, execution_id, phase, download_bytes_est,
                   cpu_seconds_est, wall_seconds_est, memory_bytes_est,
                   package_count_est, confidence, created_at
            FROM estimates
            WHERE execution_id = ? AND phase = ?
            """,
            [str(execution_id), phase.value],
        ).fetchone()

        if result is None:
            return None

        return self._row_to_entity(result)

    def get_estimate_accuracy(
        self, plugin_name: str, phase: StepPhase, days: int = 90
    ) -> dict[str, float | None]:
        """Calculate estimate accuracy for a plugin's phase.

        Compares estimated values with actual values from step_metrics
        to calculate mean absolute percentage error (MAPE).

        Args:
            plugin_name: Name of the plugin.
            phase: The phase to analyze.
            days: Number of days to look back.

        Returns:
            Dictionary with MAPE values for each estimated metric.
        """
        result = self._conn.execute(
            f"""
            SELECT
                AVG(ABS(e.download_bytes_est - sm.download_size_bytes) /
                    NULLIF(sm.download_size_bytes, 0)) as download_mape,
                AVG(ABS(e.cpu_seconds_est - (sm.cpu_user_seconds + sm.cpu_kernel_seconds)) /
                    NULLIF(sm.cpu_user_seconds + sm.cpu_kernel_seconds, 0)) as cpu_mape,
                AVG(ABS(e.wall_seconds_est - sm.wall_clock_seconds) /
                    NULLIF(sm.wall_clock_seconds, 0)) as wall_mape,
                AVG(ABS(e.memory_bytes_est - sm.memory_peak_bytes) /
                    NULLIF(sm.memory_peak_bytes, 0)) as memory_mape
            FROM estimates e
            JOIN plugin_executions pe ON e.execution_id = pe.execution_id
            JOIN step_metrics sm ON e.execution_id = sm.execution_id AND e.phase = sm.phase
            WHERE pe.plugin_name = ?
              AND e.phase = ?
              AND pe.start_time >= CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
            """,
            [plugin_name, phase.value],
        ).fetchone()

        if result is None:
            return {
                "download_mape": None,
                "cpu_mape": None,
                "wall_mape": None,
                "memory_mape": None,
            }

        return {
            "download_mape": result[0],
            "cpu_mape": result[1],
            "wall_mape": result[2],
            "memory_mape": result[3],
        }

    def get_average_confidence(self, plugin_name: str, days: int = 90) -> float | None:
        """Get average confidence level for a plugin's estimates.

        Args:
            plugin_name: Name of the plugin.
            days: Number of days to look back.

        Returns:
            Average confidence level, or None if no estimates found.
        """
        result = self._conn.execute(
            f"""
            SELECT AVG(e.confidence)
            FROM estimates e
            JOIN plugin_executions pe ON e.execution_id = pe.execution_id
            WHERE pe.plugin_name = ?
              AND pe.start_time >= CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
            """,
            [plugin_name],
        ).fetchone()

        return result[0] if result and result[0] is not None else None

    def count_by_plugin_name(self, plugin_name: str) -> int:
        """Count total estimates for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Total number of estimates for the plugin.
        """
        result = self._conn.execute(
            """
            SELECT COUNT(*)
            FROM estimates e
            JOIN plugin_executions pe ON e.execution_id = pe.execution_id
            WHERE pe.plugin_name = ?
            """,
            [plugin_name],
        ).fetchone()

        return result[0] if result else 0

    def _row_to_entity(self, row: tuple[Any, ...]) -> Estimate:
        """Convert a database row to an Estimate entity.

        Args:
            row: Database row tuple.

        Returns:
            Estimate entity.
        """
        return Estimate(
            estimate_id=UUID(row[0]),
            execution_id=UUID(row[1]),
            phase=StepPhase(row[2]),
            download_bytes_est=row[3],
            cpu_seconds_est=row[4],
            wall_seconds_est=row[5],
            memory_bytes_est=row[6],
            package_count_est=row[7],
            confidence=row[8],
            created_at=row[9],
        )

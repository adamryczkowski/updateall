"""Repository for StepMetrics entities.

This module provides CRUD operations for StepMetrics records,
representing metrics collected for each execution step.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from stats.db.models import StepMetrics, StepPhase
from stats.repository.base import BaseRepository

if TYPE_CHECKING:
    import duckdb


class MetricsRepository(BaseRepository[StepMetrics]):
    """Repository for managing StepMetrics entities.

    Provides CRUD operations and specialized queries for step metrics records.

    Example:
        >>> repo = MetricsRepository(connection)
        >>> metrics = StepMetrics(
        ...     metric_id=uuid4(),
        ...     execution_id=execution.execution_id,
        ...     step_name="update",
        ...     phase=StepPhase.EXECUTE,
        ...     wall_clock_seconds=30.5
        ... )
        >>> created = repo.create(metrics)
    """

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the metrics repository.

        Args:
            connection: DuckDB connection for database operations.
        """
        super().__init__(connection)

    def create(self, entity: StepMetrics) -> StepMetrics:
        """Create a new step metrics record.

        Args:
            entity: StepMetrics to create.

        Returns:
            Created metrics with created_at timestamp populated.
        """
        now = datetime.now(tz=UTC)
        self._conn.execute(
            """
            INSERT INTO step_metrics (
                metric_id, execution_id, step_name, phase, start_time, end_time,
                wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
                memory_peak_bytes, memory_avg_bytes, io_read_bytes, io_write_bytes,
                io_read_ops, io_write_ops, network_rx_bytes, network_tx_bytes,
                download_size_bytes, download_speed_bps, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(entity.metric_id),
                str(entity.execution_id),
                entity.step_name,
                entity.phase.value,
                entity.start_time,
                entity.end_time,
                entity.wall_clock_seconds,
                entity.cpu_user_seconds,
                entity.cpu_kernel_seconds,
                entity.memory_peak_bytes,
                entity.memory_avg_bytes,
                entity.io_read_bytes,
                entity.io_write_bytes,
                entity.io_read_ops,
                entity.io_write_ops,
                entity.network_rx_bytes,
                entity.network_tx_bytes,
                entity.download_size_bytes,
                entity.download_speed_bps,
                now,
            ],
        )

        entity.created_at = now
        return entity

    def get_by_id(self, entity_id: UUID) -> StepMetrics | None:
        """Retrieve step metrics by its ID.

        Args:
            entity_id: The metrics' unique identifier.

        Returns:
            The StepMetrics if found, None otherwise.
        """
        result = self._conn.execute(
            """
            SELECT metric_id, execution_id, step_name, phase, start_time, end_time,
                   wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
                   memory_peak_bytes, memory_avg_bytes, io_read_bytes, io_write_bytes,
                   io_read_ops, io_write_ops, network_rx_bytes, network_tx_bytes,
                   download_size_bytes, download_speed_bps, created_at
            FROM step_metrics
            WHERE metric_id = ?
            """,
            [str(entity_id)],
        ).fetchone()

        if result is None:
            return None

        return self._row_to_entity(result)

    def update(self, entity: StepMetrics) -> StepMetrics:
        """Update an existing step metrics record.

        Args:
            entity: StepMetrics with updated values.

        Returns:
            The updated metrics.

        Raises:
            ValueError: If the metrics record does not exist.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity.metric_id)
        if existing is None:
            raise ValueError(f"Metrics with id {entity.metric_id} not found")

        self._conn.execute(
            """
            UPDATE step_metrics SET
                execution_id = ?,
                step_name = ?,
                phase = ?,
                start_time = ?,
                end_time = ?,
                wall_clock_seconds = ?,
                cpu_user_seconds = ?,
                cpu_kernel_seconds = ?,
                memory_peak_bytes = ?,
                memory_avg_bytes = ?,
                io_read_bytes = ?,
                io_write_bytes = ?,
                io_read_ops = ?,
                io_write_ops = ?,
                network_rx_bytes = ?,
                network_tx_bytes = ?,
                download_size_bytes = ?,
                download_speed_bps = ?
            WHERE metric_id = ?
            """,
            [
                str(entity.execution_id),
                entity.step_name,
                entity.phase.value,
                entity.start_time,
                entity.end_time,
                entity.wall_clock_seconds,
                entity.cpu_user_seconds,
                entity.cpu_kernel_seconds,
                entity.memory_peak_bytes,
                entity.memory_avg_bytes,
                entity.io_read_bytes,
                entity.io_write_bytes,
                entity.io_read_ops,
                entity.io_write_ops,
                entity.network_rx_bytes,
                entity.network_tx_bytes,
                entity.download_size_bytes,
                entity.download_speed_bps,
                str(entity.metric_id),
            ],
        )

        return entity

    def delete(self, entity_id: UUID) -> bool:
        """Delete step metrics by its ID.

        Args:
            entity_id: The metrics' unique identifier.

        Returns:
            True if the metrics were deleted, False if not found.
        """
        # Check if the entity exists first
        existing = self.get_by_id(entity_id)
        if existing is None:
            return False

        self._conn.execute(
            "DELETE FROM step_metrics WHERE metric_id = ?",
            [str(entity_id)],
        )

        return True

    def list_by_execution_id(self, execution_id: UUID) -> list[StepMetrics]:
        """List all metrics for a specific execution.

        Args:
            execution_id: The execution's unique identifier.

        Returns:
            List of metrics for the specified execution.
        """
        results = self._conn.execute(
            """
            SELECT metric_id, execution_id, step_name, phase, start_time, end_time,
                   wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
                   memory_peak_bytes, memory_avg_bytes, io_read_bytes, io_write_bytes,
                   io_read_ops, io_write_ops, network_rx_bytes, network_tx_bytes,
                   download_size_bytes, download_speed_bps, created_at
            FROM step_metrics
            WHERE execution_id = ?
            ORDER BY start_time
            """,
            [str(execution_id)],
        ).fetchall()

        return [self._row_to_entity(row) for row in results]

    def list_by_phase(self, execution_id: UUID, phase: StepPhase) -> list[StepMetrics]:
        """List metrics for a specific phase of an execution.

        Args:
            execution_id: The execution's unique identifier.
            phase: The phase to filter by.

        Returns:
            List of metrics for the specified phase.
        """
        results = self._conn.execute(
            """
            SELECT metric_id, execution_id, step_name, phase, start_time, end_time,
                   wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
                   memory_peak_bytes, memory_avg_bytes, io_read_bytes, io_write_bytes,
                   io_read_ops, io_write_ops, network_rx_bytes, network_tx_bytes,
                   download_size_bytes, download_speed_bps, created_at
            FROM step_metrics
            WHERE execution_id = ? AND phase = ?
            ORDER BY start_time
            """,
            [str(execution_id), phase.value],
        ).fetchall()

        return [self._row_to_entity(row) for row in results]

    def get_total_wall_clock_for_execution(self, execution_id: UUID) -> float:
        """Get total wall clock time for an execution.

        Args:
            execution_id: The execution's unique identifier.

        Returns:
            Total wall clock seconds, or 0.0 if no metrics found.
        """
        result = self._conn.execute(
            """
            SELECT COALESCE(SUM(wall_clock_seconds), 0)
            FROM step_metrics
            WHERE execution_id = ?
            """,
            [str(execution_id)],
        ).fetchone()

        return result[0] if result else 0.0

    def get_total_download_size_for_execution(self, execution_id: UUID) -> int:
        """Get total download size for an execution.

        Args:
            execution_id: The execution's unique identifier.

        Returns:
            Total download size in bytes, or 0 if no metrics found.
        """
        result = self._conn.execute(
            """
            SELECT COALESCE(SUM(download_size_bytes), 0)
            FROM step_metrics
            WHERE execution_id = ?
            """,
            [str(execution_id)],
        ).fetchone()

        return int(result[0]) if result else 0

    def get_peak_memory_for_execution(self, execution_id: UUID) -> int:
        """Get peak memory usage for an execution.

        Args:
            execution_id: The execution's unique identifier.

        Returns:
            Peak memory in bytes, or 0 if no metrics found.
        """
        result = self._conn.execute(
            """
            SELECT COALESCE(MAX(memory_peak_bytes), 0)
            FROM step_metrics
            WHERE execution_id = ?
            """,
            [str(execution_id)],
        ).fetchone()

        return int(result[0]) if result else 0

    def get_average_metrics_for_plugin(
        self, plugin_name: str, step_name: str, days: int = 90
    ) -> dict[str, float | None]:
        """Get average metrics for a plugin's step over a time period.

        Args:
            plugin_name: Name of the plugin.
            step_name: Name of the step.
            days: Number of days to look back.

        Returns:
            Dictionary with average values for each metric.
        """
        result = self._conn.execute(
            f"""
            SELECT
                AVG(sm.wall_clock_seconds) as avg_wall_clock,
                AVG(sm.cpu_user_seconds) as avg_cpu_user,
                AVG(sm.cpu_kernel_seconds) as avg_cpu_kernel,
                AVG(sm.memory_peak_bytes) as avg_memory_peak,
                AVG(sm.download_size_bytes) as avg_download_size
            FROM step_metrics sm
            JOIN plugin_executions pe ON sm.execution_id = pe.execution_id
            WHERE pe.plugin_name = ?
              AND sm.step_name = ?
              AND pe.start_time >= CURRENT_TIMESTAMP - INTERVAL '{days}' DAY
            """,
            [plugin_name, step_name],
        ).fetchone()

        if result is None:
            return {
                "avg_wall_clock": None,
                "avg_cpu_user": None,
                "avg_cpu_kernel": None,
                "avg_memory_peak": None,
                "avg_download_size": None,
            }

        return {
            "avg_wall_clock": result[0],
            "avg_cpu_user": result[1],
            "avg_cpu_kernel": result[2],
            "avg_memory_peak": result[3],
            "avg_download_size": result[4],
        }

    def _row_to_entity(self, row: tuple[Any, ...]) -> StepMetrics:
        """Convert a database row to a StepMetrics entity.

        Args:
            row: Database row tuple.

        Returns:
            StepMetrics entity.
        """
        return StepMetrics(
            metric_id=UUID(row[0]),
            execution_id=UUID(row[1]),
            step_name=row[2],
            phase=StepPhase(row[3]),
            start_time=row[4],
            end_time=row[5],
            wall_clock_seconds=row[6],
            cpu_user_seconds=row[7],
            cpu_kernel_seconds=row[8],
            memory_peak_bytes=row[9],
            memory_avg_bytes=row[10],
            io_read_bytes=row[11],
            io_write_bytes=row[12],
            io_read_ops=row[13],
            io_write_ops=row[14],
            network_rx_bytes=row[15],
            network_tx_bytes=row[16],
            download_size_bytes=row[17],
            download_speed_bps=row[18],
            created_at=row[19],
        )

"""Query builders for retrieving historical data.

This module provides query interfaces for retrieving historical plugin
execution data from DuckDB, including statistics, time series data,
and training data for machine learning models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from stats.db.connection import DatabaseConnection, get_default_db_path

if TYPE_CHECKING:
    import duckdb
    import pandas as pd  # type: ignore[import-untyped]


@dataclass
class PluginStats:
    """Statistics for a plugin over a time period.

    Attributes:
        plugin_name: Name of the plugin.
        execution_count: Total number of executions.
        success_count: Number of successful executions.
        failure_count: Number of failed executions.
        success_rate: Ratio of successful executions (0.0 - 1.0).
        avg_wall_clock_seconds: Average wall-clock time in seconds.
        avg_cpu_seconds: Average CPU time in seconds.
        avg_download_bytes: Average download size in bytes.
        avg_memory_peak_bytes: Average peak memory usage in bytes.
        total_packages_updated: Total packages updated across all executions.
        first_execution: Timestamp of first execution in period.
        last_execution: Timestamp of last execution in period.
    """

    plugin_name: str
    execution_count: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_wall_clock_seconds: float | None
    avg_cpu_seconds: float | None
    avg_download_bytes: float | None
    avg_memory_peak_bytes: float | None
    total_packages_updated: int
    first_execution: datetime | None
    last_execution: datetime | None


@dataclass
class TimeSeriesPoint:
    """Single point in a time series.

    Attributes:
        timestamp: Time of the data point.
        value: Metric value at this time.
        plugin_name: Name of the plugin (optional).
        step_name: Name of the step (optional).
    """

    timestamp: datetime
    value: float
    plugin_name: str | None = None
    step_name: str | None = None


class HistoricalDataQuery:
    """Query interface for historical plugin execution data.

    This class provides methods for retrieving statistics, time series data,
    and training data from the DuckDB database.

    Example:
        >>> query = HistoricalDataQuery()
        >>> stats = query.get_plugin_stats("apt", days=90)
        >>> if stats:
        ...     print(f"Success rate: {stats.success_rate:.1%}")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialize the query interface.

        Args:
            db_path: Path to the database file. If None, uses the default path.
        """
        if db_path is None:
            self._db_path = get_default_db_path()
        else:
            self._db_path = Path(db_path)

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        """Get a database connection.

        Returns:
            DuckDB connection.
        """
        db = DatabaseConnection(self._db_path, read_only=False)
        return db.connect()

    def get_plugin_stats(self, plugin_name: str, days: int = 90) -> PluginStats | None:
        """Get statistics for a specific plugin.

        Retrieves aggregated statistics for a plugin over the specified
        time period.

        Args:
            plugin_name: Name of the plugin to query.
            days: Number of days to look back (default: 90).

        Returns:
            PluginStats object with aggregated statistics, or None if
            no data exists for the plugin in the specified period.
        """
        cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

        conn = self._get_connection()
        try:
            result = conn.execute(
                """
                SELECT
                    pe.plugin_name,
                    COUNT(*) as execution_count,
                    SUM(CASE WHEN pe.status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN pe.status = 'failed' THEN 1 ELSE 0 END) as failure_count,
                    AVG(sm.wall_clock_seconds) as avg_wall_clock_seconds,
                    AVG(sm.cpu_user_seconds + COALESCE(sm.cpu_kernel_seconds, 0))
                        as avg_cpu_seconds,
                    AVG(sm.download_size_bytes) as avg_download_bytes,
                    AVG(sm.memory_peak_bytes) as avg_memory_peak_bytes,
                    SUM(pe.packages_updated) as total_packages_updated,
                    MIN(pe.start_time) as first_execution,
                    MAX(pe.start_time) as last_execution
                FROM plugin_executions pe
                LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
                WHERE pe.plugin_name = ?
                  AND pe.start_time >= ?
                GROUP BY pe.plugin_name
                """,
                [plugin_name, cutoff_date],
            ).fetchone()

            if result is None or result[1] == 0:
                return None

            execution_count = result[1]
            success_count = result[2] or 0
            failure_count = result[3] or 0

            return PluginStats(
                plugin_name=result[0],
                execution_count=execution_count,
                success_count=success_count,
                failure_count=failure_count,
                success_rate=success_count / execution_count if execution_count > 0 else 0.0,
                avg_wall_clock_seconds=result[4],
                avg_cpu_seconds=result[5],
                avg_download_bytes=result[6],
                avg_memory_peak_bytes=result[7],
                total_packages_updated=result[8] or 0,
                first_execution=result[9],
                last_execution=result[10],
            )
        finally:
            conn.close()

    def get_execution_time_series(
        self,
        plugin_name: str,
        step_name: str | None = None,
        days: int = 90,
    ) -> list[TimeSeriesPoint]:
        """Get time series data for execution times.

        Retrieves wall-clock execution times as a time series for
        trend analysis and forecasting.

        Args:
            plugin_name: Name of the plugin to query.
            step_name: Optional step name to filter by (e.g., "update", "download").
            days: Number of days to look back (default: 90).

        Returns:
            List of TimeSeriesPoint objects ordered by timestamp.
        """
        cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

        conn = self._get_connection()
        try:
            if step_name:
                result = conn.execute(
                    """
                    SELECT
                        sm.start_time,
                        sm.wall_clock_seconds,
                        pe.plugin_name,
                        sm.step_name
                    FROM step_metrics sm
                    JOIN plugin_executions pe ON sm.execution_id = pe.execution_id
                    WHERE pe.plugin_name = ?
                      AND sm.step_name = ?
                      AND sm.start_time >= ?
                      AND sm.wall_clock_seconds IS NOT NULL
                    ORDER BY sm.start_time ASC
                    """,
                    [plugin_name, step_name, cutoff_date],
                ).fetchall()
            else:
                result = conn.execute(
                    """
                    SELECT
                        sm.start_time,
                        sm.wall_clock_seconds,
                        pe.plugin_name,
                        sm.step_name
                    FROM step_metrics sm
                    JOIN plugin_executions pe ON sm.execution_id = pe.execution_id
                    WHERE pe.plugin_name = ?
                      AND sm.start_time >= ?
                      AND sm.wall_clock_seconds IS NOT NULL
                    ORDER BY sm.start_time ASC
                    """,
                    [plugin_name, cutoff_date],
                ).fetchall()

            return [
                TimeSeriesPoint(
                    timestamp=row[0],
                    value=row[1],
                    plugin_name=row[2],
                    step_name=row[3],
                )
                for row in result
            ]
        finally:
            conn.close()

    def get_training_data_for_plugin(self, plugin_name: str, days: int = 365) -> pd.DataFrame:
        """Get training data for machine learning models.

        Retrieves historical execution data as a pandas DataFrame suitable
        for training time series forecasting models.

        The DataFrame includes:
        - timestamp: Execution start time
        - wall_clock_seconds: Wall-clock execution time
        - cpu_user_seconds: CPU time in user mode
        - cpu_kernel_seconds: CPU time in kernel mode
        - memory_peak_bytes: Peak memory usage
        - download_size_bytes: Download size
        - packages_updated: Number of packages updated
        - packages_total: Total packages managed
        - status: Execution status

        Args:
            plugin_name: Name of the plugin to query.
            days: Number of days to look back (default: 365).

        Returns:
            pandas DataFrame with training data.

        Raises:
            ImportError: If pandas is not installed.
        """
        cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

        conn = self._get_connection()
        try:
            df = conn.execute(
                """
                SELECT
                    pe.start_time as timestamp,
                    sm.wall_clock_seconds,
                    sm.cpu_user_seconds,
                    sm.cpu_kernel_seconds,
                    sm.memory_peak_bytes,
                    sm.download_size_bytes,
                    pe.packages_updated,
                    pe.packages_total,
                    pe.status
                FROM plugin_executions pe
                LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
                WHERE pe.plugin_name = ?
                  AND pe.start_time >= ?
                  AND pe.status = 'success'
                ORDER BY pe.start_time ASC
                """,
                [plugin_name, cutoff_date],
            ).df()

            return df
        finally:
            conn.close()

    def get_all_plugins_summary(self, days: int = 90) -> list[PluginStats]:
        """Get summary statistics for all plugins.

        Retrieves aggregated statistics for all plugins that have been
        executed within the specified time period.

        Args:
            days: Number of days to look back (default: 90).

        Returns:
            List of PluginStats objects, one per plugin.
        """
        cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

        conn = self._get_connection()
        try:
            results = conn.execute(
                """
                SELECT
                    pe.plugin_name,
                    COUNT(*) as execution_count,
                    SUM(CASE WHEN pe.status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN pe.status = 'failed' THEN 1 ELSE 0 END) as failure_count,
                    AVG(sm.wall_clock_seconds) as avg_wall_clock_seconds,
                    AVG(sm.cpu_user_seconds + COALESCE(sm.cpu_kernel_seconds, 0))
                        as avg_cpu_seconds,
                    AVG(sm.download_size_bytes) as avg_download_bytes,
                    AVG(sm.memory_peak_bytes) as avg_memory_peak_bytes,
                    SUM(pe.packages_updated) as total_packages_updated,
                    MIN(pe.start_time) as first_execution,
                    MAX(pe.start_time) as last_execution
                FROM plugin_executions pe
                LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
                WHERE pe.start_time >= ?
                GROUP BY pe.plugin_name
                ORDER BY pe.plugin_name
                """,
                [cutoff_date],
            ).fetchall()

            summaries = []
            for row in results:
                execution_count = row[1]
                success_count = row[2] or 0
                failure_count = row[3] or 0

                summaries.append(
                    PluginStats(
                        plugin_name=row[0],
                        execution_count=execution_count,
                        success_count=success_count,
                        failure_count=failure_count,
                        success_rate=success_count / execution_count
                        if execution_count > 0
                        else 0.0,
                        avg_wall_clock_seconds=row[4],
                        avg_cpu_seconds=row[5],
                        avg_download_bytes=row[6],
                        avg_memory_peak_bytes=row[7],
                        total_packages_updated=row[8] or 0,
                        first_execution=row[9],
                        last_execution=row[10],
                    )
                )

            return summaries
        finally:
            conn.close()

    def get_plugin_names(self, days: int | None = None) -> list[str]:
        """Get list of all plugin names in the database.

        Args:
            days: Optional number of days to look back. If None, returns all plugins.

        Returns:
            List of unique plugin names.
        """
        conn = self._get_connection()
        try:
            if days is not None:
                cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)
                results = conn.execute(
                    """
                    SELECT DISTINCT plugin_name
                    FROM plugin_executions
                    WHERE start_time >= ?
                    ORDER BY plugin_name
                    """,
                    [cutoff_date],
                ).fetchall()
            else:
                results = conn.execute(
                    """
                    SELECT DISTINCT plugin_name
                    FROM plugin_executions
                    ORDER BY plugin_name
                    """
                ).fetchall()

            return [row[0] for row in results]
        finally:
            conn.close()

    def get_recent_executions(
        self,
        plugin_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Get recent plugin executions.

        Retrieves the most recent plugin executions with their metrics.

        Args:
            plugin_name: Optional plugin name to filter by.
            limit: Maximum number of executions to return (default: 100).

        Returns:
            List of dictionaries containing execution details.
        """
        conn = self._get_connection()
        try:
            if plugin_name:
                results = conn.execute(
                    """
                    SELECT
                        pe.execution_id,
                        pe.run_id,
                        pe.plugin_name,
                        pe.status,
                        pe.start_time,
                        pe.end_time,
                        pe.packages_updated,
                        pe.packages_total,
                        pe.error_message,
                        sm.wall_clock_seconds,
                        sm.cpu_user_seconds,
                        sm.download_size_bytes,
                        sm.memory_peak_bytes
                    FROM plugin_executions pe
                    LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
                    WHERE pe.plugin_name = ?
                    ORDER BY pe.start_time DESC
                    LIMIT ?
                    """,
                    [plugin_name, limit],
                ).fetchall()
            else:
                results = conn.execute(
                    """
                    SELECT
                        pe.execution_id,
                        pe.run_id,
                        pe.plugin_name,
                        pe.status,
                        pe.start_time,
                        pe.end_time,
                        pe.packages_updated,
                        pe.packages_total,
                        pe.error_message,
                        sm.wall_clock_seconds,
                        sm.cpu_user_seconds,
                        sm.download_size_bytes,
                        sm.memory_peak_bytes
                    FROM plugin_executions pe
                    LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
                    ORDER BY pe.start_time DESC
                    LIMIT ?
                    """,
                    [limit],
                ).fetchall()

            return [
                {
                    "execution_id": row[0],
                    "run_id": row[1],
                    "plugin_name": row[2],
                    "status": row[3],
                    "start_time": row[4],
                    "end_time": row[5],
                    "packages_updated": row[6],
                    "packages_total": row[7],
                    "error_message": row[8],
                    "wall_clock_seconds": row[9],
                    "cpu_user_seconds": row[10],
                    "download_size_bytes": row[11],
                    "memory_peak_bytes": row[12],
                }
                for row in results
            ]
        finally:
            conn.close()

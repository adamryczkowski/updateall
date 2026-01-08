"""Aggregation functions for statistical analysis.

This module provides functions for computing aggregated metrics
over time periods, useful for trend analysis and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from stats.db.connection import DatabaseConnection, get_default_db_path

if TYPE_CHECKING:
    import duckdb


class TimeGranularity(str, Enum):
    """Time granularity for aggregations."""

    HOURLY = "hour"
    DAILY = "day"
    WEEKLY = "week"
    MONTHLY = "month"


@dataclass
class DailyAggregation:
    """Daily aggregated metrics.

    Attributes:
        date: The date for this aggregation.
        total_runs: Total number of update-all runs.
        total_executions: Total plugin executions.
        successful_executions: Number of successful executions.
        failed_executions: Number of failed executions.
        total_wall_clock_seconds: Sum of wall-clock time.
        total_cpu_seconds: Sum of CPU time.
        total_download_bytes: Sum of download sizes.
        avg_wall_clock_seconds: Average wall-clock time per execution.
        avg_memory_peak_bytes: Average peak memory usage.
        unique_plugins: Number of unique plugins executed.
    """

    date: datetime
    total_runs: int
    total_executions: int
    successful_executions: int
    failed_executions: int
    total_wall_clock_seconds: float
    total_cpu_seconds: float
    total_download_bytes: int
    avg_wall_clock_seconds: float | None
    avg_memory_peak_bytes: float | None
    unique_plugins: int


@dataclass
class PerformanceDataPoint:
    """Performance metric data point for time-aggregated analysis.

    Attributes:
        period_start: Start of the time period.
        period_end: End of the time period.
        plugin_name: Name of the plugin.
        metric_name: Name of the metric.
        min_value: Minimum value in the period.
        max_value: Maximum value in the period.
        avg_value: Average value in the period.
        median_value: Median value in the period.
        std_value: Standard deviation in the period.
        sample_count: Number of samples in the period.
    """

    period_start: datetime
    period_end: datetime
    plugin_name: str
    metric_name: str
    min_value: float
    max_value: float
    avg_value: float
    median_value: float | None
    std_value: float | None
    sample_count: int


def _get_connection(db_path: Path | str | None) -> duckdb.DuckDBPyConnection:
    """Get a database connection.

    Args:
        db_path: Path to the database file. If None, uses the default path.

    Returns:
        DuckDB connection.
    """
    path = get_default_db_path() if db_path is None else Path(db_path)
    db = DatabaseConnection(path, read_only=False)
    return db.connect()


def get_daily_aggregations(
    days: int = 30,
    db_path: Path | str | None = None,
) -> list[DailyAggregation]:
    """Get daily aggregated metrics.

    Computes aggregated metrics for each day over the specified period.

    Args:
        days: Number of days to look back (default: 30).
        db_path: Path to the database file. If None, uses the default path.

    Returns:
        List of DailyAggregation objects, one per day with data.
    """
    cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

    conn = _get_connection(db_path)
    try:
        results = conn.execute(
            """
            SELECT
                DATE_TRUNC('day', pe.start_time) as date,
                COUNT(DISTINCT pe.run_id) as total_runs,
                COUNT(*) as total_executions,
                SUM(CASE WHEN pe.status = 'success' THEN 1 ELSE 0 END) as successful_executions,
                SUM(CASE WHEN pe.status = 'failed' THEN 1 ELSE 0 END) as failed_executions,
                COALESCE(SUM(sm.wall_clock_seconds), 0) as total_wall_clock_seconds,
                COALESCE(SUM(sm.cpu_user_seconds + COALESCE(sm.cpu_kernel_seconds, 0)), 0)
                    as total_cpu_seconds,
                COALESCE(SUM(sm.download_size_bytes), 0) as total_download_bytes,
                AVG(sm.wall_clock_seconds) as avg_wall_clock_seconds,
                AVG(sm.memory_peak_bytes) as avg_memory_peak_bytes,
                COUNT(DISTINCT pe.plugin_name) as unique_plugins
            FROM plugin_executions pe
            LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            WHERE pe.start_time >= ?
            GROUP BY DATE_TRUNC('day', pe.start_time)
            ORDER BY date ASC
            """,
            [cutoff_date],
        ).fetchall()

        return [
            DailyAggregation(
                date=row[0],
                total_runs=row[1],
                total_executions=row[2],
                successful_executions=row[3] or 0,
                failed_executions=row[4] or 0,
                total_wall_clock_seconds=row[5] or 0.0,
                total_cpu_seconds=row[6] or 0.0,
                total_download_bytes=int(row[7] or 0),
                avg_wall_clock_seconds=row[8],
                avg_memory_peak_bytes=row[9],
                unique_plugins=row[10],
            )
            for row in results
        ]
    finally:
        conn.close()


def get_plugin_performance_over_time(
    plugin_name: str,
    metric: str = "wall_clock_seconds",
    granularity: TimeGranularity = TimeGranularity.DAILY,
    days: int = 90,
    db_path: Path | str | None = None,
) -> list[PerformanceDataPoint]:
    """Get time-aggregated performance metrics for a plugin.

    Computes statistical summaries of a metric over time periods.

    Args:
        plugin_name: Name of the plugin to query.
        metric: Metric to aggregate. One of:
            - wall_clock_seconds
            - cpu_user_seconds
            - memory_peak_bytes
            - download_size_bytes
        granularity: Time granularity for aggregation (default: DAILY).
        days: Number of days to look back (default: 90).
        db_path: Path to the database file. If None, uses the default path.

    Returns:
        List of PerformanceDataPoint objects, one per time period.

    Raises:
        ValueError: If an invalid metric name is provided.
    """
    valid_metrics = {
        "wall_clock_seconds",
        "cpu_user_seconds",
        "memory_peak_bytes",
        "download_size_bytes",
    }
    if metric not in valid_metrics:
        raise ValueError(f"Invalid metric: {metric}. Must be one of: {valid_metrics}")

    cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

    # Map granularity to DuckDB date_trunc interval
    interval_map = {
        TimeGranularity.HOURLY: "hour",
        TimeGranularity.DAILY: "day",
        TimeGranularity.WEEKLY: "week",
        TimeGranularity.MONTHLY: "month",
    }
    interval = interval_map[granularity]

    conn = _get_connection(db_path)
    try:
        # Use parameterized query for safety, but metric column is validated above
        query = f"""
            SELECT
                DATE_TRUNC('{interval}', sm.start_time) as period_start,
                DATE_TRUNC('{interval}', sm.start_time) + INTERVAL '1 {interval}' as period_end,
                pe.plugin_name,
                '{metric}' as metric_name,
                MIN(sm.{metric}) as min_value,
                MAX(sm.{metric}) as max_value,
                AVG(sm.{metric}) as avg_value,
                MEDIAN(sm.{metric}) as median_value,
                STDDEV(sm.{metric}) as std_value,
                COUNT(*) as sample_count
            FROM step_metrics sm
            JOIN plugin_executions pe ON sm.execution_id = pe.execution_id
            WHERE pe.plugin_name = ?
              AND sm.start_time >= ?
              AND sm.{metric} IS NOT NULL
            GROUP BY DATE_TRUNC('{interval}', sm.start_time), pe.plugin_name
            ORDER BY period_start ASC
        """

        results = conn.execute(query, [plugin_name, cutoff_date]).fetchall()

        return [
            PerformanceDataPoint(
                period_start=row[0],
                period_end=row[1],
                plugin_name=row[2],
                metric_name=row[3],
                min_value=float(row[4]) if row[4] is not None else 0.0,
                max_value=float(row[5]) if row[5] is not None else 0.0,
                avg_value=float(row[6]) if row[6] is not None else 0.0,
                median_value=float(row[7]) if row[7] is not None else None,
                std_value=float(row[8]) if row[8] is not None else None,
                sample_count=row[9],
            )
            for row in results
        ]
    finally:
        conn.close()


def get_success_rate_trend(
    plugin_name: str | None = None,
    granularity: TimeGranularity = TimeGranularity.DAILY,
    days: int = 90,
    db_path: Path | str | None = None,
) -> list[dict[str, object]]:
    """Get success rate trend over time.

    Computes the success rate for each time period.

    Args:
        plugin_name: Optional plugin name to filter by. If None, aggregates all plugins.
        granularity: Time granularity for aggregation (default: DAILY).
        days: Number of days to look back (default: 90).
        db_path: Path to the database file. If None, uses the default path.

    Returns:
        List of dictionaries with period_start, total_count, success_count, and success_rate.
    """
    cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

    interval_map = {
        TimeGranularity.HOURLY: "hour",
        TimeGranularity.DAILY: "day",
        TimeGranularity.WEEKLY: "week",
        TimeGranularity.MONTHLY: "month",
    }
    interval = interval_map[granularity]

    conn = _get_connection(db_path)
    try:
        if plugin_name:
            query = f"""
                SELECT
                    DATE_TRUNC('{interval}', start_time) as period_start,
                    COUNT(*) as total_count,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
                FROM plugin_executions
                WHERE plugin_name = ?
                  AND start_time >= ?
                GROUP BY DATE_TRUNC('{interval}', start_time)
                ORDER BY period_start ASC
            """
            results = conn.execute(query, [plugin_name, cutoff_date]).fetchall()
        else:
            query = f"""
                SELECT
                    DATE_TRUNC('{interval}', start_time) as period_start,
                    COUNT(*) as total_count,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count
                FROM plugin_executions
                WHERE start_time >= ?
                GROUP BY DATE_TRUNC('{interval}', start_time)
                ORDER BY period_start ASC
            """
            results = conn.execute(query, [cutoff_date]).fetchall()

        return [
            {
                "period_start": row[0],
                "total_count": row[1],
                "success_count": row[2] or 0,
                "success_rate": (row[2] or 0) / row[1] if row[1] > 0 else 0.0,
            }
            for row in results
        ]
    finally:
        conn.close()


def get_resource_usage_summary(
    days: int = 30,
    db_path: Path | str | None = None,
) -> dict[str, object]:
    """Get overall resource usage summary.

    Computes aggregate resource usage statistics over the specified period.

    Args:
        days: Number of days to look back (default: 30).
        db_path: Path to the database file. If None, uses the default path.

    Returns:
        Dictionary with resource usage statistics.
    """
    cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)

    conn = _get_connection(db_path)
    try:
        result = conn.execute(
            """
            SELECT
                COUNT(DISTINCT pe.run_id) as total_runs,
                COUNT(*) as total_executions,
                SUM(CASE WHEN pe.status = 'success' THEN 1 ELSE 0 END) as successful_executions,
                SUM(sm.wall_clock_seconds) as total_wall_clock_seconds,
                SUM(sm.cpu_user_seconds + COALESCE(sm.cpu_kernel_seconds, 0))
                    as total_cpu_seconds,
                SUM(sm.download_size_bytes) as total_download_bytes,
                AVG(sm.wall_clock_seconds) as avg_wall_clock_seconds,
                AVG(sm.memory_peak_bytes) as avg_memory_peak_bytes,
                MAX(sm.memory_peak_bytes) as max_memory_peak_bytes,
                SUM(pe.packages_updated) as total_packages_updated,
                COUNT(DISTINCT pe.plugin_name) as unique_plugins
            FROM plugin_executions pe
            LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            WHERE pe.start_time >= ?
            """,
            [cutoff_date],
        ).fetchone()

        if result is None:
            return {
                "total_runs": 0,
                "total_executions": 0,
                "successful_executions": 0,
                "success_rate": 0.0,
                "total_wall_clock_seconds": 0.0,
                "total_cpu_seconds": 0.0,
                "total_download_bytes": 0,
                "avg_wall_clock_seconds": None,
                "avg_memory_peak_bytes": None,
                "max_memory_peak_bytes": None,
                "total_packages_updated": 0,
                "unique_plugins": 0,
            }

        total_executions = result[1] or 0
        successful_executions = result[2] or 0

        return {
            "total_runs": result[0] or 0,
            "total_executions": total_executions,
            "successful_executions": successful_executions,
            "success_rate": successful_executions / total_executions
            if total_executions > 0
            else 0.0,
            "total_wall_clock_seconds": result[3] or 0.0,
            "total_cpu_seconds": result[4] or 0.0,
            "total_download_bytes": int(result[5] or 0),
            "avg_wall_clock_seconds": result[6],
            "avg_memory_peak_bytes": result[7],
            "max_memory_peak_bytes": result[8],
            "total_packages_updated": result[9] or 0,
            "unique_plugins": result[10] or 0,
        }
    finally:
        conn.close()

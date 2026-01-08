"""Data retrieval and query module for historical data.

This module provides query builders and aggregation functions for
retrieving and analyzing historical plugin execution data from DuckDB.
"""

from stats.retrieval.aggregations import (
    DailyAggregation,
    PerformanceDataPoint,
    TimeGranularity,
    get_daily_aggregations,
    get_plugin_performance_over_time,
    get_resource_usage_summary,
    get_success_rate_trend,
)
from stats.retrieval.queries import (
    HistoricalDataQuery,
    PluginStats,
    TimeSeriesPoint,
)

__all__ = [
    "DailyAggregation",
    "HistoricalDataQuery",
    "PerformanceDataPoint",
    "PluginStats",
    "TimeGranularity",
    "TimeSeriesPoint",
    "get_daily_aggregations",
    "get_plugin_performance_over_time",
    "get_resource_usage_summary",
    "get_success_rate_trend",
]

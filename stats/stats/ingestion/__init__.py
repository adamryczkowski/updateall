"""Data ingestion pipeline for metrics collection.

This package provides components for collecting and storing metrics:
- DuckDBMetricsCollector: Real-time metrics collection during plugin execution
- migrate_json_history: Migration tool for existing JSON history files
"""

from __future__ import annotations

from stats.ingestion.collector import DuckDBMetricsCollector
from stats.ingestion.loader import migrate_json_history

__all__ = ["DuckDBMetricsCollector", "migrate_json_history"]

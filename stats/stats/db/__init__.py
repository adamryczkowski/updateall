"""DuckDB database integration for update-all statistics.

This module provides database connection management, schema definitions,
and data models for storing historical plugin execution data.
"""

from stats.db.connection import DatabaseConnection, get_default_db_path
from stats.db.models import (
    Estimate,
    ExecutionStatus,
    PluginExecution,
    Run,
    StepMetrics,
    StepPhase,
)
from stats.db.schema import SCHEMA_VERSION, get_schema_version, initialize_schema

__all__ = [
    "SCHEMA_VERSION",
    "DatabaseConnection",
    "Estimate",
    "ExecutionStatus",
    "PluginExecution",
    "Run",
    "StepMetrics",
    "StepPhase",
    "get_default_db_path",
    "get_schema_version",
    "initialize_schema",
]

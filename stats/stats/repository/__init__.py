"""Repository pattern implementations for data access.

This module provides type-safe interfaces for CRUD operations on
the DuckDB database entities.
"""

from __future__ import annotations

from stats.repository.base import BaseRepository
from stats.repository.estimates import EstimatesRepository
from stats.repository.executions import ExecutionsRepository
from stats.repository.metrics import MetricsRepository
from stats.repository.runs import RunsRepository

__all__ = [
    "BaseRepository",
    "EstimatesRepository",
    "ExecutionsRepository",
    "MetricsRepository",
    "RunsRepository",
]

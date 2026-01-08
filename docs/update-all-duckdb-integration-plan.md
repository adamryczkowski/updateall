# DuckDB Integration Plan for Update-All Historical Data Storage

> **Document Version**: 1.0
> **Created**: 2025-01-08
> **Status**: Draft

## 1. Overview

This document outlines the comprehensive implementation plan for integrating DuckDB as the permanent storage backend for historical data about previous runs of the update-all procedures. DuckDB is chosen for its:

- **Embedded nature**: No separate server process required
- **OLAP optimization**: Excellent for analytical queries on historical data
- **Python integration**: Native Python API with Pandas/Polars support
- **File-based persistence**: Simple backup and migration
- **SQL support**: Standard SQL for complex queries

### 1.1 Goals

1. Replace the current JSON-based history storage with DuckDB
2. Store comprehensive metrics for each plugin execution step
3. Enable efficient querying for statistical modeling
4. Maintain backward compatibility with existing APIs
5. Support concurrent read access for reporting

### 1.2 References

- DuckDB Python API: https://duckdb.org/docs/api/python/overview
- Current implementation: [`stats/stats/history.py`](../stats/stats/history.py)
- Metrics module: [`core/core/metrics.py`](../core/core/metrics.py)

---

## 2. Database Schema Design

### 2.1 Entity-Relationship Diagram

```
┌─────────────────┐       ┌──────────────────────┐       ┌─────────────────────┐
│     runs        │       │   plugin_executions  │       │   step_metrics      │
├─────────────────┤       ├──────────────────────┤       ├─────────────────────┤
│ run_id (PK)     │──────<│ execution_id (PK)    │──────<│ metric_id (PK)      │
│ start_time      │       │ run_id (FK)          │       │ execution_id (FK)   │
│ end_time        │       │ plugin_name          │       │ step_name           │
│ hostname        │       │ status               │       │ phase               │
│ user            │       │ start_time           │       │ start_time          │
│ config_hash     │       │ end_time             │       │ end_time            │
└─────────────────┘       │ packages_updated     │       │ wall_clock_seconds  │
                          │ error_message        │       │ cpu_user_seconds    │
                          └──────────────────────┘       │ cpu_kernel_seconds  │
                                                         │ memory_peak_bytes   │
┌─────────────────────┐                                  │ io_read_bytes       │
│   estimates         │                                  │ io_write_bytes      │
├─────────────────────┤                                  │ network_rx_bytes    │
│ estimate_id (PK)    │                                  │ network_tx_bytes    │
│ execution_id (FK)   │                                  │ download_size_bytes │
│ phase               │                                  └─────────────────────┘
│ download_bytes_est  │
│ cpu_seconds_est     │
│ package_count_est   │
│ confidence          │
└─────────────────────┘
```

### 2.2 Table Definitions

#### 2.2.1 `runs` Table

Stores metadata about each complete update-all run.

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    hostname VARCHAR(255) NOT NULL,
    username VARCHAR(255),
    config_hash VARCHAR(64),
    total_plugins INTEGER DEFAULT 0,
    successful_plugins INTEGER DEFAULT 0,
    failed_plugins INTEGER DEFAULT 0,
    skipped_plugins INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_runs_start_time ON runs(start_time DESC);
```

#### 2.2.2 `plugin_executions` Table

Stores results for each plugin within a run.

```sql
CREATE TABLE IF NOT EXISTS plugin_executions (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    plugin_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,  -- pending, running, success, failed, skipped, timeout
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    packages_updated INTEGER DEFAULT 0,
    packages_total INTEGER,
    error_message TEXT,
    exit_code INTEGER,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_plugin_exec_run_id ON plugin_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_plugin_name ON plugin_executions(plugin_name);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_status ON plugin_executions(status);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_start_time ON plugin_executions(start_time DESC);
```

#### 2.2.3 `step_metrics` Table

Stores detailed metrics for each execution step (prepare, download, update).

```sql
CREATE TABLE IF NOT EXISTS step_metrics (
    metric_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES plugin_executions(execution_id) ON DELETE CASCADE,
    step_name VARCHAR(50) NOT NULL,  -- prepare, download, update
    phase VARCHAR(50) NOT NULL,      -- CHECK, DOWNLOAD, EXECUTE
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,

    -- Time metrics
    wall_clock_seconds DOUBLE,
    cpu_user_seconds DOUBLE,
    cpu_kernel_seconds DOUBLE,

    -- Memory metrics
    memory_peak_bytes BIGINT,
    memory_avg_bytes BIGINT,

    -- I/O metrics
    io_read_bytes BIGINT,
    io_write_bytes BIGINT,
    io_read_ops INTEGER,
    io_write_ops INTEGER,

    -- Network metrics
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT,

    -- Download-specific metrics
    download_size_bytes BIGINT,
    download_speed_bps DOUBLE,

    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

-- Indexes for analytical queries
CREATE INDEX IF NOT EXISTS idx_step_metrics_execution_id ON step_metrics(execution_id);
CREATE INDEX IF NOT EXISTS idx_step_metrics_step_name ON step_metrics(step_name);
CREATE INDEX IF NOT EXISTS idx_step_metrics_phase ON step_metrics(phase);
```

#### 2.2.4 `estimates` Table

Stores plugin-reported estimates for comparison with actual values.

```sql
CREATE TABLE IF NOT EXISTS estimates (
    estimate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES plugin_executions(execution_id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,  -- CHECK, DOWNLOAD, EXECUTE

    -- Estimated values
    download_bytes_est BIGINT,
    cpu_seconds_est DOUBLE,
    wall_seconds_est DOUBLE,
    memory_bytes_est BIGINT,
    package_count_est INTEGER,

    -- Confidence level (0.0 - 1.0)
    confidence DOUBLE,

    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

-- Index for joining with step_metrics
CREATE INDEX IF NOT EXISTS idx_estimates_execution_id ON estimates(execution_id);
CREATE INDEX IF NOT EXISTS idx_estimates_phase ON estimates(phase);
```

### 2.3 Views for Common Queries

#### 2.3.1 Plugin Performance Summary View

```sql
CREATE OR REPLACE VIEW plugin_performance_summary AS
SELECT
    pe.plugin_name,
    COUNT(DISTINCT pe.execution_id) as total_executions,
    COUNT(DISTINCT CASE WHEN pe.status = 'success' THEN pe.execution_id END) as successful_executions,
    AVG(sm.wall_clock_seconds) as avg_wall_clock_seconds,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as median_wall_clock_seconds,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as p95_wall_clock_seconds,
    AVG(sm.memory_peak_bytes) as avg_memory_peak_bytes,
    AVG(sm.download_size_bytes) as avg_download_size_bytes,
    MAX(pe.start_time) as last_execution
FROM plugin_executions pe
LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
WHERE pe.status = 'success'
GROUP BY pe.plugin_name;
```

#### 2.3.2 Estimate Accuracy View

```sql
CREATE OR REPLACE VIEW estimate_accuracy AS
SELECT
    pe.plugin_name,
    e.phase,
    COUNT(*) as sample_count,
    AVG(CASE WHEN e.download_bytes_est > 0 AND sm.download_size_bytes > 0
        THEN ABS(e.download_bytes_est - sm.download_size_bytes)::DOUBLE / sm.download_size_bytes
        ELSE NULL END) as avg_download_error_pct,
    AVG(CASE WHEN e.wall_seconds_est > 0 AND sm.wall_clock_seconds > 0
        THEN ABS(e.wall_seconds_est - sm.wall_clock_seconds) / sm.wall_clock_seconds
        ELSE NULL END) as avg_time_error_pct
FROM estimates e
JOIN plugin_executions pe ON e.execution_id = pe.execution_id
JOIN step_metrics sm ON e.execution_id = sm.execution_id AND e.phase = sm.phase
WHERE pe.status = 'success'
GROUP BY pe.plugin_name, e.phase;
```

---

## 3. Module Architecture

### 3.1 Package Structure

```
stats/
├── stats/
│   ├── __init__.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py      # Database connection management
│   │   ├── schema.py          # Schema definitions and migrations
│   │   ├── models.py          # Data models (dataclasses)
│   │   └── migrations/        # Schema migration scripts
│   │       ├── __init__.py
│   │       ├── v001_initial.py
│   │       └── v002_add_indexes.py
│   ├── repository/
│   │   ├── __init__.py
│   │   ├── base.py            # Base repository interface
│   │   ├── runs.py            # Runs repository
│   │   ├── executions.py      # Plugin executions repository
│   │   ├── metrics.py         # Step metrics repository
│   │   └── estimates.py       # Estimates repository
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── collector.py       # Real-time metrics collector
│   │   ├── transformer.py     # Data transformation
│   │   └── loader.py          # Batch data loader
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── queries.py         # Query builders
│   │   ├── aggregations.py    # Aggregation functions
│   │   └── export.py          # Data export utilities
│   ├── calculator.py          # Existing calculator (updated)
│   ├── estimator.py           # Existing estimator (updated)
│   └── history.py             # Existing history (deprecated, adapter)
└── tests/
    ├── __init__.py
    ├── db/
    │   ├── test_connection.py
    │   ├── test_schema.py
    │   └── test_migrations.py
    ├── repository/
    │   ├── test_runs.py
    │   ├── test_executions.py
    │   ├── test_metrics.py
    │   └── test_estimates.py
    ├── ingestion/
    │   ├── test_collector.py
    │   ├── test_transformer.py
    │   └── test_loader.py
    └── retrieval/
        ├── test_queries.py
        └── test_aggregations.py
```

### 3.2 Core Components

#### 3.2.1 Connection Manager

```python
# stats/stats/db/connection.py
"""Database connection management for DuckDB."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import structlog

if TYPE_CHECKING:
    from collections.abc import Generator

logger = structlog.get_logger(__name__)


def get_default_db_path() -> Path:
    """Get the default database path following XDG specification."""
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    data_dir = base / "update-all"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "history.duckdb"


class DatabaseConnection:
    """Manages DuckDB database connections.

    Provides connection pooling and context management for database operations.
    Supports both read-only and read-write connections.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        read_only: bool = False,
    ) -> None:
        """Initialize the database connection manager.

        Args:
            db_path: Path to the database file. Uses default if None.
            read_only: Whether to open in read-only mode.
        """
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self.read_only = read_only
        self._connection: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Establish a database connection.

        Returns:
            DuckDB connection object.
        """
        if self._connection is None:
            self._connection = duckdb.connect(
                database=str(self.db_path),
                read_only=self.read_only,
            )
            logger.debug(
                "database_connected",
                path=str(self.db_path),
                read_only=self.read_only,
            )
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            logger.debug("database_disconnected", path=str(self.db_path))

    @contextmanager
    def transaction(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Context manager for database transactions.

        Yields:
            DuckDB connection within a transaction.
        """
        conn = self.connect()
        try:
            conn.begin()
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        return self.connect()

    def __exit__(self, *args: object) -> None:
        self.close()


# Global connection instance
_default_connection: DatabaseConnection | None = None


def get_connection(
    db_path: Path | str | None = None,
    read_only: bool = False,
) -> DatabaseConnection:
    """Get a database connection.

    Args:
        db_path: Optional custom database path.
        read_only: Whether to open in read-only mode.

    Returns:
        DatabaseConnection instance.
    """
    global _default_connection

    if db_path is not None:
        return DatabaseConnection(db_path, read_only)

    if _default_connection is None:
        _default_connection = DatabaseConnection(read_only=read_only)

    return _default_connection
```

#### 3.2.2 Schema Manager

```python
# stats/stats/db/schema.py
"""Database schema management and migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ DEFAULT current_timestamp
);

-- Runs table
CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    hostname VARCHAR(255) NOT NULL,
    username VARCHAR(255),
    config_hash VARCHAR(64),
    total_plugins INTEGER DEFAULT 0,
    successful_plugins INTEGER DEFAULT 0,
    failed_plugins INTEGER DEFAULT 0,
    skipped_plugins INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_runs_start_time ON runs(start_time DESC);

-- Plugin executions table
CREATE TABLE IF NOT EXISTS plugin_executions (
    execution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    plugin_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    packages_updated INTEGER DEFAULT 0,
    packages_total INTEGER,
    error_message TEXT,
    exit_code INTEGER,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_plugin_exec_run_id ON plugin_executions(run_id);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_plugin_name ON plugin_executions(plugin_name);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_status ON plugin_executions(status);
CREATE INDEX IF NOT EXISTS idx_plugin_exec_start_time ON plugin_executions(start_time DESC);

-- Step metrics table
CREATE TABLE IF NOT EXISTS step_metrics (
    metric_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES plugin_executions(execution_id) ON DELETE CASCADE,
    step_name VARCHAR(50) NOT NULL,
    phase VARCHAR(50) NOT NULL,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    wall_clock_seconds DOUBLE,
    cpu_user_seconds DOUBLE,
    cpu_kernel_seconds DOUBLE,
    memory_peak_bytes BIGINT,
    memory_avg_bytes BIGINT,
    io_read_bytes BIGINT,
    io_write_bytes BIGINT,
    io_read_ops INTEGER,
    io_write_ops INTEGER,
    network_rx_bytes BIGINT,
    network_tx_bytes BIGINT,
    download_size_bytes BIGINT,
    download_speed_bps DOUBLE,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_step_metrics_execution_id ON step_metrics(execution_id);
CREATE INDEX IF NOT EXISTS idx_step_metrics_step_name ON step_metrics(step_name);
CREATE INDEX IF NOT EXISTS idx_step_metrics_phase ON step_metrics(phase);

-- Estimates table
CREATE TABLE IF NOT EXISTS estimates (
    estimate_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_id UUID NOT NULL REFERENCES plugin_executions(execution_id) ON DELETE CASCADE,
    phase VARCHAR(50) NOT NULL,
    download_bytes_est BIGINT,
    cpu_seconds_est DOUBLE,
    wall_seconds_est DOUBLE,
    memory_bytes_est BIGINT,
    package_count_est INTEGER,
    confidence DOUBLE,
    created_at TIMESTAMPTZ DEFAULT current_timestamp
);

CREATE INDEX IF NOT EXISTS idx_estimates_execution_id ON estimates(execution_id);
CREATE INDEX IF NOT EXISTS idx_estimates_phase ON estimates(phase);
"""


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize the database schema.

    Args:
        conn: DuckDB connection.
    """
    # Check current version
    try:
        result = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        current_version = result[0] if result and result[0] else 0
    except duckdb.CatalogException:
        current_version = 0

    if current_version >= SCHEMA_VERSION:
        logger.debug(
            "schema_up_to_date",
            current_version=current_version,
        )
        return

    # Apply schema
    logger.info(
        "applying_schema",
        from_version=current_version,
        to_version=SCHEMA_VERSION,
    )

    conn.execute(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)",
        [SCHEMA_VERSION],
    )

    logger.info("schema_applied", version=SCHEMA_VERSION)


def get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Get the current schema version.

    Args:
        conn: DuckDB connection.

    Returns:
        Current schema version number.
    """
    try:
        result = conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        return result[0] if result and result[0] else 0
    except duckdb.CatalogException:
        return 0
```

---

## 4. Data Ingestion Strategy

### 4.1 Real-Time Collection

The [`MetricsCollector`](../core/core/metrics.py) will be extended to push metrics to DuckDB in real-time.

```python
# stats/stats/ingestion/collector.py
"""Real-time metrics collection for DuckDB storage."""

from __future__ import annotations

import resource
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

from stats.db.connection import get_connection

if TYPE_CHECKING:
    import duckdb

logger = structlog.get_logger(__name__)


@dataclass
class StepMetricsData:
    """Data collected during a step execution."""

    step_name: str
    phase: str
    start_time: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    end_time: datetime | None = None

    # Resource usage at start
    _start_rusage: resource.struct_rusage | None = field(default=None, repr=False)
    _start_wall_time: float = field(default=0.0, repr=False)

    # Computed metrics
    wall_clock_seconds: float | None = None
    cpu_user_seconds: float | None = None
    cpu_kernel_seconds: float | None = None
    memory_peak_bytes: int | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    download_size_bytes: int | None = None

    def start(self) -> None:
        """Start collecting metrics."""
        self._start_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)
        self._start_wall_time = time.perf_counter()
        self.start_time = datetime.now(tz=UTC)

    def stop(self) -> None:
        """Stop collecting and compute final metrics."""
        self.end_time = datetime.now(tz=UTC)
        end_wall_time = time.perf_counter()
        end_rusage = resource.getrusage(resource.RUSAGE_CHILDREN)

        self.wall_clock_seconds = end_wall_time - self._start_wall_time

        if self._start_rusage:
            self.cpu_user_seconds = (
                end_rusage.ru_utime - self._start_rusage.ru_utime
            )
            self.cpu_kernel_seconds = (
                end_rusage.ru_stime - self._start_rusage.ru_stime
            )
            self.memory_peak_bytes = end_rusage.ru_maxrss * 1024  # KB to bytes
            self.io_read_bytes = (
                end_rusage.ru_inblock - self._start_rusage.ru_inblock
            ) * 512  # blocks to bytes
            self.io_write_bytes = (
                end_rusage.ru_oublock - self._start_rusage.ru_oublock
            ) * 512


class DuckDBMetricsCollector:
    """Collects and stores metrics in DuckDB."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the collector.

        Args:
            db_path: Optional custom database path.
        """
        self._db = get_connection(db_path)
        self._current_run_id: UUID | None = None
        self._current_executions: dict[str, UUID] = {}
        self._step_metrics: dict[str, StepMetricsData] = {}

    def start_run(self, hostname: str, username: str | None = None) -> UUID:
        """Start a new update run.

        Args:
            hostname: Machine hostname.
            username: Current user.

        Returns:
            Run ID.
        """
        run_id = uuid4()
        conn = self._db.connect()

        conn.execute(
            """
            INSERT INTO runs (run_id, start_time, hostname, username)
            VALUES (?, ?, ?, ?)
            """,
            [str(run_id), datetime.now(tz=UTC), hostname, username],
        )

        self._current_run_id = run_id
        logger.info("run_started", run_id=str(run_id))
        return run_id

    def end_run(
        self,
        total_plugins: int = 0,
        successful: int = 0,
        failed: int = 0,
        skipped: int = 0,
    ) -> None:
        """End the current run.

        Args:
            total_plugins: Total number of plugins.
            successful: Number of successful plugins.
            failed: Number of failed plugins.
            skipped: Number of skipped plugins.
        """
        if not self._current_run_id:
            return

        conn = self._db.connect()
        conn.execute(
            """
            UPDATE runs
            SET end_time = ?,
                total_plugins = ?,
                successful_plugins = ?,
                failed_plugins = ?,
                skipped_plugins = ?
            WHERE run_id = ?
            """,
            [
                datetime.now(tz=UTC),
                total_plugins,
                successful,
                failed,
                skipped,
                str(self._current_run_id),
            ],
        )

        logger.info(
            "run_ended",
            run_id=str(self._current_run_id),
            successful=successful,
            failed=failed,
        )
        self._current_run_id = None
        self._current_executions.clear()

    def start_plugin_execution(self, plugin_name: str) -> UUID:
        """Start tracking a plugin execution.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Execution ID.
        """
        if not self._current_run_id:
            raise RuntimeError("No active run")

        execution_id = uuid4()
        conn = self._db.connect()

        conn.execute(
            """
            INSERT INTO plugin_executions
            (execution_id, run_id, plugin_name, status, start_time)
            VALUES (?, ?, ?, 'running', ?)
            """,
            [
                str(execution_id),
                str(self._current_run_id),
                plugin_name,
                datetime.now(tz=UTC),
            ],
        )

        self._current_executions[plugin_name] = execution_id
        return execution_id

    def end_plugin_execution(
        self,
        plugin_name: str,
        status: str,
        packages_updated: int = 0,
        error_message: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """End a plugin execution.

        Args:
            plugin_name: Name of the plugin.
            status: Final status.
            packages_updated: Number of packages updated.
            error_message: Error message if failed.
            exit_code: Process exit code.
        """
        execution_id = self._current_executions.get(plugin_name)
        if not execution_id:
            return

        conn = self._db.connect()
        conn.execute(
            """
            UPDATE plugin_executions
            SET status = ?,
                end_time = ?,
                packages_updated = ?,
                error_message = ?,
                exit_code = ?
            WHERE execution_id = ?
            """,
            [
                status,
                datetime.now(tz=UTC),
                packages_updated,
                error_message,
                exit_code,
                str(execution_id),
            ],
        )

    def start_step(self, plugin_name: str, step_name: str, phase: str) -> None:
        """Start tracking a step within a plugin execution.

        Args:
            plugin_name: Name of the plugin.
            step_name: Name of the step (prepare, download, update).
            phase: Execution phase (CHECK, DOWNLOAD, EXECUTE).
        """
        key = f"{plugin_name}:{step_name}"
        metrics = StepMetricsData(step_name=step_name, phase=phase)
        metrics.start()
        self._step_metrics[key] = metrics

    def end_step(
        self,
        plugin_name: str,
        step_name: str,
        download_size_bytes: int | None = None,
    ) -> None:
        """End a step and store metrics.

        Args:
            plugin_name: Name of the plugin.
            step_name: Name of the step.
            download_size_bytes: Download size if applicable.
        """
        key = f"{plugin_name}:{step_name}"
        metrics = self._step_metrics.get(key)
        if not metrics:
            return

        metrics.stop()
        metrics.download_size_bytes = download_size_bytes

        execution_id = self._current_executions.get(plugin_name)
        if not execution_id:
            return

        conn = self._db.connect()
        conn.execute(
            """
            INSERT INTO step_metrics (
                execution_id, step_name, phase,
                start_time, end_time,
                wall_clock_seconds, cpu_user_seconds, cpu_kernel_seconds,
                memory_peak_bytes, io_read_bytes, io_write_bytes,
                download_size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(execution_id),
                metrics.step_name,
                metrics.phase,
                metrics.start_time,
                metrics.end_time,
                metrics.wall_clock_seconds,
                metrics.cpu_user_seconds,
                metrics.cpu_kernel_seconds,
                metrics.memory_peak_bytes,
                metrics.io_read_bytes,
                metrics.io_write_bytes,
                metrics.download_size_bytes,
            ],
        )

        del self._step_metrics[key]

    def record_estimate(
        self,
        plugin_name: str,
        phase: str,
        download_bytes: int | None = None,
        cpu_seconds: float | None = None,
        wall_seconds: float | None = None,
        memory_bytes: int | None = None,
        package_count: int | None = None,
        confidence: float | None = None,
    ) -> None:
        """Record a plugin's estimate.

        Args:
            plugin_name: Name of the plugin.
            phase: Execution phase.
            download_bytes: Estimated download size.
            cpu_seconds: Estimated CPU time.
            wall_seconds: Estimated wall-clock time.
            memory_bytes: Estimated memory usage.
            package_count: Estimated package count.
            confidence: Confidence level (0.0 - 1.0).
        """
        execution_id = self._current_executions.get(plugin_name)
        if not execution_id:
            return

        conn = self._db.connect()
        conn.execute(
            """
            INSERT INTO estimates (
                execution_id, phase,
                download_bytes_est, cpu_seconds_est, wall_seconds_est,
                memory_bytes_est, package_count_est, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(execution_id),
                phase,
                download_bytes,
                cpu_seconds,
                wall_seconds,
                memory_bytes,
                package_count,
                confidence,
            ],
        )
```

### 4.2 Data Transformation

```python
# stats/stats/ingestion/transformer.py
"""Data transformation utilities for metrics ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.models import PluginResult, RunResult


@dataclass
class TransformedRun:
    """Transformed run data ready for database insertion."""

    run_id: str
    start_time: datetime
    end_time: datetime | None
    hostname: str
    username: str | None
    total_plugins: int
    successful_plugins: int
    failed_plugins: int
    skipped_plugins: int


@dataclass
class TransformedExecution:
    """Transformed plugin execution data."""

    execution_id: str
    run_id: str
    plugin_name: str
    status: str
    start_time: datetime | None
    end_time: datetime | None
    packages_updated: int
    error_message: str | None


def transform_run_result(
    run_result: RunResult,
    hostname: str,
    username: str | None = None,
) -> tuple[TransformedRun, list[TransformedExecution]]:
    """Transform a RunResult into database-ready format.

    Args:
        run_result: The run result to transform.
        hostname: Machine hostname.
        username: Current user.

    Returns:
        Tuple of (transformed run, list of transformed executions).
    """
    successful = sum(1 for r in run_result.plugin_results if r.status.value == "success")
    failed = sum(1 for r in run_result.plugin_results if r.status.value == "failed")
    skipped = sum(1 for r in run_result.plugin_results if r.status.value == "skipped")

    run = TransformedRun(
        run_id=run_result.run_id,
        start_time=run_result.start_time,
        end_time=run_result.end_time,
        hostname=hostname,
        username=username,
        total_plugins=len(run_result.plugin_results),
        successful_plugins=successful,
        failed_plugins=failed,
        skipped_plugins=skipped,
    )

    executions = [
        TransformedExecution(
            execution_id=f"{run_result.run_id}:{r.plugin_name}",
            run_id=run_result.run_id,
            plugin_name=r.plugin_name,
            status=r.status.value,
            start_time=r.start_time,
            end_time=r.end_time,
            packages_updated=r.packages_updated,
            error_message=r.error_message,
        )
        for r in run_result.plugin_results
    ]

    return run, executions
```

### 4.3 Migration from JSON History

```python
# stats/stats/ingestion/loader.py
"""Batch data loader for migrating existing history."""

from __future__ import annotations

import json
import socket
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from stats.db.connection import get_connection
from stats.db.schema import initialize_schema

logger = structlog.get_logger(__name__)


def migrate_json_history(
    json_path: Path,
    db_path: Path | None = None,
) -> int:
    """Migrate existing JSON history to DuckDB.

    Args:
        json_path: Path to the JSON history file.
        db_path: Optional custom database path.

    Returns:
        Number of runs migrated.
    """
    if not json_path.exists():
        logger.warning("json_history_not_found", path=str(json_path))
        return 0

    # Load JSON history
    with open(json_path) as f:
        history = json.load(f)

    if not history:
        logger.info("json_history_empty")
        return 0

    # Initialize database
    db = get_connection(db_path)
    conn = db.connect()
    initialize_schema(conn)

    hostname = socket.gethostname()
    migrated = 0

    for run in history:
        try:
            run_id = run.get("id", f"migrated-{migrated}")
            start_time = (
                datetime.fromisoformat(run["start_time"])
                if run.get("start_time")
                else datetime.now()
            )
            end_time = (
                datetime.fromisoformat(run["end_time"])
                if run.get("end_time")
                else None
            )

            plugins = run.get("plugins", [])
            successful = sum(1 for p in plugins if p.get("status") == "success")
            failed = sum(1 for p in plugins if p.get("status") == "failed")
            skipped = sum(1 for p in plugins if p.get("status") == "skipped")

            # Insert run
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, start_time, end_time, hostname,
                    total_plugins, successful_plugins, failed_plugins, skipped_plugins
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO NOTHING
                """,
                [
                    run_id, start_time, end_time, hostname,
                    len(plugins), successful, failed, skipped,
                ],
            )

            # Insert plugin executions
            for plugin in plugins:
                plugin_start = (
                    datetime.fromisoformat(plugin["start_time"])
                    if plugin.get("start_time")
                    else None
                )
                plugin_end = (
                    datetime.fromisoformat(plugin["end_time"])
                    if plugin.get("end_time")
                    else None
                )

                conn.execute(
                    """
                    INSERT INTO plugin_executions (
                        run_id, plugin_name, status, start_time, end_time,
                        packages_updated, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        run_id,
                        plugin.get("name", "unknown"),
                        plugin.get("status", "unknown"),
                        plugin_start,
                        plugin_end,
                        plugin.get("packages_updated", 0),
                        plugin.get("error_message"),
                    ],
                )

            migrated += 1

        except Exception as e:
            logger.warning(
                "migration_error",
                run_id=run.get("id"),
                error=str(e),
            )

    logger.info("migration_complete", runs_migrated=migrated)
    return migrated
```

---

## 5. Data Retrieval Strategy

### 5.1 Query Builders

```python
# stats/stats/retrieval/queries.py
"""Query builders for retrieving historical data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from stats.db.connection import get_connection

if TYPE_CHECKING:
    import duckdb
    import pandas as pd

logger = structlog.get_logger(__name__)


@dataclass
class PluginStats:
    """Statistics for a plugin."""

    plugin_name: str
    execution_count: int
    success_rate: float
    avg_wall_clock_seconds: float
    median_wall_clock_seconds: float
    p95_wall_clock_seconds: float
    avg_memory_peak_bytes: int
    avg_download_size_bytes: int | None


@dataclass
class TimeSeriesPoint:
    """A single point in a time series."""

    timestamp: datetime
    value: float


class HistoricalDataQuery:
    """Query builder for historical data retrieval."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the query builder.

        Args:
            db_path: Optional custom database path.
        """
        self._db = get_connection(db_path, read_only=True)

    def get_plugin_stats(
        self,
        plugin_name: str,
        days: int = 90,
    ) -> PluginStats | None:
        """Get statistics for a specific plugin.

        Args:
            plugin_name: Name of the plugin.
            days: Number of days to look back.

        Returns:
            PluginStats or None if no data.
        """
        conn = self._db.connect()
        cutoff = datetime.now() - timedelta(days=days)

        result = conn.execute(
            """
            SELECT
                pe.plugin_name,
                COUNT(*) as execution_count,
                AVG(CASE WHEN pe.status = 'success' THEN 1.0 ELSE 0.0 END) as success_rate,
                AVG(sm.wall_clock_seconds) as avg_wall_clock,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as median_wall_clock,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as p95_wall_clock,
                AVG(sm.memory_peak_bytes)::BIGINT as avg_memory,
                AVG(sm.download_size_bytes)::BIGINT as avg_download
            FROM plugin_executions pe
            LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            WHERE pe.plugin_name = ?
              AND pe.start_time >= ?
              AND pe.status = 'success'
            GROUP BY pe.plugin_name
            """,
            [plugin_name, cutoff],
        ).fetchone()

        if not result:
            return None

        return PluginStats(
            plugin_name=result[0],
            execution_count=result[1],
            success_rate=result[2],
            avg_wall_clock_seconds=result[3] or 0.0,
            median_wall_clock_seconds=result[4] or 0.0,
            p95_wall_clock_seconds=result[5] or 0.0,
            avg_memory_peak_bytes=result[6] or 0,
            avg_download_size_bytes=result[7],
        )

    def get_execution_time_series(
        self,
        plugin_name: str,
        step_name: str = "update",
        days: int = 90,
    ) -> list[TimeSeriesPoint]:
        """Get execution time series for a plugin.

        Args:
            plugin_name: Name of the plugin.
            step_name: Step name to filter by.
            days: Number of days to look back.

        Returns:
            List of time series points.
        """
        conn = self._db.connect()
        cutoff = datetime.now() - timedelta(days=days)

        results = conn.execute(
            """
            SELECT
                pe.start_time,
                sm.wall_clock_seconds
            FROM plugin_executions pe
            JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            WHERE pe.plugin_name = ?
              AND sm.step_name = ?
              AND pe.start_time >= ?
              AND pe.status = 'success'
              AND sm.wall_clock_seconds IS NOT NULL
            ORDER BY pe.start_time
            """,
            [plugin_name, step_name, cutoff],
        ).fetchall()

        return [
            TimeSeriesPoint(timestamp=row[0], value=row[1])
            for row in results
        ]

    def get_training_data_for_plugin(
        self,
        plugin_name: str,
        days: int = 365,
    ) -> "pd.DataFrame":
        """Get training data for statistical modeling.

        Args:
            plugin_name: Name of the plugin.
            days: Number of days to look back.

        Returns:
            DataFrame with training data.
        """
        import pandas as pd

        conn = self._db.connect()
        cutoff = datetime.now() - timedelta(days=days)

        df = conn.execute(
            """
            SELECT
                pe.start_time as timestamp,
                pe.packages_updated,
                pe.packages_total,
                sm.step_name,
                sm.phase,
                sm.wall_clock_seconds,
                sm.cpu_user_seconds,
                sm.cpu_kernel_seconds,
                sm.memory_peak_bytes,
                sm.download_size_bytes,
                sm.io_read_bytes,
                sm.io_write_bytes,
                e.download_bytes_est,
                e.cpu_seconds_est,
                e.wall_seconds_est,
                e.memory_bytes_est,
                e.package_count_est,
                e.confidence as estimate_confidence
            FROM plugin_executions pe
            JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            LEFT JOIN estimates e ON pe.execution_id = e.execution_id
                AND sm.phase = e.phase
            WHERE pe.plugin_name = ?
              AND pe.start_time >= ?
              AND pe.status = 'success'
            ORDER BY pe.start_time
            """,
            [plugin_name, cutoff],
        ).df()

        return df

    def get_all_plugins_summary(self, days: int = 90) -> list[PluginStats]:
        """Get summary statistics for all plugins.

        Args:
            days: Number of days to look back.

        Returns:
            List of PluginStats for all plugins.
        """
        conn = self._db.connect()
        cutoff = datetime.now() - timedelta(days=days)

        results = conn.execute(
            """
            SELECT
                pe.plugin_name,
                COUNT(*) as execution_count,
                AVG(CASE WHEN pe.status = 'success' THEN 1.0 ELSE 0.0 END) as success_rate,
                AVG(sm.wall_clock_seconds) as avg_wall_clock,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as median_wall_clock,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY sm.wall_clock_seconds) as p95_wall_clock,
                AVG(sm.memory_peak_bytes)::BIGINT as avg_memory,
                AVG(sm.download_size_bytes)::BIGINT as avg_download
            FROM plugin_executions pe
            LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
            WHERE pe.start_time >= ?
              AND pe.status = 'success'
            GROUP BY pe.plugin_name
            ORDER BY pe.plugin_name
            """,
            [cutoff],
        ).fetchall()

        return [
            PluginStats(
                plugin_name=row[0],
                execution_count=row[1],
                success_rate=row[2],
                avg_wall_clock_seconds=row[3] or 0.0,
                median_wall_clock_seconds=row[4] or 0.0,
                p95_wall_clock_seconds=row[5] or 0.0,
                avg_memory_peak_bytes=row[6] or 0,
                avg_download_size_bytes=row[7],
            )
            for row in results
        ]
```

### 5.2 Aggregation Functions

```python
# stats/stats/retrieval/aggregations.py
"""Aggregation functions for statistical analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from stats.db.connection import get_connection

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class DailyAggregation:
    """Daily aggregated metrics."""

    date: datetime
    total_runs: int
    total_plugins: int
    successful_plugins: int
    failed_plugins: int
    total_wall_clock_seconds: float
    total_download_bytes: int


def get_daily_aggregations(
    days: int = 30,
    db_path: str | None = None,
) -> list[DailyAggregation]:
    """Get daily aggregated metrics.

    Args:
        days: Number of days to aggregate.
        db_path: Optional custom database path.

    Returns:
        List of daily aggregations.
    """
    db = get_connection(db_path, read_only=True)
    conn = db.connect()
    cutoff = datetime.now() - timedelta(days=days)

    results = conn.execute(
        """
        SELECT
            DATE_TRUNC('day', r.start_time) as date,
            COUNT(DISTINCT r.run_id) as total_runs,
            COUNT(pe.execution_id) as total_plugins,
            SUM(CASE WHEN pe.status = 'success' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN pe.status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(sm.wall_clock_seconds) as total_wall_clock,
            SUM(sm.download_size_bytes)::BIGINT as total_download
        FROM runs r
        JOIN plugin_executions pe ON r.run_id = pe.run_id
        LEFT JOIN step_metrics sm ON pe.execution_id = sm.execution_id
        WHERE r.start_time >= ?
        GROUP BY DATE_TRUNC('day', r.start_time)
        ORDER BY date
        """,
        [cutoff],
    ).fetchall()

    return [
        DailyAggregation(
            date=row[0],
            total_runs=row[1],
            total_plugins=row[2],
            successful_plugins=row[3],
            failed_plugins=row[4],
            total_wall_clock_seconds=row[5] or 0.0,
            total_download_bytes=row[6] or 0,
        )
        for row in results
    ]


def get_plugin_performance_over_time(
    plugin_name: str,
    metric: str = "wall_clock_seconds",
    granularity: str = "week",
    days: int = 90,
    db_path: str | None = None,
) -> "pd.DataFrame":
    """Get plugin performance metrics over time.

    Args:
        plugin_name: Name of the plugin.
        metric: Metric to aggregate.
        granularity: Time granularity (day, week, month).
        days: Number of days to look back.
        db_path: Optional custom database path.

    Returns:
        DataFrame with time-aggregated metrics.
    """
    import pandas as pd

    db = get_connection(db_path, read_only=True)
    conn = db.connect()
    cutoff = datetime.now() - timedelta(days=days)

    valid_metrics = {
        "wall_clock_seconds",
        "cpu_user_seconds",
        "cpu_kernel_seconds",
        "memory_peak_bytes",
        "download_size_bytes",
    }

    if metric not in valid_metrics:
        raise ValueError(f"Invalid metric: {metric}. Must be one of {valid_metrics}")

    granularity_map = {
        "day": "day",
        "week": "week",
        "month": "month",
    }

    trunc = granularity_map.get(granularity, "week")

    df = conn.execute(
        f"""
        SELECT
            DATE_TRUNC('{trunc}', pe.start_time) as period,
            COUNT(*) as execution_count,
            AVG(sm.{metric}) as avg_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sm.{metric}) as median_value,
            MIN(sm.{metric}) as min_value,
            MAX(sm.{metric}) as max_value
        FROM plugin_executions pe
        JOIN step_metrics sm ON pe.execution_id = sm.execution_id
        WHERE pe.plugin_name = ?
          AND pe.start_time >= ?
          AND pe.status = 'success'
          AND sm.{metric} IS NOT NULL
        GROUP BY DATE_TRUNC('{trunc}', pe.start_time)
        ORDER BY period
        """,
        [plugin_name, cutoff],
    ).df()

    return df
```

---

## 6. Testing Strategy

### 6.1 Test Categories

1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test database operations with real DuckDB
3. **Migration Tests**: Test JSON to DuckDB migration
4. **Performance Tests**: Ensure query performance meets requirements

### 6.2 Test Fixtures

```python
# stats/tests/conftest.py
"""Shared test fixtures for stats module."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from stats.db.connection import DatabaseConnection
from stats.db.schema import initialize_schema

if TYPE_CHECKING:
    import duckdb


@pytest.fixture
def temp_db_path() -> Path:
    """Create a temporary database path."""
    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
        return Path(f.name)


@pytest.fixture
def db_connection(temp_db_path: Path) -> DatabaseConnection:
    """Create a database connection with initialized schema."""
    db = DatabaseConnection(temp_db_path)
    conn = db.connect()
    initialize_schema(conn)
    return db


@pytest.fixture
def sample_run_data(db_connection: DatabaseConnection) -> dict:
    """Insert sample run data for testing."""
    conn = db_connection.connect()

    run_id = str(uuid4())
    now = datetime.now(tz=UTC)

    # Insert run
    conn.execute(
        """
        INSERT INTO runs (run_id, start_time, end_time, hostname,
                         total_plugins, successful_plugins, failed_plugins)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [run_id, now - timedelta(hours=1), now, "test-host", 3, 2, 1],
    )

    # Insert plugin executions
    executions = []
    for i, (name, status) in enumerate([
        ("apt", "success"),
        ("snap", "success"),
        ("flatpak", "failed"),
    ]):
        exec_id = str(uuid4())
        conn.execute(
            """
            INSERT INTO plugin_executions
            (execution_id, run_id, plugin_name, status, start_time, end_time, packages_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                exec_id, run_id, name, status,
                now - timedelta(minutes=30 - i*10),
                now - timedelta(minutes=20 - i*10),
                5 if status == "success" else 0,
            ],
        )
        executions.append({"id": exec_id, "name": name, "status": status})

        # Insert step metrics for successful executions
        if status == "success":
            conn.execute(
                """
                INSERT INTO step_metrics
                (execution_id, step_name, phase, wall_clock_seconds,
                 cpu_user_seconds, memory_peak_bytes, download_size_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    exec_id, "update", "EXECUTE",
                    60.0 + i * 10,  # wall clock
                    30.0 + i * 5,   # cpu
                    100_000_000 + i * 50_000_000,  # memory
                    50_000_000 + i * 25_000_000,   # download
                ],
            )

    return {
        "run_id": run_id,
        "executions": executions,
        "start_time": now - timedelta(hours=1),
        "end_time": now,
    }
```

### 6.3 Unit Tests

```python
# stats/tests/db/test_connection.py
"""Tests for database connection management."""

from __future__ import annotations

from pathlib import Path

import pytest

from stats.db.connection import DatabaseConnection, get_default_db_path


def test_get_default_db_path_creates_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that default path creates the data directory."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

    path = get_default_db_path()

    assert path.parent.exists()
    assert path.name == "history.duckdb"
    assert path.parent.name == "update-all"


def test_database_connection_creates_file(temp_db_path: Path) -> None:
    """Test that connecting creates the database file."""
    db = DatabaseConnection(temp_db_path)

    conn = db.connect()
    assert conn is not None
    assert temp_db_path.exists()

    db.close()


def test_database_connection_context_manager(temp_db_path: Path) -> None:
    """Test database connection as context manager."""
    with DatabaseConnection(temp_db_path) as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result == (1,)


def test_database_transaction_commit(db_connection: DatabaseConnection) -> None:
    """Test that transactions commit on success."""
    conn = db_connection.connect()

    with db_connection.transaction() as tx_conn:
        tx_conn.execute(
            "INSERT INTO runs (run_id, start_time, hostname) VALUES (?, ?, ?)",
            ["test-run", "2025-01-01 00:00:00", "test-host"],
        )

    result = conn.execute("SELECT run_id FROM runs WHERE run_id = 'test-run'").fetchone()
    assert result is not None


def test_database_transaction_rollback(db_connection: DatabaseConnection) -> None:
    """Test that transactions rollback on error."""
    conn = db_connection.connect()

    with pytest.raises(Exception):
        with db_connection.transaction() as tx_conn:
            tx_conn.execute(
                "INSERT INTO runs (run_id, start_time, hostname) VALUES (?, ?, ?)",
                ["test-run-2", "2025-01-01 00:00:00", "test-host"],
            )
            raise Exception("Simulated error")

    result = conn.execute("SELECT run_id FROM runs WHERE run_id = 'test-run-2'").fetchone()
    assert result is None
```

### 6.4 Integration Tests

```python
# stats/tests/repository/test_runs.py
"""Integration tests for runs repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stats.db.connection import DatabaseConnection
from stats.retrieval.queries import HistoricalDataQuery


def test_get_plugin_stats(db_connection: DatabaseConnection, sample_run_data: dict) -> None:
    """Test retrieving plugin statistics."""
    query = HistoricalDataQuery(db_path=str(db_connection.db_path))

    stats = query.get_plugin_stats("apt", days=90)

    assert stats is not None
    assert stats.plugin_name == "apt"
    assert stats.execution_count == 1
    assert stats.success_rate == 1.0
    assert stats.avg_wall_clock_seconds > 0


def test_get_plugin_stats_no_data(db_connection: DatabaseConnection) -> None:
    """Test retrieving stats for non-existent plugin."""
    query = HistoricalDataQuery(db_path=str(db_connection.db_path))

    stats = query.get_plugin_stats("nonexistent", days=90)

    assert stats is None


def test_get_execution_time_series(
    db_connection: DatabaseConnection,
    sample_run_data: dict,
) -> None:
    """Test retrieving execution time series."""
    query = HistoricalDataQuery(db_path=str(db_connection.db_path))

    series = query.get_execution_time_series("apt", step_name="update", days=90)

    assert len(series) == 1
    assert series[0].value > 0


def test_get_all_plugins_summary(
    db_connection: DatabaseConnection,
    sample_run_data: dict,
) -> None:
    """Test retrieving summary for all plugins."""
    query = HistoricalDataQuery(db_path=str(db_connection.db_path))

    summaries = query.get_all_plugins_summary(days=90)

    assert len(summaries) == 2  # Only successful plugins
    plugin_names = {s.plugin_name for s in summaries}
    assert "apt" in plugin_names
    assert "snap" in plugin_names
    assert "flatpak" not in plugin_names  # Failed
```

### 6.5 Migration Tests

```python
# stats/tests/ingestion/test_loader.py
"""Tests for data migration from JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stats.db.connection import DatabaseConnection
from stats.ingestion.loader import migrate_json_history


@pytest.fixture
def sample_json_history(tmp_path: Path) -> Path:
    """Create a sample JSON history file."""
    history = [
        {
            "id": "run-1",
            "start_time": "2025-01-01T10:00:00+00:00",
            "end_time": "2025-01-01T10:30:00+00:00",
            "plugins": [
                {
                    "name": "apt",
                    "status": "success",
                    "packages_updated": 5,
                    "start_time": "2025-01-01T10:00:00+00:00",
                    "end_time": "2025-01-01T10:15:00+00:00",
                },
                {
                    "name": "snap",
                    "status": "failed",
                    "packages_updated": 0,
                    "error_message": "Network error",
                    "start_time": "2025-01-01T10:15:00+00:00",
                    "end_time": "2025-01-01T10:30:00+00:00",
                },
            ],
        },
    ]

    json_path = tmp_path / "history.json"
    with open(json_path, "w") as f:
        json.dump(history, f)

    return json_path


def test_migrate_json_history(
    sample_json_history: Path,
    temp_db_path: Path,
) -> None:
    """Test migrating JSON history to DuckDB."""
    migrated = migrate_json_history(sample_json_history, temp_db_path)

    assert migrated == 1

    # Verify data in database
    db = DatabaseConnection(temp_db_path)
    conn = db.connect()

    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
    assert runs[0] == 1

    executions = conn.execute("SELECT COUNT(*) FROM plugin_executions").fetchone()
    assert executions[0] == 2


def test_migrate_empty_history(tmp_path: Path, temp_db_path: Path) -> None:
    """Test migrating empty JSON history."""
    json_path = tmp_path / "empty.json"
    with open(json_path, "w") as f:
        json.dump([], f)

    migrated = migrate_json_history(json_path, temp_db_path)

    assert migrated == 0


def test_migrate_nonexistent_file(tmp_path: Path, temp_db_path: Path) -> None:
    """Test migrating non-existent file."""
    json_path = tmp_path / "nonexistent.json"

    migrated = migrate_json_history(json_path, temp_db_path)

    assert migrated == 0
```

---

## 7. Implementation Phases

### Phase 1: Core Infrastructure (Week 1)

1. Create database connection module
2. Implement schema management
3. Write unit tests for connection handling
4. Set up CI/CD for database tests

### Phase 2: Data Models and Repositories (Week 2)

1. Define data models (dataclasses)
2. Implement repository pattern for each table
3. Write integration tests
4. Document API

### Phase 3: Data Ingestion (Week 3)

1. Implement real-time metrics collector
2. Create data transformation utilities
3. Build JSON migration tool
4. Test migration with production data

### Phase 4: Data Retrieval (Week 4)

1. Implement query builders
2. Create aggregation functions
3. Build export utilities
4. Performance testing and optimization

### Phase 5: Integration (Week 5)

1. Update existing [`HistoryStore`](../stats/stats/history.py) as adapter
2. Integrate with [`TimeEstimator`](../stats/stats/estimator.py)
3. Update orchestrator to use new collector
4. End-to-end testing

### Phase 6: Documentation and Cleanup (Week 6)

1. Complete API documentation
2. Write migration guide
3. Remove deprecated code
4. Final review and release

---

## 8. Dependencies

### 8.1 Python Packages

Add to [`stats/pyproject.toml`](../stats/pyproject.toml):

```toml
[tool.poetry.dependencies]
duckdb = "^1.4.0"
pandas = "^2.0.0"  # For DataFrame support
```

### 8.2 Development Dependencies

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-asyncio = "^0.23.0"
```

---

## 9. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Data loss during migration | High | Backup JSON before migration, validate counts |
| Performance degradation | Medium | Index optimization, query caching |
| Concurrent write conflicts | Medium | Use transactions, consider WAL mode |
| Schema migration failures | High | Version tracking, rollback capability |
| Disk space growth | Low | Implement data retention policy |

---

## 10. Success Criteria

1. **Functional**: All existing history queries work with new backend
2. **Performance**: Query response time < 100ms for common queries
3. **Reliability**: Zero data loss during migration
4. **Maintainability**: 80%+ test coverage for new code
5. **Documentation**: Complete API documentation

---

*Document created: 2025-01-08*
*Last updated: 2025-01-08*

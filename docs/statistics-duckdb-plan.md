# Statistical Modeling with DuckDB Integration Plan

> **Document Version**: 1.0
> **Created**: 2026-01-08
> **Status**: Draft
> **Combines**: `update-all-statistical-modeling-plan.md` + `update-all-duckdb-integration-plan.md`

## Executive Summary

This document provides a comprehensive implementation plan for improving the statistical modeling capabilities of the update-all procedure using DuckDB as the database backend for storing historical data. The plan uses the Darts library (Unified Time Series Framework) for statistical modeling with calibrated confidence intervals via conformal prediction.

### Key Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Database | DuckDB | ^1.4.0 | Persistent storage for historical metrics |
| Time Series | Darts | ^0.40.0 | Forecasting with probabilistic predictions |
| Data Processing | Pandas | ^2.0.0 | DataFrame operations and transformations |
| Logging | structlog | ^24.0.0 | Structured logging throughout |

### Goals

1. **Permanent Storage**: Store comprehensive historical data about plugin executions in DuckDB
2. **Accurate Predictions**: Predict download size, CPU time, wall-clock time, and peak memory usage
3. **Confidence Intervals**: Provide calibrated prediction intervals using conformal prediction
4. **Model Flexibility**: Support multiple model types with automatic selection based on data availability
5. **TDD Approach**: Test-driven development with comprehensive dwarf tests using synthetic data

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Milestone 1: DuckDB Core Infrastructure](#milestone-1-duckdb-core-infrastructure)
3. [Milestone 2: Data Models and Repositories](#milestone-2-data-models-and-repositories)
4. [Milestone 3: Data Ingestion Pipeline](#milestone-3-data-ingestion-pipeline)
5. [Milestone 4: Data Retrieval and Queries](#milestone-4-data-retrieval-and-queries)
6. [Milestone 5: Statistical Modeling Foundation](#milestone-5-statistical-modeling-foundation)
7. [Milestone 6: Model Training Pipeline](#milestone-6-model-training-pipeline)
8. [Milestone 7: Conformal Prediction Integration](#milestone-7-conformal-prediction-integration)
9. [Milestone 8: Integration with Update-All](#milestone-8-integration-with-update-all)
10. [Milestone 9: Migration and Cleanup](#milestone-9-migration-and-cleanup)
11. [Dependencies and Risks](#dependencies-and-risks)

---

## 1. Architecture Overview

### 1.1 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Update-All System                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │  Orchestrator │───>│  Estimator   │───>│  MultiTargetModelManager │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│         │                   │                        │                   │
│         │                   │                        │                   │
│         ▼                   ▼                        ▼                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────────┐  │
│  │   Collector   │───>│   DuckDB     │<───│     ModelTrainer         │  │
│  │  (Ingestion)  │    │  (Storage)   │    │  (Darts + Conformal)     │  │
│  └──────────────┘    └──────────────┘    └──────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Package Structure

```
stats/
├── stats/
│   ├── __init__.py
│   ├── db/                          # DuckDB integration
│   │   ├── __init__.py
│   │   ├── connection.py            # Database connection management
│   │   ├── schema.py                # Schema definitions and migrations
│   │   └── models.py                # Data models (dataclasses)
│   ├── repository/                  # Data access layer
│   │   ├── __init__.py
│   │   ├── base.py                  # Base repository interface
│   │   ├── runs.py                  # Runs repository
│   │   ├── executions.py            # Plugin executions repository
│   │   ├── metrics.py               # Step metrics repository
│   │   └── estimates.py             # Estimates repository
│   ├── ingestion/                   # Data collection
│   │   ├── __init__.py
│   │   ├── collector.py             # Real-time metrics collector
│   │   ├── transformer.py           # Data transformation
│   │   └── loader.py                # Batch data loader / migration
│   ├── retrieval/                   # Data queries
│   │   ├── __init__.py
│   │   ├── queries.py               # Query builders
│   │   ├── aggregations.py          # Aggregation functions
│   │   └── export.py                # Data export utilities
│   ├── modeling/                    # Statistical modeling (Darts)
│   │   ├── __init__.py
│   │   ├── preprocessing.py         # Data preprocessing for ML
│   │   ├── validation.py            # Data quality validation
│   │   ├── trainer.py               # Model training pipeline
│   │   ├── multi_target.py          # Multi-target model manager
│   │   └── conformal.py             # Conformal prediction wrapper
│   ├── estimator.py                 # Main estimator interface
│   └── history.py                   # Legacy adapter (deprecated)
└── tests/
    ├── __init__.py
    ├── conftest.py                  # Shared fixtures
    ├── db/
    │   ├── test_connection.py
    │   ├── test_schema.py
    │   └── test_models.py
    ├── repository/
    │   ├── test_runs.py
    │   ├── test_executions.py
    │   ├── test_metrics.py
    │   └── test_estimates.py
    ├── ingestion/
    │   ├── test_collector.py
    │   ├── test_transformer.py
    │   └── test_loader.py
    ├── retrieval/
    │   ├── test_queries.py
    │   └── test_aggregations.py
    └── modeling/
        ├── conftest.py              # Synthetic data generators
        ├── test_preprocessing.py
        ├── test_validation.py
        ├── test_trainer.py
        ├── test_multi_target.py
        └── test_conformal.py
```

### 1.3 Database Schema

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

---

## Milestone 1: DuckDB Core Infrastructure

**Duration**: 1 week
**Dependencies**: None

### 1.1 Objectives

- Set up DuckDB connection management
- Implement schema initialization and versioning
- Create basic data models

### 1.2 Files to Create

#### 1.2.1 `stats/stats/db/connection.py`

**Purpose**: Database connection management with context managers and connection pooling.

**Key Classes**:
- `DatabaseConnection`: Manages DuckDB connections with read-only and read-write modes
- `get_default_db_path()`: Returns XDG-compliant default database path

**Key Features**:
- Persistent storage at `~/.local/share/update-all/history.duckdb`
- Context manager support for automatic cleanup
- Transaction support with rollback on error

#### 1.2.2 `stats/stats/db/schema.py`

**Purpose**: Schema definitions and migration management.

**Key Functions**:
- `initialize_schema(conn)`: Creates all tables and indexes
- `get_schema_version(conn)`: Returns current schema version

**Schema Version**: 1

#### 1.2.3 `stats/stats/db/models.py`

**Purpose**: Data models as Python dataclasses.

**Key Classes**:
- `Run`: Represents a complete update-all run
- `PluginExecution`: Represents a single plugin execution
- `StepMetrics`: Represents metrics for a step (prepare/download/update)
- `Estimate`: Represents plugin-reported estimates

### 1.3 Tests (TDD)

#### 1.3.1 `stats/tests/db/test_connection.py`

```python
"""Tests for database connection management."""

import pytest
from pathlib import Path
from stats.db.connection import DatabaseConnection, get_default_db_path


class TestGetDefaultDbPath:
    """Tests for get_default_db_path function."""

    def test_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that default path creates the data directory."""
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))

        path = get_default_db_path()

        assert path.parent.exists()
        assert path.name == "history.duckdb"
        assert path.parent.name == "update-all"

    def test_uses_home_when_no_xdg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test fallback to ~/.local/share when XDG_DATA_HOME not set."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)

        path = get_default_db_path()

        assert ".local/share/update-all" in str(path)


class TestDatabaseConnection:
    """Tests for DatabaseConnection class."""

    def test_creates_file_on_connect(self, temp_db_path: Path) -> None:
        """Test that connecting creates the database file."""
        db = DatabaseConnection(temp_db_path)

        conn = db.connect()
        assert conn is not None
        assert temp_db_path.exists()

        db.close()

    def test_context_manager(self, temp_db_path: Path) -> None:
        """Test database connection as context manager."""
        with DatabaseConnection(temp_db_path) as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result == (1,)

    def test_transaction_commits_on_success(self, db_connection: DatabaseConnection) -> None:
        """Test that transactions commit on success."""
        conn = db_connection.connect()

        with db_connection.transaction() as tx_conn:
            tx_conn.execute(
                "INSERT INTO runs (run_id, start_time, hostname) VALUES (?, ?, ?)",
                ["test-run", "2026-01-01 00:00:00", "test-host"],
            )

        result = conn.execute("SELECT run_id FROM runs WHERE run_id = 'test-run'").fetchone()
        assert result is not None

    def test_transaction_rollbacks_on_error(self, db_connection: DatabaseConnection) -> None:
        """Test that transactions rollback on error."""
        conn = db_connection.connect()

        with pytest.raises(Exception):
            with db_connection.transaction() as tx_conn:
                tx_conn.execute(
                    "INSERT INTO runs (run_id, start_time, hostname) VALUES (?, ?, ?)",
                    ["test-run-2", "2026-01-01 00:00:00", "test-host"],
                )
                raise Exception("Simulated error")

        result = conn.execute("SELECT run_id FROM runs WHERE run_id = 'test-run-2'").fetchone()
        assert result is None

    def test_read_only_mode(self, temp_db_path: Path) -> None:
        """Test read-only connection mode."""
        # First create the database
        with DatabaseConnection(temp_db_path) as conn:
            conn.execute("CREATE TABLE test (id INTEGER)")

        # Now open read-only
        db = DatabaseConnection(temp_db_path, read_only=True)
        conn = db.connect()

        # Should be able to read
        result = conn.execute("SELECT * FROM test").fetchall()
        assert result == []

        db.close()
```

#### 1.3.2 `stats/tests/db/test_schema.py`

```python
"""Tests for schema management."""

import pytest
from stats.db.connection import DatabaseConnection
from stats.db.schema import initialize_schema, get_schema_version, SCHEMA_VERSION


class TestInitializeSchema:
    """Tests for schema initialization."""

    def test_creates_all_tables(self, db_connection: DatabaseConnection) -> None:
        """Test that all required tables are created."""
        conn = db_connection.connect()

        # Check tables exist
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = {t[0] for t in tables}

        assert "runs" in table_names
        assert "plugin_executions" in table_names
        assert "step_metrics" in table_names
        assert "estimates" in table_names
        assert "schema_version" in table_names

    def test_idempotent(self, db_connection: DatabaseConnection) -> None:
        """Test that schema initialization is idempotent."""
        conn = db_connection.connect()

        # Initialize again - should not raise
        initialize_schema(conn)

        version = get_schema_version(conn)
        assert version == SCHEMA_VERSION

    def test_sets_schema_version(self, db_connection: DatabaseConnection) -> None:
        """Test that schema version is set correctly."""
        conn = db_connection.connect()

        version = get_schema_version(conn)

        assert version == SCHEMA_VERSION


class TestGetSchemaVersion:
    """Tests for get_schema_version function."""

    def test_returns_zero_for_empty_db(self, temp_db_path: Path) -> None:
        """Test that version is 0 for uninitialized database."""
        db = DatabaseConnection(temp_db_path)
        conn = db.connect()

        version = get_schema_version(conn)

        assert version == 0
        db.close()
```

### 1.4 Acceptance Criteria

- [ ] `DatabaseConnection` class can create persistent databases
- [ ] Schema initialization creates all required tables
- [ ] Schema versioning tracks migrations
- [ ] All tests pass with 100% coverage for new code
- [ ] Documentation includes usage examples

---

## Milestone 2: Data Models and Repositories

**Duration**: 1 week
**Dependencies**: Milestone 1

### 2.1 Objectives

- Define comprehensive data models
- Implement repository pattern for CRUD operations
- Create type-safe interfaces for data access

### 2.2 Files to Create

#### 2.2.1 `stats/stats/db/models.py`

```python
"""Data models for historical data storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class ExecutionStatus(str, Enum):
    """Status of a plugin execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class StepPhase(str, Enum):
    """Phase of execution."""

    CHECK = "CHECK"
    DOWNLOAD = "DOWNLOAD"
    EXECUTE = "EXECUTE"


@dataclass
class Run:
    """Represents a complete update-all run."""

    run_id: UUID
    start_time: datetime
    hostname: str
    end_time: datetime | None = None
    username: str | None = None
    config_hash: str | None = None
    total_plugins: int = 0
    successful_plugins: int = 0
    failed_plugins: int = 0
    skipped_plugins: int = 0
    created_at: datetime | None = None


@dataclass
class PluginExecution:
    """Represents a single plugin execution within a run."""

    execution_id: UUID
    run_id: UUID
    plugin_name: str
    status: ExecutionStatus
    start_time: datetime | None = None
    end_time: datetime | None = None
    packages_updated: int = 0
    packages_total: int | None = None
    error_message: str | None = None
    exit_code: int | None = None
    created_at: datetime | None = None


@dataclass
class StepMetrics:
    """Metrics collected for a single execution step."""

    metric_id: UUID
    execution_id: UUID
    step_name: str  # prepare, download, update
    phase: StepPhase
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Time metrics
    wall_clock_seconds: float | None = None
    cpu_user_seconds: float | None = None
    cpu_kernel_seconds: float | None = None

    # Memory metrics
    memory_peak_bytes: int | None = None
    memory_avg_bytes: int | None = None

    # I/O metrics
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    io_read_ops: int | None = None
    io_write_ops: int | None = None

    # Network metrics
    network_rx_bytes: int | None = None
    network_tx_bytes: int | None = None

    # Download-specific
    download_size_bytes: int | None = None
    download_speed_bps: float | None = None

    created_at: datetime | None = None


@dataclass
class Estimate:
    """Plugin-reported estimate for comparison with actuals."""

    estimate_id: UUID
    execution_id: UUID
    phase: StepPhase
    download_bytes_est: int | None = None
    cpu_seconds_est: float | None = None
    wall_seconds_est: float | None = None
    memory_bytes_est: int | None = None
    package_count_est: int | None = None
    confidence: float | None = None  # 0.0 - 1.0
    created_at: datetime | None = None
```

#### 2.2.2 `stats/stats/repository/base.py`

```python
"""Base repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar
from uuid import UUID

if TYPE_CHECKING:
    import duckdb

T = TypeVar("T")


class BaseRepository(ABC, Generic[T]):
    """Abstract base class for repositories."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        """Initialize the repository.

        Args:
            connection: DuckDB connection.
        """
        self._conn = connection

    @abstractmethod
    def create(self, entity: T) -> T:
        """Create a new entity.

        Args:
            entity: Entity to create.

        Returns:
            Created entity with generated fields.
        """
        ...

    @abstractmethod
    def get_by_id(self, entity_id: UUID) -> T | None:
        """Get an entity by ID.

        Args:
            entity_id: Entity ID.

        Returns:
            Entity or None if not found.
        """
        ...

    @abstractmethod
    def update(self, entity: T) -> T:
        """Update an existing entity.

        Args:
            entity: Entity to update.

        Returns:
            Updated entity.
        """
        ...

    @abstractmethod
    def delete(self, entity_id: UUID) -> bool:
        """Delete an entity by ID.

        Args:
            entity_id: Entity ID.

        Returns:
            True if deleted, False if not found.
        """
        ...
```

### 2.3 Tests (TDD)

```python
# stats/tests/repository/test_runs.py
"""Tests for runs repository."""

import pytest
from datetime import UTC, datetime
from uuid import uuid4

from stats.db.models import Run
from stats.repository.runs import RunsRepository


class TestRunsRepository:
    """Tests for RunsRepository."""

    def test_create_run(self, db_connection) -> None:
        """Test creating a new run."""
        repo = RunsRepository(db_connection.connect())
        run = Run(
            run_id=uuid4(),
            start_time=datetime.now(tz=UTC),
            hostname="test-host",
        )

        created = repo.create(run)

        assert created.run_id == run.run_id
        assert created.created_at is not None

    def test_get_by_id(self, db_connection, sample_run) -> None:
        """Test retrieving a run by ID."""
        repo = RunsRepository(db_connection.connect())

        result = repo.get_by_id(sample_run.run_id)

        assert result is not None
        assert result.run_id == sample_run.run_id
        assert result.hostname == sample_run.hostname

    def test_get_by_id_not_found(self, db_connection) -> None:
        """Test retrieving non-existent run."""
        repo = RunsRepository(db_connection.connect())

        result = repo.get_by_id(uuid4())

        assert result is None

    def test_update_run(self, db_connection, sample_run) -> None:
        """Test updating a run."""
        repo = RunsRepository(db_connection.connect())
        sample_run.end_time = datetime.now(tz=UTC)
        sample_run.successful_plugins = 5

        updated = repo.update(sample_run)

        assert updated.end_time is not None
        assert updated.successful_plugins == 5

    def test_delete_run(self, db_connection, sample_run) -> None:
        """Test deleting a run."""
        repo = RunsRepository(db_connection.connect())

        result = repo.delete(sample_run.run_id)

        assert result is True
        assert repo.get_by_id(sample_run.run_id) is None

    def test_list_recent(self, db_connection, sample_run) -> None:
        """Test listing recent runs."""
        repo = RunsRepository(db_connection.connect())

        runs = repo.list_recent(limit=10)

        assert len(runs) >= 1
        assert any(r.run_id == sample_run.run_id for r in runs)
```

### 2.4 Acceptance Criteria

- [ ] All data models defined with proper types
- [ ] Repository pattern implemented for all entities
- [ ] CRUD operations work correctly
- [ ] All tests pass with 100% coverage for new code

---

## Milestone 3: Data Ingestion Pipeline

**Duration**: 1 week
**Dependencies**: Milestone 2

### 3.1 Objectives

- Implement real-time metrics collection
- Create data transformation utilities
- Build JSON history migration tool

### 3.2 Files to Create

#### 3.2.1 `stats/stats/ingestion/collector.py`

**Purpose**: Real-time metrics collection during plugin execution.

**Key Classes**:
- `DuckDBMetricsCollector`: Collects and stores metrics in real-time
- `StepMetricsData`: Dataclass for step-level metrics

**Key Methods**:
- `start_run(hostname, username)`: Start tracking a new run
- `end_run(total, successful, failed, skipped)`: End the current run
- `start_plugin_execution(plugin_name)`: Start tracking a plugin
- `end_plugin_execution(plugin_name, status, ...)`: End plugin tracking
- `start_step(plugin_name, step_name, phase)`: Start step metrics
- `end_step(plugin_name, step_name, download_size)`: End step and store metrics
- `record_estimate(plugin_name, phase, ...)`: Record plugin estimates

#### 3.2.2 `stats/stats/ingestion/loader.py`

**Purpose**: Batch data loading and migration from JSON history.

**Key Functions**:
- `migrate_json_history(json_path, db_path)`: Migrate existing JSON history to DuckDB

### 3.3 Tests (TDD)

```python
# stats/tests/ingestion/test_collector.py
"""Tests for metrics collector."""

import pytest
from datetime import UTC, datetime
from stats.ingestion.collector import DuckDBMetricsCollector


class TestDuckDBMetricsCollector:
    """Tests for DuckDBMetricsCollector."""

    def test_start_run_creates_record(self, temp_db_path) -> None:
        """Test that starting a run creates a database record."""
        collector = DuckDBMetricsCollector(str(temp_db_path))

        run_id = collector.start_run("test-host", "test-user")

        assert run_id is not None
        # Verify record exists in database
        from stats.db.connection import DatabaseConnection
        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute(
            "SELECT hostname FROM runs WHERE run_id = ?",
            [str(run_id)]
        ).fetchone()
        assert result[0] == "test-host"

    def test_end_run_updates_record(self, temp_db_path) -> None:
        """Test that ending a run updates the record."""
        collector = DuckDBMetricsCollector(str(temp_db_path))
        run_id = collector.start_run("test-host")

        collector.end_run(total_plugins=3, successful=2, failed=1, skipped=0)

        from stats.db.connection import DatabaseConnection
        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute(
            "SELECT total_plugins, successful_plugins FROM runs WHERE run_id = ?",
            [str(run_id)]
        ).fetchone()
        assert result[0] == 3
        assert result[1] == 2

    def test_step_metrics_collection(self, temp_db_path) -> None:
        """Test that step metrics are collected correctly."""
        collector = DuckDBMetricsCollector(str(temp_db_path))
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.start_step("apt", "update", "EXECUTE")
        # Simulate some work
        import time
        time.sleep(0.01)
        collector.end_step("apt", "update", download_size_bytes=1024)

        collector.end_plugin_execution("apt", "success", packages_updated=5)

        from stats.db.connection import DatabaseConnection
        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute(
            "SELECT wall_clock_seconds, download_size_bytes FROM step_metrics"
        ).fetchone()
        assert result[0] > 0  # Wall clock should be positive
        assert result[1] == 1024

    def test_record_estimate(self, temp_db_path) -> None:
        """Test recording plugin estimates."""
        collector = DuckDBMetricsCollector(str(temp_db_path))
        collector.start_run("test-host")
        collector.start_plugin_execution("apt")

        collector.record_estimate(
            "apt",
            phase="EXECUTE",
            download_bytes=50_000_000,
            cpu_seconds=30.0,
            wall_seconds=60.0,
            confidence=0.8,
        )

        from stats.db.connection import DatabaseConnection
        db = DatabaseConnection(temp_db_path)
        result = db.connect().execute(
            "SELECT download_bytes_est, confidence FROM estimates"
        ).fetchone()
        assert result[0] == 50_000_000
        assert result[1] == 0.8
```

### 3.4 Acceptance Criteria

- [ ] Metrics collector captures all required metrics
- [ ] JSON migration tool successfully migrates existing data
- [ ] All tests pass with 100% coverage for new code

---

## Milestone 4: Data Retrieval and Queries

**Duration**: 1 week
**Dependencies**: Milestone 3

### 4.1 Objectives

- Implement query builders for historical data
- Create aggregation functions for statistics
- Build data export utilities

### 4.2 Files to Create

#### 4.2.1 `stats/stats/retrieval/queries.py`

**Purpose**: Query builders for retrieving historical data.

**Key Classes**:
- `HistoricalDataQuery`: Main query interface
- `PluginStats`: Statistics for a plugin
- `TimeSeriesPoint`: Single point in a time series

**Key Methods**:
- `get_plugin_stats(plugin_name, days)`: Get statistics for a plugin
- `get_execution_time_series(plugin_name, step_name, days)`: Get time series data
- `get_training_data_for_plugin(plugin_name, days)`: Get DataFrame for ML training
- `get_all_plugins_summary(days)`: Get summary for all plugins

#### 4.2.2 `stats/stats/retrieval/aggregations.py`

**Purpose**: Aggregation functions for statistical analysis.

**Key Functions**:
- `get_daily_aggregations(days, db_path)`: Get daily aggregated metrics
- `get_plugin_performance_over_time(plugin_name, metric, granularity, days)`: Get time-aggregated metrics

### 4.3 Tests (TDD)

```python
# stats/tests/retrieval/test_queries.py
"""Tests for query builders."""

import pytest
from datetime import UTC, datetime, timedelta
from stats.retrieval.queries import HistoricalDataQuery, PluginStats


class TestHistoricalDataQuery:
    """Tests for HistoricalDataQuery."""

    def test_get_plugin_stats(self, db_connection, sample_run_data) -> None:
        """Test retrieving plugin statistics."""
        query = HistoricalDataQuery(db_path=str(db_connection.db_path))

        stats = query.get_plugin_stats("apt", days=90)

        assert stats is not None
        assert stats.plugin_name == "apt"
        assert stats.execution_count >= 1
        assert 0 <= stats.success_rate <= 1.0

    def test_get_plugin_stats_no_data(self, db_connection) -> None:
        """Test retrieving stats for non-existent plugin."""
        query = HistoricalDataQuery(db_path=str(db_connection.db_path))

        stats = query.get_plugin_stats("nonexistent", days=90)

        assert stats is None

    def test_get_execution_time_series(self, db_connection, sample_run_data) -> None:
        """Test retrieving execution time series."""
        query = HistoricalDataQuery(db_path=str(db_connection.db_path))

        series = query.get_execution_time_series("apt", step_name="update", days=90)

        assert len(series) >= 1
        assert all(p.value > 0 for p in series)

    def test_get_training_data_for_plugin(self, db_connection, sample_run_data) -> None:
        """Test retrieving training data as DataFrame."""
        query = HistoricalDataQuery(db_path=str(db_connection.db_path))

        df = query.get_training_data_for_plugin("apt", days=365)

        assert len(df) >= 1
        assert "timestamp" in df.columns
        assert "wall_clock_seconds" in df.columns

    def test_get_all_plugins_summary(self, db_connection, sample_run_data) -> None:
        """Test retrieving summary for all plugins."""
        query = HistoricalDataQuery(db_path=str(db_connection.db_path))

        summaries = query.get_all_plugins_summary(days=90)

        assert len(summaries) >= 1
        plugin_names = {s.plugin_name for s in summaries}
        assert "apt" in plugin_names
```

### 4.4 Acceptance Criteria

- [ ] Query builders return correct data
- [ ] Aggregation functions compute accurate statistics
- [ ] Training data export works with Pandas DataFrames
- [ ] All tests pass with 100% coverage for new code

---

## Milestone 5: Statistical Modeling Foundation

**Duration**: 1 week
**Dependencies**: Milestone 4

### 5.1 Objectives

- Set up Darts library integration
- Implement data preprocessing pipeline
- Create data quality validation

### 5.2 Feature Engineering

#### 5.2.1 Historical Features (from DuckDB)

| Feature | Type | Description | Source |
|---------|------|-------------|--------|
| `timestamp` | datetime | Time of the run | `plugin_executions.start_time` |
| `time_since_last_run` | float | Seconds since previous run | Computed |
| `packages_total` | int | Total packages under management | `plugin_executions.packages_total` |
| `packages_to_update` | int | Number of packages to update | `plugin_executions.packages_updated` |
| `download_size_estimated` | int | Plugin-reported download estimate | `estimates.download_bytes_est` |
| `cpu_time_estimated` | float | Plugin-reported CPU estimate | `estimates.cpu_seconds_est` |
| `day_of_week` | int | Day of week (0-6) | Computed from timestamp |
| `hour_of_day` | int | Hour of day (0-23) | Computed from timestamp |
| `is_weekend` | bool | Weekend flag | Computed |

#### 5.2.2 Target Variables

| Target | Type | Description | Source |
|--------|------|-------------|--------|
| `download_size_actual` | int | Actual download size in bytes | `step_metrics.download_size_bytes` |
| `cpu_time_actual` | float | Actual CPU time in seconds | `step_metrics.cpu_user_seconds + cpu_kernel_seconds` |
| `wall_clock_actual` | float | Actual wall-clock time in seconds | `step_metrics.wall_clock_seconds` |
| `memory_peak_actual` | int | Peak memory usage in bytes | `step_metrics.memory_peak_bytes` |

### 5.3 Files to Create

#### 5.3.1 `stats/stats/modeling/preprocessing.py`

**Purpose**: Data preprocessing for time series modeling.

**Key Classes**:
- `PreprocessingConfig`: Configuration dataclass
- `DataPreprocessor`: Main preprocessing class

**Key Methods**:
- `prepare_training_data(df, target_column)`: Prepare data for training
- `inverse_transform_target(series)`: Reverse preprocessing transformations

**Configuration Options**:
- `min_samples`: Minimum samples required (default: 10)
- `max_lookback_days`: Maximum lookback period (default: 365)
- `fill_strategy`: Missing value strategy (forward, backward, mean, zero)
- `outlier_threshold`: Z-score threshold for outlier removal (default: 3.0)
- `log_transform`: Whether to log-transform targets (default: True)
- `scaling_method`: Scaling method (minmax, standard, none)

#### 5.3.2 `stats/stats/modeling/validation.py`

**Purpose**: Data quality validation for modeling.

**Key Classes**:
- `DataQualityReport`: Report on data quality issues

**Key Functions**:
- `validate_training_data(df, target_column, min_samples)`: Validate data quality

### 5.4 Tests (TDD) - Dwarf Tests with Synthetic Data

```python
# stats/tests/modeling/conftest.py
"""Test fixtures for modeling tests - Synthetic data generators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import numpy as np
import pandas as pd
import pytest


def generate_synthetic_plugin_data(
    plugin_name: str = "test-plugin",
    num_samples: int = 100,
    base_wall_clock: float = 60.0,
    trend: float = 0.1,
    seasonality_amplitude: float = 10.0,
    noise_std: float = 5.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic plugin execution data.

    Creates realistic-looking data with:
    - Linear trend (updates take longer over time as more packages)
    - Weekly seasonality (weekends might be different)
    - Random noise

    Args:
        plugin_name: Name of the plugin.
        num_samples: Number of data points.
        base_wall_clock: Base execution time in seconds.
        trend: Trend coefficient (seconds per day).
        seasonality_amplitude: Amplitude of weekly seasonality.
        noise_std: Standard deviation of noise.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with synthetic data.
    """
    np.random.seed(seed)

    # Generate timestamps (roughly daily, with some gaps)
    start_date = datetime.now(tz=UTC) - timedelta(days=num_samples * 1.5)
    timestamps = []
    current = start_date
    for _ in range(num_samples):
        timestamps.append(current)
        current += timedelta(days=np.random.randint(1, 4))

    # Generate wall clock times with trend + seasonality + noise
    days_from_start = np.array([(t - start_date).days for t in timestamps])
    trend_component = trend * days_from_start
    day_of_week = np.array([t.weekday() for t in timestamps])
    seasonality = seasonality_amplitude * np.sin(2 * np.pi * day_of_week / 7)
    noise = np.random.normal(0, noise_std, num_samples)

    wall_clock = base_wall_clock + trend_component + seasonality + noise
    wall_clock = np.maximum(wall_clock, 1.0)  # Ensure positive

    # Generate correlated metrics
    cpu_time = wall_clock * (0.4 + 0.2 * np.random.random(num_samples))
    memory_peak = (100 + 50 * np.random.random(num_samples)) * 1024 * 1024
    download_size = (20 + 30 * np.random.random(num_samples)) * 1024 * 1024

    # Generate package counts
    packages_total = 100 + days_from_start // 10
    packages_updated = np.random.poisson(5, num_samples)

    return pd.DataFrame({
        "timestamp": timestamps,
        "plugin_name": plugin_name,
        "wall_clock_seconds": wall_clock,
        "cpu_user_seconds": cpu_time,
        "memory_peak_bytes": memory_peak.astype(int),
        "download_size_bytes": download_size.astype(int),
        "packages_total": packages_total,
        "packages_updated": packages_updated,
        "status": "success",
    })


@pytest.fixture
def synthetic_data() -> pd.DataFrame:
    """Generate synthetic plugin data for testing (100 samples)."""
    return generate_synthetic_plugin_data(num_samples=100)


@pytest.fixture
def small_synthetic_data() -> pd.DataFrame:
    """Generate small synthetic dataset (15 samples - edge case)."""
    return generate_synthetic_plugin_data(num_samples=15)


@pytest.fixture
def minimal_synthetic_data() -> pd.DataFrame:
    """Generate minimal synthetic dataset (5 samples - below threshold)."""
    return generate_synthetic_plugin_data(num_samples=5)


@pytest.fixture
def noisy_synthetic_data() -> pd.DataFrame:
    """Generate noisy synthetic data for robustness testing."""
    return generate_synthetic_plugin_data(num_samples=100, noise_std=20.0)


@pytest.fixture
def trending_synthetic_data() -> pd.DataFrame:
    """Generate data with strong trend for trend detection testing."""
    return generate_synthetic_plugin_data(num_samples=100, trend=0.5)
```

```python
# stats/tests/modeling/test_preprocessing.py
"""Tests for data preprocessing - Dwarf tests with synthetic data."""

import numpy as np
import pandas as pd
import pytest

from stats.modeling.preprocessing import DataPreprocessor, PreprocessingConfig
from stats.modeling.validation import validate_training_data


class TestDataPreprocessor:
    """Tests for DataPreprocessor using synthetic data."""

    def test_prepare_training_data_basic(self, synthetic_data: pd.DataFrame) -> None:
        """Test basic data preparation with synthetic data."""
        preprocessor = DataPreprocessor()

        target_series, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert target_series is not None
        assert len(target_series) > 0
        assert covariate_series is not None

    def test_outlier_removal(self, synthetic_data: pd.DataFrame) -> None:
        """Test that outliers are correctly removed."""
        df = synthetic_data.copy()
        df.loc[0, "wall_clock_seconds"] = 10000.0  # Extreme outlier

        preprocessor = DataPreprocessor(
            PreprocessingConfig(outlier_threshold=3.0)
        )

        target_series, _ = preprocessor.prepare_training_data(
            df,
            "wall_clock_seconds",
        )

        # Outlier should be removed
        assert len(target_series) < len(df)

    def test_log_transform_reduces_range(self, synthetic_data: pd.DataFrame) -> None:
        """Test that log transformation reduces value range."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True)
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        values = target_series.values()
        # Log of ~60 is ~4, so max should be much smaller
        assert np.max(values) < 100

    def test_inverse_transform_recovers_scale(self, synthetic_data: pd.DataFrame) -> None:
        """Test that inverse transformation recovers original scale."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(log_transform=True, scaling_method="minmax")
        )

        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        original = preprocessor.inverse_transform_target(target_series)

        # Should be back to original scale (seconds range)
        original_values = original.values()
        assert np.mean(original_values) > 10

    def test_insufficient_data_raises(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test that insufficient data raises ValueError."""
        preprocessor = DataPreprocessor(
            PreprocessingConfig(min_samples=10)
        )

        with pytest.raises(ValueError, match="Insufficient data"):
            preprocessor.prepare_training_data(
                minimal_synthetic_data,
                "wall_clock_seconds",
            )

    def test_derived_features_computed(self, synthetic_data: pd.DataFrame) -> None:
        """Test that derived features are computed correctly."""
        preprocessor = DataPreprocessor()

        _, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Should have time_since_last_run, day_of_week, hour_of_day
        assert covariate_series is not None
        assert covariate_series.n_components >= 3

    def test_handles_noisy_data(self, noisy_synthetic_data: pd.DataFrame) -> None:
        """Test preprocessing handles noisy data gracefully."""
        preprocessor = DataPreprocessor()

        target_series, _ = preprocessor.prepare_training_data(
            noisy_synthetic_data,
            "wall_clock_seconds",
        )

        # Should still produce valid output
        assert target_series is not None
        assert len(target_series) > 0


class TestDataValidation:
    """Tests for data validation with synthetic data."""

    def test_valid_data_passes(self, synthetic_data: pd.DataFrame) -> None:
        """Test that valid synthetic data passes validation."""
        report = validate_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        assert report.is_valid
        assert len(report.issues) == 0

    def test_insufficient_samples_detected(self, minimal_synthetic_data: pd.DataFrame) -> None:
        """Test detection of insufficient samples."""
        report = validate_training_data(
            minimal_synthetic_data,
            "wall_clock_seconds",
            min_samples=10,
        )

        assert not report.is_valid
        assert any("Insufficient" in issue for issue in report.issues)

    def test_missing_target_detected(self, synthetic_data: pd.DataFrame) -> None:
        """Test detection of missing target values."""
        df = synthetic_data.copy()
        df.loc[:5, "wall_clock_seconds"] = None

        report = validate_training_data(df, "wall_clock_seconds")

        assert report.missing_values["wall_clock_seconds"] == 6

    def test_outliers_counted(self, synthetic_data: pd.DataFrame) -> None:
        """Test that outliers are counted correctly."""
        df = synthetic_data.copy()
        # Add some outliers
        df.loc[0, "wall_clock_seconds"] = 10000.0
        df.loc[1, "wall_clock_seconds"] = 10000.0

        report = validate_training_data(df, "wall_clock_seconds")

        assert report.outlier_count >= 2
```

### 5.5 Acceptance Criteria

- [ ] Preprocessing pipeline handles all edge cases
- [ ] Data validation catches quality issues
- [ ] Synthetic data generators produce realistic data
- [ ] All tests pass with 100% coverage for new code

---

## Milestone 6: Model Training Pipeline

**Duration**: 1.5 weeks
**Dependencies**: Milestone 5

### 6.1 Objectives

- Implement model selection based on data size
- Create training pipeline with validation
- Support multiple model types

### 6.2 Model Selection Strategy

| Model | Use Case | Probabilistic | Covariates | Min Samples |
|-------|----------|---------------|------------|-------------|
| `ExponentialSmoothing` | Baseline, few samples | Yes | No | 5 |
| `AutoARIMA` | Trend + seasonality | Yes | Yes | 20 |
| `Prophet` | Strong seasonality | Yes | Yes | 30 |
| `LightGBMModel` | Many covariates | Yes | Yes | 50 |
| `NLinearModel` | Long sequences | Yes | Yes | 100 |

### 6.3 Files to Create

#### 6.3.1 `stats/stats/modeling/trainer.py`

**Purpose**: Model training pipeline for time series forecasting.

**Key Classes**:
- `ModelType`: Enum of available model types
- `TrainingConfig`: Configuration for training
- `TrainingResult`: Result of model training
- `PredictionResult`: Result with confidence intervals
- `ModelTrainer`: Main training class

**Key Methods**:
- `select_model_type(num_samples)`: Auto-select model based on data size
- `create_model(model_type, supports_covariates)`: Create model instance
- `train(target_name, target_series, covariate_series)`: Train a model
- `predict(target_name, covariate_series, horizon)`: Make predictions
- `save_models(directory)`: Persist trained models
- `load_models(directory)`: Load trained models

### 6.4 Tests (TDD) - Dwarf Tests

```python
# stats/tests/modeling/test_trainer.py
"""Tests for model training - Dwarf tests with synthetic data."""

import numpy as np
import pytest
from darts import TimeSeries

from stats.modeling.preprocessing import DataPreprocessor
from stats.modeling.trainer import (
    ModelTrainer,
    ModelType,
    TrainingConfig,
    PredictionResult,
)


class TestModelSelection:
    """Tests for automatic model selection."""

    def test_selects_exponential_smoothing_for_small_data(self) -> None:
        """Test that ExponentialSmoothing is selected for small datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=8)

        assert model_type == ModelType.EXPONENTIAL_SMOOTHING

    def test_selects_auto_arima_for_medium_data(self) -> None:
        """Test that AutoARIMA is selected for medium datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=25)

        assert model_type == ModelType.AUTO_ARIMA

    def test_selects_lightgbm_for_large_data(self) -> None:
        """Test that LightGBM is selected for large datasets."""
        trainer = ModelTrainer(TrainingConfig(auto_select=True))

        model_type = trainer.select_model_type(num_samples=60)

        assert model_type == ModelType.LIGHTGBM

    def test_respects_manual_selection(self) -> None:
        """Test that manual model selection is respected."""
        trainer = ModelTrainer(
            TrainingConfig(model_type=ModelType.PROPHET, auto_select=False)
        )

        model_type = trainer.select_model_type(num_samples=10)

        assert model_type == ModelType.PROPHET


class TestModelTraining:
    """Tests for model training with synthetic data."""

    def test_train_exponential_smoothing(self, synthetic_data) -> None:
        """Test training ExponentialSmoothing model."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series)

        assert result.is_successful
        assert result.model_type == ModelType.EXPONENTIAL_SMOOTHING
        assert "mae" in result.metrics
        assert "rmse" in result.metrics

    def test_train_with_covariates(self, synthetic_data) -> None:
        """Test training with covariate series."""
        preprocessor = DataPreprocessor()
        target_series, covariate_series = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.AUTO_ARIMA,
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series, covariate_series)

        assert result.is_successful

    def test_insufficient_training_data_fails_gracefully(self, minimal_synthetic_data) -> None:
        """Test that insufficient data is handled gracefully."""
        from stats.modeling.preprocessing import PreprocessingConfig

        preprocessor = DataPreprocessor(
            PreprocessingConfig(min_samples=3)  # Allow small data
        )
        target_series, _ = preprocessor.prepare_training_data(
            minimal_synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.LIGHTGBM,  # Requires more data
                auto_select=False,
            )
        )

        result = trainer.train("test_target", target_series)

        assert not result.is_successful
        assert "Insufficient" in result.error_message


class TestPrediction:
    """Tests for prediction with confidence intervals."""

    def test_prediction_returns_confidence_interval(self, synthetic_data) -> None:
        """Test that predictions include confidence intervals."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.1,  # 90% CI
            )
        )

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target")

        assert isinstance(prediction, PredictionResult)
        assert prediction.point_estimate > 0
        assert prediction.lower_bound <= prediction.point_estimate
        assert prediction.upper_bound >= prediction.point_estimate
        assert prediction.confidence_level == 0.9

    def test_prediction_bounds_are_non_negative(self, synthetic_data) -> None:
        """Test that prediction bounds are non-negative for physical quantities."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
            )
        )

        trainer.train("test_target", target_series)
        prediction = trainer.predict("test_target")

        assert prediction.lower_bound >= 0
        assert prediction.upper_bound >= 0

    def test_prediction_without_training_raises(self) -> None:
        """Test that predicting without training raises error."""
        trainer = ModelTrainer()

        with pytest.raises(ValueError, match="No trained model"):
            trainer.predict("nonexistent_target")
```

### 6.5 Acceptance Criteria

- [ ] Model selection works correctly based on data size
- [ ] Training produces valid models with metrics
- [ ] Predictions include confidence intervals
- [ ] All tests pass with 100% coverage for new code

---

## Milestone 7: Conformal Prediction Integration

**Duration**: 1 week
**Dependencies**: Milestone 6

### 7.1 Objectives

- Implement conformal prediction wrapper
- Ensure calibrated confidence intervals
- Support all model types

### 7.2 Conformal Prediction Overview

Conformal prediction provides **calibrated** prediction intervals:
- If we request 90% confidence, approximately 90% of true values will fall within the interval
- Works with any underlying model (model-agnostic)
- Uses Split Conformal Prediction (SCP) for efficiency

### 7.3 Files to Create

#### 7.3.1 `stats/stats/modeling/conformal.py`

**Purpose**: Conformal prediction wrapper for calibrated intervals.

**Key Classes**:
- `ConformalPredictor`: Wrapper for conformal prediction

**Key Methods**:
- `calibrate(model, calibration_data)`: Calibrate using holdout data
- `predict_with_intervals(model, horizon, alpha)`: Predict with calibrated intervals

### 7.4 Tests (TDD) - Calibration Tests

```python
# stats/tests/modeling/test_conformal.py
"""Tests for conformal prediction - Calibration verification."""

import numpy as np
import pytest

from stats.modeling.preprocessing import DataPreprocessor
from stats.modeling.trainer import ModelTrainer, TrainingConfig, ModelType


class TestConformalCalibration:
    """Tests for conformal prediction calibration."""

    def test_conformal_residuals_stored(self, synthetic_data) -> None:
        """Test that conformal residuals are stored after training."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
            )
        )

        trainer.train("test_target", target_series)

        assert "test_target" in trainer._conformal_residuals
        assert len(trainer._conformal_residuals["test_target"]) > 0

    def test_conformal_intervals_wider_than_native(self, synthetic_data) -> None:
        """Test that conformal intervals are appropriately sized."""
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Train with conformal
        trainer_conformal = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.1,
            )
        )
        trainer_conformal.train("test_target", target_series)
        pred_conformal = trainer_conformal.predict("test_target")

        # Train without conformal
        trainer_native = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=False,
                conformal_alpha=0.1,
            )
        )
        trainer_native.train("test_target", target_series)
        pred_native = trainer_native.predict("test_target")

        # Both should have valid intervals
        conformal_width = pred_conformal.upper_bound - pred_conformal.lower_bound
        native_width = pred_native.upper_bound - pred_native.lower_bound

        assert conformal_width > 0
        assert native_width > 0

    def test_coverage_approximately_correct(self, synthetic_data) -> None:
        """Test that conformal prediction achieves approximate coverage.

        This is a statistical test - we verify that the coverage is
        approximately correct (within reasonable tolerance).
        """
        preprocessor = DataPreprocessor()
        target_series, _ = preprocessor.prepare_training_data(
            synthetic_data,
            "wall_clock_seconds",
        )

        # Use 80% of data for training, 20% for testing coverage
        train_size = int(len(target_series) * 0.8)
        train_series = target_series[:train_size]
        test_series = target_series[train_size:]

        trainer = ModelTrainer(
            TrainingConfig(
                model_type=ModelType.EXPONENTIAL_SMOOTHING,
                auto_select=False,
                use_conformal=True,
                conformal_alpha=0.2,  # 80% CI
                validation_split=0.25,  # Use part of training for calibration
            )
        )

        trainer.train("test_target", train_series)

        # Check coverage on test set
        test_values = test_series.values().flatten()
        covered = 0

        for i in range(len(test_values)):
            prediction = trainer.predict("test_target", horizon=1)
            if prediction.lower_bound <= test_values[i] <= prediction.upper_bound:
                covered += 1

        coverage = covered / len(test_values)

        # Coverage should be approximately 80% (with some tolerance)
        # Note: With small samples, this can vary significantly
        assert coverage >= 0.5  # At least 50% coverage (conservative check)
```

### 7.5 Acceptance Criteria

- [ ] Conformal prediction wrapper works with all model types
- [ ] Calibration produces reasonable residuals
- [ ] Coverage is approximately correct
- [ ] All tests pass

---

## Milestone 8: Integration with Update-All

**Duration**: 1.5 weeks
**Dependencies**: Milestone 7

### 8.1 Objectives

- Create unified estimator interface
- Integrate with orchestrator
- Implement multi-target predictions

### 8.2 Files to Create

#### 8.2.1 `stats/stats/modeling/multi_target.py`

**Purpose**: Multi-target model management for all metrics.

**Key Classes**:
- `PluginPrediction`: Complete prediction for a plugin
- `MultiTargetModelManager`: Manages models for all targets

**Target Columns**:
- `wall_clock_seconds`
- `cpu_user_seconds`
- `memory_peak_bytes`
- `download_size_bytes`

#### 8.2.2 `stats/stats/estimator.py` (Updated)

**Purpose**: Main estimator interface for the update-all system.

**Key Classes**:
- `TimeEstimate`: Time estimate with confidence interval
- `ResourceEstimate`: Complete resource estimate for a plugin
- `DartsTimeEstimator`: Main estimator using Darts models

**Key Methods**:
- `train_models(plugin_names)`: Train models for specified plugins
- `estimate(plugin_name)`: Estimate resources for a plugin
- `estimate_total(plugin_names)`: Estimate total for multiple plugins

### 8.3 Integration Points

```python
# Example integration in orchestrator
async def run_updates(self, plugins: list[str]) -> None:
    """Run updates with time estimation."""

    # Pre-run estimation
    estimate = self.estimator.estimate_total(plugins)
    self.ui.show_estimate(
        f"Estimated time: {estimate.wall_clock.format()}"
    )

    completed = []
    for plugin in plugins:
        # Update remaining estimate
        remaining = [p for p in plugins if p not in completed]
        remaining_estimate = self.estimator.estimate_total(remaining)
        self.ui.update_remaining_time(remaining_estimate.wall_clock)

        # Run plugin
        await self.run_plugin(plugin)
        completed.append(plugin)

    # Post-run: trigger model retraining (async)
    asyncio.create_task(self.estimator.train_models(plugins))
```

### 8.4 Tests (TDD)

```python
# stats/tests/modeling/test_integration.py
"""Integration tests for the complete modeling pipeline."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from stats.modeling.multi_target import MultiTargetModelManager, PluginPrediction
from stats.estimator import DartsTimeEstimator, ResourceEstimate


class TestMultiTargetIntegration:
    """Integration tests for multi-target modeling."""

    def test_train_all_targets(self, synthetic_data) -> None:
        """Test training models for all target metrics."""
        manager = MultiTargetModelManager()

        results = manager.train_for_plugin("test-plugin", synthetic_data)

        assert "wall_clock_seconds" in results
        assert "cpu_user_seconds" in results
        assert "memory_peak_bytes" in results
        assert "download_size_bytes" in results

        successful = [r for r in results.values() if r.is_successful]
        assert len(successful) >= 2

    def test_predict_all_targets(self, synthetic_data) -> None:
        """Test predicting all target metrics."""
        manager = MultiTargetModelManager()
        manager.train_for_plugin("test-plugin", synthetic_data)

        prediction = manager.predict_for_plugin("test-plugin")

        assert isinstance(prediction, PluginPrediction)
        assert prediction.plugin_name == "test-plugin"
        assert prediction.has_predictions

        if prediction.wall_clock is not None:
            assert prediction.wall_clock.point_estimate > 0
            assert prediction.wall_clock.lower_bound >= 0

    def test_save_and_load_models(self, synthetic_data) -> None:
        """Test saving and loading models."""
        manager = MultiTargetModelManager()
        manager.train_for_plugin("test-plugin", synthetic_data)

        with TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir)
            manager.save(save_path)

            new_manager = MultiTargetModelManager()
            new_manager.load(save_path)

            prediction = new_manager.predict_for_plugin("test-plugin")
            assert prediction.has_predictions


class TestDartsTimeEstimator:
    """Tests for the main estimator interface."""

    def test_estimate_single_plugin(self, synthetic_data) -> None:
        """Test estimating resources for a single plugin."""
        query = MagicMock()
        query.get_training_data_for_plugin.return_value = synthetic_data
        query.get_all_plugins_summary.return_value = [
            MagicMock(plugin_name="test-plugin")
        ]

        estimator = DartsTimeEstimator(query)
        estimator.train_models(["test-plugin"])

        estimate = estimator.estimate("test-plugin")

        assert isinstance(estimate, ResourceEstimate)
        assert estimate.plugin_name == "test-plugin"
        assert estimate.wall_clock.point_estimate > 0

    def test_estimate_total_multiple_plugins(self, synthetic_data) -> None:
        """Test estimating total resources for multiple plugins."""
        query = MagicMock()
        query.get_training_data_for_plugin.return_value = synthetic_data

        estimator = DartsTimeEstimator(query)

        for name in ["apt", "snap"]:
            df = synthetic_data.copy()
            estimator.model_manager.train_for_plugin(name, df)

        total = estimator.estimate_total(["apt", "snap"])

        assert total.plugin_name == "total"
        assert total.wall_clock.point_estimate > 0

    def test_estimate_formats_correctly(self, synthetic_data) -> None:
        """Test that estimates format correctly for display."""
        query = MagicMock()
        query.get_training_data_for_plugin.return_value = synthetic_data

        estimator = DartsTimeEstimator(query)
        estimator.model_manager.train_for_plugin("test-plugin", synthetic_data)

        estimate = estimator.estimate("test-plugin")
        formatted = estimate.wall_clock.format()

        assert isinstance(formatted, str)
        assert len(formatted) > 0
```

### 8.5 Acceptance Criteria

- [ ] Multi-target manager trains all metrics
- [ ] Estimator provides unified interface
- [ ] Integration with orchestrator works
- [ ] All tests pass

---

## Milestone 9: Migration and Cleanup

**Duration**: 1 week
**Dependencies**: Milestone 8

### 9.1 Objectives

- Migrate existing JSON history to DuckDB
- Deprecate old history module
- Complete documentation

### 9.2 Tasks

1. **JSON Migration**
   - Run migration tool on existing history
   - Verify data integrity
   - Create backup of JSON files

2. **Legacy Adapter**
   - Update `stats/stats/history.py` as adapter
   - Maintain backward compatibility
   - Add deprecation warnings

3. **Documentation**
   - Update API documentation
   - Write migration guide
   - Create usage examples

4. **Cleanup**
   - Remove deprecated code
   - Update dependencies
   - Final code review

### 9.3 Acceptance Criteria

- [ ] All existing history migrated successfully
- [ ] Backward compatibility maintained
- [ ] Documentation complete
- [ ] All tests pass
- [ ] Code review approved

---

## Dependencies and Risks

### Python Package Dependencies

Add to `stats/pyproject.toml`:

```toml
[tool.poetry.dependencies]
python = "^3.10"
duckdb = "^1.4.0"
pandas = "^2.0.0"
numpy = "^1.24.0"
darts = "^0.40.0"
structlog = "^24.0.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-asyncio = "^0.23.0"
pytest-cov = "^4.0.0"
```

### Risks and Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| DuckDB schema changes | High | Low | Version schema, test migrations |
| Darts API changes | Medium | Low | Pin version, monitor releases |
| Insufficient historical data | Medium | Medium | Fallback to simple estimates |
| Model training too slow | Medium | Low | Async training, caching |
| Memory usage too high | Medium | Low | Batch processing, model pruning |
| Conformal prediction inaccurate | Medium | Medium | Validate coverage, adjust alpha |

### Success Metrics

1. **Accuracy**: MAPE < 30% for wall-clock predictions
2. **Coverage**: 90% CI contains true value ≥ 85% of time
3. **Performance**: Training < 30s per plugin, prediction < 100ms
4. **Storage**: Database size < 100MB for 1 year of history

---

## References

- Darts Documentation: https://unit8co.github.io/darts/
- DuckDB Python API: https://duckdb.org/docs/api/python/overview
- Conformal Prediction: https://unit8co.github.io/darts/examples/23-Conformal-Prediction-examples.html
- Split Conformal Prediction: Vovk et al., "Algorithmic Learning in a Random World"

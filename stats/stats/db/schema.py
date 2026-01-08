"""Schema definitions and migration management for DuckDB.

This module handles database schema initialization and versioning.
All schema changes should be managed through migrations to ensure
data integrity across updates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

# Current schema version - increment when making schema changes
SCHEMA_VERSION = 1


def get_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Get the current schema version from the database.

    Args:
        conn: DuckDB connection.

    Returns:
        The current schema version, or 0 if the schema_version table
        doesn't exist (indicating an uninitialized database).
    """
    try:
        result = conn.execute(
            "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return result[0] if result else 0
    except Exception:
        # Table doesn't exist
        return 0


def initialize_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize the database schema.

    Creates all required tables and indexes if they don't exist.
    This function is idempotent - safe to call multiple times.

    Args:
        conn: DuckDB connection.
    """
    current_version = get_schema_version(conn)

    if current_version >= SCHEMA_VERSION:
        # Schema is already up to date
        return

    # Create schema_version table first
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description VARCHAR
        )
    """)

    # Create runs table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id VARCHAR PRIMARY KEY,
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            hostname VARCHAR NOT NULL,
            username VARCHAR,
            config_hash VARCHAR,
            total_plugins INTEGER DEFAULT 0,
            successful_plugins INTEGER DEFAULT 0,
            failed_plugins INTEGER DEFAULT 0,
            skipped_plugins INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create plugin_executions table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plugin_executions (
            execution_id VARCHAR PRIMARY KEY,
            run_id VARCHAR NOT NULL REFERENCES runs(run_id),
            plugin_name VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            packages_updated INTEGER DEFAULT 0,
            packages_total INTEGER,
            error_message VARCHAR,
            exit_code INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create step_metrics table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS step_metrics (
            metric_id VARCHAR PRIMARY KEY,
            execution_id VARCHAR NOT NULL REFERENCES plugin_executions(execution_id),
            step_name VARCHAR NOT NULL,
            phase VARCHAR NOT NULL,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create estimates table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS estimates (
            estimate_id VARCHAR PRIMARY KEY,
            execution_id VARCHAR NOT NULL REFERENCES plugin_executions(execution_id),
            phase VARCHAR NOT NULL,
            download_bytes_est BIGINT,
            cpu_seconds_est DOUBLE,
            wall_seconds_est DOUBLE,
            memory_bytes_est BIGINT,
            package_count_est INTEGER,
            confidence DOUBLE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create indexes for common queries
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_start_time
        ON runs(start_time)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugin_executions_run_id
        ON plugin_executions(run_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_plugin_executions_plugin_name
        ON plugin_executions(plugin_name)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_step_metrics_execution_id
        ON step_metrics(execution_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_estimates_execution_id
        ON estimates(execution_id)
    """)

    # Record the schema version
    if current_version == 0:
        conn.execute(
            """
            INSERT INTO schema_version (version, description)
            VALUES (?, ?)
            """,
            [SCHEMA_VERSION, "Initial schema creation"],
        )

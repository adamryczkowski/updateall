"""Tests for schema management."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from stats.db.connection import DatabaseConnection
from stats.db.schema import SCHEMA_VERSION, get_schema_version, initialize_schema


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

    def test_creates_indexes(self, db_connection: DatabaseConnection) -> None:
        """Test that indexes are created."""
        conn = db_connection.connect()

        # Query for indexes
        indexes = conn.execute("""
            SELECT index_name
            FROM duckdb_indexes()
            WHERE table_name IN ('runs', 'plugin_executions', 'step_metrics', 'estimates')
        """).fetchall()
        index_names = {idx[0] for idx in indexes}

        assert "idx_runs_start_time" in index_names
        assert "idx_plugin_executions_run_id" in index_names
        assert "idx_plugin_executions_plugin_name" in index_names
        assert "idx_step_metrics_execution_id" in index_names
        assert "idx_estimates_execution_id" in index_names


class TestGetSchemaVersion:
    """Tests for get_schema_version function."""

    def test_returns_zero_for_empty_db(self, temp_db_path: Path) -> None:
        """Test that version is 0 for uninitialized database."""
        # Create a raw connection without schema initialization
        conn = duckdb.connect(database=str(temp_db_path), read_only=False)

        version = get_schema_version(conn)

        assert version == 0
        conn.close()

    def test_returns_current_version_after_init(self, db_connection: DatabaseConnection) -> None:
        """Test that version matches SCHEMA_VERSION after initialization."""
        conn = db_connection.connect()

        version = get_schema_version(conn)

        assert version == SCHEMA_VERSION

    def test_handles_missing_table_gracefully(self, temp_db_path: Path) -> None:
        """Test that missing schema_version table returns 0."""
        conn = duckdb.connect(database=str(temp_db_path), read_only=False)

        # Create some other table but not schema_version
        conn.execute("CREATE TABLE other_table (id INTEGER)")

        version = get_schema_version(conn)

        assert version == 0
        conn.close()


class TestSchemaStructure:
    """Tests for the schema structure and constraints."""

    def test_runs_table_structure(self, db_connection: DatabaseConnection) -> None:
        """Test that runs table has correct columns."""
        conn = db_connection.connect()

        columns = conn.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'runs'
            ORDER BY ordinal_position
        """).fetchall()

        column_dict = {col[0]: (col[1], col[2]) for col in columns}

        assert "run_id" in column_dict
        assert "start_time" in column_dict
        assert "hostname" in column_dict
        assert "end_time" in column_dict
        assert "username" in column_dict
        assert "total_plugins" in column_dict

    def test_plugin_executions_table_structure(self, db_connection: DatabaseConnection) -> None:
        """Test that plugin_executions table has correct columns."""
        conn = db_connection.connect()

        columns = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'plugin_executions'
        """).fetchall()

        column_names = {col[0] for col in columns}

        assert "execution_id" in column_names
        assert "run_id" in column_names
        assert "plugin_name" in column_names
        assert "status" in column_names
        assert "packages_updated" in column_names

    def test_step_metrics_table_structure(self, db_connection: DatabaseConnection) -> None:
        """Test that step_metrics table has correct columns."""
        conn = db_connection.connect()

        columns = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'step_metrics'
        """).fetchall()

        column_names = {col[0] for col in columns}

        assert "metric_id" in column_names
        assert "execution_id" in column_names
        assert "step_name" in column_names
        assert "phase" in column_names
        assert "wall_clock_seconds" in column_names
        assert "cpu_user_seconds" in column_names
        assert "download_size_bytes" in column_names

    def test_estimates_table_structure(self, db_connection: DatabaseConnection) -> None:
        """Test that estimates table has correct columns."""
        conn = db_connection.connect()

        columns = conn.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'estimates'
        """).fetchall()

        column_names = {col[0] for col in columns}

        assert "estimate_id" in column_names
        assert "execution_id" in column_names
        assert "phase" in column_names
        assert "download_bytes_est" in column_names
        assert "confidence" in column_names

    def test_foreign_key_constraint_plugin_executions(
        self, db_connection: DatabaseConnection
    ) -> None:
        """Test that plugin_executions references runs."""
        conn = db_connection.connect()

        # Try to insert a plugin_execution with non-existent run_id
        # DuckDB enforces foreign keys
        with pytest.raises(duckdb.ConstraintException):
            conn.execute("""
                INSERT INTO plugin_executions
                (execution_id, run_id, plugin_name, status)
                VALUES ('exec-1', 'non-existent-run', 'apt', 'success')
            """)

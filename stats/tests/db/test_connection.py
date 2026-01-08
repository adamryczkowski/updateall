"""Tests for database connection management."""

from __future__ import annotations

from pathlib import Path

import pytest

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

    def test_uses_home_when_no_xdg(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test fallback to ~/.local/share when XDG_DATA_HOME not set."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        # Set HOME to tmp_path to avoid affecting real home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        path = get_default_db_path()

        assert ".local/share/update-all" in str(path)

    def test_respects_xdg_data_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that XDG_DATA_HOME is respected."""
        custom_data_dir = tmp_path / "custom_data"
        monkeypatch.setenv("XDG_DATA_HOME", str(custom_data_dir))

        path = get_default_db_path()

        assert path.parent == custom_data_dir / "update-all"


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

    def test_context_manager_closes_connection(self, temp_db_path: Path) -> None:
        """Test that context manager properly closes connection."""
        db = DatabaseConnection(temp_db_path)
        with db as conn:
            conn.execute("SELECT 1")

        # Connection should be closed
        assert db._connection is None

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

        with pytest.raises(Exception, match="Simulated error"):
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
        # First create the database with schema
        with DatabaseConnection(temp_db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
            conn.execute("INSERT INTO test VALUES (42)")

        # Now open read-only
        db = DatabaseConnection(temp_db_path, read_only=True)
        conn = db.connect()

        # Should be able to read
        result = conn.execute("SELECT * FROM test").fetchall()
        assert result == [(42,)]

        db.close()

    def test_connect_returns_same_connection(self, temp_db_path: Path) -> None:
        """Test that connect() returns the same connection on subsequent calls."""
        db = DatabaseConnection(temp_db_path)

        conn1 = db.connect()
        conn2 = db.connect()

        assert conn1 is conn2

        db.close()

    def test_close_allows_reconnect(self, temp_db_path: Path) -> None:
        """Test that close() allows reconnecting."""
        db = DatabaseConnection(temp_db_path)

        conn1 = db.connect()
        db.close()
        conn2 = db.connect()

        # Should be different connection objects
        assert conn1 is not conn2

        db.close()

    def test_close_is_idempotent(self, temp_db_path: Path) -> None:
        """Test that close() can be called multiple times safely."""
        db = DatabaseConnection(temp_db_path)
        db.connect()

        # Should not raise
        db.close()
        db.close()
        db.close()

    def test_transaction_without_connection_raises(self, temp_db_path: Path) -> None:
        """Test that transaction() raises if no connection exists."""
        db = DatabaseConnection(temp_db_path)

        with pytest.raises(RuntimeError, match="No connection established"):
            with db.transaction():
                pass

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        """Test that connect creates parent directories if needed."""
        nested_path = tmp_path / "deep" / "nested" / "path" / "test.duckdb"
        db = DatabaseConnection(nested_path)

        db.connect()

        assert nested_path.exists()
        db.close()

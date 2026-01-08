"""Database connection management for DuckDB.

This module provides connection management with context managers,
transaction support, and XDG-compliant default paths.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from collections.abc import Iterator


def get_default_db_path() -> Path:
    """Get the default database path following XDG Base Directory specification.

    Returns the path to the history database, creating the parent directory
    if it doesn't exist. The path follows XDG conventions:
    - Uses $XDG_DATA_HOME if set
    - Falls back to ~/.local/share otherwise

    Returns:
        Path to the default database file.
    """
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"

    data_dir = base_dir / "update-all"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir / "history.duckdb"


class DatabaseConnection:
    """Manages DuckDB database connections.

    This class provides connection management with support for:
    - Persistent file-based databases
    - Read-only and read-write modes
    - Context manager protocol
    - Transaction management with automatic rollback on error

    Example:
        >>> with DatabaseConnection(Path("/tmp/test.duckdb")) as conn:
        ...     conn.execute("SELECT 1").fetchone()
        (1,)

    Attributes:
        db_path: Path to the database file.
        read_only: Whether the connection is read-only.
    """

    def __init__(self, db_path: Path, *, read_only: bool = False) -> None:
        """Initialize the database connection manager.

        Args:
            db_path: Path to the database file. Will be created if it doesn't exist.
            read_only: If True, open the database in read-only mode.
                      Read-only mode allows multiple processes to access
                      the database simultaneously.
        """
        self.db_path = db_path
        self.read_only = read_only
        self._connection: duckdb.DuckDBPyConnection | None = None

    def connect(self) -> duckdb.DuckDBPyConnection:
        """Establish a connection to the database.

        Creates the database file if it doesn't exist (unless read_only=True).
        If a connection already exists, returns the existing connection.

        Returns:
            The DuckDB connection object.

        Raises:
            duckdb.IOException: If read_only=True and the database doesn't exist.
        """
        if self._connection is None:
            # Ensure parent directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            self._connection = duckdb.connect(
                database=str(self.db_path),
                read_only=self.read_only,
            )

            # Initialize schema for new databases (only if not read-only)
            if not self.read_only:
                from stats.db.schema import initialize_schema

                initialize_schema(self._connection)

        return self._connection

    def close(self) -> None:
        """Close the database connection.

        Safe to call multiple times. After closing, connect() can be
        called again to re-establish the connection.
        """
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        """Enter the context manager, returning the connection.

        Returns:
            The DuckDB connection object.
        """
        return self.connect()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Exit the context manager, closing the connection."""
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[duckdb.DuckDBPyConnection]:
        """Context manager for database transactions.

        Provides automatic commit on success and rollback on error.
        The connection must already be established before calling this method.

        Yields:
            The DuckDB connection object within a transaction.

        Raises:
            RuntimeError: If no connection has been established.

        Example:
            >>> db = DatabaseConnection(Path("/tmp/test.duckdb"))
            >>> db.connect()
            >>> with db.transaction() as conn:
            ...     conn.execute("INSERT INTO runs ...")
            ...     # Automatically commits on success
            >>> # Or rolls back on exception
        """
        if self._connection is None:
            raise RuntimeError("No connection established. Call connect() first.")

        conn = self._connection
        conn.execute("BEGIN TRANSACTION")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

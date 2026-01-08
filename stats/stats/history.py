"""History storage for update runs.

This module provides backward-compatible access to update run history.
The original JSON-based storage has been deprecated in favor of DuckDB.

.. deprecated:: 0.9.0
    The JSON-based :class:`HistoryStore` is deprecated. Use
    :class:`DuckDBHistoryStore` instead for new code. The old class
    will continue to work but will emit deprecation warnings.

Migration Guide
---------------
To migrate from JSON to DuckDB storage:

1. Use the migration function to import existing history::

    from stats.ingestion.loader import migrate_json_history
    result = migrate_json_history()
    print(f"Migrated {result.runs_migrated} runs")

2. Update your code to use DuckDBHistoryStore::

    # Old (deprecated):
    from stats.history import HistoryStore
    store = HistoryStore()

    # New (recommended):
    from stats.history import DuckDBHistoryStore
    store = DuckDBHistoryStore()

The API is compatible, so most code will work without changes.
"""

from __future__ import annotations

import json
import os
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from stats.db.connection import DatabaseConnection, get_default_db_path
from stats.db.models import ExecutionStatus, PluginExecution, Run
from stats.repository.executions import ExecutionsRepository
from stats.repository.runs import RunsRepository

if TYPE_CHECKING:
    from core.models import RunResult

logger = structlog.get_logger(__name__)


def get_data_dir() -> Path:
    """Get the data directory for storing history.

    Returns:
        Path to the data directory.
    """
    # Follow XDG Base Directory Specification
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"

    data_dir = base / "update-all"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class DuckDBHistoryStore:
    """Persistent storage for update run history using DuckDB.

    This is the recommended storage backend for update history.
    It provides better performance, querying capabilities, and
    integration with the statistical modeling pipeline.

    Example:
        >>> store = DuckDBHistoryStore()
        >>> store.save_run(run_result)
        >>> recent = store.get_recent_runs(limit=10)
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        """Initialize the DuckDB history store.

        Args:
            db_path: Optional path to database file. Uses default if not provided.
        """
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        self._db = DatabaseConnection(self.db_path)
        self._conn = self._db.connect()
        self._runs_repo = RunsRepository(self._conn)
        self._executions_repo = ExecutionsRepository(self._conn)

    def save_run(self, run_result: RunResult) -> None:
        """Save a run result to history.

        Args:
            run_result: The run result to save.
        """
        from uuid import uuid4

        # Create run record
        run_id = UUID(run_result.run_id) if run_result.run_id else uuid4()

        # Count plugin statistics
        successful = sum(1 for r in run_result.plugin_results if r.status.value == "success")
        failed = sum(1 for r in run_result.plugin_results if r.status.value == "failed")
        skipped = sum(1 for r in run_result.plugin_results if r.status.value == "skipped")

        run = Run(
            run_id=run_id,
            start_time=run_result.start_time or datetime.now(tz=UTC),
            end_time=run_result.end_time,
            hostname=os.uname().nodename,
            username=os.environ.get("USER"),
            total_plugins=len(run_result.plugin_results),
            successful_plugins=successful,
            failed_plugins=failed,
            skipped_plugins=skipped,
        )

        self._runs_repo.create(run)

        # Create plugin execution records
        for plugin_result in run_result.plugin_results:
            execution = PluginExecution(
                execution_id=uuid4(),
                run_id=run_id,
                plugin_name=plugin_result.plugin_name,
                status=ExecutionStatus(plugin_result.status.value),
                start_time=plugin_result.start_time,
                end_time=plugin_result.end_time,
                packages_updated=plugin_result.packages_updated or 0,
                error_message=plugin_result.error_message,
            )
            self._executions_repo.create(execution)

        logger.info("run_saved", run_id=str(run_id))

    def get_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run records, most recent first.
        """
        runs = self._runs_repo.list_recent(limit=limit)
        return [self._run_to_dict(run) for run in runs]

    def get_runs_by_plugin(self, plugin_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get runs that include a specific plugin.

        Args:
            plugin_name: Name of the plugin to filter by.
            limit: Maximum number of runs to return.

        Returns:
            List of run records containing the plugin.
        """
        # Query runs that have executions for this plugin
        query = """
            SELECT DISTINCT r.run_id
            FROM runs r
            JOIN plugin_executions e ON r.run_id = e.run_id
            WHERE e.plugin_name = ?
            ORDER BY r.start_time DESC
            LIMIT ?
        """
        result = self._conn.execute(query, [plugin_name, limit]).fetchall()
        run_ids = [row[0] for row in result]

        runs = []
        for run_id in run_ids:
            run = self._runs_repo.get_by_id(UUID(run_id))
            if run:
                runs.append(self._run_to_dict(run))

        return runs

    def get_runs_in_range(
        self,
        start: datetime,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get runs within a date range.

        Args:
            start: Start of the date range.
            end: End of the date range. Defaults to now.

        Returns:
            List of run records in the range.
        """
        if end is None:
            end = datetime.now(tz=UTC)

        runs = self._runs_repo.list_in_range(start, end)
        return [self._run_to_dict(run) for run in runs]

    def clear_history(self) -> None:
        """Clear all history."""
        self._conn.execute("DELETE FROM step_metrics")
        self._conn.execute("DELETE FROM estimates")
        self._conn.execute("DELETE FROM plugin_executions")
        self._conn.execute("DELETE FROM runs")
        logger.info("history_cleared")

    def get_total_runs(self) -> int:
        """Get the total number of runs in history.

        Returns:
            Total number of runs.
        """
        result = self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()
        return result[0] if result else 0

    def _run_to_dict(self, run: Run) -> dict[str, Any]:
        """Convert a Run object to a dictionary.

        Args:
            run: Run object to convert.

        Returns:
            Dictionary representation of the run.
        """
        executions = self._executions_repo.list_by_run_id(run.run_id)

        return {
            "id": str(run.run_id),
            "start_time": run.start_time.isoformat() if run.start_time else None,
            "end_time": run.end_time.isoformat() if run.end_time else None,
            "hostname": run.hostname,
            "username": run.username,
            "plugins": [
                {
                    "name": e.plugin_name,
                    "status": e.status.value,
                    "packages_updated": e.packages_updated,
                    "error_message": e.error_message,
                    "start_time": e.start_time.isoformat() if e.start_time else None,
                    "end_time": e.end_time.isoformat() if e.end_time else None,
                }
                for e in executions
            ],
        }

    def close(self) -> None:
        """Close the database connection."""
        self._db.close()


class HistoryStore:
    """Persistent storage for update run history.

    .. deprecated:: 0.9.0
        This class uses JSON file storage which is deprecated.
        Use :class:`DuckDBHistoryStore` instead for new code.
        This class now delegates to DuckDB storage while maintaining
        backward compatibility with the JSON file format.

    Stores history in a JSON file, with each run as a separate entry.
    """

    def __init__(self, history_file: Path | None = None) -> None:
        """Initialize the history store.

        Args:
            history_file: Optional path to history file. Uses default if not provided.

        .. deprecated:: 0.9.0
            JSON file storage is deprecated. Consider using DuckDBHistoryStore.
        """
        warnings.warn(
            "HistoryStore with JSON storage is deprecated. "
            "Use DuckDBHistoryStore instead. "
            "See stats.history module docstring for migration guide.",
            DeprecationWarning,
            stacklevel=2,
        )

        self.history_file = history_file or get_data_dir() / "history.json"
        self._ensure_file_exists()

        # Also initialize DuckDB store for dual-write
        self._duckdb_store = DuckDBHistoryStore()

    def _ensure_file_exists(self) -> None:
        """Ensure the history file exists."""
        if not self.history_file.exists():
            self.history_file.write_text("[]")

    def _load_history(self) -> list[dict[str, Any]]:
        """Load history from file.

        Returns:
            List of run records.
        """
        try:
            content = self.history_file.read_text()
            return json.loads(content)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("failed_to_load_history", error=str(e))
            return []

    def _save_history(self, history: list[dict[str, Any]]) -> None:
        """Save history to file.

        Args:
            history: List of run records.
        """
        try:
            content = json.dumps(history, indent=2, default=str)
            self.history_file.write_text(content)
        except OSError as e:
            logger.error("failed_to_save_history", error=str(e))

    def save_run(self, run_result: RunResult) -> None:
        """Save a run result to history.

        Writes to both JSON file (for backward compatibility) and
        DuckDB (for new functionality).

        Args:
            run_result: The run result to save.
        """
        # Save to JSON (legacy)
        history = self._load_history()

        record = {
            "id": run_result.run_id,
            "start_time": run_result.start_time.isoformat() if run_result.start_time else None,
            "end_time": run_result.end_time.isoformat() if run_result.end_time else None,
            "plugins": [
                {
                    "name": r.plugin_name,
                    "status": r.status.value,
                    "packages_updated": r.packages_updated,
                    "error_message": r.error_message,
                    "start_time": r.start_time.isoformat() if r.start_time else None,
                    "end_time": r.end_time.isoformat() if r.end_time else None,
                }
                for r in run_result.plugin_results
            ],
        }

        history.append(record)
        self._save_history(history)

        # Also save to DuckDB
        self._duckdb_store.save_run(run_result)

        logger.info("run_saved", run_id=run_result.run_id)

    def get_recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent runs.

        Returns data from DuckDB if available, falls back to JSON.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run records, most recent first.
        """
        # Try DuckDB first
        try:
            duckdb_runs = self._duckdb_store.get_recent_runs(limit)
            if duckdb_runs:
                return duckdb_runs
        except Exception as e:
            logger.warning("duckdb_query_failed", error=str(e))

        # Fall back to JSON
        history = self._load_history()
        # Sort by start_time descending
        history.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return history[:limit]

    def get_runs_by_plugin(self, plugin_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get runs that include a specific plugin.

        Args:
            plugin_name: Name of the plugin to filter by.
            limit: Maximum number of runs to return.

        Returns:
            List of run records containing the plugin.
        """
        # Try DuckDB first
        try:
            duckdb_runs = self._duckdb_store.get_runs_by_plugin(plugin_name, limit)
            if duckdb_runs:
                return duckdb_runs
        except Exception as e:
            logger.warning("duckdb_query_failed", error=str(e))

        # Fall back to JSON
        history = self._load_history()
        filtered = [
            run
            for run in history
            if any(p.get("name") == plugin_name for p in run.get("plugins", []))
        ]
        filtered.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return filtered[:limit]

    def get_runs_in_range(
        self,
        start: datetime,
        end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Get runs within a date range.

        Args:
            start: Start of the date range.
            end: End of the date range. Defaults to now.

        Returns:
            List of run records in the range.
        """
        if end is None:
            end = datetime.now(tz=UTC)

        # Try DuckDB first
        try:
            duckdb_runs = self._duckdb_store.get_runs_in_range(start, end)
            if duckdb_runs:
                return duckdb_runs
        except Exception as e:
            logger.warning("duckdb_query_failed", error=str(e))

        # Fall back to JSON
        history = self._load_history()
        filtered = []

        for run in history:
            run_time_str = run.get("start_time")
            if run_time_str:
                try:
                    run_time = datetime.fromisoformat(run_time_str)
                    if start <= run_time <= end:
                        filtered.append(run)
                except ValueError:
                    continue

        filtered.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return filtered

    def clear_history(self) -> None:
        """Clear all history from both JSON and DuckDB."""
        self._save_history([])
        self._duckdb_store.clear_history()
        logger.info("history_cleared")

    def get_total_runs(self) -> int:
        """Get the total number of runs in history.

        Returns:
            Total number of runs.
        """
        # Try DuckDB first
        try:
            count = self._duckdb_store.get_total_runs()
            if count > 0:
                return count
        except Exception as e:
            logger.warning("duckdb_query_failed", error=str(e))

        # Fall back to JSON
        return len(self._load_history())


# Convenience function for migration
def migrate_to_duckdb(
    json_path: Path | str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, int | list[str]]:
    """Migrate JSON history to DuckDB.

    This is a convenience wrapper around the migration function
    in the ingestion module.

    Args:
        json_path: Path to JSON history file. Uses default if not provided.
        db_path: Path to DuckDB database. Uses default if not provided.

    Returns:
        Dictionary with migration statistics:
        - runs_migrated: Number of runs migrated
        - runs_failed: Number of runs that failed to migrate
        - executions_migrated: Number of plugin executions migrated
        - errors: List of error messages

    Example:
        >>> result = migrate_to_duckdb()
        >>> print(f"Migrated {result['runs_migrated']} runs")
    """
    from stats.ingestion.loader import migrate_json_history

    result = migrate_json_history(json_path, db_path)

    return {
        "runs_migrated": result.runs_migrated,
        "runs_failed": result.runs_failed,
        "executions_migrated": result.executions_migrated,
        "errors": result.errors,
    }

"""Batch data loading and migration from JSON history.

This module provides utilities for migrating existing JSON history
files to the DuckDB database format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

from stats.db.connection import DatabaseConnection, get_default_db_path
from stats.db.models import ExecutionStatus, PluginExecution, Run
from stats.repository.executions import ExecutionsRepository
from stats.repository.runs import RunsRepository

logger = structlog.get_logger(__name__)


@dataclass
class MigrationResult:
    """Result of a JSON history migration.

    Attributes:
        runs_migrated: Number of runs successfully migrated.
        runs_failed: Number of runs that failed to migrate.
        executions_migrated: Total number of plugin executions migrated.
        errors: List of error messages for failed migrations.
    """

    runs_migrated: int = 0
    runs_failed: int = 0
    executions_migrated: int = 0
    errors: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Initialize errors list if not provided."""
        if self.errors is None:
            self.errors = []


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO format datetime string.

    Args:
        value: ISO format datetime string or None.

    Returns:
        Parsed datetime or None.
    """
    if value is None:
        return None
    try:
        # Handle both timezone-aware and naive datetimes
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _parse_status(status_str: str | None) -> ExecutionStatus:
    """Parse a status string to ExecutionStatus enum.

    Args:
        status_str: Status string from JSON.

    Returns:
        ExecutionStatus enum value.
    """
    if status_str is None:
        return ExecutionStatus.PENDING

    # Map common status strings to enum values
    status_map = {
        "success": ExecutionStatus.SUCCESS,
        "succeeded": ExecutionStatus.SUCCESS,
        "completed": ExecutionStatus.SUCCESS,
        "failed": ExecutionStatus.FAILED,
        "error": ExecutionStatus.FAILED,
        "skipped": ExecutionStatus.SKIPPED,
        "timeout": ExecutionStatus.TIMEOUT,
        "running": ExecutionStatus.RUNNING,
        "pending": ExecutionStatus.PENDING,
    }

    return status_map.get(status_str.lower(), ExecutionStatus.PENDING)


def _migrate_single_run(
    run_data: dict[str, Any],
    runs_repo: RunsRepository,
    executions_repo: ExecutionsRepository,
    hostname: str,
) -> int:
    """Migrate a single run from JSON data.

    Args:
        run_data: Dictionary containing run data from JSON.
        runs_repo: Repository for run records.
        executions_repo: Repository for execution records.
        hostname: Default hostname to use if not in data.

    Returns:
        Number of executions migrated for this run.

    Raises:
        ValueError: If required data is missing or invalid.
    """
    # Parse run ID - generate new one if not present or invalid
    run_id_str = run_data.get("id")
    if run_id_str:
        try:
            run_id = UUID(run_id_str)
        except ValueError:
            run_id = uuid4()
    else:
        run_id = uuid4()

    # Parse timestamps
    start_time = _parse_datetime(run_data.get("start_time"))
    end_time = _parse_datetime(run_data.get("end_time"))

    if start_time is None:
        # Use a default time if not available
        start_time = datetime.now(tz=UTC)

    # Create run record
    run = Run(
        run_id=run_id,
        start_time=start_time,
        end_time=end_time,
        hostname=run_data.get("hostname", hostname),
        username=run_data.get("username"),
        config_hash=run_data.get("config_hash"),
    )

    # Count plugin statistics
    plugins = run_data.get("plugins", [])
    run.total_plugins = len(plugins)
    run.successful_plugins = sum(
        1 for p in plugins if _parse_status(p.get("status")) == ExecutionStatus.SUCCESS
    )
    run.failed_plugins = sum(
        1 for p in plugins if _parse_status(p.get("status")) == ExecutionStatus.FAILED
    )
    run.skipped_plugins = sum(
        1 for p in plugins if _parse_status(p.get("status")) == ExecutionStatus.SKIPPED
    )

    runs_repo.create(run)

    # Migrate plugin executions
    executions_migrated = 0
    for plugin_data in plugins:
        plugin_name = plugin_data.get("name")
        if not plugin_name:
            continue

        execution = PluginExecution(
            execution_id=uuid4(),
            run_id=run_id,
            plugin_name=plugin_name,
            status=_parse_status(plugin_data.get("status")),
            start_time=_parse_datetime(plugin_data.get("start_time")),
            end_time=_parse_datetime(plugin_data.get("end_time")),
            packages_updated=plugin_data.get("packages_updated", 0) or 0,
            packages_total=plugin_data.get("packages_total"),
            error_message=plugin_data.get("error_message"),
            exit_code=plugin_data.get("exit_code"),
        )

        executions_repo.create(execution)
        executions_migrated += 1

    return executions_migrated


def migrate_json_history(
    json_path: str | Path | None = None,
    db_path: str | Path | None = None,
    hostname: str | None = None,
) -> MigrationResult:
    """Migrate existing JSON history to DuckDB.

    Reads the JSON history file and imports all runs and plugin
    executions into the DuckDB database.

    Args:
        json_path: Path to the JSON history file.
                  Defaults to ~/.local/share/update-all/history.json
        db_path: Path to the DuckDB database file.
                Defaults to the standard XDG path.
        hostname: Default hostname for runs without one.
                 Defaults to "migrated".

    Returns:
        MigrationResult with statistics about the migration.

    Example:
        >>> result = migrate_json_history()
        >>> print(f"Migrated {result.runs_migrated} runs")
    """
    result = MigrationResult()

    # Determine paths
    json_path_resolved: Path
    if json_path is None:
        from stats.history import get_data_dir

        json_path_resolved = get_data_dir() / "history.json"
    else:
        json_path_resolved = Path(json_path)

    db_path_resolved: Path = get_default_db_path() if db_path is None else Path(db_path)

    if hostname is None:
        hostname = "migrated"

    # Check if JSON file exists
    if not json_path_resolved.exists():
        logger.info("json_history_not_found", path=str(json_path_resolved))
        return result

    # Load JSON history
    try:
        content = json_path_resolved.read_text()
        history = json.loads(content)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("failed_to_load_json_history", error=str(e))
        result.errors.append(f"Failed to load JSON history: {e}")
        return result

    if not isinstance(history, list):
        logger.error("invalid_json_history_format")
        result.errors.append("JSON history is not a list")
        return result

    # Connect to database
    db = DatabaseConnection(db_path_resolved)
    conn = db.connect()

    runs_repo = RunsRepository(conn)
    executions_repo = ExecutionsRepository(conn)

    # Migrate each run
    for i, run_data in enumerate(history):
        try:
            executions = _migrate_single_run(
                run_data,
                runs_repo,
                executions_repo,
                hostname,
            )
            result.runs_migrated += 1
            result.executions_migrated += executions
        except Exception as e:
            result.runs_failed += 1
            error_msg = f"Failed to migrate run {i}: {e}"
            result.errors.append(error_msg)
            logger.warning("run_migration_failed", index=i, error=str(e))

    db.close()

    logger.info(
        "migration_completed",
        runs_migrated=result.runs_migrated,
        runs_failed=result.runs_failed,
        executions_migrated=result.executions_migrated,
    )

    return result


def load_runs_from_json(
    json_data: list[dict[str, Any]],
    db_path: str | Path | None = None,
    hostname: str = "imported",
) -> MigrationResult:
    """Load runs from JSON data directly.

    This function is useful for importing data from sources other
    than the standard history file.

    Args:
        json_data: List of run dictionaries.
        db_path: Path to the DuckDB database file.
        hostname: Default hostname for runs without one.

    Returns:
        MigrationResult with statistics about the import.
    """
    result = MigrationResult()

    db_path_resolved: Path = get_default_db_path() if db_path is None else Path(db_path)

    # Connect to database
    db = DatabaseConnection(db_path_resolved)
    conn = db.connect()

    runs_repo = RunsRepository(conn)
    executions_repo = ExecutionsRepository(conn)

    # Import each run
    for i, run_data in enumerate(json_data):
        try:
            executions = _migrate_single_run(
                run_data,
                runs_repo,
                executions_repo,
                hostname,
            )
            result.runs_migrated += 1
            result.executions_migrated += executions
        except Exception as e:
            result.runs_failed += 1
            error_msg = f"Failed to import run {i}: {e}"
            result.errors.append(error_msg)
            logger.warning("run_import_failed", index=i, error=str(e))

    db.close()

    return result


def export_to_json(
    db_path: str | Path | None = None,
    output_path: str | Path | None = None,
    limit: int | None = None,
) -> Path:
    """Export runs from DuckDB to JSON format.

    This function exports data from DuckDB back to JSON format,
    useful for backup or interoperability.

    Args:
        db_path: Path to the DuckDB database file.
        output_path: Path for the output JSON file.
                    Defaults to history_export.json in the data directory.
        limit: Maximum number of runs to export. None for all.

    Returns:
        Path to the exported JSON file.
    """
    db_path_resolved: Path = get_default_db_path() if db_path is None else Path(db_path)

    output_path_resolved: Path
    if output_path is None:
        from stats.history import get_data_dir

        output_path_resolved = get_data_dir() / "history_export.json"
    else:
        output_path_resolved = Path(output_path)

    # Connect to database
    db = DatabaseConnection(db_path_resolved, read_only=True)
    conn = db.connect()

    runs_repo = RunsRepository(conn)
    executions_repo = ExecutionsRepository(conn)

    # Get runs
    runs = runs_repo.list_recent(limit=limit) if limit else runs_repo.list_recent(limit=100000)

    # Build JSON structure
    history = []
    for run in runs:
        executions = executions_repo.list_by_run_id(run.run_id)

        run_data = {
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
        history.append(run_data)

    db.close()

    # Write JSON file
    content = json.dumps(history, indent=2, default=str)
    output_path_resolved.write_text(content)

    logger.info("export_completed", path=str(output_path_resolved), runs=len(history))

    return output_path_resolved

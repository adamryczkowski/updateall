"""History storage for update runs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

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


class HistoryStore:
    """Persistent storage for update run history.

    Stores history in a JSON file, with each run as a separate entry.
    """

    def __init__(self, history_file: Path | None = None) -> None:
        """Initialize the history store.

        Args:
            history_file: Optional path to history file. Uses default if not provided.
        """
        self.history_file = history_file or get_data_dir() / "history.json"
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Ensure the history file exists."""
        if not self.history_file.exists():
            self.history_file.write_text("[]")

    def _load_history(self) -> list[dict]:
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

    def _save_history(self, history: list[dict]) -> None:
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

        Args:
            run_result: The run result to save.
        """
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
        logger.info("run_saved", run_id=run_result.run_id)

    def get_recent_runs(self, limit: int = 10) -> list[dict]:
        """Get the most recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of run records, most recent first.
        """
        history = self._load_history()
        # Sort by start_time descending
        history.sort(key=lambda x: x.get("start_time", ""), reverse=True)
        return history[:limit]

    def get_runs_by_plugin(self, plugin_name: str, limit: int = 10) -> list[dict]:
        """Get runs that include a specific plugin.

        Args:
            plugin_name: Name of the plugin to filter by.
            limit: Maximum number of runs to return.

        Returns:
            List of run records containing the plugin.
        """
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
    ) -> list[dict]:
        """Get runs within a date range.

        Args:
            start: Start of the date range.
            end: End of the date range. Defaults to now.

        Returns:
            List of run records in the range.
        """
        if end is None:
            end = datetime.now(tz=UTC)

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
        """Clear all history."""
        self._save_history([])
        logger.info("history_cleared")

    def get_total_runs(self) -> int:
        """Get the total number of runs in history.

        Returns:
            Total number of runs.
        """
        return len(self._load_history())

"""Tests for history storage module.

Tests both the new DuckDBHistoryStore and the deprecated HistoryStore.
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from stats.history import DuckDBHistoryStore, HistoryStore, migrate_to_duckdb


class MockPluginResult:
    """Mock plugin result for testing."""

    def __init__(
        self,
        plugin_name: str,
        status: str = "success",
        packages_updated: int = 0,
        error_message: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> None:
        self.plugin_name = plugin_name
        self.status = MagicMock(value=status)
        self.packages_updated = packages_updated
        self.error_message = error_message
        self.start_time = start_time or datetime.now(tz=UTC)
        self.end_time = end_time or datetime.now(tz=UTC)


class MockRunResult:
    """Mock run result for testing."""

    def __init__(
        self,
        run_id: str | None = None,
        plugin_results: list[MockPluginResult] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> None:
        self.run_id = run_id or str(uuid4())
        self.plugin_results = plugin_results or []
        self.start_time = start_time or datetime.now(tz=UTC)
        self.end_time = end_time or datetime.now(tz=UTC)


class TestDuckDBHistoryStore:
    """Tests for DuckDBHistoryStore."""

    def test_init_creates_database(self, tmp_path: Path) -> None:
        """Test that initialization creates the database."""
        db_path = tmp_path / "test.duckdb"

        store = DuckDBHistoryStore(db_path)

        assert db_path.exists()
        store.close()

    def test_save_run(self, tmp_path: Path) -> None:
        """Test saving a run result."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        run_result = MockRunResult(
            plugin_results=[
                MockPluginResult("apt", "success", packages_updated=5),
                MockPluginResult("snap", "failed", error_message="Error"),
            ]
        )

        store.save_run(run_result)  # type: ignore[arg-type]

        runs = store.get_recent_runs(limit=10)
        assert len(runs) == 1
        assert len(runs[0]["plugins"]) == 2

        store.close()

    def test_get_recent_runs_empty(self, tmp_path: Path) -> None:
        """Test getting recent runs from empty database."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        runs = store.get_recent_runs()

        assert runs == []
        store.close()

    def test_get_recent_runs_sorted(self, tmp_path: Path) -> None:
        """Test that recent runs are sorted by time."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        now = datetime.now(tz=UTC)

        # Save runs in non-chronological order
        for delta in [2, 0, 1]:
            run_result = MockRunResult(
                start_time=now - timedelta(days=delta),
                plugin_results=[MockPluginResult("apt")],
            )
            store.save_run(run_result)  # type: ignore[arg-type]

        runs = store.get_recent_runs(limit=3)

        # Should be sorted most recent first
        assert len(runs) == 3
        # Verify ordering by checking start times are in descending order
        start_times = [run["start_time"] for run in runs]
        assert start_times == sorted(start_times, reverse=True)
        store.close()

    def test_get_runs_by_plugin(self, tmp_path: Path) -> None:
        """Test filtering runs by plugin."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        # Save runs with different plugins
        store.save_run(
            MockRunResult(plugin_results=[MockPluginResult("apt"), MockPluginResult("snap")])  # type: ignore[arg-type]
        )
        store.save_run(
            MockRunResult(plugin_results=[MockPluginResult("flatpak")])  # type: ignore[arg-type]
        )

        runs = store.get_runs_by_plugin("apt")

        assert len(runs) == 1
        plugin_names = {p["name"] for p in runs[0]["plugins"]}
        assert "apt" in plugin_names

        store.close()

    def test_get_runs_in_range(self, tmp_path: Path) -> None:
        """Test getting runs in a date range."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        now = datetime.now(tz=UTC)

        # Save runs at different times
        store.save_run(
            MockRunResult(
                start_time=now - timedelta(days=10),
                plugin_results=[MockPluginResult("apt")],
            )  # type: ignore[arg-type]
        )
        store.save_run(
            MockRunResult(
                start_time=now - timedelta(days=2),
                plugin_results=[MockPluginResult("snap")],
            )  # type: ignore[arg-type]
        )
        store.save_run(
            MockRunResult(
                start_time=now,
                plugin_results=[MockPluginResult("flatpak")],
            )  # type: ignore[arg-type]
        )

        runs = store.get_runs_in_range(now - timedelta(days=5), now)

        assert len(runs) == 2
        plugin_names = {runs[0]["plugins"][0]["name"], runs[1]["plugins"][0]["name"]}
        assert plugin_names == {"snap", "flatpak"}

        store.close()

    def test_clear_history(self, tmp_path: Path) -> None:
        """Test clearing history."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        store.save_run(
            MockRunResult(plugin_results=[MockPluginResult("apt")])  # type: ignore[arg-type]
        )
        assert store.get_total_runs() == 1

        store.clear_history()

        assert store.get_total_runs() == 0
        store.close()

    def test_get_total_runs(self, tmp_path: Path) -> None:
        """Test getting total run count."""
        db_path = tmp_path / "test.duckdb"
        store = DuckDBHistoryStore(db_path)

        assert store.get_total_runs() == 0

        for _ in range(3):
            store.save_run(
                MockRunResult(plugin_results=[MockPluginResult("apt")])  # type: ignore[arg-type]
            )

        assert store.get_total_runs() == 3
        store.close()


class TestHistoryStoreDeprecation:
    """Tests for deprecated HistoryStore."""

    def test_emits_deprecation_warning(self, tmp_path: Path) -> None:
        """Test that HistoryStore emits deprecation warning."""
        history_file = tmp_path / "history.json"

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            HistoryStore(history_file)

            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

    def test_backward_compatibility(self, tmp_path: Path) -> None:
        """Test that HistoryStore maintains backward compatibility."""
        history_file = tmp_path / "history.json"

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            store = HistoryStore(history_file)

        # Should still work
        runs = store.get_recent_runs()
        assert runs == []

        count = store.get_total_runs()
        assert count == 0


class TestMigrateToDuckDB:
    """Tests for migrate_to_duckdb function."""

    def test_migrate_empty_history(self, tmp_path: Path) -> None:
        """Test migrating empty history file."""
        json_path = tmp_path / "history.json"
        json_path.write_text("[]")
        db_path = tmp_path / "history.duckdb"

        result = migrate_to_duckdb(json_path, db_path)

        assert result["runs_migrated"] == 0
        assert result["runs_failed"] == 0
        assert result["executions_migrated"] == 0

    def test_migrate_with_data(self, tmp_path: Path) -> None:
        """Test migrating history with data."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "id": str(uuid4()),
                "start_time": datetime.now(tz=UTC).isoformat(),
                "plugins": [
                    {"name": "apt", "status": "success", "packages_updated": 5},
                    {"name": "snap", "status": "failed", "error_message": "Error"},
                ],
            }
        ]
        json_path.write_text(json.dumps(history))
        db_path = tmp_path / "history.duckdb"

        result = migrate_to_duckdb(json_path, db_path)

        assert result["runs_migrated"] == 1
        assert result["executions_migrated"] == 2
        errors = result["errors"]
        assert isinstance(errors, list)
        assert len(errors) == 0

    def test_migrate_nonexistent_file(self, tmp_path: Path) -> None:
        """Test migrating from nonexistent file."""
        json_path = tmp_path / "nonexistent.json"
        db_path = tmp_path / "history.duckdb"

        result = migrate_to_duckdb(json_path, db_path)

        assert result["runs_migrated"] == 0

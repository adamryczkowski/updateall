"""Tests for batch data loading and migration."""

from __future__ import annotations

import json
from pathlib import Path

from stats.db.connection import DatabaseConnection
from stats.ingestion.loader import (
    MigrationResult,
    export_to_json,
    load_runs_from_json,
    migrate_json_history,
)


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        result = MigrationResult()

        assert result.runs_migrated == 0
        assert result.runs_failed == 0
        assert result.executions_migrated == 0
        assert result.errors == []

    def test_errors_list_initialized(self) -> None:
        """Test that errors list is properly initialized."""
        result = MigrationResult(runs_migrated=5)

        assert result.errors == []
        result.errors.append("test error")
        assert len(result.errors) == 1


class TestMigrateJsonHistory:
    """Tests for migrate_json_history function."""

    def test_migrate_empty_history(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating an empty history file."""
        json_path = tmp_path / "history.json"
        json_path.write_text("[]")

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 0
        assert result.runs_failed == 0
        assert result.executions_migrated == 0

    def test_migrate_single_run(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating a single run."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "start_time": "2026-01-01T10:00:00+00:00",
                "end_time": "2026-01-01T10:05:00+00:00",
                "plugins": [
                    {
                        "name": "apt",
                        "status": "success",
                        "packages_updated": 5,
                        "start_time": "2026-01-01T10:00:00+00:00",
                        "end_time": "2026-01-01T10:02:00+00:00",
                    },
                    {
                        "name": "snap",
                        "status": "success",
                        "packages_updated": 2,
                        "start_time": "2026-01-01T10:02:00+00:00",
                        "end_time": "2026-01-01T10:05:00+00:00",
                    },
                ],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1
        assert result.runs_failed == 0
        assert result.executions_migrated == 2

        # Verify data in database
        db = DatabaseConnection(temp_db_path)
        conn = db.connect()

        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()
        assert runs is not None
        assert runs[0] == 1

        executions = conn.execute(
            "SELECT plugin_name, packages_updated FROM plugin_executions ORDER BY plugin_name"
        ).fetchall()
        assert len(executions) == 2
        assert executions[0][0] == "apt"
        assert executions[0][1] == 5
        assert executions[1][0] == "snap"
        assert executions[1][1] == 2

        db.close()

    def test_migrate_multiple_runs(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating multiple runs."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [{"name": "apt", "status": "success", "packages_updated": 3}],
            },
            {
                "id": "550e8400-e29b-41d4-a716-446655440002",
                "start_time": "2026-01-02T10:00:00+00:00",
                "plugins": [{"name": "snap", "status": "failed", "error_message": "Error"}],
            },
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 2
        assert result.executions_migrated == 2

    def test_migrate_with_missing_id(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating run without ID generates new UUID."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [{"name": "apt", "status": "success"}],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1

        db = DatabaseConnection(temp_db_path)
        run = db.connect().execute("SELECT run_id FROM runs").fetchone()
        assert run is not None
        assert len(run[0]) == 36  # UUID string length

        db.close()

    def test_migrate_with_invalid_id(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating run with invalid ID generates new UUID."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "id": "not-a-valid-uuid",
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1

    def test_migrate_with_missing_start_time(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating run without start_time uses current time."""
        json_path = tmp_path / "history.json"
        history = [{"plugins": [{"name": "apt", "status": "success"}]}]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1

        db = DatabaseConnection(temp_db_path)
        run = db.connect().execute("SELECT start_time FROM runs").fetchone()
        assert run is not None
        assert run[0] is not None

        db.close()

    def test_migrate_with_various_statuses(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating runs with various status strings."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [
                    {"name": "apt", "status": "success"},
                    {"name": "snap", "status": "succeeded"},
                    {"name": "flatpak", "status": "completed"},
                    {"name": "pip", "status": "failed"},
                    {"name": "npm", "status": "error"},
                    {"name": "cargo", "status": "skipped"},
                    {"name": "brew", "status": "timeout"},
                ],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1
        assert result.executions_migrated == 7

        db = DatabaseConnection(temp_db_path)
        db.connect().execute("SELECT * FROM runs").fetchone()

        # Check plugin counts
        db_conn = db.connect()
        successful_row = db_conn.execute(
            "SELECT COUNT(*) FROM plugin_executions WHERE status = 'success'"
        ).fetchone()
        assert successful_row is not None
        successful = successful_row[0]
        failed_row = db_conn.execute(
            "SELECT COUNT(*) FROM plugin_executions WHERE status = 'failed'"
        ).fetchone()
        assert failed_row is not None
        failed = failed_row[0]
        skipped_row = db_conn.execute(
            "SELECT COUNT(*) FROM plugin_executions WHERE status = 'skipped'"
        ).fetchone()
        assert skipped_row is not None
        skipped = skipped_row[0]
        timeout_row = db_conn.execute(
            "SELECT COUNT(*) FROM plugin_executions WHERE status = 'timeout'"
        ).fetchone()
        assert timeout_row is not None
        timeout = timeout_row[0]

        assert successful == 3  # success, succeeded, completed
        assert failed == 2  # failed, error
        assert skipped == 1
        assert timeout == 1

        db.close()

    def test_migrate_nonexistent_file(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating from nonexistent file returns empty result."""
        json_path = tmp_path / "nonexistent.json"

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 0
        assert result.runs_failed == 0

    def test_migrate_invalid_json(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating invalid JSON file returns error."""
        json_path = tmp_path / "history.json"
        json_path.write_text("not valid json")

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 0
        assert len(result.errors) == 1
        assert "Failed to load JSON history" in result.errors[0]

    def test_migrate_non_list_json(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating JSON that is not a list returns error."""
        json_path = tmp_path / "history.json"
        json_path.write_text('{"not": "a list"}')

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 0
        assert len(result.errors) == 1
        assert "not a list" in result.errors[0]

    def test_migrate_with_custom_hostname(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating with custom hostname."""
        json_path = tmp_path / "history.json"
        history = [{"start_time": "2026-01-01T10:00:00+00:00", "plugins": []}]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path, hostname="custom-host")

        assert result.runs_migrated == 1

        db = DatabaseConnection(temp_db_path)
        run = db.connect().execute("SELECT hostname FROM runs").fetchone()
        assert run is not None
        assert run[0] == "custom-host"

        db.close()

    def test_migrate_preserves_hostname_from_data(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test that hostname from data takes precedence."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "hostname": "data-host",
                "plugins": [],
            }
        ]
        json_path.write_text(json.dumps(history))

        migrate_json_history(json_path, temp_db_path, hostname="default-host")

        db = DatabaseConnection(temp_db_path)
        run = db.connect().execute("SELECT hostname FROM runs").fetchone()
        assert run is not None
        assert run[0] == "data-host"

        db.close()

    def test_migrate_with_naive_datetime(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test migrating with naive datetime (no timezone)."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "start_time": "2026-01-01T10:00:00",  # No timezone
                "plugins": [{"name": "apt", "status": "success"}],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1

    def test_migrate_skips_plugins_without_name(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test that plugins without name are skipped."""
        json_path = tmp_path / "history.json"
        history = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [
                    {"name": "apt", "status": "success"},
                    {"status": "success"},  # No name
                    {"name": "", "status": "success"},  # Empty name
                ],
            }
        ]
        json_path.write_text(json.dumps(history))

        result = migrate_json_history(json_path, temp_db_path)

        assert result.runs_migrated == 1
        assert result.executions_migrated == 1  # Only apt


class TestLoadRunsFromJson:
    """Tests for load_runs_from_json function."""

    def test_load_from_list(self, temp_db_path: Path) -> None:
        """Test loading runs from a list directly."""
        json_data = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "plugins": [{"name": "apt", "status": "success", "packages_updated": 5}],
            }
        ]

        result = load_runs_from_json(json_data, temp_db_path)

        assert result.runs_migrated == 1
        assert result.executions_migrated == 1

    def test_load_with_custom_hostname(self, temp_db_path: Path) -> None:
        """Test loading with custom hostname."""
        json_data = [{"start_time": "2026-01-01T10:00:00+00:00", "plugins": []}]

        load_runs_from_json(json_data, temp_db_path, hostname="imported-host")

        db = DatabaseConnection(temp_db_path)
        run = db.connect().execute("SELECT hostname FROM runs").fetchone()
        assert run is not None
        assert run[0] == "imported-host"

        db.close()


class TestExportToJson:
    """Tests for export_to_json function."""

    def test_export_empty_database(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test exporting empty database."""
        # Initialize empty database
        db = DatabaseConnection(temp_db_path)
        db.connect()
        db.close()

        output_path = tmp_path / "export.json"
        result_path = export_to_json(temp_db_path, output_path)

        assert result_path == output_path
        assert output_path.exists()

        content = json.loads(output_path.read_text())
        assert content == []

    def test_export_with_data(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test exporting database with data."""
        # First import some data
        json_data = [
            {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "start_time": "2026-01-01T10:00:00+00:00",
                "end_time": "2026-01-01T10:05:00+00:00",
                "hostname": "test-host",
                "username": "test-user",
                "plugins": [
                    {"name": "apt", "status": "success", "packages_updated": 5},
                    {"name": "snap", "status": "failed", "error_message": "Error"},
                ],
            }
        ]
        load_runs_from_json(json_data, temp_db_path)

        # Export
        output_path = tmp_path / "export.json"
        export_to_json(temp_db_path, output_path)

        # Verify export
        content = json.loads(output_path.read_text())
        assert len(content) == 1

        run = content[0]
        assert run["hostname"] == "test-host"
        assert run["username"] == "test-user"
        assert len(run["plugins"]) == 2

        plugin_names = {p["name"] for p in run["plugins"]}
        assert plugin_names == {"apt", "snap"}

    def test_export_with_limit(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test exporting with limit."""
        # Import multiple runs
        json_data = [
            {
                "start_time": f"2026-01-0{i}T10:00:00+00:00",
                "plugins": [{"name": "apt", "status": "success"}],
            }
            for i in range(1, 6)
        ]
        load_runs_from_json(json_data, temp_db_path)

        # Export with limit
        output_path = tmp_path / "export.json"
        export_to_json(temp_db_path, output_path, limit=3)

        content = json.loads(output_path.read_text())
        assert len(content) == 3

    def test_export_roundtrip(self, temp_db_path: Path, tmp_path: Path) -> None:
        """Test that export and re-import preserves data."""
        # Original data
        original_data = [
            {
                "start_time": "2026-01-01T10:00:00+00:00",
                "hostname": "test-host",
                "plugins": [
                    {"name": "apt", "status": "success", "packages_updated": 5},
                ],
            }
        ]
        load_runs_from_json(original_data, temp_db_path)

        # Export
        export_path = tmp_path / "export.json"
        export_to_json(temp_db_path, export_path)

        # Re-import to new database
        new_db_path = tmp_path / "new.duckdb"
        exported_data = json.loads(export_path.read_text())
        load_runs_from_json(exported_data, new_db_path)

        # Verify data matches
        db = DatabaseConnection(new_db_path)
        conn = db.connect()

        run = conn.execute("SELECT hostname FROM runs").fetchone()
        assert run is not None
        assert run[0] == "test-host"

        execution = conn.execute(
            "SELECT plugin_name, packages_updated FROM plugin_executions"
        ).fetchone()
        assert execution is not None
        assert execution[0] == "apt"
        assert execution[1] == 5

        db.close()

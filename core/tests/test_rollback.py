"""Tests for rollback support module."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.rollback import (
    PluginSnapshot,
    RollbackError,
    RollbackManager,
    RollbackPoint,
    RollbackResult,
    RollbackStatus,
    SnapshotError,
    SnapshotManager,
    SnapshotType,
)


class TestPluginSnapshot:
    """Tests for PluginSnapshot dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        snapshot = PluginSnapshot(
            plugin_name="apt",
            snapshot_type=SnapshotType.PLUGIN,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            data={"packages": ["vim", "git"]},
            files=["/etc/apt/sources.list"],
        )

        data = snapshot.to_dict()

        assert data["plugin_name"] == "apt"
        assert data["snapshot_type"] == "plugin"
        assert "2025-01-01" in data["created_at"]
        assert data["data"]["packages"] == ["vim", "git"]

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "plugin_name": "flatpak",
            "snapshot_type": "package_list",
            "created_at": "2025-01-01T00:00:00+00:00",
            "data": {},
            "files": [],
            "snapshot_path": "/tmp/snapshot",
        }

        snapshot = PluginSnapshot.from_dict(data)

        assert snapshot.plugin_name == "flatpak"
        assert snapshot.snapshot_type == SnapshotType.PACKAGE_LIST
        assert snapshot.snapshot_path == Path("/tmp/snapshot")

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = PluginSnapshot(
            plugin_name="test",
            snapshot_type=SnapshotType.FULL,
            created_at=datetime.now(tz=UTC),
        )

        data = original.to_dict()
        restored = PluginSnapshot.from_dict(data)

        assert restored.plugin_name == original.plugin_name
        assert restored.snapshot_type == original.snapshot_type


class TestRollbackPoint:
    """Tests for RollbackPoint dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization."""
        point = RollbackPoint(
            run_id="run-123",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            status=RollbackStatus.PENDING,
            description="Before update",
        )

        data = point.to_dict()

        assert data["run_id"] == "run-123"
        assert data["status"] == "pending"
        assert data["description"] == "Before update"

    def test_from_dict(self) -> None:
        """Test deserialization."""
        data = {
            "run_id": "run-456",
            "created_at": "2025-01-01T00:00:00+00:00",
            "snapshots": [],
            "status": "completed",
            "description": "Test",
        }

        point = RollbackPoint.from_dict(data)

        assert point.run_id == "run-456"
        assert point.status == RollbackStatus.COMPLETED


class TestRollbackResult:
    """Tests for RollbackResult dataclass."""

    def test_is_successful(self) -> None:
        """Test is_successful property."""
        result = RollbackResult(
            run_id="run-123",
            status=RollbackStatus.COMPLETED,
            plugins_rolled_back=["apt", "flatpak"],
        )

        assert result.is_successful is True

    def test_is_partial(self) -> None:
        """Test is_partial property."""
        result = RollbackResult(
            run_id="run-123",
            status=RollbackStatus.PARTIAL,
            plugins_rolled_back=["apt"],
            plugins_failed=["flatpak"],
        )

        assert result.is_partial is True
        assert result.is_successful is False


class TestSnapshotManager:
    """Tests for SnapshotManager class."""

    def test_create_snapshot_with_data(self) -> None:
        """Test creating a snapshot with data."""
        with TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(snapshot_dir=Path(tmpdir))

            snapshot = manager.create_snapshot(
                plugin_name="apt",
                snapshot_type=SnapshotType.PACKAGE_LIST,
                data={"packages": ["vim", "git", "curl"]},
            )

            assert snapshot.plugin_name == "apt"
            assert snapshot.data["packages"] == ["vim", "git", "curl"]
            assert snapshot.snapshot_path is not None
            assert snapshot.snapshot_path.exists()

    def test_create_snapshot_with_files(self) -> None:
        """Test creating a snapshot with file backup."""
        with TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            files_dir = Path(tmpdir) / "files"
            files_dir.mkdir()

            # Create test file
            test_file = files_dir / "config.txt"
            test_file.write_text("original content")

            manager = SnapshotManager(snapshot_dir=snapshot_dir)

            snapshot = manager.create_snapshot(
                plugin_name="test",
                snapshot_type=SnapshotType.PLUGIN,
                files=[test_file],
            )

            assert str(test_file) in snapshot.files
            # Verify file was backed up
            assert snapshot.snapshot_path is not None
            backup_file = snapshot.snapshot_path / "config.txt"
            assert backup_file.exists()
            assert backup_file.read_text() == "original content"

    def test_restore_snapshot(self) -> None:
        """Test restoring from a snapshot."""
        with TemporaryDirectory() as tmpdir:
            snapshot_dir = Path(tmpdir) / "snapshots"
            files_dir = Path(tmpdir) / "files"
            files_dir.mkdir()

            # Create and backup file
            test_file = files_dir / "config.txt"
            test_file.write_text("original content")

            manager = SnapshotManager(snapshot_dir=snapshot_dir)
            snapshot = manager.create_snapshot(
                plugin_name="test",
                snapshot_type=SnapshotType.PLUGIN,
                files=[test_file],
            )

            # Modify file
            test_file.write_text("modified content")
            assert test_file.read_text() == "modified content"

            # Restore
            result = manager.restore_snapshot(snapshot)

            assert result is True
            assert test_file.read_text() == "original content"

    def test_restore_snapshot_missing_path(self) -> None:
        """Test restoring from snapshot with missing path."""
        with TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(snapshot_dir=Path(tmpdir))

            snapshot = PluginSnapshot(
                plugin_name="test",
                snapshot_type=SnapshotType.PLUGIN,
                created_at=datetime.now(tz=UTC),
                snapshot_path=Path("/nonexistent/path"),
            )

            with pytest.raises(SnapshotError):
                manager.restore_snapshot(snapshot)

    def test_delete_snapshot(self) -> None:
        """Test deleting a snapshot."""
        with TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(snapshot_dir=Path(tmpdir))

            snapshot = manager.create_snapshot(
                plugin_name="test",
                snapshot_type=SnapshotType.PLUGIN,
            )

            assert snapshot.snapshot_path is not None
            assert snapshot.snapshot_path.exists()

            result = manager.delete_snapshot(snapshot)

            assert result is True
            assert not snapshot.snapshot_path.exists()

    def test_list_snapshots(self) -> None:
        """Test listing snapshots."""
        with TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(snapshot_dir=Path(tmpdir))

            # Create multiple snapshots
            manager.create_snapshot("apt", SnapshotType.PLUGIN)
            manager.create_snapshot("flatpak", SnapshotType.PLUGIN)
            manager.create_snapshot("apt", SnapshotType.PACKAGE_LIST)

            all_snapshots = manager.list_snapshots()
            apt_snapshots = manager.list_snapshots(plugin_name="apt")

            assert len(all_snapshots) == 3
            assert len(apt_snapshots) == 2

    def test_cleanup_old_snapshots(self) -> None:
        """Test cleaning up old snapshots."""
        with TemporaryDirectory() as tmpdir:
            manager = SnapshotManager(snapshot_dir=Path(tmpdir))

            # Create snapshots for the same plugin
            for _i in range(5):
                manager.create_snapshot("testplugin", SnapshotType.PLUGIN)

            # Cleanup keeping only 2 per plugin
            manager.cleanup_old_snapshots(max_age_days=365, max_count=2)

            # Should delete 3 (keeping 2 for the same plugin)
            remaining = manager.list_snapshots()
            assert len(remaining) == 2


class TestRollbackManager:
    """Tests for RollbackManager class."""

    def test_create_rollback_point(self) -> None:
        """Test creating a rollback point."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")

            point = manager.create_rollback_point(
                run_id="run-123",
                description="Before update",
            )

            assert point.run_id == "run-123"
            assert point.description == "Before update"
            assert point.status == RollbackStatus.PENDING

    def test_add_snapshot_to_rollback_point(self) -> None:
        """Test adding a snapshot to a rollback point."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")
            manager.create_rollback_point("run-123")

            snapshot = manager.add_snapshot(
                run_id="run-123",
                plugin_name="apt",
                data={"packages": ["vim"]},
            )

            assert snapshot.plugin_name == "apt"
            point = manager.get_rollback_point("run-123")
            assert point is not None
            assert len(point.snapshots) == 1

    def test_add_snapshot_to_nonexistent_point(self) -> None:
        """Test adding snapshot to non-existent rollback point."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")

            with pytest.raises(RollbackError):
                manager.add_snapshot(
                    run_id="nonexistent",
                    plugin_name="apt",
                )

    def test_execute_rollback(self) -> None:
        """Test executing a rollback."""
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            files_dir = Path(tmpdir) / "files"
            files_dir.mkdir()

            # Create test file
            test_file = files_dir / "config.txt"
            test_file.write_text("original")

            manager = RollbackManager(state_dir=state_dir)
            manager.create_rollback_point("run-123")
            manager.add_snapshot(
                run_id="run-123",
                plugin_name="test",
                files=[test_file],
            )

            # Modify file
            test_file.write_text("modified")

            # Execute rollback
            result = manager.execute_rollback("run-123")

            assert result.is_successful
            assert "test" in result.plugins_rolled_back
            assert test_file.read_text() == "original"

    def test_execute_rollback_specific_plugins(self) -> None:
        """Test rolling back specific plugins only."""
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            files_dir = Path(tmpdir) / "files"
            files_dir.mkdir()

            # Create test files
            file1 = files_dir / "config1.txt"
            file2 = files_dir / "config2.txt"
            file1.write_text("original1")
            file2.write_text("original2")

            manager = RollbackManager(state_dir=state_dir)
            manager.create_rollback_point("run-123")
            manager.add_snapshot("run-123", "plugin1", files=[file1])
            manager.add_snapshot("run-123", "plugin2", files=[file2])

            # Modify files
            file1.write_text("modified1")
            file2.write_text("modified2")

            # Rollback only plugin1
            result = manager.execute_rollback("run-123", plugins=["plugin1"])

            assert result.is_successful
            assert "plugin1" in result.plugins_rolled_back
            assert "plugin2" not in result.plugins_rolled_back
            assert file1.read_text() == "original1"
            assert file2.read_text() == "modified2"  # Not rolled back

    def test_mark_success(self) -> None:
        """Test marking rollback point as successful (no longer needed)."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")
            manager.create_rollback_point("run-123")
            manager.add_snapshot("run-123", "apt")

            manager.mark_success("run-123")

            assert manager.get_rollback_point("run-123") is None

    def test_list_rollback_points(self) -> None:
        """Test listing rollback points."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")

            manager.create_rollback_point("run-1")
            manager.create_rollback_point("run-2")
            manager.create_rollback_point("run-3")

            points = manager.list_rollback_points()

            assert len(points) == 3
            # Should be sorted newest first
            assert points[0].run_id == "run-3"

    def test_state_persistence(self) -> None:
        """Test that state is persisted and loaded."""
        with TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"

            # Create manager and add data
            manager1 = RollbackManager(state_dir=state_dir)
            manager1.create_rollback_point("run-123", description="Test")
            manager1.add_snapshot("run-123", "apt")

            # Create new manager and verify state is loaded
            manager2 = RollbackManager(state_dir=state_dir)

            point = manager2.get_rollback_point("run-123")
            assert point is not None
            assert point.description == "Test"
            assert len(point.snapshots) == 1

    def test_cleanup(self) -> None:
        """Test cleaning up old rollback points."""
        with TemporaryDirectory() as tmpdir:
            manager = RollbackManager(state_dir=Path(tmpdir) / "state")

            # Create rollback points
            for i in range(5):
                manager.create_rollback_point(f"run-{i}")

            # Cleanup (all are recent, so none should be deleted with default settings)
            deleted = manager.cleanup(max_age_days=0)  # Delete all

            assert deleted == 5
            assert len(manager.list_rollback_points()) == 0

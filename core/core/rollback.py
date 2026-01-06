"""Rollback support for failed updates (Phase 4).

This module provides rollback capabilities for failed updates, including:

1. Snapshot creation before updates
2. State tracking during updates
3. Rollback execution on failure
4. Recovery from partial failures
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class RollbackError(Exception):
    """Base exception for rollback operations."""


class SnapshotError(RollbackError):
    """Failed to create or restore snapshot."""


class RollbackStatus(str, Enum):
    """Status of a rollback operation."""

    NOT_NEEDED = "not_needed"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class SnapshotType(str, Enum):
    """Type of snapshot."""

    FULL = "full"  # Complete system state
    PLUGIN = "plugin"  # Single plugin state
    PACKAGE_LIST = "package_list"  # List of installed packages


@dataclass
class PluginSnapshot:
    """Snapshot of a plugin's state before update."""

    plugin_name: str
    snapshot_type: SnapshotType
    created_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    snapshot_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "plugin_name": self.plugin_name,
            "snapshot_type": self.snapshot_type.value,
            "created_at": self.created_at.isoformat(),
            "data": self.data,
            "files": self.files,
            "snapshot_path": str(self.snapshot_path) if self.snapshot_path else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginSnapshot:
        """Create from dictionary."""
        return cls(
            plugin_name=data["plugin_name"],
            snapshot_type=SnapshotType(data["snapshot_type"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            data=data.get("data", {}),
            files=data.get("files", []),
            snapshot_path=Path(data["snapshot_path"]) if data.get("snapshot_path") else None,
        )


@dataclass
class RollbackPoint:
    """A point in time to which the system can be rolled back."""

    run_id: str
    created_at: datetime
    snapshots: list[PluginSnapshot] = field(default_factory=list)
    status: RollbackStatus = RollbackStatus.PENDING
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at.isoformat(),
            "snapshots": [s.to_dict() for s in self.snapshots],
            "status": self.status.value,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RollbackPoint:
        """Create from dictionary."""
        return cls(
            run_id=data["run_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            snapshots=[PluginSnapshot.from_dict(s) for s in data.get("snapshots", [])],
            status=RollbackStatus(data.get("status", "pending")),
            description=data.get("description", ""),
        )


@dataclass
class RollbackResult:
    """Result of a rollback operation."""

    run_id: str
    status: RollbackStatus
    plugins_rolled_back: list[str] = field(default_factory=list)
    plugins_failed: list[str] = field(default_factory=list)
    message: str = ""
    completed_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    @property
    def is_successful(self) -> bool:
        """Check if rollback was fully successful."""
        return self.status == RollbackStatus.COMPLETED

    @property
    def is_partial(self) -> bool:
        """Check if rollback was partially successful."""
        return self.status == RollbackStatus.PARTIAL


class SnapshotManager:
    """Manages creation and restoration of snapshots.

    Provides functionality to:
    - Create snapshots before updates
    - Store snapshot data
    - Restore from snapshots
    """

    def __init__(self, snapshot_dir: Path | None = None) -> None:
        """Initialize the snapshot manager.

        Args:
            snapshot_dir: Directory for storing snapshots.
        """
        self.snapshot_dir = snapshot_dir or self._get_default_snapshot_dir()
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def _get_default_snapshot_dir(self) -> Path:
        """Get the default snapshot directory."""
        import os

        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
        return base / "update-all" / "snapshots"

    def create_snapshot(
        self,
        plugin_name: str,
        snapshot_type: SnapshotType,
        data: dict[str, Any] | None = None,
        files: list[Path] | None = None,
    ) -> PluginSnapshot:
        """Create a snapshot for a plugin.

        Args:
            plugin_name: Name of the plugin.
            snapshot_type: Type of snapshot to create.
            data: Optional data to include in snapshot.
            files: Optional list of files to backup.

        Returns:
            Created PluginSnapshot.
        """
        log = logger.bind(plugin=plugin_name, snapshot_type=snapshot_type.value)
        log.info("creating_snapshot")

        timestamp = datetime.now(tz=UTC)
        # Include microseconds to avoid collisions when creating multiple snapshots quickly
        snapshot_path = (
            self.snapshot_dir / f"{plugin_name}_{timestamp.strftime('%Y%m%d_%H%M%S_%f')}"
        )
        snapshot_path.mkdir(parents=True, exist_ok=True)

        backed_up_files: list[str] = []

        # Backup files if provided
        if files:
            for file_path in files:
                if file_path.exists():
                    try:
                        dest = snapshot_path / file_path.name
                        if file_path.is_dir():
                            shutil.copytree(file_path, dest)
                        else:
                            shutil.copy2(file_path, dest)
                        backed_up_files.append(str(file_path))
                    except Exception as e:
                        log.warning("file_backup_failed", file=str(file_path), error=str(e))

        snapshot = PluginSnapshot(
            plugin_name=plugin_name,
            snapshot_type=snapshot_type,
            created_at=timestamp,
            data=data or {},
            files=backed_up_files,
            snapshot_path=snapshot_path,
        )

        # Save snapshot metadata
        metadata_path = snapshot_path / "metadata.json"
        with metadata_path.open("w") as f:
            json.dump(snapshot.to_dict(), f, indent=2)

        log.info("snapshot_created", path=str(snapshot_path))
        return snapshot

    def restore_snapshot(self, snapshot: PluginSnapshot) -> bool:
        """Restore from a snapshot.

        Args:
            snapshot: Snapshot to restore from.

        Returns:
            True if restoration was successful.

        Raises:
            SnapshotError: If restoration fails.
        """
        log = logger.bind(plugin=snapshot.plugin_name)

        if not snapshot.snapshot_path or not snapshot.snapshot_path.exists():
            raise SnapshotError(f"Snapshot path not found: {snapshot.snapshot_path}")

        log.info("restoring_snapshot", path=str(snapshot.snapshot_path))

        try:
            # Restore backed up files
            for file_str in snapshot.files:
                original_path = Path(file_str)
                backup_path = snapshot.snapshot_path / original_path.name

                if backup_path.exists():
                    # Remove current file/directory
                    if original_path.exists():
                        if original_path.is_dir():
                            shutil.rmtree(original_path)
                        else:
                            original_path.unlink()

                    # Restore from backup
                    if backup_path.is_dir():
                        shutil.copytree(backup_path, original_path)
                    else:
                        shutil.copy2(backup_path, original_path)

                    log.debug("file_restored", file=file_str)

            log.info("snapshot_restored")
            return True

        except Exception as e:
            log.error("snapshot_restore_failed", error=str(e))
            raise SnapshotError(f"Failed to restore snapshot: {e}") from e

    def delete_snapshot(self, snapshot: PluginSnapshot) -> bool:
        """Delete a snapshot.

        Args:
            snapshot: Snapshot to delete.

        Returns:
            True if deletion was successful.
        """
        if snapshot.snapshot_path and snapshot.snapshot_path.exists():
            try:
                shutil.rmtree(snapshot.snapshot_path)
                logger.info("snapshot_deleted", path=str(snapshot.snapshot_path))
                return True
            except Exception as e:
                logger.warning("snapshot_delete_failed", error=str(e))
                return False
        return False

    def list_snapshots(self, plugin_name: str | None = None) -> list[PluginSnapshot]:
        """List available snapshots.

        Args:
            plugin_name: Optional filter by plugin name.

        Returns:
            List of available snapshots.
        """
        snapshots = []

        for path in self.snapshot_dir.iterdir():
            if not path.is_dir():
                continue

            metadata_path = path / "metadata.json"
            if metadata_path.exists():
                try:
                    with metadata_path.open() as f:
                        data = json.load(f)
                    snapshot = PluginSnapshot.from_dict(data)

                    if plugin_name is None or snapshot.plugin_name == plugin_name:
                        snapshots.append(snapshot)
                except Exception as e:
                    logger.warning("failed_to_load_snapshot", path=str(path), error=str(e))

        return sorted(snapshots, key=lambda s: s.created_at, reverse=True)

    def cleanup_old_snapshots(self, max_age_days: int = 30, max_count: int = 10) -> int:
        """Clean up old snapshots.

        Args:
            max_age_days: Maximum age of snapshots to keep.
            max_count: Maximum number of snapshots per plugin.

        Returns:
            Number of snapshots deleted.
        """
        from datetime import timedelta

        deleted = 0
        cutoff = datetime.now(tz=UTC) - timedelta(days=max_age_days)

        # Group snapshots by plugin
        by_plugin: dict[str, list[PluginSnapshot]] = {}
        for snapshot in self.list_snapshots():
            if snapshot.plugin_name not in by_plugin:
                by_plugin[snapshot.plugin_name] = []
            by_plugin[snapshot.plugin_name].append(snapshot)

        for _plugin_name, snapshots in by_plugin.items():
            # Sort by date, newest first
            snapshots.sort(key=lambda s: s.created_at, reverse=True)

            for i, snapshot in enumerate(snapshots):
                # Delete if too old or exceeds count
                should_delete = snapshot.created_at < cutoff or i >= max_count
                if should_delete and self.delete_snapshot(snapshot):
                    deleted += 1

        logger.info("snapshots_cleaned_up", deleted=deleted)
        return deleted


class RollbackManager:
    """Manages rollback operations for failed updates.

    Provides functionality to:
    - Create rollback points before updates
    - Execute rollbacks on failure
    - Track rollback history
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        snapshot_manager: SnapshotManager | None = None,
    ) -> None:
        """Initialize the rollback manager.

        Args:
            state_dir: Directory for storing rollback state.
            snapshot_manager: Optional snapshot manager instance.
        """
        self.state_dir = state_dir or self._get_default_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.snapshot_manager = snapshot_manager or SnapshotManager()
        self.rollback_points: dict[str, RollbackPoint] = {}

        self._load_state()

    def _get_default_state_dir(self) -> Path:
        """Get the default state directory."""
        import os

        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
        return base / "update-all" / "rollback"

    def _load_state(self) -> None:
        """Load rollback state from file."""
        state_file = self.state_dir / "rollback_state.json"
        if not state_file.exists():
            return

        try:
            with state_file.open() as f:
                data = json.load(f)

            for point_data in data.get("rollback_points", []):
                point = RollbackPoint.from_dict(point_data)
                self.rollback_points[point.run_id] = point

        except Exception as e:
            logger.warning("failed_to_load_rollback_state", error=str(e))

    def _save_state(self) -> None:
        """Save rollback state to file."""
        state_file = self.state_dir / "rollback_state.json"

        data = {
            "rollback_points": [p.to_dict() for p in self.rollback_points.values()],
        }

        with state_file.open("w") as f:
            json.dump(data, f, indent=2)

    def create_rollback_point(
        self,
        run_id: str,
        description: str = "",
    ) -> RollbackPoint:
        """Create a new rollback point.

        Args:
            run_id: Unique identifier for the update run.
            description: Optional description.

        Returns:
            Created RollbackPoint.
        """
        point = RollbackPoint(
            run_id=run_id,
            created_at=datetime.now(tz=UTC),
            description=description,
        )

        self.rollback_points[run_id] = point
        self._save_state()

        logger.info("rollback_point_created", run_id=run_id)
        return point

    def add_snapshot(
        self,
        run_id: str,
        plugin_name: str,
        snapshot_type: SnapshotType = SnapshotType.PLUGIN,
        data: dict[str, Any] | None = None,
        files: list[Path] | None = None,
    ) -> PluginSnapshot:
        """Add a snapshot to a rollback point.

        Args:
            run_id: Run ID of the rollback point.
            plugin_name: Name of the plugin.
            snapshot_type: Type of snapshot.
            data: Optional data to include.
            files: Optional files to backup.

        Returns:
            Created PluginSnapshot.

        Raises:
            RollbackError: If rollback point not found.
        """
        if run_id not in self.rollback_points:
            raise RollbackError(f"Rollback point not found: {run_id}")

        snapshot = self.snapshot_manager.create_snapshot(
            plugin_name=plugin_name,
            snapshot_type=snapshot_type,
            data=data,
            files=files,
        )

        self.rollback_points[run_id].snapshots.append(snapshot)
        self._save_state()

        return snapshot

    def execute_rollback(
        self,
        run_id: str,
        plugins: list[str] | None = None,
    ) -> RollbackResult:
        """Execute a rollback to a previous state.

        Args:
            run_id: Run ID of the rollback point.
            plugins: Optional list of specific plugins to rollback.

        Returns:
            RollbackResult with outcome.

        Raises:
            RollbackError: If rollback point not found.
        """
        log = logger.bind(run_id=run_id)

        if run_id not in self.rollback_points:
            raise RollbackError(f"Rollback point not found: {run_id}")

        point = self.rollback_points[run_id]
        point.status = RollbackStatus.IN_PROGRESS
        self._save_state()

        log.info("executing_rollback", snapshot_count=len(point.snapshots))

        rolled_back: list[str] = []
        failed: list[str] = []

        for snapshot in point.snapshots:
            # Skip if specific plugins requested and this isn't one
            if plugins and snapshot.plugin_name not in plugins:
                continue

            try:
                self.snapshot_manager.restore_snapshot(snapshot)
                rolled_back.append(snapshot.plugin_name)
            except SnapshotError as e:
                log.error("plugin_rollback_failed", plugin=snapshot.plugin_name, error=str(e))
                failed.append(snapshot.plugin_name)

        # Determine final status
        if not failed:
            status = RollbackStatus.COMPLETED
            message = f"Successfully rolled back {len(rolled_back)} plugin(s)"
        elif not rolled_back:
            status = RollbackStatus.FAILED
            message = f"Failed to rollback any plugins. Failed: {', '.join(failed)}"
        else:
            status = RollbackStatus.PARTIAL
            message = f"Partial rollback: {len(rolled_back)} succeeded, {len(failed)} failed"

        point.status = status
        self._save_state()

        result = RollbackResult(
            run_id=run_id,
            status=status,
            plugins_rolled_back=rolled_back,
            plugins_failed=failed,
            message=message,
        )

        log.info("rollback_completed", status=status.value, message=message)
        return result

    def mark_success(self, run_id: str) -> None:
        """Mark a rollback point as no longer needed (update succeeded).

        Args:
            run_id: Run ID of the rollback point.
        """
        if run_id in self.rollback_points:
            point = self.rollback_points[run_id]
            point.status = RollbackStatus.NOT_NEEDED

            # Clean up snapshots
            for snapshot in point.snapshots:
                self.snapshot_manager.delete_snapshot(snapshot)

            del self.rollback_points[run_id]
            self._save_state()

            logger.info("rollback_point_cleared", run_id=run_id)

    def get_rollback_point(self, run_id: str) -> RollbackPoint | None:
        """Get a rollback point by run ID.

        Args:
            run_id: Run ID to look up.

        Returns:
            RollbackPoint or None if not found.
        """
        return self.rollback_points.get(run_id)

    def list_rollback_points(self) -> list[RollbackPoint]:
        """List all rollback points.

        Returns:
            List of rollback points, newest first.
        """
        return sorted(
            self.rollback_points.values(),
            key=lambda p: p.created_at,
            reverse=True,
        )

    def cleanup(self, max_age_days: int = 7) -> int:
        """Clean up old rollback points.

        Args:
            max_age_days: Maximum age of rollback points to keep.

        Returns:
            Number of rollback points deleted.
        """
        from datetime import timedelta

        deleted = 0
        cutoff = datetime.now(tz=UTC) - timedelta(days=max_age_days)

        for run_id, point in list(self.rollback_points.items()):
            if point.created_at < cutoff:
                # Clean up snapshots
                for snapshot in point.snapshots:
                    self.snapshot_manager.delete_snapshot(snapshot)

                del self.rollback_points[run_id]
                deleted += 1

        if deleted > 0:
            self._save_state()
            logger.info("rollback_points_cleaned_up", deleted=deleted)

        return deleted

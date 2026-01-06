"""Tests for schedule management functionality."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.schedule import (
    INTERVAL_TO_CALENDAR,
    ScheduleError,
    ScheduleInterval,
    ScheduleManager,
    ScheduleStatus,
    get_schedule_manager,
)


class TestScheduleInterval:
    """Tests for ScheduleInterval enum."""

    def test_interval_values(self) -> None:
        """Test interval enum values."""
        assert ScheduleInterval.HOURLY.value == "hourly"
        assert ScheduleInterval.DAILY.value == "daily"
        assert ScheduleInterval.WEEKLY.value == "weekly"
        assert ScheduleInterval.MONTHLY.value == "monthly"

    def test_interval_to_calendar_mapping(self) -> None:
        """Test interval to calendar value mapping."""
        assert INTERVAL_TO_CALENDAR[ScheduleInterval.HOURLY] == "hourly"
        assert INTERVAL_TO_CALENDAR[ScheduleInterval.DAILY] == "daily"
        assert INTERVAL_TO_CALENDAR[ScheduleInterval.WEEKLY] == "weekly"
        assert INTERVAL_TO_CALENDAR[ScheduleInterval.MONTHLY] == "monthly"


class TestScheduleStatus:
    """Tests for ScheduleStatus dataclass."""

    def test_schedule_status_creation(self) -> None:
        """Test creating ScheduleStatus."""
        status = ScheduleStatus(
            enabled=True,
            active=True,
            schedule="weekly",
            next_run=datetime.now(),
            last_run=None,
            last_result="success",
        )

        assert status.enabled is True
        assert status.active is True
        assert status.schedule == "weekly"
        assert status.last_result == "success"

    def test_schedule_status_disabled(self) -> None:
        """Test disabled schedule status."""
        status = ScheduleStatus(
            enabled=False,
            active=False,
            schedule=None,
            next_run=None,
            last_run=None,
            last_result=None,
        )

        assert status.enabled is False
        assert status.schedule is None


class TestScheduleManager:
    """Tests for ScheduleManager."""

    def test_init_user_mode(self) -> None:
        """Test ScheduleManager initialization in user mode."""
        manager = ScheduleManager(user_mode=True)

        assert manager.user_mode is True
        assert manager.unit_dir == Path.home() / ".config" / "systemd" / "user"
        assert manager.timer_name == "update-all.timer"
        assert manager.service_name == "update-all.service"

    def test_init_system_mode(self) -> None:
        """Test ScheduleManager initialization in system mode."""
        manager = ScheduleManager(user_mode=False)

        assert manager.user_mode is False
        assert manager.unit_dir == Path("/etc/systemd/system")

    def test_timer_path(self) -> None:
        """Test timer path property."""
        manager = ScheduleManager(user_mode=True)
        expected = Path.home() / ".config" / "systemd" / "user" / "update-all.timer"

        assert manager.timer_path == expected

    def test_service_path(self) -> None:
        """Test service path property."""
        manager = ScheduleManager(user_mode=True)
        expected = Path.home() / ".config" / "systemd" / "user" / "update-all.service"

        assert manager.service_path == expected

    def test_get_update_all_path_fallback(self) -> None:
        """Test getting update-all path with fallback."""
        manager = ScheduleManager()

        # Should return "update-all" as fallback when not found in common paths
        with patch.object(Path, "exists", return_value=False):
            path = manager._get_update_all_path()
            assert path == "update-all"

    def test_timer_template(self) -> None:
        """Test timer template content."""
        manager = ScheduleManager()

        assert "[Unit]" in manager.TIMER_TEMPLATE
        assert "[Timer]" in manager.TIMER_TEMPLATE
        assert "OnCalendar={schedule}" in manager.TIMER_TEMPLATE
        assert "RandomizedDelaySec=3600" in manager.TIMER_TEMPLATE
        assert "[Install]" in manager.TIMER_TEMPLATE

    def test_service_template(self) -> None:
        """Test service template content."""
        manager = ScheduleManager()

        assert "[Unit]" in manager.SERVICE_TEMPLATE
        assert "[Service]" in manager.SERVICE_TEMPLATE
        assert "Type=oneshot" in manager.SERVICE_TEMPLATE
        assert "{update_all_path}" in manager.SERVICE_TEMPLATE
        assert "UPDATE_ALL_SCHEDULED=1" in manager.SERVICE_TEMPLATE

    @patch("subprocess.run")
    def test_systemctl_user_mode(self, mock_run: MagicMock) -> None:
        """Test systemctl command in user mode."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = ScheduleManager(user_mode=True)

        manager._systemctl("status", "update-all.timer")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "systemctl" in call_args
        assert "--user" in call_args
        assert "status" in call_args

    @patch("subprocess.run")
    def test_systemctl_system_mode(self, mock_run: MagicMock) -> None:
        """Test systemctl command in system mode."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = ScheduleManager(user_mode=False)

        manager._systemctl("status", "update-all.timer")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "systemctl" in call_args
        assert "--user" not in call_args

    @patch("subprocess.run")
    def test_systemctl_not_found(self, mock_run: MagicMock) -> None:
        """Test systemctl command when systemctl is not found."""
        mock_run.side_effect = FileNotFoundError("systemctl not found")
        manager = ScheduleManager()

        with pytest.raises(ScheduleError, match="systemctl not found"):
            manager._systemctl("status", "update-all.timer")

    def test_parse_usec_timestamp_valid(self) -> None:
        """Test parsing valid microsecond timestamp."""
        manager = ScheduleManager()

        # 1704067200000000 = 2024-01-01 00:00:00 UTC
        result = manager._parse_usec_timestamp("1704067200000000")

        assert result is not None
        assert isinstance(result, datetime)

    def test_parse_usec_timestamp_invalid(self) -> None:
        """Test parsing invalid timestamp."""
        manager = ScheduleManager()

        assert manager._parse_usec_timestamp("invalid") is None
        assert manager._parse_usec_timestamp("0") is None
        assert manager._parse_usec_timestamp("") is None

    @patch("subprocess.run")
    def test_get_status_disabled(self, mock_run: MagicMock) -> None:
        """Test getting status when schedule is disabled."""
        # is-enabled returns non-zero for disabled
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        manager = ScheduleManager()

        status = manager.get_status()

        assert status.enabled is False
        assert status.active is False

    @patch("subprocess.run")
    def test_disable_success(self, mock_run: MagicMock) -> None:
        """Test disabling schedule successfully."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        manager = ScheduleManager()

        # Should not raise
        manager.disable()

    @patch("subprocess.run")
    def test_get_logs(self, mock_run: MagicMock) -> None:
        """Test getting logs."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Jan 01 12:00:00 host update-all[123]: Update completed",
            stderr="",
        )
        manager = ScheduleManager()

        logs = manager.get_logs(lines=10)

        assert "Update completed" in logs

    @patch("subprocess.run")
    def test_get_logs_not_found(self, mock_run: MagicMock) -> None:
        """Test getting logs when journalctl is not found."""
        mock_run.side_effect = FileNotFoundError()
        manager = ScheduleManager()

        logs = manager.get_logs()

        assert logs == "journalctl not found"


class TestGetScheduleManager:
    """Tests for get_schedule_manager function."""

    def test_get_schedule_manager_user_mode(self) -> None:
        """Test getting schedule manager in user mode."""
        manager = get_schedule_manager(user_mode=True)

        assert isinstance(manager, ScheduleManager)
        assert manager.user_mode is True

    def test_get_schedule_manager_system_mode(self) -> None:
        """Test getting schedule manager in system mode."""
        manager = get_schedule_manager(user_mode=False)

        assert isinstance(manager, ScheduleManager)
        assert manager.user_mode is False

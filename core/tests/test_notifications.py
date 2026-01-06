"""Tests for notification functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.notifications import (
    NotificationConfig,
    NotificationManager,
    NotificationUrgency,
    get_notification_manager,
    load_notification_config,
)


class TestNotificationUrgency:
    """Tests for NotificationUrgency enum."""

    def test_urgency_values(self) -> None:
        """Test urgency enum values."""
        assert NotificationUrgency.LOW.value == "low"
        assert NotificationUrgency.NORMAL.value == "normal"
        assert NotificationUrgency.CRITICAL.value == "critical"


class TestNotificationConfig:
    """Tests for NotificationConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = NotificationConfig()

        assert config.enabled is True
        assert config.on_success is False
        assert config.on_failure is True
        assert config.on_updates_available is True
        assert config.app_name == "update-all"
        assert config.icon == "system-software-update"

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = NotificationConfig(
            enabled=False,
            on_success=True,
            on_failure=False,
            app_name="my-updater",
            icon="custom-icon",
        )

        assert config.enabled is False
        assert config.on_success is True
        assert config.on_failure is False
        assert config.app_name == "my-updater"
        assert config.icon == "custom-icon"


class TestNotificationManager:
    """Tests for NotificationManager."""

    def test_init_default_config(self) -> None:
        """Test initialization with default config."""
        manager = NotificationManager()

        assert manager.config.enabled is True
        assert manager._notify_send_available is None

    def test_init_custom_config(self) -> None:
        """Test initialization with custom config."""
        config = NotificationConfig(enabled=False)
        manager = NotificationManager(config=config)

        assert manager.config.enabled is False

    @patch("subprocess.run")
    def test_check_notify_send_available(self, mock_run: MagicMock) -> None:
        """Test checking if notify-send is available."""
        mock_run.return_value = MagicMock(returncode=0)
        manager = NotificationManager()

        result = manager._check_notify_send()

        assert result is True
        assert manager._notify_send_available is True

    @patch("subprocess.run")
    def test_check_notify_send_not_available(self, mock_run: MagicMock) -> None:
        """Test checking when notify-send is not available."""
        mock_run.return_value = MagicMock(returncode=1)
        manager = NotificationManager()

        result = manager._check_notify_send()

        assert result is False
        assert manager._notify_send_available is False

    @patch("subprocess.run")
    def test_check_notify_send_cached(self, mock_run: MagicMock) -> None:
        """Test that notify-send check is cached."""
        mock_run.return_value = MagicMock(returncode=0)
        manager = NotificationManager()

        # First call
        manager._check_notify_send()
        # Second call should use cached value
        manager._check_notify_send()

        # Should only be called once
        assert mock_run.call_count == 1

    def test_notify_disabled(self) -> None:
        """Test notify when notifications are disabled."""
        config = NotificationConfig(enabled=False)
        manager = NotificationManager(config=config)

        result = manager.notify("Test", "Message")

        assert result is False

    @patch("subprocess.run")
    def test_notify_send_not_available(self, mock_run: MagicMock) -> None:
        """Test notify when notify-send is not available."""
        mock_run.return_value = MagicMock(returncode=1)  # which returns 1
        manager = NotificationManager()

        result = manager.notify("Test", "Message")

        assert result is False

    @patch("subprocess.run")
    def test_notify_success(self, mock_run: MagicMock) -> None:
        """Test successful notification."""
        # First call for which, second for notify-send
        mock_run.side_effect = [
            MagicMock(returncode=0),  # which notify-send
            MagicMock(returncode=0),  # notify-send
        ]
        manager = NotificationManager()

        result = manager.notify("Test Title", "Test Message")

        assert result is True
        # Verify notify-send was called with correct args
        call_args = mock_run.call_args_list[1][0][0]
        assert "notify-send" in call_args
        assert "--urgency" in call_args
        assert "normal" in call_args
        assert "Test Title" in call_args
        assert "Test Message" in call_args

    @patch("subprocess.run")
    def test_notify_with_urgency(self, mock_run: MagicMock) -> None:
        """Test notification with custom urgency."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify(
            "Critical Alert",
            "Something went wrong",
            urgency=NotificationUrgency.CRITICAL,
        )

        assert result is True
        call_args = mock_run.call_args_list[1][0][0]
        assert "critical" in call_args

    @patch("subprocess.run")
    def test_notify_with_timeout(self, mock_run: MagicMock) -> None:
        """Test notification with custom timeout."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify("Test", "Message", timeout_ms=5000)

        assert result is True
        call_args = mock_run.call_args_list[1][0][0]
        assert "--expire-time" in call_args
        assert "5000" in call_args

    @patch("subprocess.run")
    def test_notify_update_started(self, mock_run: MagicMock) -> None:
        """Test update started notification."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify_update_started(plugin_count=5)

        assert result is True

    @patch("subprocess.run")
    def test_notify_update_completed_success(self, mock_run: MagicMock) -> None:
        """Test update completed notification on success."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        config = NotificationConfig(on_success=True)
        manager = NotificationManager(config=config)

        result = manager.notify_update_completed(
            successful=5,
            failed=0,
            packages_updated=25,
            duration_seconds=120.5,
        )

        assert result is True

    def test_notify_update_completed_success_disabled(self) -> None:
        """Test update completed notification when on_success is disabled."""
        config = NotificationConfig(on_success=False)
        manager = NotificationManager(config=config)

        result = manager.notify_update_completed(
            successful=5,
            failed=0,
            packages_updated=25,
            duration_seconds=120.5,
        )

        assert result is False

    @patch("subprocess.run")
    def test_notify_update_completed_with_failures(self, mock_run: MagicMock) -> None:
        """Test update completed notification with failures."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify_update_completed(
            successful=3,
            failed=2,
            packages_updated=15,
            duration_seconds=90.0,
        )

        assert result is True

    @patch("subprocess.run")
    def test_notify_updates_available(self, mock_run: MagicMock) -> None:
        """Test updates available notification."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify_updates_available(
            plugin_name="apt",
            update_count=10,
        )

        assert result is True

    def test_notify_updates_available_disabled(self) -> None:
        """Test updates available notification when disabled."""
        config = NotificationConfig(on_updates_available=False)
        manager = NotificationManager(config=config)

        result = manager.notify_updates_available(
            plugin_name="apt",
            update_count=10,
        )

        assert result is False

    @patch("subprocess.run")
    def test_notify_error(self, mock_run: MagicMock) -> None:
        """Test error notification."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify_error(
            plugin_name="apt",
            error_message="Failed to update packages",
        )

        assert result is True

    def test_notify_error_disabled(self) -> None:
        """Test error notification when on_failure is disabled."""
        config = NotificationConfig(on_failure=False)
        manager = NotificationManager(config=config)

        result = manager.notify_error(
            plugin_name="apt",
            error_message="Failed to update packages",
        )

        assert result is False

    @patch("subprocess.run")
    def test_notify_reboot_required(self, mock_run: MagicMock) -> None:
        """Test reboot required notification."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        manager = NotificationManager()

        result = manager.notify_reboot_required()

        assert result is True


class TestGetNotificationManager:
    """Tests for get_notification_manager function."""

    def test_get_notification_manager_default(self) -> None:
        """Test getting notification manager with default config."""
        manager = get_notification_manager()

        assert isinstance(manager, NotificationManager)
        assert manager.config.enabled is True

    def test_get_notification_manager_custom_config(self) -> None:
        """Test getting notification manager with custom config."""
        config = NotificationConfig(enabled=False)
        manager = get_notification_manager(config=config)

        assert isinstance(manager, NotificationManager)
        assert manager.config.enabled is False


class TestLoadNotificationConfig:
    """Tests for load_notification_config function."""

    def test_load_empty_config(self) -> None:
        """Test loading from empty config."""
        config = load_notification_config({})

        assert config.enabled is True
        assert config.on_success is False
        assert config.on_failure is True

    def test_load_full_config(self) -> None:
        """Test loading from full config."""
        config_data = {
            "notifications": {
                "enabled": False,
                "on_success": True,
                "on_failure": False,
                "on_updates_available": False,
                "app_name": "custom-app",
                "icon": "custom-icon",
            }
        }
        config = load_notification_config(config_data)

        assert config.enabled is False
        assert config.on_success is True
        assert config.on_failure is False
        assert config.on_updates_available is False
        assert config.app_name == "custom-app"
        assert config.icon == "custom-icon"

    def test_load_partial_config(self) -> None:
        """Test loading from partial config."""
        config_data = {
            "notifications": {
                "enabled": True,
                "on_success": True,
            }
        }
        config = load_notification_config(config_data)

        assert config.enabled is True
        assert config.on_success is True
        # Defaults for unspecified values
        assert config.on_failure is True
        assert config.app_name == "update-all"

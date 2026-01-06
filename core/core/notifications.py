"""Desktop notifications for update-all.

This module provides desktop notification support for update completion,
errors, and other important events. It uses notify-send on Linux systems.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class NotificationUrgency(str, Enum):
    """Urgency level for notifications."""

    LOW = "low"
    NORMAL = "normal"
    CRITICAL = "critical"


class NotificationError(Exception):
    """Error sending notification."""


@dataclass
class NotificationConfig:
    """Configuration for notifications."""

    enabled: bool = True
    on_success: bool = False
    on_failure: bool = True
    on_updates_available: bool = True
    app_name: str = "update-all"
    icon: str = "system-software-update"


class NotificationManager:
    """Manages desktop notifications for update-all.

    This class provides methods to send desktop notifications using
    the system's notification daemon (via notify-send on Linux).
    """

    def __init__(self, config: NotificationConfig | None = None) -> None:
        """Initialize the notification manager.

        Args:
            config: Notification configuration. Uses defaults if not provided.
        """
        self.config = config or NotificationConfig()
        self._notify_send_available: bool | None = None

    def _check_notify_send(self) -> bool:
        """Check if notify-send is available.

        Returns:
            True if notify-send is available, False otherwise.
        """
        if self._notify_send_available is None:
            try:
                result = subprocess.run(
                    ["which", "notify-send"],
                    capture_output=True,
                    check=False,
                )
                self._notify_send_available = result.returncode == 0
            except FileNotFoundError:
                self._notify_send_available = False

        return self._notify_send_available

    def notify(
        self,
        title: str,
        message: str,
        urgency: NotificationUrgency = NotificationUrgency.NORMAL,
        icon: str | None = None,
        timeout_ms: int | None = None,
    ) -> bool:
        """Send a desktop notification.

        Args:
            title: Notification title.
            message: Notification message body.
            urgency: Urgency level (low, normal, critical).
            icon: Icon name or path. Uses default if not provided.
            timeout_ms: Notification timeout in milliseconds.

        Returns:
            True if notification was sent successfully, False otherwise.
        """
        if not self.config.enabled:
            logger.debug("notifications_disabled")
            return False

        if not self._check_notify_send():
            logger.warning("notify_send_not_available")
            return False

        cmd = [
            "notify-send",
            "--urgency",
            urgency.value,
            "--app-name",
            self.config.app_name,
        ]

        if icon or self.config.icon:
            cmd.extend(["--icon", icon or self.config.icon])

        if timeout_ms is not None:
            cmd.extend(["--expire-time", str(timeout_ms)])

        cmd.extend([title, message])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
            )

            if result.returncode == 0:
                logger.debug("notification_sent", title=title)
                return True
            else:
                logger.warning(
                    "notification_failed",
                    title=title,
                    stderr=result.stderr.decode(),
                )
                return False

        except FileNotFoundError:
            logger.warning("notify_send_not_found")
            return False
        except Exception as e:
            logger.error("notification_error", error=str(e))
            return False

    def notify_update_started(self, plugin_count: int) -> bool:
        """Send notification that updates are starting.

        Args:
            plugin_count: Number of plugins to run.

        Returns:
            True if notification was sent successfully.
        """
        return self.notify(
            title="System Updates Starting",
            message=f"Running updates for {plugin_count} plugin(s)...",
            urgency=NotificationUrgency.LOW,
        )

    def notify_update_completed(
        self,
        successful: int,
        failed: int,
        packages_updated: int,
        duration_seconds: float,
    ) -> bool:
        """Send notification that updates completed.

        Args:
            successful: Number of successful plugins.
            failed: Number of failed plugins.
            packages_updated: Total packages updated.
            duration_seconds: Total duration in seconds.

        Returns:
            True if notification was sent successfully.
        """
        if failed > 0:
            if not self.config.on_failure:
                return False

            title = "System Updates Completed with Errors"
            urgency = NotificationUrgency.CRITICAL
            icon = "dialog-error"
        else:
            if not self.config.on_success:
                return False

            title = "System Updates Completed"
            urgency = NotificationUrgency.NORMAL
            icon = "dialog-information"

        # Format duration
        if duration_seconds < 60:
            duration_str = f"{duration_seconds:.0f}s"
        else:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            duration_str = f"{minutes}m {seconds}s"

        message_parts = []
        if packages_updated > 0:
            message_parts.append(f"{packages_updated} packages updated")
        message_parts.append(f"{successful} plugins succeeded")
        if failed > 0:
            message_parts.append(f"{failed} plugins failed")
        message_parts.append(f"Duration: {duration_str}")

        message = "\n".join(message_parts)

        return self.notify(
            title=title,
            message=message,
            urgency=urgency,
            icon=icon,
        )

    def notify_updates_available(
        self,
        plugin_name: str,
        update_count: int,
    ) -> bool:
        """Send notification that updates are available.

        Args:
            plugin_name: Name of the plugin with updates.
            update_count: Number of available updates.

        Returns:
            True if notification was sent successfully.
        """
        if not self.config.on_updates_available:
            return False

        return self.notify(
            title="Updates Available",
            message=f"{update_count} updates available from {plugin_name}",
            urgency=NotificationUrgency.LOW,
        )

    def notify_error(
        self,
        plugin_name: str,
        error_message: str,
    ) -> bool:
        """Send notification about an error.

        Args:
            plugin_name: Name of the plugin that failed.
            error_message: Error message.

        Returns:
            True if notification was sent successfully.
        """
        if not self.config.on_failure:
            return False

        return self.notify(
            title=f"Update Failed: {plugin_name}",
            message=error_message,
            urgency=NotificationUrgency.CRITICAL,
            icon="dialog-error",
        )

    def notify_reboot_required(self) -> bool:
        """Send notification that a reboot is required.

        Returns:
            True if notification was sent successfully.
        """
        return self.notify(
            title="Reboot Required",
            message="System updates require a reboot to complete.",
            urgency=NotificationUrgency.CRITICAL,
            icon="system-reboot",
        )


def get_notification_manager(
    config: NotificationConfig | None = None,
) -> NotificationManager:
    """Get a notification manager instance.

    Args:
        config: Optional notification configuration.

    Returns:
        Configured NotificationManager.
    """
    return NotificationManager(config=config)


def load_notification_config(config_data: dict[str, Any]) -> NotificationConfig:
    """Load notification configuration from a dictionary.

    Args:
        config_data: Configuration dictionary.

    Returns:
        NotificationConfig instance.
    """
    notifications_data = config_data.get("notifications", {})

    return NotificationConfig(
        enabled=notifications_data.get("enabled", True),
        on_success=notifications_data.get("on_success", False),
        on_failure=notifications_data.get("on_failure", True),
        on_updates_available=notifications_data.get("on_updates_available", True),
        app_name=notifications_data.get("app_name", "update-all"),
        icon=notifications_data.get("icon", "system-software-update"),
    )

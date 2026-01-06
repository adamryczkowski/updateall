"""Scheduled updates via systemd timers.

This module provides systemd timer integration for scheduled updates.
It can create, enable, disable, and manage systemd timer units for
automatic update execution.
"""

from __future__ import annotations

import contextlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class ScheduleError(Exception):
    """Error during schedule management."""


class ScheduleInterval(str, Enum):
    """Predefined schedule intervals."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


# Mapping of intervals to systemd OnCalendar values
INTERVAL_TO_CALENDAR: dict[ScheduleInterval, str] = {
    ScheduleInterval.HOURLY: "hourly",
    ScheduleInterval.DAILY: "daily",
    ScheduleInterval.WEEKLY: "weekly",
    ScheduleInterval.MONTHLY: "monthly",
}


@dataclass
class ScheduleStatus:
    """Status of the update schedule."""

    enabled: bool
    active: bool
    schedule: str | None
    next_run: datetime | None
    last_run: datetime | None
    last_result: str | None


class ScheduleManager:
    """Manages systemd timer for scheduled updates.

    This class provides methods to enable, disable, and check the status
    of scheduled updates using systemd timers.
    """

    TIMER_TEMPLATE = """[Unit]
Description=Scheduled system updates via update-all

[Timer]
OnCalendar={schedule}
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
"""

    SERVICE_TEMPLATE = """[Unit]
Description=Run update-all system updates
After=network-online.target

[Service]
Type=oneshot
ExecStart={update_all_path} run --scheduled
Environment=UPDATE_ALL_SCHEDULED=1
"""

    def __init__(self, user_mode: bool = True) -> None:
        """Initialize the schedule manager.

        Args:
            user_mode: If True, use user systemd units (~/.config/systemd/user).
                      If False, use system units (/etc/systemd/system).
        """
        self.user_mode = user_mode
        if user_mode:
            self.unit_dir = Path.home() / ".config" / "systemd" / "user"
        else:
            self.unit_dir = Path("/etc/systemd/system")

        self.timer_name = "update-all.timer"
        self.service_name = "update-all.service"

    @property
    def timer_path(self) -> Path:
        """Path to the timer unit file."""
        return self.unit_dir / self.timer_name

    @property
    def service_path(self) -> Path:
        """Path to the service unit file."""
        return self.unit_dir / self.service_name

    def _get_update_all_path(self) -> str:
        """Get the path to the update-all executable.

        Returns:
            Path to the update-all executable.
        """
        # Try to find update-all in common locations
        common_paths = [
            "/usr/local/bin/update-all",
            "/usr/bin/update-all",
            str(Path.home() / ".local" / "bin" / "update-all"),
        ]

        for path in common_paths:
            if Path(path).exists():
                return path

        # Fall back to assuming it's in PATH
        return "update-all"

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run a systemctl command.

        Args:
            *args: Arguments to pass to systemctl.
            check: If True, raise an exception on non-zero exit code.

        Returns:
            CompletedProcess with the result.

        Raises:
            ScheduleError: If the command fails and check is True.
        """
        cmd = ["systemctl"]
        if self.user_mode:
            cmd.append("--user")
        cmd.extend(args)

        logger.debug("running_systemctl", command=cmd)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise ScheduleError(f"systemctl command failed: {e.stderr}") from e
        except FileNotFoundError as e:
            raise ScheduleError("systemctl not found. Is systemd installed?") from e

    def enable(
        self,
        schedule: str | ScheduleInterval = ScheduleInterval.WEEKLY,
        randomized_delay_sec: int = 3600,
    ) -> None:
        """Enable scheduled updates.

        Args:
            schedule: Schedule interval or custom OnCalendar value.
            randomized_delay_sec: Random delay to add to scheduled time.

        Raises:
            ScheduleError: If enabling fails.
        """
        # Convert ScheduleInterval to string if needed
        if isinstance(schedule, ScheduleInterval):
            calendar_value = INTERVAL_TO_CALENDAR[schedule]
        else:
            calendar_value = schedule

        # Create unit directory if needed
        self.unit_dir.mkdir(parents=True, exist_ok=True)

        # Write timer unit
        timer_content = self.TIMER_TEMPLATE.format(
            schedule=calendar_value,
        )
        # Update RandomizedDelaySec if different from default
        if randomized_delay_sec != 3600:
            timer_content = timer_content.replace(
                "RandomizedDelaySec=3600",
                f"RandomizedDelaySec={randomized_delay_sec}",
            )
        self.timer_path.write_text(timer_content)
        logger.info("timer_unit_created", path=str(self.timer_path))

        # Write service unit
        service_content = self.SERVICE_TEMPLATE.format(
            update_all_path=self._get_update_all_path(),
        )
        self.service_path.write_text(service_content)
        logger.info("service_unit_created", path=str(self.service_path))

        # Reload systemd daemon
        self._systemctl("daemon-reload")

        # Enable and start the timer
        self._systemctl("enable", "--now", self.timer_name)

        logger.info("schedule_enabled", schedule=calendar_value)

    def disable(self) -> None:
        """Disable scheduled updates.

        Raises:
            ScheduleError: If disabling fails.
        """
        # Stop and disable the timer (timer might not exist, which is fine)
        with contextlib.suppress(ScheduleError):
            self._systemctl("disable", "--now", self.timer_name, check=False)
            logger.info("schedule_disabled")

    def get_status(self) -> ScheduleStatus:
        """Get the current schedule status.

        Returns:
            ScheduleStatus with current state.
        """
        # Check if timer is enabled
        result = self._systemctl("is-enabled", self.timer_name, check=False)
        enabled = result.returncode == 0

        # Check if timer is active
        result = self._systemctl("is-active", self.timer_name, check=False)
        active = result.returncode == 0

        # Get timer details
        schedule = None
        next_run = None
        last_run = None

        if enabled or active:
            # Get timer properties
            result = self._systemctl(
                "show",
                self.timer_name,
                "--property=TimersCalendar,NextElapseUSecRealtime,LastTriggerUSec",
                check=False,
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        if key == "TimersCalendar" and value:
                            # Extract schedule from TimersCalendar value
                            # (e.g., "OnCalendar=weekly { ... }" -> "weekly")
                            schedule = value.split("{")[0].strip()
                        elif key == "NextElapseUSecRealtime" and value:
                            next_run = self._parse_usec_timestamp(value)
                        elif key == "LastTriggerUSec" and value:
                            last_run = self._parse_usec_timestamp(value)

        # Get last service result
        last_result = None
        result = self._systemctl(
            "show",
            self.service_name,
            "--property=Result",
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line.startswith("Result="):
                    last_result = line.split("=", 1)[1]

        return ScheduleStatus(
            enabled=enabled,
            active=active,
            schedule=schedule,
            next_run=next_run,
            last_run=last_run,
            last_result=last_result,
        )

    def _parse_usec_timestamp(self, value: str) -> datetime | None:
        """Parse a microsecond timestamp from systemd.

        Args:
            value: Timestamp string in microseconds.

        Returns:
            datetime if parseable, None otherwise.
        """
        try:
            # systemd returns timestamps in microseconds since epoch
            usec = int(value)
            if usec > 0:
                return datetime.fromtimestamp(usec / 1_000_000)
        except (ValueError, OSError):
            pass
        return None

    def run_now(self) -> None:
        """Trigger an immediate update run.

        Raises:
            ScheduleError: If triggering fails.
        """
        self._systemctl("start", self.service_name)
        logger.info("manual_run_triggered")

    def get_logs(self, lines: int = 50) -> str:
        """Get recent logs from the update service.

        Args:
            lines: Number of log lines to retrieve.

        Returns:
            Log output as a string.
        """
        cmd = ["journalctl"]
        if self.user_mode:
            cmd.append("--user")
        cmd.extend(["-u", self.service_name, "-n", str(lines), "--no-pager"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout
        except FileNotFoundError:
            return "journalctl not found"

    def cleanup(self) -> None:
        """Remove all schedule-related files.

        This disables the schedule and removes the unit files.
        """
        self.disable()

        # Remove unit files
        if self.timer_path.exists():
            self.timer_path.unlink()
            logger.info("timer_unit_removed", path=str(self.timer_path))

        if self.service_path.exists():
            self.service_path.unlink()
            logger.info("service_unit_removed", path=str(self.service_path))

        # Reload daemon
        with contextlib.suppress(ScheduleError):
            self._systemctl("daemon-reload", check=False)


def get_schedule_manager(user_mode: bool = True) -> ScheduleManager:
    """Get a schedule manager instance.

    Args:
        user_mode: If True, use user systemd units.

    Returns:
        Configured ScheduleManager.
    """
    return ScheduleManager(user_mode=user_mode)

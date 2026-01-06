"""Sudo pre-authentication utilities.

This module provides utilities for handling sudo authentication before
streaming operations begin. This prevents sudo password prompts from
blocking the streaming output.

Phase 3 - UI Integration (Section 7.3.3)
See docs/update-all-architecture-refinement-plan.md
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

logger = structlog.get_logger(__name__)


class SudoStatus(str, Enum):
    """Status of sudo authentication."""

    AUTHENTICATED = "authenticated"
    """Sudo credentials are cached and valid."""

    NOT_AUTHENTICATED = "not_authenticated"
    """Sudo credentials are not cached."""

    NOT_AVAILABLE = "not_available"
    """Sudo is not available on this system."""

    PASSWORD_REQUIRED = "password_required"
    """Sudo requires a password (not cached)."""

    NO_SUDO_REQUIRED = "no_sudo_required"
    """User is root or sudo is not needed."""


@dataclass
class SudoCheckResult:
    """Result of checking sudo status."""

    status: SudoStatus
    message: str = ""
    user: str | None = None


async def check_sudo_status() -> SudoCheckResult:
    """Check the current sudo authentication status.

    This function checks if sudo credentials are cached and valid,
    without prompting for a password.

    Returns:
        SudoCheckResult with the current status.
    """
    log = logger.bind(component="sudo_check")

    # Check if running as root
    if os.geteuid() == 0:
        log.debug("running_as_root")
        return SudoCheckResult(
            status=SudoStatus.NO_SUDO_REQUIRED,
            message="Running as root",
            user="root",
        )

    # Check if sudo is available
    if not shutil.which("sudo"):
        log.warning("sudo_not_found")
        return SudoCheckResult(
            status=SudoStatus.NOT_AVAILABLE,
            message="sudo command not found",
        )

    # Try to check if sudo is cached using -n (non-interactive)
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            "-v",  # Validate cached credentials
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            log.debug("sudo_cached")
            return SudoCheckResult(
                status=SudoStatus.AUTHENTICATED,
                message="Sudo credentials are cached",
            )
        else:
            # Check if password is required
            if "password is required" in stderr_str.lower():
                log.debug("sudo_password_required")
                return SudoCheckResult(
                    status=SudoStatus.PASSWORD_REQUIRED,
                    message="Sudo password required",
                )
            else:
                log.debug("sudo_not_authenticated", stderr=stderr_str)
                return SudoCheckResult(
                    status=SudoStatus.NOT_AUTHENTICATED,
                    message=stderr_str or "Sudo not authenticated",
                )

    except TimeoutError:
        log.warning("sudo_check_timeout")
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message="Sudo check timed out",
        )
    except Exception as e:
        log.exception("sudo_check_error", error=str(e))
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message=f"Error checking sudo: {e}",
        )


async def ensure_sudo_authenticated(
    on_password_prompt: Callable[[str], str] | None = None,
    timeout: float = 60.0,
) -> SudoCheckResult:
    """Ensure sudo is authenticated before proceeding.

    This function checks if sudo credentials are cached. If not, it can
    optionally prompt for a password using the provided callback.

    Args:
        on_password_prompt: Optional callback to get password from user.
            The callback receives a prompt message and should return the password.
            If None, the function will return PASSWORD_REQUIRED status.
        timeout: Timeout for the authentication process in seconds.

    Returns:
        SudoCheckResult with the final status.
    """
    log = logger.bind(component="sudo_auth")

    # First check current status
    result = await check_sudo_status()

    if result.status in (SudoStatus.AUTHENTICATED, SudoStatus.NO_SUDO_REQUIRED):
        return result

    if result.status == SudoStatus.NOT_AVAILABLE:
        return result

    # Password is required
    if on_password_prompt is None:
        log.info("sudo_password_required_no_callback")
        return SudoCheckResult(
            status=SudoStatus.PASSWORD_REQUIRED,
            message="Sudo password required but no prompt callback provided",
        )

    # Get password from callback
    log.info("prompting_for_sudo_password")
    try:
        password = on_password_prompt("Enter sudo password: ")
    except Exception as e:
        log.exception("password_prompt_error", error=str(e))
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message=f"Error getting password: {e}",
        )

    if not password:
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message="No password provided",
        )

    # Try to authenticate with the password
    try:
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-S",  # Read password from stdin
            "-v",  # Validate and cache credentials
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send password followed by newline
        password_bytes = (password + "\n").encode("utf-8")

        _, stderr = await asyncio.wait_for(
            process.communicate(input=password_bytes),
            timeout=timeout,
        )
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if process.returncode == 0:
            log.info("sudo_authenticated_successfully")
            return SudoCheckResult(
                status=SudoStatus.AUTHENTICATED,
                message="Sudo authenticated successfully",
            )
        else:
            log.warning("sudo_authentication_failed", stderr=stderr_str)
            return SudoCheckResult(
                status=SudoStatus.NOT_AUTHENTICATED,
                message=stderr_str or "Authentication failed",
            )

    except TimeoutError:
        log.warning("sudo_authentication_timeout")
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message="Sudo authentication timed out",
        )
    except Exception as e:
        log.exception("sudo_authentication_error", error=str(e))
        return SudoCheckResult(
            status=SudoStatus.NOT_AUTHENTICATED,
            message=f"Error during authentication: {e}",
        )


async def refresh_sudo_timestamp() -> bool:
    """Refresh the sudo timestamp to extend the cached credentials.

    This should be called periodically during long-running operations
    to prevent the sudo cache from expiring.

    Returns:
        True if the timestamp was refreshed successfully.
    """
    log = logger.bind(component="sudo_refresh")

    try:
        process = await asyncio.create_subprocess_exec(
            "sudo",
            "-n",
            "-v",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await asyncio.wait_for(process.communicate(), timeout=5.0)

        if process.returncode == 0:
            log.debug("sudo_timestamp_refreshed")
            return True
        else:
            log.debug("sudo_timestamp_refresh_failed")
            return False

    except Exception as e:
        log.warning("sudo_timestamp_refresh_error", error=str(e))
        return False


class SudoKeepAlive:
    """Background task that keeps sudo credentials alive.

    This class runs a background task that periodically refreshes
    the sudo timestamp to prevent credential expiration during
    long-running operations.
    """

    def __init__(self, interval_seconds: float = 60.0) -> None:
        """Initialize the keep-alive.

        Args:
            interval_seconds: How often to refresh the timestamp.
        """
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._log = logger.bind(component="sudo_keepalive")

    async def start(self) -> None:
        """Start the keep-alive background task."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._keepalive_loop())
        self._log.debug("started", interval=self.interval_seconds)

    async def stop(self) -> None:
        """Stop the keep-alive background task."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        self._log.debug("stopped")

    async def _keepalive_loop(self) -> None:
        """Background loop that refreshes sudo timestamp."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                if self._running:
                    await refresh_sudo_timestamp()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log.warning("keepalive_error", error=str(e))

    async def __aenter__(self) -> SudoKeepAlive:
        """Context manager entry."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        """Context manager exit."""
        await self.stop()

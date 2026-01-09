"""PTY session manager for managing multiple PTY sessions.

This module provides a PTYSessionManager class that creates and manages
multiple PTYSession instances, routing I/O between PTY and UI components.

Phase 1 - Core PTY Infrastructure
See docs/interactive-tabs-implementation-plan.md section 3.2.3
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from typing import TYPE_CHECKING

from ui.pty_session import PTYReadTimeoutError, PTYSession

if TYPE_CHECKING:
    import signal
    from collections.abc import Callable
    from types import TracebackType


class SessionNotFoundError(Exception):
    """Raised when a session is not found."""


class PTYSessionManager:
    """Manager for multiple PTY sessions.

    This class provides:
    - Creation and management of PTYSession instances
    - I/O routing between PTY and UI components
    - Concurrent session management
    - Cleanup on app exit

    Example:
        async with PTYSessionManager() as manager:
            await manager.create_session("apt", ["/bin/bash"])
            await manager.write_to_session("apt", b"apt update\\n")
            output = await manager.read_from_session("apt", timeout=1.0)
    """

    def __init__(
        self,
        *,
        default_cols: int = 80,
        default_rows: int = 24,
        on_output: Callable[[str, bytes], None] | None = None,
        on_exit: Callable[[str, int | None], None] | None = None,
    ) -> None:
        """Initialize the session manager.

        Args:
            default_cols: Default terminal width for new sessions.
            default_rows: Default terminal height for new sessions.
            on_output: Callback for session output (session_id, data).
            on_exit: Callback for session exit (session_id, exit_code).
        """
        self._default_cols = default_cols
        self._default_rows = default_rows
        self._on_output = on_output
        self._on_exit = on_exit

        self._sessions: dict[str, PTYSession] = {}
        self._read_tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    @property
    def default_cols(self) -> int:
        """Get the default terminal width."""
        return self._default_cols

    @property
    def default_rows(self) -> int:
        """Get the default terminal height."""
        return self._default_rows

    @property
    def session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    @property
    def session_ids(self) -> list[str]:
        """Get the list of active session IDs."""
        return list(self._sessions.keys())

    async def create_session(
        self,
        command: list[str],
        *,
        session_id: str | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        cols: int | None = None,
        rows: int | None = None,
    ) -> str:
        """Create a new PTY session.

        Args:
            command: Command and arguments to run in the PTY.
            session_id: Unique identifier for the session (auto-generated if None).
            env: Environment variables to set.
            cwd: Working directory for the subprocess.
            cols: Terminal width (uses default if None).
            rows: Terminal height (uses default if None).

        Returns:
            The session ID.
        """
        if session_id is None:
            session_id = str(uuid.uuid4())

        session = PTYSession(
            command,
            env=env,
            cwd=cwd,
            cols=cols or self._default_cols,
            rows=rows or self._default_rows,
        )

        await session.start()

        async with self._lock:
            self._sessions[session_id] = session

        return session_id

    def get_session(self, session_id: str) -> PTYSession | None:
        """Get a session by ID.

        Args:
            session_id: The session ID.

        Returns:
            The session, or None if not found.
        """
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        """Close a specific session.

        Args:
            session_id: The session ID to close.
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            read_task = self._read_tasks.pop(session_id, None)

        if read_task is not None:
            read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await read_task

        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        """Close all sessions."""
        async with self._lock:
            session_ids = list(self._sessions.keys())

        for session_id in session_ids:
            await self.close_session(session_id)

    async def write_to_session(self, session_id: str, data: bytes) -> None:
        """Write data to a session.

        Args:
            session_id: The session ID.
            data: Data to write.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        await session.write(data)

    async def read_from_session(
        self,
        session_id: str,
        *,
        size: int = 4096,
        timeout: float | None = None,
    ) -> bytes:
        """Read data from a session.

        Args:
            session_id: The session ID.
            size: Maximum bytes to read.
            timeout: Timeout in seconds.

        Returns:
            Data read from the session.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
            PTYReadTimeoutError: If the read times out.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        return await session.read(size=size, timeout=timeout)

    async def resize_session(self, session_id: str, cols: int, rows: int) -> None:
        """Resize a session's terminal.

        Args:
            session_id: The session ID.
            cols: New terminal width.
            rows: New terminal height.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        await session.resize(cols=cols, rows=rows)

    async def resize_all(self, cols: int, rows: int) -> None:
        """Resize all sessions' terminals.

        Args:
            cols: New terminal width.
            rows: New terminal height.
        """
        for session_id in list(self._sessions.keys()):
            with contextlib.suppress(SessionNotFoundError):
                await self.resize_session(session_id, cols, rows)

    async def send_signal(self, session_id: str, sig: signal.Signals) -> None:
        """Send a signal to a session's process.

        Args:
            session_id: The session ID.
            sig: Signal to send.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        await session.send_signal(sig)

    async def start_reading(self, session_id: str) -> None:
        """Start a background task to read from a session.

        This will call the on_output callback for each chunk of data read,
        and the on_exit callback when the session exits.

        Args:
            session_id: The session ID.

        Raises:
            SessionNotFoundError: If the session doesn't exist.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        if session_id in self._read_tasks:
            return  # Already reading

        task = asyncio.create_task(self._read_loop(session_id))
        self._read_tasks[session_id] = task

    async def _read_loop(self, session_id: str) -> None:
        """Background task to read from a session.

        Args:
            session_id: The session ID.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return

        try:
            # Read output while process is running or has remaining data
            # Use a flag to track if we've read any data
            read_attempts = 0
            max_empty_reads = 3  # Allow a few empty reads after process exits

            while True:
                # Check if process is still running
                is_running = session.is_running

                try:
                    data = await session.read(timeout=0.1)
                    if data:
                        read_attempts = 0  # Reset counter on successful read
                        if self._on_output:
                            self._on_output(session_id, data)
                    elif not is_running:
                        # Process exited and no data - increment counter
                        read_attempts += 1
                        if read_attempts >= max_empty_reads:
                            break
                except PTYReadTimeoutError:
                    if not is_running:
                        # Process exited and no more data available
                        read_attempts += 1
                        if read_attempts >= max_empty_reads:
                            break
                    # If still running, just continue the loop
                    continue
                except Exception:
                    # Other error - exit the loop
                    break

            # Wait for process to fully exit and get exit code
            # This handles fast-exiting commands where process may have
            # exited before we started reading
            with contextlib.suppress(Exception):
                await session.wait(timeout=0.5)

            # Session has exited - call exit callback
            if self._on_exit:
                self._on_exit(session_id, session.exit_code)

        except asyncio.CancelledError:
            pass

    async def __aenter__(self) -> PTYSessionManager:
        """Enter async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager."""
        await self.close_all()

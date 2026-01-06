"""PTY session wrapper for interactive terminal tabs.

This module provides a PTYSession class that wraps ptyprocess for PTY management,
providing an async read/write interface for terminal I/O.

Phase 1 - Core PTY Infrastructure
See docs/interactive-tabs-implementation-plan.md section 3.2.2
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import signal
    from types import TracebackType

    import ptyprocess  # type: ignore[import-untyped]


class PTYError(Exception):
    """Base exception for PTY-related errors."""


class PTYReadTimeoutError(PTYError):
    """Raised when a read operation times out."""


class PTYNotStartedError(PTYError):
    """Raised when trying to use a PTY session that hasn't been started."""


class PTYAlreadyStartedError(PTYError):
    """Raised when trying to start a PTY session that's already running."""


def is_pty_available() -> bool:
    """Check if PTY is available on this platform.

    Returns:
        True if PTY can be allocated, False otherwise.
    """
    if sys.platform == "win32":
        # Windows: PTY not supported, fall back to non-interactive mode
        return False

    # Unix-like systems: check if we can allocate a PTY
    try:
        import pty

        master, slave = pty.openpty()
        os.close(master)
        os.close(slave)
        return True
    except (ImportError, OSError):
        return False


class PTYSession:
    """Wrapper for PTY subprocess management with async I/O.

    This class provides:
    - PTY allocation and subprocess spawning
    - Async read/write interface
    - Process lifecycle management (start, stop, signal)
    - Terminal size synchronization

    Example:
        async with PTYSession(["/bin/bash"]) as session:
            await session.write(b"echo hello\\n")
            output = await session.read(timeout=1.0)
            print(output.decode())
    """

    def __init__(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> None:
        """Initialize a PTY session.

        Args:
            command: Command and arguments to run in the PTY.
            env: Environment variables to set (merged with current env).
            cwd: Working directory for the subprocess.
            cols: Initial terminal width in columns.
            rows: Initial terminal height in rows.
        """
        self._command = command
        self._env = env
        self._cwd = cwd
        self._cols = cols
        self._rows = rows

        self._process: ptyprocess.PtyProcess | None = None
        self._exit_code: int | None = None
        self._closed = False
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def pid(self) -> int | None:
        """Get the process ID of the subprocess."""
        if self._process is None:
            return None
        return int(self._process.pid)

    @property
    def is_running(self) -> bool:
        """Check if the subprocess is still running."""
        if self._process is None:
            return False
        return bool(self._process.isalive())

    @property
    def exit_code(self) -> int | None:
        """Get the exit code of the subprocess, or None if still running."""
        if self._process is None:
            return self._exit_code
        if self._process.isalive():
            return None
        # Cache the exit code
        if self._exit_code is None:
            self._exit_code = self._process.exitstatus
            if self._exit_code is None:
                # Process was killed by signal
                self._exit_code = self._process.signalstatus
                if self._exit_code is not None:
                    self._exit_code = -self._exit_code
        return self._exit_code

    @property
    def cols(self) -> int:
        """Get the current terminal width in columns."""
        return self._cols

    @property
    def rows(self) -> int:
        """Get the current terminal height in rows."""
        return self._rows

    async def start(self) -> None:
        """Start the PTY session and spawn the subprocess.

        Raises:
            PTYAlreadyStartedError: If the session is already started.
            PTYError: If PTY allocation fails.
        """
        if self._process is not None:
            raise PTYAlreadyStartedError("PTY session already started")

        # Import here to allow graceful fallback on Windows
        try:
            import ptyprocess
        except ImportError as e:
            raise PTYError("ptyprocess not available") from e

        # Prepare environment
        env = os.environ.copy()
        if self._env:
            env.update(self._env)

        # Spawn the process
        try:
            self._process = ptyprocess.PtyProcess.spawn(
                self._command,
                env=env,
                cwd=self._cwd,
                dimensions=(self._rows, self._cols),
            )
        except Exception as e:
            raise PTYError(f"Failed to spawn PTY process: {e}") from e

    async def read(self, size: int = 4096, timeout: float | None = None) -> bytes:
        """Read data from the PTY.

        Args:
            size: Maximum number of bytes to read.
            timeout: Timeout in seconds, or None for no timeout.

        Returns:
            Bytes read from the PTY.

        Raises:
            PTYNotStartedError: If the session hasn't been started.
            PTYReadTimeoutError: If the read times out.
        """
        if self._process is None:
            raise PTYNotStartedError("PTY session not started")

        async with self._read_lock:
            loop = asyncio.get_event_loop()
            process = self._process  # Capture for closure

            def _read() -> bytes:
                try:
                    result = process.read(size)
                    return bytes(result) if result else b""
                except EOFError:
                    return b""

            try:
                if timeout is not None:
                    return await asyncio.wait_for(
                        loop.run_in_executor(None, _read),
                        timeout=timeout,
                    )
                else:
                    return await loop.run_in_executor(None, _read)
            except TimeoutError as e:
                raise PTYReadTimeoutError("Read operation timed out") from e

    async def write(self, data: bytes) -> None:
        """Write data to the PTY.

        Args:
            data: Bytes to write to the PTY.

        Raises:
            PTYNotStartedError: If the session hasn't been started.
        """
        if self._process is None:
            raise PTYNotStartedError("PTY session not started")

        async with self._write_lock:
            loop = asyncio.get_event_loop()

            def _write() -> None:
                self._process.write(data)  # type: ignore[union-attr]

            await loop.run_in_executor(None, _write)

    async def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY terminal.

        This sends SIGWINCH to the subprocess to notify it of the size change.

        Args:
            cols: New terminal width in columns.
            rows: New terminal height in rows.

        Raises:
            PTYNotStartedError: If the session hasn't been started.
        """
        if self._process is None:
            raise PTYNotStartedError("PTY session not started")

        self._cols = cols
        self._rows = rows
        self._process.setwinsize(rows, cols)

    async def send_signal(self, sig: signal.Signals) -> None:
        """Send a signal to the subprocess.

        Args:
            sig: Signal to send (e.g., signal.SIGTERM).

        Raises:
            PTYNotStartedError: If the session hasn't been started.
        """
        if self._process is None:
            raise PTYNotStartedError("PTY session not started")

        self._process.kill(sig)

    async def wait(self, timeout: float | None = None) -> int:
        """Wait for the subprocess to exit.

        Args:
            timeout: Timeout in seconds, or None for no timeout.

        Returns:
            Exit code of the subprocess.

        Raises:
            PTYNotStartedError: If the session hasn't been started.
            TimeoutError: If the wait times out.
        """
        if self._process is None:
            raise PTYNotStartedError("PTY session not started")

        loop = asyncio.get_event_loop()

        def _wait() -> int:
            self._process.wait()  # type: ignore[union-attr]
            return self.exit_code or 0

        if timeout is not None:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _wait),
                timeout=timeout,
            )
        else:
            return await loop.run_in_executor(None, _wait)

    async def close(self) -> None:
        """Close the PTY session and terminate the subprocess.

        This method is idempotent - it can be called multiple times safely.
        """
        if self._closed:
            return

        self._closed = True

        if self._process is None:
            return

        # Try to terminate gracefully first
        if self._process.isalive():
            try:
                self._process.terminate(force=False)
                # Give it a moment to exit
                await asyncio.sleep(0.1)
            except Exception:
                pass

        # Force kill if still alive
        if self._process.isalive():
            with contextlib.suppress(Exception):
                self._process.terminate(force=True)

        # Close the PTY file descriptor
        with contextlib.suppress(Exception):
            self._process.close()

        # Cache exit code before clearing process
        _ = self.exit_code
        self._process = None

    async def __aenter__(self) -> PTYSession:
        """Enter async context manager."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit async context manager."""
        await self.close()

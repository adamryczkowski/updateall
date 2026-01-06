"""Tests for PTYSession - PTY session wrapper for interactive terminal tabs.

Phase 1 - Core PTY Infrastructure
See docs/interactive-tabs-implementation-plan.md section 5.2.1
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

import pytest

# Skip all tests on Windows where PTY is not available
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="PTY not available on Windows",
)


class TestPTYSessionCreation:
    """Tests for PTY session creation and initialization."""

    @pytest.mark.asyncio
    async def test_create_session_with_command(self) -> None:
        """Test creating a PTY session with a command."""
        from ui.pty_session import PTYSession

        # Given: A command to run
        command = ["/bin/echo", "hello"]

        # When: Creating a PTY session
        session = PTYSession(command)
        await session.start()

        try:
            # Then: Session should be created with PTY allocated
            assert session.is_running or session.exit_code is not None
            assert session.pid is not None
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_create_session_with_environment(self) -> None:
        """Test creating a PTY session with custom environment."""
        from ui.pty_session import PTYSession

        # Given: Custom environment variables
        env = {"MY_TEST_VAR": "test_value_12345"}
        command = ["/bin/sh", "-c", "echo $MY_TEST_VAR"]

        # When: Creating a PTY session
        session = PTYSession(command, env=env)
        await session.start()

        try:
            # Then: Environment should be passed to subprocess
            output = await session.read(timeout=2.0)
            assert b"test_value_12345" in output
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_create_session_with_working_directory(self) -> None:
        """Test creating a PTY session with custom working directory."""
        from ui.pty_session import PTYSession

        # Given: A working directory path
        cwd = "/tmp"
        command = ["/bin/pwd"]

        # When: Creating a PTY session
        session = PTYSession(command, cwd=cwd)
        await session.start()

        try:
            # Then: Process should start in specified directory
            output = await session.read(timeout=2.0)
            assert b"/tmp" in output
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_create_session_with_dimensions(self) -> None:
        """Test creating a PTY session with custom terminal dimensions."""
        from ui.pty_session import PTYSession

        # Given: Custom terminal dimensions
        cols, rows = 120, 40
        command = ["/bin/stty", "size"]

        # When: Creating a PTY session with dimensions
        session = PTYSession(command, cols=cols, rows=rows)
        await session.start()

        try:
            # Then: PTY should have the specified dimensions
            output = await session.read(timeout=2.0)
            # stty size outputs "rows cols"
            assert b"40 120" in output
        finally:
            await session.close()


class TestPTYSessionIO:
    """Tests for PTY session I/O operations."""

    @pytest.mark.asyncio
    async def test_read_output_from_command(self) -> None:
        """Test reading output from a running command."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running 'echo hello'
        session = PTYSession(["/bin/echo", "hello"])
        await session.start()

        try:
            # When: Reading from the session
            output = await session.read(timeout=2.0)

            # Then: Should receive 'hello' in output
            assert b"hello" in output
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_write_input_to_command(self) -> None:
        """Test writing input to a running command."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running 'cat'
        session = PTYSession(["/bin/cat"])
        await session.start()

        try:
            # When: Writing 'test' to stdin
            await session.write(b"test\n")

            # Then: Should receive 'test' echoed back
            output = await session.read(timeout=2.0)
            assert b"test" in output
        finally:
            # Send EOF to terminate cat
            await session.write(b"\x04")  # Ctrl+D
            await session.close()

    @pytest.mark.asyncio
    async def test_read_timeout_handling(self) -> None:
        """Test handling read timeout."""
        from ui.pty_session import PTYReadTimeoutError, PTYSession

        # Given: A PTY session with no output (sleep command)
        session = PTYSession(["/bin/sleep", "10"])
        await session.start()

        try:
            # When: Reading with short timeout
            # Then: Should raise TimeoutError or return empty
            with pytest.raises(PTYReadTimeoutError):
                await session.read(timeout=0.1)
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_concurrent_read_write(self) -> None:
        """Test concurrent read and write operations."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running interactive command
        session = PTYSession(["/bin/cat"])
        await session.start()

        try:
            # When: Reading and writing concurrently
            async def write_task() -> None:
                for i in range(3):
                    await session.write(f"line{i}\n".encode())
                    await asyncio.sleep(0.1)
                await session.write(b"\x04")  # Ctrl+D to end

            async def read_task() -> bytes:
                output = b""
                for _ in range(10):  # Max iterations to prevent infinite loop
                    try:
                        chunk = await session.read(timeout=0.5)
                        output += chunk
                        if b"line2" in output:
                            break
                    except Exception:
                        break
                return output

            # Then: Both operations should complete without deadlock
            write_future = asyncio.create_task(write_task())
            read_future = asyncio.create_task(read_task())

            output = await asyncio.wait_for(
                asyncio.gather(write_future, read_future),
                timeout=5.0,
            )

            assert b"line0" in output[1]
            assert b"line1" in output[1]
            assert b"line2" in output[1]
        finally:
            await session.close()


class TestPTYSessionLifecycle:
    """Tests for PTY session lifecycle management."""

    @pytest.mark.asyncio
    async def test_session_cleanup_on_close(self) -> None:
        """Test that resources are cleaned up on close."""
        from ui.pty_session import PTYSession

        # Given: An active PTY session
        session = PTYSession(["/bin/sleep", "100"])
        await session.start()
        pid = session.pid

        # When: Closing the session
        await session.close()

        # Then: PTY and process should be terminated
        assert not session.is_running
        # Check that the process is no longer running
        try:
            os.kill(pid, 0)  # type: ignore[arg-type]
            pytest.fail("Process should have been terminated")
        except OSError:
            pass  # Expected - process doesn't exist

    @pytest.mark.asyncio
    async def test_session_handles_process_exit(self) -> None:
        """Test handling of process exit."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running 'exit 0'
        session = PTYSession(["/bin/sh", "-c", "exit 0"])
        await session.start()

        try:
            # When: Process exits
            await session.wait(timeout=2.0)

            # Then: Session should report exit status
            assert session.exit_code == 0
            assert not session.is_running
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_session_handles_nonzero_exit(self) -> None:
        """Test handling of non-zero exit code."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running 'exit 42'
        session = PTYSession(["/bin/sh", "-c", "exit 42"])
        await session.start()

        try:
            # When: Process exits with non-zero code
            await session.wait(timeout=2.0)

            # Then: Session should report correct exit status
            assert session.exit_code == 42
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_send_signal_to_process(self) -> None:
        """Test sending signals to the subprocess."""
        from ui.pty_session import PTYSession

        # Given: A PTY session running 'sleep 100'
        session = PTYSession(["/bin/sleep", "100"])
        await session.start()

        try:
            # When: Sending SIGTERM
            await session.send_signal(signal.SIGTERM)

            # Then: Process should terminate
            await session.wait(timeout=2.0)
            assert not session.is_running
            # SIGTERM causes exit code to be -15 or 128+15=143
            assert session.exit_code is not None
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        """Test that close can be called multiple times safely."""
        from ui.pty_session import PTYSession

        # Given: A PTY session
        session = PTYSession(["/bin/echo", "test"])
        await session.start()

        # When: Closing multiple times
        await session.close()
        await session.close()  # Should not raise
        await session.close()  # Should not raise

        # Then: Session should be closed
        assert not session.is_running


class TestPTYSessionResize:
    """Tests for PTY terminal resize."""

    @pytest.mark.asyncio
    async def test_resize_terminal(self) -> None:
        """Test resizing the terminal."""
        from ui.pty_session import PTYSession

        # Given: A PTY session with 80x24 size
        session = PTYSession(["/bin/cat"], cols=80, rows=24)
        await session.start()

        try:
            # When: Resizing to 120x40
            await session.resize(cols=120, rows=40)

            # Then: PTY should report new size
            assert session.cols == 120
            assert session.rows == 40
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_resize_sends_sigwinch(self) -> None:
        """Test that resize sends SIGWINCH to process.

        This test verifies that resize() works correctly and the process
        continues running after receiving the signal. We don't verify
        the output because SIGWINCH handling is timing-sensitive.
        """
        from ui.pty_session import PTYSession

        # Given: A session running a long-running command
        session = PTYSession(["/bin/sh", "-c", "sleep 5"], cols=80, rows=24)
        await session.start()

        try:
            # Give the shell time to start
            await asyncio.sleep(0.1)

            # When: Resizing the terminal
            await session.resize(cols=100, rows=50)

            # Then: Process should still be running (resize doesn't kill it)
            assert session.is_running

            # And: The session should report the new size
            assert session.cols == 100
            assert session.rows == 50
        finally:
            await session.close()


class TestPTYAvailability:
    """Tests for PTY availability checking."""

    def test_is_pty_available_on_unix(self) -> None:
        """Test PTY availability check on Unix systems."""
        from ui.pty_session import is_pty_available

        # On Unix-like systems, PTY should be available
        if sys.platform != "win32":
            assert is_pty_available() is True

    def test_is_pty_available_returns_bool(self) -> None:
        """Test that is_pty_available returns a boolean."""
        from ui.pty_session import is_pty_available

        result = is_pty_available()
        assert isinstance(result, bool)


class TestPTYSessionContextManager:
    """Tests for PTY session context manager support."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using PTYSession as async context manager."""
        from ui.pty_session import PTYSession

        # Given/When: Using PTYSession as context manager
        async with PTYSession(["/bin/echo", "hello"]) as session:
            output = await session.read(timeout=2.0)
            assert b"hello" in output

        # Then: Session should be closed after exiting context
        assert not session.is_running

    @pytest.mark.asyncio
    async def test_context_manager_handles_exception(self) -> None:
        """Test that context manager cleans up on exception."""
        from ui.pty_session import PTYSession

        session: PTYSession | None = None

        with pytest.raises(ValueError, match="test error"):
            async with PTYSession(["/bin/sleep", "100"]) as s:
                session = s
                pid = session.pid
                raise ValueError("test error")

        # Then: Session should be closed even after exception
        assert session is not None
        assert not session.is_running
        # Process should be terminated
        try:
            os.kill(pid, 0)  # type: ignore[arg-type]
            pytest.fail("Process should have been terminated")
        except OSError:
            pass  # Expected

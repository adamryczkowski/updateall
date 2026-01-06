"""Tests for PTYSessionManager - manages multiple PTY sessions.

Phase 1 - Core PTY Infrastructure
See docs/interactive-tabs-implementation-plan.md section 5.2.1
"""

from __future__ import annotations

import asyncio
import sys

import pytest

# Skip all tests on Windows where PTY is not available
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="PTY not available on Windows",
)


class TestPTYSessionManagerCreation:
    """Tests for PTYSessionManager creation and initialization."""

    def test_create_manager(self) -> None:
        """Test creating a PTYSessionManager."""
        from ui.pty_manager import PTYSessionManager

        # When: Creating a manager
        manager = PTYSessionManager()

        # Then: Manager should be created with no sessions
        assert manager.session_count == 0
        assert manager.session_ids == []

    def test_manager_with_custom_config(self) -> None:
        """Test creating a manager with custom configuration."""
        from ui.pty_manager import PTYSessionManager

        # When: Creating a manager with custom config
        manager = PTYSessionManager(default_cols=120, default_rows=40)

        # Then: Manager should use custom config
        assert manager.default_cols == 120
        assert manager.default_rows == 40


class TestPTYSessionManagerSessionLifecycle:
    """Tests for session lifecycle management."""

    @pytest.mark.asyncio
    async def test_create_session(self) -> None:
        """Test creating a new PTY session through the manager."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # When: Creating a session
            session_id = await manager.create_session(
                session_id="test-session",
                command=["/bin/echo", "hello"],
            )

            # Then: Session should be created and tracked
            assert session_id == "test-session"
            assert manager.session_count == 1
            assert "test-session" in manager.session_ids
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_create_session_auto_id(self) -> None:
        """Test creating a session with auto-generated ID."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # When: Creating a session without explicit ID
            session_id = await manager.create_session(
                command=["/bin/echo", "hello"],
            )

            # Then: Session should have an auto-generated ID
            assert session_id is not None
            assert len(session_id) > 0
            assert manager.session_count == 1
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_get_session(self) -> None:
        """Test getting a session by ID."""
        from ui.pty_manager import PTYSessionManager
        from ui.pty_session import PTYSession

        manager = PTYSessionManager()

        try:
            # Given: A created session
            await manager.create_session(
                session_id="test-session",
                command=["/bin/cat"],
            )

            # When: Getting the session
            session = manager.get_session("test-session")

            # Then: Should return the session
            assert session is not None
            assert isinstance(session, PTYSession)
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self) -> None:
        """Test getting a session that doesn't exist."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        # When: Getting a non-existent session
        session = manager.get_session("nonexistent")

        # Then: Should return None
        assert session is None

    @pytest.mark.asyncio
    async def test_close_session(self) -> None:
        """Test closing a specific session."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: A created session
            await manager.create_session(
                session_id="test-session",
                command=["/bin/sleep", "100"],
            )
            assert manager.session_count == 1

            # When: Closing the session
            await manager.close_session("test-session")

            # Then: Session should be removed
            assert manager.session_count == 0
            assert "test-session" not in manager.session_ids
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_close_nonexistent_session(self) -> None:
        """Test closing a session that doesn't exist."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        # When: Closing a non-existent session
        # Then: Should not raise
        await manager.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_close_all_sessions(self) -> None:
        """Test closing all sessions."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        # Given: Multiple sessions
        await manager.create_session(
            session_id="session-1",
            command=["/bin/sleep", "100"],
        )
        await manager.create_session(
            session_id="session-2",
            command=["/bin/sleep", "100"],
        )
        await manager.create_session(
            session_id="session-3",
            command=["/bin/sleep", "100"],
        )
        assert manager.session_count == 3

        # When: Closing all sessions
        await manager.close_all()

        # Then: All sessions should be removed
        assert manager.session_count == 0


class TestPTYSessionManagerIO:
    """Tests for I/O routing through the manager."""

    @pytest.mark.asyncio
    async def test_write_to_session(self) -> None:
        """Test writing to a session through the manager."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: A session running cat
            await manager.create_session(
                session_id="test-session",
                command=["/bin/cat"],
            )

            # When: Writing through the manager
            await manager.write_to_session("test-session", b"hello\n")

            # Then: Data should be written
            output = await manager.read_from_session("test-session", timeout=2.0)
            assert b"hello" in output
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_read_from_session(self) -> None:
        """Test reading from a session through the manager."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: A session that produces output
            await manager.create_session(
                session_id="test-session",
                command=["/bin/echo", "test output"],
            )

            # When: Reading through the manager
            output = await manager.read_from_session("test-session", timeout=2.0)

            # Then: Should receive the output
            assert b"test output" in output
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_write_to_nonexistent_session(self) -> None:
        """Test writing to a session that doesn't exist."""
        from ui.pty_manager import PTYSessionManager, SessionNotFoundError

        manager = PTYSessionManager()

        # When: Writing to a non-existent session
        # Then: Should raise SessionNotFoundError
        with pytest.raises(SessionNotFoundError):
            await manager.write_to_session("nonexistent", b"data")

    @pytest.mark.asyncio
    async def test_read_from_nonexistent_session(self) -> None:
        """Test reading from a session that doesn't exist."""
        from ui.pty_manager import PTYSessionManager, SessionNotFoundError

        manager = PTYSessionManager()

        # When: Reading from a non-existent session
        # Then: Should raise SessionNotFoundError
        with pytest.raises(SessionNotFoundError):
            await manager.read_from_session("nonexistent", timeout=1.0)


class TestPTYSessionManagerConcurrency:
    """Tests for concurrent session management."""

    @pytest.mark.asyncio
    async def test_multiple_sessions_concurrent_io(self) -> None:
        """Test concurrent I/O across multiple sessions."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: Multiple sessions
            await manager.create_session(
                session_id="session-1",
                command=["/bin/cat"],
            )
            await manager.create_session(
                session_id="session-2",
                command=["/bin/cat"],
            )

            # When: Writing to both sessions concurrently
            await asyncio.gather(
                manager.write_to_session("session-1", b"hello1\n"),
                manager.write_to_session("session-2", b"hello2\n"),
            )

            # Then: Both should receive their respective data
            output1, output2 = await asyncio.gather(
                manager.read_from_session("session-1", timeout=2.0),
                manager.read_from_session("session-2", timeout=2.0),
            )

            assert b"hello1" in output1
            assert b"hello2" in output2
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_session_isolation(self) -> None:
        """Test that sessions are isolated from each other."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: Two sessions
            await manager.create_session(
                session_id="session-1",
                command=["/bin/cat"],
            )
            await manager.create_session(
                session_id="session-2",
                command=["/bin/cat"],
            )

            # When: Writing to session-1 only
            await manager.write_to_session("session-1", b"secret\n")

            # Then: session-2 should not receive the data
            output1 = await manager.read_from_session("session-1", timeout=2.0)
            assert b"secret" in output1

            # session-2 should timeout with no data
            from ui.pty_session import PTYReadTimeoutError

            with pytest.raises(PTYReadTimeoutError):
                await manager.read_from_session("session-2", timeout=0.2)
        finally:
            await manager.close_all()


class TestPTYSessionManagerResize:
    """Tests for resizing sessions through the manager."""

    @pytest.mark.asyncio
    async def test_resize_session(self) -> None:
        """Test resizing a session through the manager."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: A session
            await manager.create_session(
                session_id="test-session",
                command=["/bin/cat"],
                cols=80,
                rows=24,
            )

            # When: Resizing through the manager
            await manager.resize_session("test-session", cols=120, rows=40)

            # Then: Session should be resized
            session = manager.get_session("test-session")
            assert session is not None
            assert session.cols == 120
            assert session.rows == 40
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_resize_all_sessions(self) -> None:
        """Test resizing all sessions at once."""
        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: Multiple sessions
            await manager.create_session(
                session_id="session-1",
                command=["/bin/cat"],
            )
            await manager.create_session(
                session_id="session-2",
                command=["/bin/cat"],
            )

            # When: Resizing all sessions
            await manager.resize_all(cols=100, rows=50)

            # Then: All sessions should be resized
            session1 = manager.get_session("session-1")
            session2 = manager.get_session("session-2")
            assert session1 is not None and session1.cols == 100
            assert session2 is not None and session2.cols == 100
        finally:
            await manager.close_all()


class TestPTYSessionManagerSignals:
    """Tests for sending signals through the manager."""

    @pytest.mark.asyncio
    async def test_send_signal_to_session(self) -> None:
        """Test sending a signal to a session."""
        import signal

        from ui.pty_manager import PTYSessionManager

        manager = PTYSessionManager()

        try:
            # Given: A session running sleep
            await manager.create_session(
                session_id="test-session",
                command=["/bin/sleep", "100"],
            )

            # When: Sending SIGTERM
            await manager.send_signal("test-session", signal.SIGTERM)

            # Then: Session should terminate
            session = manager.get_session("test-session")
            assert session is not None
            await session.wait(timeout=2.0)
            assert not session.is_running
        finally:
            await manager.close_all()


class TestPTYSessionManagerContextManager:
    """Tests for context manager support."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self) -> None:
        """Test using PTYSessionManager as async context manager."""
        from ui.pty_manager import PTYSessionManager

        # Given/When: Using manager as context manager
        async with PTYSessionManager() as manager:
            await manager.create_session(
                session_id="test-session",
                command=["/bin/echo", "hello"],
            )
            assert manager.session_count == 1

        # Then: All sessions should be closed after exiting context
        assert manager.session_count == 0

    @pytest.mark.asyncio
    async def test_context_manager_handles_exception(self) -> None:
        """Test that context manager cleans up on exception."""
        from ui.pty_manager import PTYSessionManager

        manager: PTYSessionManager | None = None

        with pytest.raises(ValueError, match="test error"):
            async with PTYSessionManager() as m:
                manager = m
                await manager.create_session(
                    session_id="test-session",
                    command=["/bin/sleep", "100"],
                )
                raise ValueError("test error")

        # Then: Sessions should be closed even after exception
        assert manager is not None
        assert manager.session_count == 0


class TestPTYSessionManagerEvents:
    """Tests for session event callbacks."""

    @pytest.mark.asyncio
    async def test_on_session_output_callback(self) -> None:
        """Test callback for session output."""
        from ui.pty_manager import PTYSessionManager

        outputs: list[tuple[str, bytes]] = []

        def on_output(session_id: str, data: bytes) -> None:
            outputs.append((session_id, data))

        manager = PTYSessionManager(on_output=on_output)

        try:
            # Given: A session that produces output
            await manager.create_session(
                session_id="test-session",
                command=["/bin/echo", "callback test"],
            )

            # When: Starting the output reader
            await manager.start_reading("test-session")
            await asyncio.sleep(0.5)

            # Then: Callback should have been called
            assert len(outputs) > 0
            assert any(b"callback test" in data for _, data in outputs)
        finally:
            await manager.close_all()

    @pytest.mark.asyncio
    async def test_on_session_exit_callback(self) -> None:
        """Test callback for session exit."""
        from ui.pty_manager import PTYSessionManager

        exits: list[tuple[str, int | None]] = []

        def on_exit(session_id: str, exit_code: int | None) -> None:
            exits.append((session_id, exit_code))

        manager = PTYSessionManager(on_exit=on_exit)

        try:
            # Given: A session that exits quickly
            await manager.create_session(
                session_id="test-session",
                command=["/bin/sh", "-c", "exit 42"],
            )

            # When: Waiting for the session to exit
            await manager.start_reading("test-session")
            await asyncio.sleep(0.5)

            # Then: Exit callback should have been called
            assert len(exits) > 0
            assert ("test-session", 42) in exits
        finally:
            await manager.close_all()

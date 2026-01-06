"""Tests for TerminalPane container widget.

Phase 4 - Integration
See docs/interactive-tabs-implementation-plan.md
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.terminal_pane import (
    PaneConfig,
    PaneOutputMessage,
    PaneState,
    PaneStateChanged,
    PaneStatusBar,
    TerminalPane,
)


class TestPaneConfig:
    """Tests for PaneConfig dataclass."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = PaneConfig()
        assert config.columns == 80
        assert config.lines == 24
        assert config.scrollback_lines == 10000
        assert config.env == {}
        assert config.cwd is None
        assert config.show_status_bar is True
        assert config.show_scrollbar is True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = PaneConfig(
            columns=120,
            lines=40,
            scrollback_lines=5000,
            env={"TERM": "xterm"},
            cwd="/tmp",
            show_status_bar=False,
            show_scrollbar=False,
        )
        assert config.columns == 120
        assert config.lines == 40
        assert config.scrollback_lines == 5000
        assert config.env == {"TERM": "xterm"}
        assert config.cwd == "/tmp"
        assert config.show_status_bar is False
        assert config.show_scrollbar is False


class TestPaneState:
    """Tests for PaneState enum."""

    def test_state_values(self) -> None:
        """Test that all expected states exist."""
        assert PaneState.IDLE.value == "idle"
        assert PaneState.RUNNING.value == "running"
        assert PaneState.SUCCESS.value == "success"
        assert PaneState.FAILED.value == "failed"
        assert PaneState.EXITED.value == "exited"


class TestPaneOutputMessage:
    """Tests for PaneOutputMessage."""

    def test_message_creation(self) -> None:
        """Test creating a pane output message."""
        msg = PaneOutputMessage("apt", b"Hello, World!")
        assert msg.pane_id == "apt"
        assert msg.data == b"Hello, World!"


class TestPaneStateChanged:
    """Tests for PaneStateChanged message."""

    def test_message_creation_without_exit_code(self) -> None:
        """Test creating a state change message without exit code."""
        msg = PaneStateChanged("apt", PaneState.RUNNING)
        assert msg.pane_id == "apt"
        assert msg.state == PaneState.RUNNING
        assert msg.exit_code is None

    def test_message_creation_with_exit_code(self) -> None:
        """Test creating a state change message with exit code."""
        msg = PaneStateChanged("apt", PaneState.SUCCESS, exit_code=0)
        assert msg.pane_id == "apt"
        assert msg.state == PaneState.SUCCESS
        assert msg.exit_code == 0


class TestPaneStatusBar:
    """Tests for PaneStatusBar widget."""

    def test_status_bar_creation(self) -> None:
        """Test creating a status bar."""
        bar = PaneStatusBar("APT Updates")
        assert bar.pane_name == "APT Updates"
        assert bar.state == PaneState.IDLE
        assert bar.status_message == ""

    def test_status_bar_state_change(self) -> None:
        """Test status bar state changes."""
        bar = PaneStatusBar("APT Updates")
        bar.state = PaneState.RUNNING
        assert bar.state == PaneState.RUNNING

    def test_status_bar_message_update(self) -> None:
        """Test status bar message updates."""
        bar = PaneStatusBar("APT Updates")
        bar.status_message = "Processing..."
        assert bar.status_message == "Processing..."


class TestTerminalPaneCreation:
    """Tests for TerminalPane creation."""

    def test_pane_creation_minimal(self) -> None:
        """Test creating a pane with minimal arguments."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test Pane",
            command=["/bin/echo", "hello"],
        )
        assert pane.pane_id == "test"
        assert pane.pane_name == "Test Pane"
        assert pane.command == ["/bin/echo", "hello"]
        assert pane.state == PaneState.IDLE
        assert pane.exit_code is None
        assert pane.is_running is False

    def test_pane_creation_with_config(self) -> None:
        """Test creating a pane with custom config."""
        config = PaneConfig(columns=120, lines=40)
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test Pane",
            command=["/bin/bash"],
            config=config,
        )
        assert pane.config.columns == 120
        assert pane.config.lines == 40

    def test_pane_creation_with_plugin(self) -> None:
        """Test creating a pane with an associated plugin."""
        mock_plugin = MagicMock()
        mock_plugin.name = "apt"

        pane = TerminalPane(
            pane_id="apt",
            pane_name="APT Updates",
            command=["/bin/bash"],
            plugin=mock_plugin,
        )
        assert pane.plugin is mock_plugin

    def test_pane_id_used_in_widget_id(self) -> None:
        """Test that pane_id is used in the widget ID."""
        pane = TerminalPane(
            pane_id="my-pane",
            pane_name="My Pane",
            command=["/bin/bash"],
        )
        assert pane.id == "pane-my-pane"

    def test_custom_widget_id_overrides_default(self) -> None:
        """Test that a custom widget ID overrides the default."""
        pane = TerminalPane(
            pane_id="my-pane",
            pane_name="My Pane",
            command=["/bin/bash"],
            id="custom-id",
        )
        assert pane.id == "custom-id"


class TestTerminalPaneProperties:
    """Tests for TerminalPane properties."""

    def test_state_property(self) -> None:
        """Test the state property."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        assert pane.state == PaneState.IDLE

    def test_is_running_property(self) -> None:
        """Test the is_running property."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        assert pane.is_running is False

        # Manually set state to running
        pane._state = PaneState.RUNNING
        assert pane.is_running is True

    def test_exit_code_property(self) -> None:
        """Test the exit_code property."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        assert pane.exit_code is None

        pane._exit_code = 0
        assert pane.exit_code == 0

    def test_terminal_view_property_before_compose(self) -> None:
        """Test terminal_view property before compose."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        assert pane.terminal_view is None


class TestTerminalPaneSessionManager:
    """Tests for TerminalPane session manager."""

    @pytest.mark.asyncio
    async def test_get_session_manager_creates_singleton(self) -> None:
        """Test that get_session_manager creates a singleton."""
        # Reset the class-level manager
        TerminalPane._session_manager = None

        manager1 = await TerminalPane.get_session_manager()
        manager2 = await TerminalPane.get_session_manager()

        assert manager1 is manager2

        # Clean up
        await TerminalPane.cleanup_session_manager()

    @pytest.mark.asyncio
    async def test_cleanup_session_manager(self) -> None:
        """Test cleaning up the session manager."""
        # Ensure manager exists
        await TerminalPane.get_session_manager()
        assert TerminalPane._session_manager is not None

        # Clean up
        await TerminalPane.cleanup_session_manager()
        assert TerminalPane._session_manager is None


class TestTerminalPaneFocus:
    """Tests for TerminalPane focus handling."""

    def test_is_focused_default(self) -> None:
        """Test default focus state."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        assert pane.is_focused is False

    def test_is_focused_reactive(self) -> None:
        """Test that is_focused is reactive."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane.is_focused = True
        assert pane.is_focused is True


class TestTerminalPaneScrolling:
    """Tests for TerminalPane scrolling."""

    def test_scroll_history_up_without_terminal_view(self) -> None:
        """Test scroll_history_up when terminal view is not set."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        # Should not raise
        pane.scroll_history_up(5)

    def test_scroll_history_down_without_terminal_view(self) -> None:
        """Test scroll_history_down when terminal view is not set."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        # Should not raise
        pane.scroll_history_down(5)

    def test_scroll_to_history_top_without_terminal_view(self) -> None:
        """Test scroll_to_history_top when terminal view is not set."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        # Should not raise
        pane.scroll_to_history_top()

    def test_scroll_to_history_bottom_without_terminal_view(self) -> None:
        """Test scroll_to_history_bottom when terminal view is not set."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        # Should not raise
        pane.scroll_to_history_bottom()


class TestTerminalPaneInput:
    """Tests for TerminalPane input handling."""

    @pytest.mark.asyncio
    async def test_process_key_when_not_focused(self) -> None:
        """Test that keys are not handled when not focused."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._input_router = MagicMock()
        pane._input_router.route_key = AsyncMock()
        pane.is_focused = False

        result = await pane.process_key("a")
        assert result is False
        pane._input_router.route_key.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_key_when_focused(self) -> None:
        """Test that keys are handled when focused."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._input_router = MagicMock()
        pane._input_router.route_key = AsyncMock()
        pane.is_focused = True

        result = await pane.process_key("a")
        assert result is True
        pane._input_router.route_key.assert_called_once_with("a")

    @pytest.mark.asyncio
    async def test_process_text_when_not_focused(self) -> None:
        """Test that text is not handled when not focused."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._input_router = MagicMock()
        pane._input_router.route_text = AsyncMock()
        pane.is_focused = False

        await pane.process_text("hello")
        pane._input_router.route_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_text_when_focused(self) -> None:
        """Test that text is handled when focused."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._input_router = MagicMock()
        pane._input_router.route_text = AsyncMock()
        pane.is_focused = True

        await pane.process_text("hello")
        pane._input_router.route_text.assert_called_once_with("hello")

    @pytest.mark.asyncio
    async def test_paste_text_when_focused(self) -> None:
        """Test paste when focused."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._input_router = MagicMock()
        pane._input_router.paste = AsyncMock()
        pane.is_focused = True

        await pane.paste_text("pasted text")
        pane._input_router.paste.assert_called_once_with("pasted text")


class TestTerminalPaneWrite:
    """Tests for TerminalPane write operations."""

    @pytest.mark.asyncio
    async def test_write_when_not_running(self) -> None:
        """Test that write does nothing when not running."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        # Should not raise
        await pane.write(b"hello")

    @pytest.mark.asyncio
    async def test_write_when_running(self) -> None:
        """Test write when running."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._state = PaneState.RUNNING

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            await pane.write(b"hello")
            mock_manager.write_to_session.assert_called_once_with("test", b"hello")


class TestTerminalPaneResize:
    """Tests for TerminalPane resize operations."""

    @pytest.mark.asyncio
    async def test_resize_updates_config(self) -> None:
        """Test that resize updates the config."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        await pane.resize(120, 40)
        assert pane.config.columns == 120
        assert pane.config.lines == 40

    @pytest.mark.asyncio
    async def test_resize_updates_terminal_view(self) -> None:
        """Test that resize updates the terminal view."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        mock_view = MagicMock()
        pane._terminal_view = mock_view

        await pane.resize(120, 40)
        mock_view.resize_terminal.assert_called_once_with(120, 40)

    @pytest.mark.asyncio
    async def test_resize_updates_pty_when_running(self) -> None:
        """Test that resize updates PTY when running."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._state = PaneState.RUNNING

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            await pane.resize(120, 40)
            mock_manager.resize_session.assert_called_once_with("test", 120, 40)


class TestTerminalPaneLifecycle:
    """Tests for TerminalPane lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_session(self) -> None:
        """Test that start creates a PTY session."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "hello"],
        )

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            # Mock the read loop to exit immediately
            with patch.object(pane, "_read_loop", return_value=asyncio.sleep(0)):
                await pane.start()

                assert pane.state == PaneState.RUNNING
                assert pane._start_time is not None
                mock_manager.create_session.assert_called_once()

            # Clean up
            await pane.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running(self) -> None:
        """Test that start does nothing when already running."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )
        pane._state = PaneState.RUNNING

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            await pane.start()
            mock_manager.create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_read_task(self) -> None:
        """Test that stop cancels the read task."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )

        # Create a mock read task
        async def mock_read() -> None:
            await asyncio.sleep(100)

        pane._read_task = asyncio.create_task(mock_read())

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            await pane.stop()

            assert pane._read_task is None
            mock_manager.close_session.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_stop_closes_session(self) -> None:
        """Test that stop closes the PTY session."""
        pane = TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/bash"],
        )

        mock_manager = AsyncMock()
        with patch.object(TerminalPane, "get_session_manager", return_value=mock_manager):
            await pane.stop()
            mock_manager.close_session.assert_called_once_with("test")

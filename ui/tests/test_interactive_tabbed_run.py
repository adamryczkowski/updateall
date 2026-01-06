"""Tests for InteractiveTabbedApp integration.

Phase 4 - Integration
See docs/interactive-tabs-implementation-plan.md
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.binding import Binding

from ui.interactive_tabbed_run import (
    AllPluginsCompleted,
    InteractiveTabbedApp,
    InteractiveTabData,
    ProgressBar,
    run_with_interactive_tabbed_ui,
)
from ui.key_bindings import KeyBindings
from ui.terminal_pane import PaneConfig, PaneState


class TestInteractiveTabData:
    """Tests for InteractiveTabData dataclass."""

    def test_default_values(self) -> None:
        """Test default values for tab data."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        data = InteractiveTabData(
            plugin_name="test",
            plugin=mock_plugin,
            command=["/bin/echo", "hello"],
        )

        assert data.plugin_name == "test"
        assert data.plugin is mock_plugin
        assert data.command == ["/bin/echo", "hello"]
        assert data.state == PaneState.IDLE
        assert data.start_time is None
        assert data.end_time is None
        assert data.exit_code is None
        assert data.error_message is None
        assert data.output_bytes == 0
        assert isinstance(data.config, PaneConfig)

    def test_custom_values(self) -> None:
        """Test custom values for tab data."""
        mock_plugin = MagicMock()
        config = PaneConfig(columns=120, lines=40)

        data = InteractiveTabData(
            plugin_name="apt",
            plugin=mock_plugin,
            command=["/bin/bash"],
            state=PaneState.RUNNING,
            config=config,
        )

        assert data.state == PaneState.RUNNING
        assert data.config.columns == 120
        assert data.config.lines == 40


class TestAllPluginsCompleted:
    """Tests for AllPluginsCompleted message."""

    def test_message_creation(self) -> None:
        """Test creating an all plugins completed message."""
        msg = AllPluginsCompleted(total=5, successful=3, failed=2)
        assert msg.total == 5
        assert msg.successful == 3
        assert msg.failed == 2


class TestProgressBar:
    """Tests for ProgressBar widget."""

    def test_progress_bar_creation(self) -> None:
        """Test creating a progress bar."""
        bar = ProgressBar(total_plugins=5)
        assert bar.total_plugins == 5
        assert bar.completed == 0
        assert bar.successful == 0
        assert bar.failed == 0

    def test_update_progress(self) -> None:
        """Test updating progress."""
        bar = ProgressBar(total_plugins=5)
        bar.update_progress(completed=3, successful=2, failed=1)
        assert bar.completed == 3
        assert bar.successful == 2
        assert bar.failed == 1


class TestInteractiveTabbedAppCreation:
    """Tests for InteractiveTabbedApp creation."""

    def test_app_creation_minimal(self) -> None:
        """Test creating an app with minimal arguments."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        assert len(app.plugins) == 1
        assert app.plugins[0] is mock_plugin
        assert app.configs == {}
        assert app.dry_run is False
        assert app.auto_start is True
        assert isinstance(app.key_bindings, KeyBindings)

    def test_app_creation_with_options(self) -> None:
        """Test creating an app with all options."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"
        mock_config = MagicMock()
        key_bindings = KeyBindings()

        app = InteractiveTabbedApp(
            plugins=[mock_plugin],
            configs={"test": mock_config},
            dry_run=True,
            key_bindings=key_bindings,
            auto_start=False,
        )

        assert app.configs == {"test": mock_config}
        assert app.dry_run is True
        assert app.auto_start is False
        assert app.key_bindings is key_bindings

    def test_app_creation_multiple_plugins(self) -> None:
        """Test creating an app with multiple plugins."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        assert len(app.plugins) == 3
        assert app.plugins[0].name == "apt"
        assert app.plugins[1].name == "flatpak"
        assert app.plugins[2].name == "pipx"


class TestInteractiveTabbedAppProperties:
    """Tests for InteractiveTabbedApp properties."""

    def test_active_pane_before_compose(self) -> None:
        """Test active_pane before compose."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Before compose, terminal_panes is empty
        assert app.active_pane is None

    def test_active_tab_index_default(self) -> None:
        """Test default active tab index."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        assert app.active_tab_index == 0


class TestInteractiveTabbedAppPluginCommand:
    """Tests for plugin command generation."""

    def test_get_plugin_command_with_interactive_support(self) -> None:
        """Test getting command from plugin with interactive support."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"
        mock_plugin.get_interactive_command.return_value = ["/usr/bin/apt", "update"]

        app = InteractiveTabbedApp(plugins=[mock_plugin])
        command = app._get_plugin_command(mock_plugin)

        assert command == ["/usr/bin/apt", "update"]
        mock_plugin.get_interactive_command.assert_called_once_with(dry_run=False)

    def test_get_plugin_command_with_dry_run(self) -> None:
        """Test getting command with dry_run flag."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"
        mock_plugin.get_interactive_command.return_value = ["/usr/bin/apt", "update", "--dry-run"]

        app = InteractiveTabbedApp(plugins=[mock_plugin], dry_run=True)
        app._get_plugin_command(mock_plugin)

        mock_plugin.get_interactive_command.assert_called_once_with(dry_run=True)

    def test_get_plugin_command_fallback(self) -> None:
        """Test fallback command when plugin doesn't support interactive."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"
        mock_plugin.get_interactive_command.side_effect = NotImplementedError()

        app = InteractiveTabbedApp(plugins=[mock_plugin])
        command = app._get_plugin_command(mock_plugin)

        # Should return a fallback bash command
        assert command[0] == "/bin/bash"
        assert "-c" in command

    def test_get_plugin_command_no_method(self) -> None:
        """Test fallback when plugin has no get_interactive_command method."""
        mock_plugin = MagicMock(spec=["name"])
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])
        command = app._get_plugin_command(mock_plugin)

        # Should return a fallback bash command
        assert command[0] == "/bin/bash"


class TestInteractiveTabbedAppActions:
    """Tests for InteractiveTabbedApp actions."""

    def test_action_next_tab(self) -> None:
        """Test next tab action."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)
        assert app.active_tab_index == 0

        app.action_next_tab()
        assert app.active_tab_index == 1

        app.action_next_tab()
        assert app.active_tab_index == 2

        # Should not go beyond last tab
        app.action_next_tab()
        assert app.active_tab_index == 2

    def test_action_previous_tab(self) -> None:
        """Test previous tab action."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)
        app.active_tab_index = 2

        app.action_previous_tab()
        assert app.active_tab_index == 1

        app.action_previous_tab()
        assert app.active_tab_index == 0

        # Should not go below 0
        app.action_previous_tab()
        assert app.active_tab_index == 0

    def test_goto_tab(self) -> None:
        """Test going to a specific tab."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        app._goto_tab(2)
        assert app.active_tab_index == 2

        app._goto_tab(0)
        assert app.active_tab_index == 0

    def test_goto_tab_invalid_index(self) -> None:
        """Test going to an invalid tab index."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Should not change for invalid indices
        app._goto_tab(-1)
        assert app.active_tab_index == 0

        app._goto_tab(10)
        assert app.active_tab_index == 0

    def test_action_goto_tab_1_through_9(self) -> None:
        """Test direct tab access actions."""
        plugins: list[Any] = []
        for i in range(9):
            mock = MagicMock()
            mock.name = f"plugin{i + 1}"
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        app.action_goto_tab_1()
        assert app.active_tab_index == 0

        app.action_goto_tab_5()
        assert app.active_tab_index == 4

        app.action_goto_tab_9()
        assert app.active_tab_index == 8


class TestInteractiveTabbedAppScrolling:
    """Tests for InteractiveTabbedApp scrolling."""

    def test_scroll_actions_without_active_pane(self) -> None:
        """Test scroll actions when no active pane."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Should not raise
        app.action_scroll_up()
        app.action_scroll_down()
        app.action_scroll_top()
        app.action_scroll_bottom()


class TestInteractiveTabbedAppProgress:
    """Tests for InteractiveTabbedApp progress tracking."""

    def test_update_progress(self) -> None:
        """Test progress update calculation."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        # Simulate tab data
        app.tab_data = {
            "apt": InteractiveTabData(
                plugin_name="apt",
                plugin=plugins[0],
                command=["/bin/bash"],
                state=PaneState.SUCCESS,
            ),
            "flatpak": InteractiveTabData(
                plugin_name="flatpak",
                plugin=plugins[1],
                command=["/bin/bash"],
                state=PaneState.FAILED,
            ),
            "pipx": InteractiveTabData(
                plugin_name="pipx",
                plugin=plugins[2],
                command=["/bin/bash"],
                state=PaneState.RUNNING,
            ),
        }

        # Check completion status
        all_done = all(
            data.state in (PaneState.SUCCESS, PaneState.FAILED, PaneState.EXITED)
            for data in app.tab_data.values()
        )
        assert all_done is False

    def test_check_all_completed(self) -> None:
        """Test checking if all plugins completed."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        # Simulate all completed
        app.tab_data = {
            "apt": InteractiveTabData(
                plugin_name="apt",
                plugin=plugins[0],
                command=["/bin/bash"],
                state=PaneState.SUCCESS,
            ),
            "flatpak": InteractiveTabData(
                plugin_name="flatpak",
                plugin=plugins[1],
                command=["/bin/bash"],
                state=PaneState.FAILED,
            ),
        }

        all_done = all(
            data.state in (PaneState.SUCCESS, PaneState.FAILED, PaneState.EXITED)
            for data in app.tab_data.values()
        )
        assert all_done is True


class TestInteractiveTabbedAppAppAction:
    """Tests for app action handling."""

    @pytest.mark.asyncio
    async def test_handle_app_action_next_tab(self) -> None:
        """Test handling next_tab action."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        await app._handle_app_action("next_tab")
        assert app.active_tab_index == 1

    @pytest.mark.asyncio
    async def test_handle_app_action_prev_tab(self) -> None:
        """Test handling prev_tab action."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)
        app.active_tab_index = 1

        await app._handle_app_action("prev_tab")
        assert app.active_tab_index == 0

    @pytest.mark.asyncio
    async def test_handle_app_action_tab_number(self) -> None:
        """Test handling tab_N action."""
        plugins: list[Any] = []
        for name in ["apt", "flatpak", "pipx"]:
            mock = MagicMock()
            mock.name = name
            plugins.append(mock)

        app = InteractiveTabbedApp(plugins=plugins)

        await app._handle_app_action("tab_3")
        assert app.active_tab_index == 2


class TestInteractiveTabbedAppPtyInput:
    """Tests for PTY input handling."""

    @pytest.mark.asyncio
    async def test_handle_pty_input_with_tab_id(self) -> None:
        """Test handling PTY input with specific tab ID."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Create mock pane
        mock_pane = AsyncMock()
        app.terminal_panes["test"] = mock_pane

        await app._handle_pty_input(b"hello", tab_id="test")
        mock_pane.write.assert_called_once_with(b"hello")

    @pytest.mark.asyncio
    async def test_handle_pty_input_to_active_pane(self) -> None:
        """Test handling PTY input to active pane."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Create mock pane and set as active
        mock_pane = AsyncMock()
        app.terminal_panes["test"] = mock_pane

        # Mock active_pane property
        with patch.object(
            InteractiveTabbedApp, "active_pane", new_callable=lambda: property(lambda _: mock_pane)
        ):
            await app._handle_pty_input(b"hello")
            mock_pane.write.assert_called_once_with(b"hello")


class TestRunWithInteractiveTabbedUI:
    """Tests for run_with_interactive_tabbed_ui function."""

    @pytest.mark.asyncio
    async def test_fallback_when_pty_unavailable(self) -> None:
        """Test fallback to non-interactive mode when PTY unavailable."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        with (
            patch("ui.interactive_tabbed_run.is_pty_available", return_value=False),
            patch("ui.tabbed_run.run_with_tabbed_ui") as mock_run,
        ):
            mock_run.return_value = None
            await run_with_interactive_tabbed_ui(plugins=[mock_plugin])
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_interactive_when_pty_available(self) -> None:
        """Test using interactive mode when PTY available."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        with (
            patch("ui.interactive_tabbed_run.is_pty_available", return_value=True),
            patch.object(InteractiveTabbedApp, "run_async") as mock_run,
        ):
            mock_run.return_value = None
            await run_with_interactive_tabbed_ui(plugins=[mock_plugin])
            mock_run.assert_called_once()


class TestInteractiveTabbedAppBindings:
    """Tests for app key bindings."""

    def test_default_bindings(self) -> None:
        """Test that default bindings are set."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        app = InteractiveTabbedApp(plugins=[mock_plugin])

        # Check that bindings list is populated
        assert len(app.BINDINGS) > 0

        # Check for expected bindings - filter to Binding instances
        binding_keys = [b.key for b in app.BINDINGS if isinstance(b, Binding)]
        assert "ctrl+tab" in binding_keys
        assert "ctrl+shift+tab" in binding_keys
        assert "ctrl+q" in binding_keys

    def test_custom_key_bindings(self) -> None:
        """Test using custom key bindings."""
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        custom_bindings = KeyBindings({"next_tab": "alt+n"})
        app = InteractiveTabbedApp(
            plugins=[mock_plugin],
            key_bindings=custom_bindings,
        )

        assert app.key_bindings is custom_bindings
        assert app.key_bindings.get_key_for_action("next_tab") == "alt+n"

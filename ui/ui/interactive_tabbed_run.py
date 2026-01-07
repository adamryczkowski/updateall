"""Interactive tabbed run display with PTY-based terminal emulation.

This module provides an InteractiveTabbedApp that runs plugins in PTY sessions
with full terminal emulation, allowing for interactive input and live output.

Phase 4 - Integration
See docs/interactive-tabs-implementation-plan.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Key  # noqa: TC002 - Required at runtime for event dispatch
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from ui.input_router import InputRouter
from ui.key_bindings import KeyBindings
from ui.pty_session import is_pty_available
from ui.sudo import SudoKeepAlive, SudoStatus, check_sudo_status
from ui.terminal_pane import (
    PaneConfig,
    PaneOutputMessage,
    PaneState,
    PaneStateChanged,
    TerminalPane,
)

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin
    from core.models import PluginConfig


@dataclass
class InteractiveTabData:
    """Data for an interactive tab."""

    plugin_name: str
    plugin: UpdatePlugin
    command: list[str]
    state: PaneState = PaneState.IDLE
    start_time: datetime | None = None
    end_time: datetime | None = None
    exit_code: int | None = None
    error_message: str | None = None
    output_bytes: int = 0
    config: PaneConfig = field(default_factory=PaneConfig)


class AllPluginsCompleted(Message):
    """Message sent when all plugins have completed."""

    def __init__(
        self,
        total: int,
        successful: int,
        failed: int,
    ) -> None:
        """Initialize the message.

        Args:
            total: Total number of plugins.
            successful: Number of successful plugins.
            failed: Number of failed plugins.
        """
        self.total = total
        self.successful = successful
        self.failed = failed
        super().__init__()


class ProgressBar(Static):
    """Progress bar showing overall completion status."""

    DEFAULT_CSS = """
    ProgressBar {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    """

    def __init__(
        self,
        total_plugins: int,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the progress bar.

        Args:
            total_plugins: Total number of plugins.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.total_plugins = total_plugins
        self.completed = 0
        self.successful = 0
        self.failed = 0

    def update_progress(
        self,
        completed: int,
        successful: int,
        failed: int,
    ) -> None:
        """Update the progress display.

        Args:
            completed: Number of completed plugins.
            successful: Number of successful plugins.
            failed: Number of failed plugins.
        """
        self.completed = completed
        self.successful = successful
        self.failed = failed
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the progress display."""
        pending = self.total_plugins - self.completed
        percent = (self.completed / self.total_plugins * 100) if self.total_plugins > 0 else 0

        # Build progress bar
        bar_width = 30
        filled = int(bar_width * percent / 100)
        empty = bar_width - filled
        bar = f"[{'█' * filled}{'░' * empty}]"

        text = (
            f"Progress: {bar} {percent:.0f}% "
            f"({self.completed}/{self.total_plugins}) "
            f"[green]✓ {self.successful}[/green] "
            f"[red]✗ {self.failed}[/red] "
            f"[dim]⏳ {pending}[/dim]"
        )
        self.update(text)


def _get_ui_version() -> str:
    """Get the UI package version."""
    try:
        import importlib.metadata

        return importlib.metadata.version("update-all-ui")
    except Exception:
        return "unknown"


class InteractiveTabbedApp(App[None]):
    """Textual application for running plugins with interactive PTY terminals.

    This app provides:
    - A tab for each plugin with full PTY terminal emulation
    - Live output display with ANSI escape sequence support
    - Interactive input support (sudo prompts, confirmations, etc.)
    - Independent scrollback buffer per tab
    - Configurable keyboard shortcuts for tab navigation
    - Mouse click tab switching

    Example:
        app = InteractiveTabbedApp(plugins=[apt_plugin, flatpak_plugin])
        await app.run_async()
    """

    TITLE = f"InteractiveTabbedApp (UI v{_get_ui_version()})"

    CSS = """
    InteractiveTabbedApp {
        background: $surface;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
        height: 1fr;
    }

    #help-text {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: center;
    }

    #sudo-status {
        dock: top;
        height: 1;
        background: $warning;
        color: $text;
        text-align: center;
    }

    #sudo-status.authenticated {
        background: $success;
    }

    #sudo-status.hidden {
        display: none;
    }

    #pty-unavailable {
        dock: top;
        height: 1;
        background: $error;
        color: $text;
        text-align: center;
    }

    #pty-unavailable.hidden {
        display: none;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+tab", "next_tab", "Next Tab", show=True),
        Binding("ctrl+shift+tab", "previous_tab", "Previous Tab", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("f1", "help", "Help", show=False),
        Binding("shift+pageup", "scroll_up", "Scroll Up", show=False),
        Binding("shift+pagedown", "scroll_down", "Scroll Down", show=False),
        Binding("shift+home", "scroll_top", "Scroll Top", show=False),
        Binding("shift+end", "scroll_bottom", "Scroll Bottom", show=False),
        # Alt+number for direct tab access
        Binding("alt+1", "goto_tab_1", "Tab 1", show=False),
        Binding("alt+2", "goto_tab_2", "Tab 2", show=False),
        Binding("alt+3", "goto_tab_3", "Tab 3", show=False),
        Binding("alt+4", "goto_tab_4", "Tab 4", show=False),
        Binding("alt+5", "goto_tab_5", "Tab 5", show=False),
        Binding("alt+6", "goto_tab_6", "Tab 6", show=False),
        Binding("alt+7", "goto_tab_7", "Tab 7", show=False),
        Binding("alt+8", "goto_tab_8", "Tab 8", show=False),
        Binding("alt+9", "goto_tab_9", "Tab 9", show=False),
    ]

    # Reactive properties
    active_tab_index: reactive[int] = reactive(0)

    def __init__(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
        dry_run: bool = False,
        key_bindings: KeyBindings | None = None,
        auto_start: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the interactive tabbed app.

        Args:
            plugins: List of plugins to run.
            configs: Optional plugin configurations.
            dry_run: Whether to run in dry-run mode.
            key_bindings: Custom key bindings.
            auto_start: Whether to start plugins automatically on mount.
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)

        self.plugins = plugins
        self.configs = configs or {}
        self.dry_run = dry_run
        self.key_bindings = key_bindings or KeyBindings()
        self.auto_start = auto_start

        # Tab data
        self.tab_data: dict[str, InteractiveTabData] = {}
        self.terminal_panes: dict[str, TerminalPane] = {}

        # Input routing
        self._input_router: InputRouter | None = None

        # Sudo management
        self._sudo_keepalive: SudoKeepAlive | None = None

        # PTY availability
        self._pty_available = is_pty_available()

    @property
    def active_pane(self) -> TerminalPane | None:
        """Get the currently active terminal pane."""
        # Use internal attribute to avoid triggering reactive watcher
        index = getattr(self, "_reactive_active_tab_index", 0)
        if index < len(self.plugins):
            plugin_name = self.plugins[index].name
            return self.terminal_panes.get(plugin_name)
        return None

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header(show_clock=True)

        # PTY unavailable warning
        yield Static(
            "⚠️ PTY not available - falling back to non-interactive mode",
            id="pty-unavailable",
            classes="hidden" if self._pty_available else "",
        )

        # Sudo status bar
        yield Static("", id="sudo-status", classes="hidden")

        with TabbedContent(id="tabs"):
            for plugin in self.plugins:
                # Build command for the plugin
                command = self._get_plugin_command(plugin)

                # Create pane config
                pane_config = PaneConfig(
                    columns=80,
                    lines=24,
                    scrollback_lines=10000,
                )

                # Create tab data
                self.tab_data[plugin.name] = InteractiveTabData(
                    plugin_name=plugin.name,
                    plugin=plugin,
                    command=command,
                    config=pane_config,
                )

                with TabPane(plugin.name, id=f"tab-{plugin.name}"):
                    pane = TerminalPane(
                        pane_id=plugin.name,
                        pane_name=plugin.name,
                        command=command,
                        config=pane_config,
                        plugin=plugin,
                        key_bindings=self.key_bindings,
                    )
                    self.terminal_panes[plugin.name] = pane
                    yield pane

        yield ProgressBar(len(self.plugins), id="progress")
        yield Static(
            "Ctrl+Tab/Ctrl+Shift+Tab: Navigate | Ctrl+Q: Quit | Shift+PgUp/PgDn: Scroll",
            id="help-text",
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Handle app mount."""
        # Set up input router
        self._input_router = InputRouter(
            key_bindings=self.key_bindings,
            on_pty_input=self._handle_pty_input,
            on_app_action=self._handle_app_action,
        )

        # Update initial progress
        progress = self.query_one("#progress", ProgressBar)
        progress._refresh_display()

        # Set initial active tab
        if self.plugins:
            self._update_active_pane()

        # Check sudo status
        await self._check_and_authenticate_sudo()

        # Start plugins if auto_start is enabled
        if self.auto_start and self._pty_available:
            await self._start_all_plugins()

    async def on_unmount(self) -> None:
        """Handle app unmount."""
        # Stop sudo keepalive
        if self._sudo_keepalive:
            await self._sudo_keepalive.stop()

        # Clean up terminal panes
        await TerminalPane.cleanup_session_manager()

    def _get_plugin_command(self, plugin: UpdatePlugin) -> list[str]:
        """Get the command to run for a plugin.

        Args:
            plugin: The plugin.

        Returns:
            Command and arguments as a list.
        """
        # Check if plugin supports interactive mode
        if hasattr(plugin, "get_interactive_command"):
            try:
                return plugin.get_interactive_command(dry_run=self.dry_run)
            except NotImplementedError:
                pass

        # Fall back to a shell that runs the plugin's execute method
        # This is a placeholder - in practice, plugins should implement
        # get_interactive_command() for proper interactive support
        return ["/bin/bash", "-c", f"echo 'Running {plugin.name}...' && sleep 2 && echo 'Done'"]

    async def _check_and_authenticate_sudo(self) -> None:
        """Check sudo status and authenticate if needed."""
        # Check if any plugin requires sudo
        needs_sudo = any(
            getattr(self.configs.get(p.name), "requires_sudo", False) for p in self.plugins
        )

        if not needs_sudo:
            return

        sudo_status_widget = self.query_one("#sudo-status", Static)

        # Check current sudo status
        result = await check_sudo_status()

        if result.status == SudoStatus.AUTHENTICATED:
            sudo_status_widget.update("🔓 Sudo authenticated")
            sudo_status_widget.remove_class("hidden")
            sudo_status_widget.add_class("authenticated")

            # Start keepalive
            self._sudo_keepalive = SudoKeepAlive(interval_seconds=60.0)
            await self._sudo_keepalive.start()

        elif result.status == SudoStatus.PASSWORD_REQUIRED:
            sudo_status_widget.update("🔒 Sudo password required - please authenticate")
            sudo_status_widget.remove_class("hidden")
            self.notify("Sudo password may be required", severity="warning")

    async def _start_all_plugins(self) -> None:
        """Start all plugin PTY sessions."""
        for plugin_name, pane in self.terminal_panes.items():
            # Check if plugin is enabled
            config = self.configs.get(plugin_name)
            if config and not getattr(config, "enabled", True):
                self.tab_data[plugin_name].state = PaneState.EXITED
                self.tab_data[plugin_name].error_message = "Plugin is disabled"
                continue

            # Start the pane
            self.tab_data[plugin_name].start_time = datetime.now(tz=UTC)
            await pane.start()

    def _update_active_pane(self) -> None:
        """Update which pane is marked as active."""
        for i, plugin in enumerate(self.plugins):
            pane = self.terminal_panes.get(plugin.name)
            if pane:
                pane.is_focused = i == self.active_tab_index

        # Update input router
        if self._input_router and self.active_tab_index < len(self.plugins):
            plugin_name = self.plugins[self.active_tab_index].name
            self._input_router.set_active_tab(plugin_name)

    def watch_active_tab_index(self, index: int) -> None:
        """React to active tab index changes.

        Args:
            index: New active tab index.
        """
        # Only update if the app is composed (has DOM)
        # Use _is_mounted attribute to avoid mypy warning about truthy-function
        if not getattr(self, "_is_mounted", False):
            return

        self._update_active_pane()

        # Update TabbedContent
        if index < len(self.plugins):
            try:
                tabs = self.query_one("#tabs", TabbedContent)
                plugin_name = self.plugins[index].name
                tabs.active = f"tab-{plugin_name}"
            except Exception:
                # DOM not ready yet
                pass

    async def _handle_pty_input(self, data: bytes, tab_id: str | None = None) -> None:
        """Handle input to be sent to PTY.

        Args:
            data: Input data.
            tab_id: Optional tab ID to send input to.
        """
        if tab_id and tab_id in self.terminal_panes:
            await self.terminal_panes[tab_id].write(data)
        elif self.active_pane:
            await self.active_pane.write(data)

    async def _handle_app_action(self, action: str) -> None:
        """Handle an application action.

        Args:
            action: Action name.
        """
        if action == "next_tab":
            self.action_next_tab()
        elif action == "prev_tab":
            self.action_previous_tab()
        elif action == "quit":
            self.exit()
        elif action == "scroll_up":
            self.action_scroll_up()
        elif action == "scroll_down":
            self.action_scroll_down()
        elif action == "scroll_top":
            self.action_scroll_top()
        elif action == "scroll_bottom":
            self.action_scroll_bottom()
        elif action.startswith("tab_"):
            try:
                tab_num = int(action.split("_")[1])
                self._goto_tab(tab_num - 1)
            except (ValueError, IndexError):
                pass

    @on(PaneStateChanged)
    def handle_pane_state_changed(self, message: PaneStateChanged) -> None:
        """Handle pane state change messages.

        Args:
            message: The state change message.
        """
        plugin_name = message.pane_id
        if plugin_name in self.tab_data:
            self.tab_data[plugin_name].state = message.state
            self.tab_data[plugin_name].exit_code = message.exit_code

            if message.state in (PaneState.SUCCESS, PaneState.FAILED, PaneState.EXITED):
                self.tab_data[plugin_name].end_time = datetime.now(tz=UTC)

        # Update progress
        self._update_progress()

        # Check if all plugins completed
        self._check_all_completed()

    @on(PaneOutputMessage)
    def handle_pane_output(self, message: PaneOutputMessage) -> None:
        """Handle pane output messages.

        Args:
            message: The output message.
        """
        plugin_name = message.pane_id
        if plugin_name in self.tab_data:
            self.tab_data[plugin_name].output_bytes += len(message.data)

    def _update_progress(self) -> None:
        """Update the progress bar."""
        completed = sum(
            1
            for data in self.tab_data.values()
            if data.state in (PaneState.SUCCESS, PaneState.FAILED, PaneState.EXITED)
        )
        successful = sum(1 for data in self.tab_data.values() if data.state == PaneState.SUCCESS)
        failed = sum(1 for data in self.tab_data.values() if data.state == PaneState.FAILED)

        try:
            progress = self.query_one("#progress", ProgressBar)
            progress.update_progress(completed, successful, failed)
        except Exception:
            # Progress bar not yet mounted or already unmounted
            pass

    def _check_all_completed(self) -> None:
        """Check if all plugins have completed."""
        all_done = all(
            data.state in (PaneState.SUCCESS, PaneState.FAILED, PaneState.EXITED)
            for data in self.tab_data.values()
        )

        if all_done:
            successful = sum(
                1 for data in self.tab_data.values() if data.state == PaneState.SUCCESS
            )
            failed = sum(1 for data in self.tab_data.values() if data.state == PaneState.FAILED)
            self.post_message(
                AllPluginsCompleted(
                    total=len(self.tab_data),
                    successful=successful,
                    failed=failed,
                )
            )

    @on(AllPluginsCompleted)
    def handle_all_completed(self, message: AllPluginsCompleted) -> None:
        """Handle all plugins completed message.

        Args:
            message: The completion message.
        """
        if message.failed > 0:
            self.notify(
                f"Completed: {message.successful} succeeded, {message.failed} failed",
                severity="warning",
            )
        else:
            self.notify(
                f"All {message.total} plugins completed successfully!",
                severity="information",
            )

    # Tab navigation actions
    def action_next_tab(self) -> None:
        """Switch to the next tab."""
        if self.active_tab_index < len(self.plugins) - 1:
            self.active_tab_index += 1

    def action_previous_tab(self) -> None:
        """Switch to the previous tab."""
        if self.active_tab_index > 0:
            self.active_tab_index -= 1

    def _goto_tab(self, index: int) -> None:
        """Go to a specific tab by index.

        Args:
            index: Tab index (0-based).
        """
        if 0 <= index < len(self.plugins):
            self.active_tab_index = index

    # Direct tab access actions
    def action_goto_tab_1(self) -> None:
        """Go to tab 1."""
        self._goto_tab(0)

    def action_goto_tab_2(self) -> None:
        """Go to tab 2."""
        self._goto_tab(1)

    def action_goto_tab_3(self) -> None:
        """Go to tab 3."""
        self._goto_tab(2)

    def action_goto_tab_4(self) -> None:
        """Go to tab 4."""
        self._goto_tab(3)

    def action_goto_tab_5(self) -> None:
        """Go to tab 5."""
        self._goto_tab(4)

    def action_goto_tab_6(self) -> None:
        """Go to tab 6."""
        self._goto_tab(5)

    def action_goto_tab_7(self) -> None:
        """Go to tab 7."""
        self._goto_tab(6)

    def action_goto_tab_8(self) -> None:
        """Go to tab 8."""
        self._goto_tab(7)

    def action_goto_tab_9(self) -> None:
        """Go to tab 9."""
        self._goto_tab(8)

    # Scroll actions
    def action_scroll_up(self) -> None:
        """Scroll up in the active terminal."""
        if self.active_pane:
            self.active_pane.scroll_history_up(5)

    def action_scroll_down(self) -> None:
        """Scroll down in the active terminal."""
        if self.active_pane:
            self.active_pane.scroll_history_down(5)

    def action_scroll_top(self) -> None:
        """Scroll to top of history."""
        if self.active_pane:
            self.active_pane.scroll_to_history_top()

    def action_scroll_bottom(self) -> None:
        """Scroll to bottom (current output)."""
        if self.active_pane:
            self.active_pane.scroll_to_history_bottom()

    def action_help(self) -> None:
        """Show help."""
        self.notify(
            "Ctrl+Tab: Next tab | Ctrl+Shift+Tab: Prev tab | Alt+1-9: Go to tab | Ctrl+Q: Quit",
            title="Keyboard Shortcuts",
        )

    async def on_key(self, event: Key) -> None:
        """Handle key events and route them to the active PTY.

        This method intercepts all key events and routes them appropriately:
        - Navigation keys (Ctrl+Tab, etc.) are handled by Textual's binding system
        - All other keys are sent to the active PTY session

        Args:
            event: The key event from Textual.
        """
        # Skip if no input router or no active pane
        if not self._input_router or not self.active_pane:
            return

        # Get the key string in a format the input router understands
        key = event.key

        # Check if this is a navigation key that should be handled by the app
        if self._input_router.get_route_target(key).name == "APP":
            # Let Textual handle navigation keys via its binding system
            return

        # For printable characters, use event.character directly
        # This handles uppercase letters, symbols, etc. correctly
        if event.character is not None and event.is_printable:
            # Send the character directly to PTY
            data = event.character.encode("utf-8")
            await self._handle_pty_input(data)
        else:
            # For special keys (Enter, Backspace, arrows, etc.), use the router
            await self._input_router.route_key(key)

        # Prevent the key from being processed further by Textual
        event.prevent_default()
        event.stop()


async def run_with_interactive_tabbed_ui(
    plugins: list[UpdatePlugin],
    configs: dict[str, PluginConfig] | None = None,
    dry_run: bool = False,
    key_bindings: KeyBindings | None = None,
) -> None:
    """Run plugins with the interactive tabbed UI.

    This function provides a convenient way to run plugins with the
    interactive tabbed UI. It handles PTY availability checking and
    falls back to the non-interactive TabbedRunApp if PTY is not available.

    Args:
        plugins: List of plugins to run.
        configs: Optional plugin configurations.
        dry_run: Whether to run in dry-run mode.
        key_bindings: Custom key bindings.
    """
    if not is_pty_available():
        # Fall back to non-interactive mode
        from ui.tabbed_run import run_with_tabbed_ui

        await run_with_tabbed_ui(
            plugins=plugins,
            configs=configs,
            dry_run=dry_run,
            use_streaming=True,
        )
        return

    app = InteractiveTabbedApp(
        plugins=plugins,
        configs=configs,
        dry_run=dry_run,
        key_bindings=key_bindings,
    )
    await app.run_async()

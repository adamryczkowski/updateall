"""Interactive tabbed run display with PTY-based terminal emulation.

This module provides an InteractiveTabbedApp that runs plugins in PTY sessions
with full terminal emulation, allowing for interactive input and live output.

Phase 4 - Integration (with Phase 2 Visual Enhancements)
See docs/interactive-tabs-implementation-plan.md
See docs/UI-revision-plan.md section 4 Phase 2

UI Revision Plan - Phase 4 Hot Keys and CLI
See docs/UI-revision-plan.md section 3.5 and 4 Phase 4

Phase 1 - Core Infrastructure (PhaseController)
See docs/UI-revision-plan.md section 4 Phase 1
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Key  # noqa: TC002 - Required at runtime for event dispatch
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from core.streaming import Phase
from ui.input_router import InputRouter
from ui.key_bindings import KeyBindings
from ui.phase_controller import PhaseController  # PhaseResult, PhaseState not used directly
from ui.phase_tab import (
    PHASE_TAB_CSS,
    DisplayPhase,
    TabStatus,
    determine_tab_status,
    get_tab_css_class,
    get_tab_label,
)
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
    from stats.estimator import ResourceEstimate

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
    # Phase 2: Visual enhancement fields
    current_phase: DisplayPhase = DisplayPhase.PENDING
    tab_status: TabStatus = TabStatus.PENDING


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

    CSS = (
        """
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
        + PHASE_TAB_CSS
    )

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
        # Phase control bindings (Phase 4 - Hot Keys and CLI)
        # See docs/UI-revision-plan.md section 3.5
        Binding("ctrl+p", "toggle_pause", "Pause/Resume", show=True),
        Binding("f8", "toggle_pause", "Pause/Resume", show=False),
        Binding("ctrl+r", "retry_phase", "Retry", show=True),
        Binding("f9", "retry_phase", "Retry", show=False),
        Binding("ctrl+s", "save_logs", "Save Logs", show=True),
        Binding("f10", "save_logs", "Save Logs", show=False),
        Binding("ctrl+h", "show_help", "Help", show=True),
    ]

    # Disable Textual's built-in command palette to prevent Ctrl+P conflict
    # Our app uses Ctrl+P for toggle_pause action instead
    # See: https://textual.textualize.io/guide/command_palette/#disabling-the-command-palette
    ENABLE_COMMAND_PALETTE: ClassVar[bool] = False

    # Reactive properties
    active_tab_index: reactive[int] = reactive(0)

    def __init__(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
        dry_run: bool = False,
        key_bindings: KeyBindings | None = None,
        auto_start: bool = True,
        pause_phases: bool = False,
        max_concurrent: int = 4,
        **kwargs: Any,
    ) -> None:
        """Initialize the interactive tabbed app.

        Args:
            plugins: List of plugins to run.
            configs: Optional plugin configurations.
            dry_run: Whether to run in dry-run mode.
            key_bindings: Custom key bindings.
            auto_start: Whether to start plugins automatically on mount.
            pause_phases: Whether to pause before each phase.
            max_concurrent: Maximum number of concurrent operations.
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)

        self.plugins = plugins
        self.configs = configs or {}
        self.dry_run = dry_run
        self.key_bindings = key_bindings or KeyBindings()
        self.auto_start = auto_start
        self.pause_phases = pause_phases
        self.max_concurrent = max_concurrent

        # Tab data
        self.tab_data: dict[str, InteractiveTabData] = {}
        self.terminal_panes: dict[str, TerminalPane] = {}

        # Input routing
        self._input_router: InputRouter | None = None

        # Sudo management
        self._sudo_keepalive: SudoKeepAlive | None = None

        # PTY availability
        self._pty_available = is_pty_available()

        # Phase control state (Phase 4 - Hot Keys and CLI)
        self._pause_enabled = pause_phases

        # Phase controller for multi-phase execution (Phase 1 - Core Infrastructure)
        # See docs/UI-revision-plan.md section 4 Phase 1
        self._phase_controller = PhaseController(
            plugins=plugins,
            pause_between_phases=pause_phases,
        )

        # Stats estimates for projected download sizes
        self._plugin_estimates: dict[str, ResourceEstimate] = {}

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

                # Create tab data with Phase 2 visual enhancement fields
                tab_data = InteractiveTabData(
                    plugin_name=plugin.name,
                    plugin=plugin,
                    command=command,
                    config=pane_config,
                    current_phase=DisplayPhase.PENDING,
                    tab_status=TabStatus.PENDING,
                )
                self.tab_data[plugin.name] = tab_data

                # Generate phase-aware tab label
                # Format: [status_icon] plugin_name (phase_name)
                initial_label = get_tab_label(
                    plugin.name,
                    tab_data.tab_status,
                    tab_data.current_phase,
                )
                initial_css_class = get_tab_css_class(tab_data.tab_status)

                with TabPane(
                    initial_label,
                    id=f"tab-{plugin.name}",
                    classes=initial_css_class,
                ):
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

        # Load stats estimates for projected download sizes
        self._load_plugin_estimates()

        # Check sudo status
        await self._check_and_authenticate_sudo()

        # Start plugins if auto_start is enabled
        if self.auto_start and self._pty_available:
            await self._start_all_plugins()

    def _load_plugin_estimates(self) -> None:
        """Load resource estimates from the stats module.

        This loads projected download sizes and other estimates for each plugin
        from historical data. The estimates are displayed in the PhaseStatusBar.
        """
        # Try to load estimates from the stats module
        with contextlib.suppress(Exception):
            from stats.estimator import DartsTimeEstimator

            estimator = DartsTimeEstimator()

            for plugin in self.plugins:
                with contextlib.suppress(Exception):
                    estimate = estimator.estimate(plugin.name)
                    self._plugin_estimates[plugin.name] = estimate

                    # Update the pane's metrics with projected download sizes
                    pane = self.terminal_panes.get(plugin.name)
                    if pane and pane.metrics_collector:
                        metrics = pane.metrics_collector._metrics

                        # Set projected download size if available
                        if estimate.download_size:
                            metrics.projected_download_bytes = int(
                                estimate.download_size.point_estimate
                            )
                            # For now, use same estimate for upgrade phase
                            # In future, this could be phase-specific
                            metrics.projected_upgrade_bytes = int(
                                estimate.download_size.point_estimate
                            )

                        # Set ETA from wall clock estimate
                        if estimate.wall_clock:
                            pane.metrics_collector.update_eta(
                                estimate.wall_clock.point_estimate,
                                estimate.wall_clock.upper_bound
                                - estimate.wall_clock.point_estimate,
                            )

    async def on_unmount(self) -> None:
        """Handle app unmount."""
        # Stop sudo keepalive
        if self._sudo_keepalive:
            await self._sudo_keepalive.stop()

        # Clean up terminal panes
        await TerminalPane.cleanup_session_manager()

    def _get_plugin_command(
        self,
        plugin: UpdatePlugin,
        phase: Phase | None = None,
    ) -> list[str]:
        """Get the command to run for a plugin.

        Args:
            plugin: The plugin.
            phase: Optional phase to get command for. If None, tries
                   get_interactive_command() first for backward compatibility,
                   then falls back to phase commands.

        Returns:
            Command and arguments as a list.
        """
        # If a specific phase is requested, get the phase-specific command
        if phase is not None:
            command = self._phase_controller.get_phase_command(plugin.name, phase)
            if command:
                return command

        # Try get_interactive_command() first for backward compatibility
        # This is the primary method for plugins that don't use multi-phase execution
        if hasattr(plugin, "get_interactive_command"):
            try:
                return plugin.get_interactive_command(dry_run=self.dry_run)
            except NotImplementedError:
                pass

        # Fall back to phase commands for multi-phase plugins
        current_phase = self._phase_controller.get_current_phase(plugin.name)
        if current_phase:
            command = self._phase_controller.get_phase_command(plugin.name, current_phase)
            if command:
                return command

        # Last resort: echo a message indicating no command is defined
        return [
            "/bin/bash",
            "-c",
            f"echo '[{plugin.name}] No interactive command defined'",
        ]

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
        """Start all plugin PTY sessions with phase-based execution.

        If pause_phases is enabled, plugins will be set to PAUSED state
        instead of starting immediately. Users can then manually start
        each plugin or resume all.

        This method uses the PhaseController to manage phase transitions
        and execute phase-specific commands for each plugin.
        """
        for plugin_name, pane in self.terminal_panes.items():
            tab_data = self.tab_data[plugin_name]
            plugin = tab_data.plugin

            # Check if plugin is enabled
            config = self.configs.get(plugin_name)
            if config and not getattr(config, "enabled", True):
                tab_data.state = PaneState.EXITED
                tab_data.error_message = "Plugin is disabled"
                tab_data.tab_status = TabStatus.LOCKED
                self._phase_controller.skip_plugin(plugin_name, "Plugin is disabled")
                self._update_tab_visual(plugin_name, tab_data)
                self._update_progress()
                continue

            # Check if plugin is available (e.g., required tools are installed)
            try:
                if hasattr(plugin, "check_available"):
                    available = await plugin.check_available()
                elif hasattr(plugin, "is_available"):
                    available = plugin.is_available()
                else:
                    available = True

                if not available:
                    tab_data.state = PaneState.EXITED
                    tab_data.error_message = "Not applicable (required tools not installed)"
                    tab_data.end_time = datetime.now(tz=UTC)
                    tab_data.tab_status = TabStatus.LOCKED
                    tab_data.current_phase = DisplayPhase.NOT_APPLICABLE
                    self._phase_controller.skip_plugin(
                        plugin_name,
                        "Required tools not installed",
                    )

                    # Display message in the terminal view
                    if pane.terminal_view:
                        msg = (
                            f"\r\n\x1b[33m╭─ Not Applicable ───────────────────────────╮\x1b[0m\r\n"
                            f"\x1b[33m│\x1b[0m Plugin: {plugin_name}\r\n"
                            f"\x1b[33m│\x1b[0m\r\n"
                            f"\x1b[33m│\x1b[0m Required tools are not installed.\r\n"
                            f"\x1b[33m│\x1b[0m This plugin will be skipped.\r\n"
                            f"\x1b[33m╰─────────────────────────────────────────────╯\x1b[0m\r\n"
                        )
                        pane.terminal_view.feed(msg.encode("utf-8"))

                    self._update_tab_visual(plugin_name, tab_data)
                    self._update_progress()
                    pane.post_message(PaneStateChanged(plugin_name, PaneState.EXITED))
                    continue
            except Exception:
                # If availability check fails, try to start anyway
                pass

            # If pause_phases is enabled, don't start the plugin automatically
            if self._pause_enabled:
                tab_data.state = PaneState.IDLE
                tab_data.current_phase = DisplayPhase.PENDING
                tab_data.tab_status = TabStatus.PENDING

                # Get the first phase for this plugin
                first_phase = self._phase_controller.get_current_phase(plugin_name)
                phase_name = first_phase.value if first_phase else "CHECK"

                # Display pause message in the terminal view
                if pane.terminal_view:
                    pause_msg = (
                        f"\r\n\x1b[36m╭─ Paused ────────────────────────────────────╮\x1b[0m\r\n"
                        f"\x1b[36m│\x1b[0m Plugin: {plugin_name}\r\n"
                        f"\x1b[36m│\x1b[0m Next Phase: {phase_name}\r\n"
                        f"\x1b[36m│\x1b[0m\r\n"
                        f"\x1b[36m│\x1b[0m Waiting for user to start.\r\n"
                        f"\x1b[36m│\x1b[0m Press Ctrl+R to start this phase.\r\n"
                        f"\x1b[36m│\x1b[0m Press Ctrl+P to toggle auto-pause.\r\n"
                        f"\x1b[36m╰─────────────────────────────────────────────╯\x1b[0m\r\n"
                    )
                    pane.terminal_view.feed(pause_msg.encode("utf-8"))

                self._update_tab_visual(plugin_name, tab_data)
                self._update_progress()
                continue

            # Start the first phase for this plugin
            await self._start_plugin_phase(plugin_name)

    async def _start_plugin_phase(self, plugin_name: str) -> None:
        """Start the current phase for a plugin.

        This method gets the current phase command from the PhaseController
        and starts the PTY session with that command.

        Args:
            plugin_name: Name of the plugin to start.
        """
        pane = self.terminal_panes.get(plugin_name)
        tab_data = self.tab_data.get(plugin_name)

        if not pane or not tab_data:
            return

        # Get the current phase and command
        current_phase = self._phase_controller.get_current_phase(plugin_name)
        if not current_phase:
            # No more phases - plugin is complete
            tab_data.state = PaneState.SUCCESS
            tab_data.end_time = datetime.now(tz=UTC)
            tab_data.current_phase = DisplayPhase.COMPLETE
            tab_data.tab_status = TabStatus.SUCCESS
            self._update_tab_visual(plugin_name, tab_data)
            self._update_progress()
            pane.post_message(PaneStateChanged(plugin_name, PaneState.SUCCESS))
            return

        # Get the command for this phase
        command = self._phase_controller.get_phase_command(plugin_name, current_phase)
        if not command:
            # No command for this phase - mark as skipped and move to next
            # We need to start the phase first so the result exists
            self._phase_controller.start_phase_sync(plugin_name, current_phase)
            # Mark as skipped (not completed) to indicate no command was run
            state = self._phase_controller.plugin_states.get(plugin_name)
            if state and current_phase in state.phase_results:
                from ui.phase_controller import PhaseState

                state.phase_results[current_phase].state = PhaseState.SKIPPED

            # Check for next phase (don't recurse infinitely)
            next_phase = self._phase_controller.get_current_phase(plugin_name)
            if next_phase and next_phase != current_phase:
                await self._start_plugin_phase(plugin_name)
            else:
                # No more phases or stuck on same phase - mark as complete
                tab_data.state = PaneState.SUCCESS
                tab_data.end_time = datetime.now(tz=UTC)
                tab_data.current_phase = DisplayPhase.COMPLETE
                tab_data.tab_status = TabStatus.COMPLETED
                self._update_tab_visual(plugin_name, tab_data)
                self._update_progress()
            return

        # Update pane command and start
        pane.command = command

        # Map Phase to DisplayPhase
        phase_display_map = {
            Phase.CHECK: DisplayPhase.UPDATE,
            Phase.DOWNLOAD: DisplayPhase.DOWNLOAD,
            Phase.EXECUTE: DisplayPhase.UPGRADE,
        }
        tab_data.current_phase = phase_display_map.get(current_phase, DisplayPhase.UPDATE)
        tab_data.tab_status = TabStatus.RUNNING
        tab_data.state = PaneState.RUNNING

        # Display phase start message
        if pane.terminal_view:
            phase_msg = (
                f"\r\n\x1b[32m╭─ Phase: {current_phase.value} ─────────────────────────╮\x1b[0m\r\n"
                f"\x1b[32m│\x1b[0m Command: {' '.join(command)}\r\n"
                f"\x1b[32m╰─────────────────────────────────────────────╯\x1b[0m\r\n\r\n"
            )
            pane.terminal_view.feed(phase_msg.encode("utf-8"))

        self._update_tab_visual(plugin_name, tab_data)

        # Start the phase in the PhaseController
        self._phase_controller.start_phase_sync(plugin_name, current_phase)

        # Start the pane with error handling
        if not tab_data.start_time:
            tab_data.start_time = datetime.now(tz=UTC)

        try:
            await pane.start()
        except Exception as e:
            # Handle startup errors gracefully - display in the tab
            error_msg = str(e)
            tab_data.state = PaneState.FAILED
            tab_data.error_message = error_msg
            tab_data.end_time = datetime.now(tz=UTC)
            self._phase_controller.complete_phase_sync(
                plugin_name,
                current_phase,
                success=False,
                error=error_msg,
            )

            # Display error in the terminal view
            if pane.terminal_view:
                error_display = (
                    f"\r\n\x1b[31m╭─ Error ─────────────────────────────────────╮\x1b[0m\r\n"
                    f"\x1b[31m│\x1b[0m Failed to start plugin: {plugin_name}\r\n"
                    f"\x1b[31m│\x1b[0m\r\n"
                    f"\x1b[31m│\x1b[0m {error_msg}\r\n"
                    f"\x1b[31m╰─────────────────────────────────────────────╯\x1b[0m\r\n"
                )
                pane.terminal_view.feed(error_display.encode("utf-8"))

            # Update tab visual and progress
            self._update_tab_visual(plugin_name, tab_data)
            self._update_progress()

            # Post state change message
            pane.post_message(PaneStateChanged(plugin_name, PaneState.FAILED))

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
    async def handle_pane_state_changed(self, message: PaneStateChanged) -> None:
        """Handle pane state change messages.

        Updates the tab data, visual status, and progress bar when a pane's
        state changes. This method also handles phase transitions using the
        PhaseController.

        Args:
            message: The state change message.
        """
        plugin_name = message.pane_id
        if plugin_name not in self.tab_data:
            return

        tab_data = self.tab_data[plugin_name]
        tab_data.state = message.state
        tab_data.exit_code = message.exit_code

        # Get current phase from PhaseController
        current_phase = self._phase_controller.get_current_phase(plugin_name)

        # Handle phase completion
        if message.state == PaneState.SUCCESS:
            # Phase completed successfully
            if current_phase:
                self._phase_controller.complete_phase_sync(
                    plugin_name,
                    current_phase,
                    success=True,
                )

                # Check if there are more phases
                next_phase = self._phase_controller.get_current_phase(plugin_name)
                if next_phase:
                    # More phases to run
                    if self._pause_enabled:
                        # Pause before next phase
                        tab_data.state = PaneState.IDLE
                        pane = self.terminal_panes.get(plugin_name)
                        if pane and pane.terminal_view:
                            pause_msg = (
                                f"\r\n\x1b[36m╭─ Phase Complete ────────────────────────────╮\x1b[0m\r\n"
                                f"\x1b[36m│\x1b[0m Completed: {current_phase.value}\r\n"
                                f"\x1b[36m│\x1b[0m Next Phase: {next_phase.value}\r\n"
                                f"\x1b[36m│\x1b[0m\r\n"
                                f"\x1b[36m│\x1b[0m Press Ctrl+R to continue.\r\n"
                                f"\x1b[36m╰─────────────────────────────────────────────╯\x1b[0m\r\n"
                            )
                            pane.terminal_view.feed(pause_msg.encode("utf-8"))

                        # Update display phase to show next phase is pending
                        phase_display_map = {
                            Phase.CHECK: DisplayPhase.UPDATE,
                            Phase.DOWNLOAD: DisplayPhase.DOWNLOAD,
                            Phase.EXECUTE: DisplayPhase.UPGRADE,
                        }
                        tab_data.current_phase = phase_display_map.get(
                            next_phase,
                            DisplayPhase.PENDING,
                        )
                        tab_data.tab_status = TabStatus.PENDING
                        self._update_tab_visual(plugin_name, tab_data)
                        return
                    else:
                        # Auto-continue to next phase
                        await self._start_plugin_phase(plugin_name)
                        return
                else:
                    # All phases complete
                    tab_data.current_phase = DisplayPhase.COMPLETE
                    tab_data.end_time = datetime.now(tz=UTC)
            else:
                # No phase tracking - just mark as complete
                tab_data.current_phase = DisplayPhase.COMPLETE
                tab_data.end_time = datetime.now(tz=UTC)

        elif message.state == PaneState.FAILED:
            # Phase failed
            if current_phase:
                self._phase_controller.complete_phase_sync(
                    plugin_name,
                    current_phase,
                    success=False,
                    error=tab_data.error_message,
                )
            tab_data.end_time = datetime.now(tz=UTC)

        elif message.state == PaneState.EXITED:
            tab_data.end_time = datetime.now(tz=UTC)

        # Update tab status based on pane state
        new_status = determine_tab_status(message.state.value)
        old_status = tab_data.tab_status
        tab_data.tab_status = new_status

        # Update the tab's visual appearance if status changed
        if new_status != old_status:
            self._update_tab_visual(plugin_name, tab_data)

        # Update progress
        self._update_progress()

        # Check if all plugins completed
        self._check_all_completed()

    def _update_tab_visual(
        self,
        plugin_name: str,
        tab_data: InteractiveTabData,
    ) -> None:
        """Update the visual appearance of a tab.

        This updates the tab's CSS class and label to reflect the current
        status and phase. Part of Phase 2 Visual Enhancements.

        Args:
            plugin_name: Name of the plugin/tab.
            tab_data: The tab data containing current status and phase.
        """
        try:
            # Get the TabPane widget
            tab_pane = self.query_one(f"#tab-{plugin_name}", TabPane)

            # Update CSS classes for status coloring
            # Remove all status classes first
            for status in TabStatus:
                css_class = get_tab_css_class(status)
                tab_pane.remove_class(css_class)

            # Add the new status class
            new_css_class = get_tab_css_class(tab_data.tab_status)
            tab_pane.add_class(new_css_class)

            # Update the tab label dynamically using TabbedContent.get_tab()
            # This requires Textual 0.40+ API
            try:
                tabs = self.query_one("#tabs", TabbedContent)
                tab_id = f"tab-{plugin_name}"
                tab = tabs.get_tab(tab_id)
                if tab:
                    # Generate the new label with status icon and phase
                    new_label = get_tab_label(
                        plugin_name,
                        tab_data.tab_status,
                        tab_data.current_phase,
                    )
                    tab.label = new_label
            except Exception:
                # TabbedContent.get_tab() may not be available in older Textual versions
                # Fall back to CSS class coloring only
                pass

        except Exception:
            # Tab not yet mounted or already unmounted
            pass

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

    # Phase control actions (Phase 4 - Hot Keys and CLI)
    # See docs/UI-revision-plan.md section 3.5

    def action_toggle_pause(self) -> None:
        """Toggle pause before next phase.

        When enabled, the app will pause before transitioning to the next phase,
        allowing the user to review the current state before proceeding.
        """
        self._pause_enabled = not self._pause_enabled
        status = "enabled" if self._pause_enabled else "disabled"
        self.notify(f"Phase pause {status}")

        # Update metrics collectors to show pause indicator
        for pane in self.terminal_panes.values():
            if pane.metrics_collector:
                pane.metrics_collector._metrics.pause_after_phase = self._pause_enabled

    async def action_retry_phase(self) -> None:
        """Retry the current phase or start/continue a paused plugin.

        This method handles:
        - Starting a paused plugin (IDLE state with pause_phases enabled)
        - Continuing to the next phase after a phase completes
        - Retrying a failed phase

        Uses the PhaseController to manage phase transitions and get
        phase-specific commands.
        """
        if not self.active_pane:
            self.notify("No active pane", severity="warning")
            return

        plugin_name = self.plugins[self.active_tab_index].name
        tab_data = self.tab_data.get(plugin_name)

        if not tab_data:
            self.notify("No tab data found", severity="warning")
            return

        # Check if plugin is locked (not applicable or disabled)
        if tab_data.tab_status == TabStatus.LOCKED:
            self.notify("Plugin is not applicable or disabled", severity="warning")
            return

        # Get current phase from PhaseController
        current_phase = self._phase_controller.get_current_phase(plugin_name)

        # Handle failed state - retry the current phase
        if self.active_pane.state == PaneState.FAILED:
            if current_phase:
                # Reset the phase state in PhaseController
                self._phase_controller.reset_phase(plugin_name, current_phase)

            # Reset tab data
            tab_data.state = PaneState.IDLE
            tab_data.exit_code = None
            tab_data.error_message = None
            tab_data.end_time = None

            # Start the phase using PhaseController
            await self._start_plugin_phase(plugin_name)
            self.notify(f"Retrying {current_phase.value if current_phase else 'phase'}...")
            return

        # Handle idle state - start paused plugin or continue to next phase
        if self.active_pane.state == PaneState.IDLE:
            if current_phase:
                # Start the current phase
                await self._start_plugin_phase(plugin_name)
                self.notify(f"Starting {current_phase.value} phase for {plugin_name}...")
            else:
                # No more phases - plugin is complete
                tab_data.state = PaneState.SUCCESS
                tab_data.end_time = datetime.now(tz=UTC)
                tab_data.current_phase = DisplayPhase.COMPLETE
                tab_data.tab_status = TabStatus.SUCCESS
                self._update_tab_visual(plugin_name, tab_data)
                self._update_progress()
                self.notify(f"{plugin_name} completed all phases")
            return

        # Handle success state - check if there are more phases
        if self.active_pane.state == PaneState.SUCCESS:
            if current_phase:
                # There are more phases to run
                await self._start_plugin_phase(plugin_name)
                self.notify(f"Starting {current_phase.value} phase...")
            else:
                self.notify("Plugin already completed all phases", severity="information")
            return

        # Already running
        if self.active_pane.state == PaneState.RUNNING:
            self.notify("Plugin is already running", severity="information")
        else:
            self.notify("No action available for current state", severity="warning")

    async def action_save_logs(self) -> None:
        """Save logs for the current tab.

        Saves the terminal output to a file in the logs directory.
        The file is named with the plugin name and timestamp.
        """
        if not self.active_pane:
            self.notify("No active pane to save logs from", severity="warning")
            return

        plugin_name = self.plugins[self.active_tab_index].name
        tab_data = self.tab_data.get(plugin_name)

        try:
            log_path = await self._save_pane_logs(plugin_name, tab_data)
            self.notify(f"Logs saved to {log_path}")
        except Exception as e:
            self.notify(f"Failed to save logs: {e}", severity="error")

    async def _save_pane_logs(
        self,
        plugin_name: str,
        tab_data: InteractiveTabData | None,
    ) -> Path:
        """Save logs for a pane to a file.

        Args:
            plugin_name: Name of the plugin.
            tab_data: Tab data for the plugin.

        Returns:
            Path to the saved log file.

        Raises:
            OSError: If the log file cannot be written.
        """
        # Create logs directory
        logs_dir = Path.home() / ".local" / "share" / "update-all" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        log_path = logs_dir / f"update-all-{plugin_name}-{timestamp}.log"

        # Get terminal content
        terminal_content = ""
        if self.active_pane and self.active_pane.terminal_view:
            # Get the terminal display content
            display = self.active_pane.terminal_view.terminal_display
            terminal_content = "\n".join(display)

        # Build log content
        lines = [
            "=" * 40,
            f"Update-All Log: {plugin_name}",
            f"Date: {datetime.now(tz=UTC).isoformat()}",
        ]

        if tab_data:
            lines.extend(
                [
                    f"Phase: {tab_data.current_phase.value}",
                    f"Status: {tab_data.state.value}",
                ]
            )

        lines.extend(
            [
                "=" * 40,
                "",
                "--- Terminal Output ---",
                terminal_content,
                "",
                "--- Metrics Summary ---",
            ]
        )

        if tab_data:
            duration = ""
            if tab_data.start_time:
                end = tab_data.end_time or datetime.now(tz=UTC)
                duration = f"{(end - tab_data.start_time).total_seconds():.1f}s"

            lines.extend(
                [
                    f"Duration: {duration}",
                    f"Exit Code: {tab_data.exit_code}",
                ]
            )

        # Write log file
        log_path.write_text("\n".join(lines))
        return log_path

    def action_show_help(self) -> None:
        """Show help overlay with all keyboard shortcuts.

        Displays a comprehensive help message with all available
        keyboard shortcuts organized by category.
        """
        help_text = """
Keyboard Shortcuts:

Navigation:
  Ctrl+Tab / Ctrl+Shift+Tab  - Next/Previous tab
  Alt+1-9                    - Go to tab N
  Shift+PgUp/PgDn            - Scroll history

Phase Control:
  Ctrl+P / F8               - Toggle pause before next phase
  Ctrl+R / F9               - Retry failed phase
  Ctrl+S / F10              - Save logs to file
  Ctrl+H / F1               - Show this help

Application:
  Ctrl+Q                    - Quit
"""
        self.notify(help_text, title="Help", timeout=10)

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
    pause_phases: bool = False,
    max_concurrent: int = 4,
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
        pause_phases: Whether to pause before each phase.
        max_concurrent: Maximum number of concurrent operations.
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
        pause_phases=pause_phases,
        max_concurrent=max_concurrent,
    )
    await app.run_async()

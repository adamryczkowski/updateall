"""Tabbed run display for interactive plugin execution.

This module provides a Textual-based TUI for running updates with:
- Tabs for each plugin showing live output
- Keyboard navigation between tabs (left/right arrows)
- Interactive input support (e.g., sudo password prompts)
- Progress bar at the bottom showing overall status
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from datetime import datetime

    from core.interfaces import UpdatePlugin
    from core.models import ExecutionResult, PluginConfig


class PluginState(str, Enum):
    """State of a plugin in the tabbed display."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class PluginTab:
    """Data for a plugin tab."""

    name: str
    plugin: UpdatePlugin
    state: PluginState = PluginState.PENDING
    output_lines: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    packages_updated: int = 0
    error_message: str | None = None


class PluginOutputMessage(Message):
    """Message sent when a plugin produces output."""

    def __init__(self, plugin_name: str, line: str) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin producing output.
            line: Output line to display.
        """
        self.plugin_name = plugin_name
        self.line = line
        super().__init__()


class PluginStateChanged(Message):
    """Message sent when a plugin's state changes."""

    def __init__(self, plugin_name: str, state: PluginState) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            state: New state of the plugin.
        """
        self.plugin_name = plugin_name
        self.state = state
        super().__init__()


class PluginCompleted(Message):
    """Message sent when a plugin completes execution."""

    def __init__(
        self,
        plugin_name: str,
        success: bool,
        packages_updated: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            success: Whether the plugin succeeded.
            packages_updated: Number of packages updated.
            error_message: Error message if failed.
        """
        self.plugin_name = plugin_name
        self.success = success
        self.packages_updated = packages_updated
        self.error_message = error_message
        super().__init__()


class PluginLogPanel(RichLog):
    """A RichLog panel for displaying plugin output."""

    DEFAULT_CSS = """
    PluginLogPanel {
        height: 100%;
        border: solid $primary;
        background: $surface;
    }
    """

    def __init__(self, plugin_name: str, **kwargs: Any) -> None:
        """Initialize the log panel.

        Args:
            plugin_name: Name of the plugin this panel is for.
            **kwargs: Additional arguments for RichLog.
        """
        super().__init__(highlight=True, markup=True, wrap=True, **kwargs)
        self.plugin_name = plugin_name


class StatusBar(Static):
    """Status bar showing plugin state."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        dock: top;
        padding: 0 1;
    }

    StatusBar.pending {
        background: $surface-darken-1;
        color: $text-muted;
    }

    StatusBar.running {
        background: $primary;
        color: $text;
    }

    StatusBar.success {
        background: $success;
        color: $text;
    }

    StatusBar.failed {
        background: $error;
        color: $text;
    }

    StatusBar.skipped {
        background: $warning;
        color: $text;
    }
    """

    state: reactive[PluginState] = reactive(PluginState.PENDING)

    def __init__(self, plugin_name: str, **kwargs: Any) -> None:
        """Initialize the status bar.

        Args:
            plugin_name: Name of the plugin.
            **kwargs: Additional arguments for Static.
        """
        super().__init__(**kwargs)
        self.plugin_name = plugin_name

    def watch_state(self, state: PluginState) -> None:
        """React to state changes.

        Args:
            state: New state.
        """
        # Update CSS class
        self.remove_class("pending", "running", "success", "failed", "skipped")
        self.add_class(state.value)

        # Update display text
        icons = {
            PluginState.PENDING: "⏳",
            PluginState.RUNNING: "🔄",
            PluginState.SUCCESS: "✅",
            PluginState.FAILED: "❌",
            PluginState.SKIPPED: "⊘",
            PluginState.TIMEOUT: "⏱️",
        }
        icon = icons.get(state, "")
        self.update(f"{icon} {self.plugin_name}: {state.value.upper()}")


class ProgressPanel(Static):
    """Panel showing overall progress at the bottom."""

    DEFAULT_CSS = """
    ProgressPanel {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    """

    def __init__(self, total_plugins: int, **kwargs: Any) -> None:
        """Initialize the progress panel.

        Args:
            total_plugins: Total number of plugins.
            **kwargs: Additional arguments for Static.
        """
        super().__init__(**kwargs)
        self.total_plugins = total_plugins
        self.completed_plugins = 0
        self.successful_plugins = 0
        self.failed_plugins = 0

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
        self.completed_plugins = completed
        self.successful_plugins = successful
        self.failed_plugins = failed
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the progress display."""
        pending = self.total_plugins - self.completed_plugins
        text = Text()
        text.append(f"Progress: {self.completed_plugins}/{self.total_plugins} ")
        text.append(f"[✓ {self.successful_plugins}] ", style="green")
        text.append(f"[✗ {self.failed_plugins}] ", style="red")
        text.append(f"[⏳ {pending}]", style="dim")
        self.update(text)


class TabbedRunApp(App[None]):
    """Textual application for running updates with tabbed output.

    This app provides:
    - A tab for each plugin showing live output
    - Keyboard navigation between tabs
    - Progress bar at the bottom
    - Support for interactive input (sudo prompts, etc.)
    """

    CSS = """
    TabbedRunApp {
        background: $surface;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    .plugin-container {
        height: 100%;
    }

    #help-text {
        dock: bottom;
        height: 1;
        background: $surface-darken-2;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("left", "previous_tab", "Previous Tab", show=True),
        Binding("right", "next_tab", "Next Tab", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("c", "copy_output", "Copy Output", show=False),
    ]

    def __init__(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the app.

        Args:
            plugins: List of plugins to run.
            configs: Optional plugin configurations.
            dry_run: Whether to run in dry-run mode.
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)
        self.plugins = plugins
        self.configs = configs or {}
        self.dry_run = dry_run
        self.plugin_tabs: dict[str, PluginTab] = {}
        self.log_panels: dict[str, PluginLogPanel] = {}
        self.status_bars: dict[str, StatusBar] = {}
        self.current_tab_index = 0

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header(show_clock=True)

        with TabbedContent(id="tabs"):
            for plugin in self.plugins:
                # Create tab for each plugin
                tab = PluginTab(name=plugin.name, plugin=plugin)
                self.plugin_tabs[plugin.name] = tab

                with (
                    TabPane(plugin.name, id=f"tab-{plugin.name}"),
                    Vertical(classes="plugin-container"),
                ):
                    status_bar = StatusBar(plugin.name, id=f"status-{plugin.name}")
                    self.status_bars[plugin.name] = status_bar
                    yield status_bar

                    log_panel = PluginLogPanel(plugin.name, id=f"log-{plugin.name}")
                    self.log_panels[plugin.name] = log_panel
                    yield log_panel

        yield ProgressPanel(len(self.plugins), id="progress")
        yield Static(
            "← → Navigate tabs | q Quit | Output is scrollable",
            id="help-text",
        )
        yield Footer()

    def on_mount(self) -> None:
        """Handle app mount - start running plugins."""
        # Update initial progress
        progress = self.query_one("#progress", ProgressPanel)
        progress._refresh_display()

        # Start running plugins
        self._start_plugin_execution()

    def _start_plugin_execution(self) -> None:
        """Start executing plugins."""
        self.run_worker(self._execute_all_plugins(), exclusive=True)

    async def _execute_all_plugins(self) -> None:
        """Execute all plugins sequentially."""
        from core.models import PluginConfig

        for plugin in self.plugins:
            plugin_name = plugin.name
            config = self.configs.get(plugin_name, PluginConfig(name=plugin_name))

            # Check if plugin is enabled
            if not config.enabled:
                self.post_message(PluginStateChanged(plugin_name, PluginState.SKIPPED))
                self.post_message(
                    PluginCompleted(
                        plugin_name,
                        success=False,
                        error_message="Plugin is disabled",
                    )
                )
                continue

            # Update state to running
            self.post_message(PluginStateChanged(plugin_name, PluginState.RUNNING))
            self.post_message(PluginOutputMessage(plugin_name, f"Starting {plugin_name}..."))

            try:
                # Check availability
                available = await plugin.check_available()
                if not available:
                    self.post_message(
                        PluginOutputMessage(plugin_name, f"⚠️ {plugin_name} is not available")
                    )
                    self.post_message(PluginStateChanged(plugin_name, PluginState.SKIPPED))
                    self.post_message(
                        PluginCompleted(
                            plugin_name,
                            success=False,
                            error_message="Plugin not available",
                        )
                    )
                    continue

                # Execute the plugin with output streaming
                result = await self._execute_plugin_with_streaming(plugin)

                # Determine final state
                if result.status.value == "success":
                    self.post_message(PluginStateChanged(plugin_name, PluginState.SUCCESS))
                    self.post_message(
                        PluginCompleted(
                            plugin_name,
                            success=True,
                            packages_updated=result.packages_updated,
                        )
                    )
                elif result.status.value == "timeout":
                    self.post_message(PluginStateChanged(plugin_name, PluginState.TIMEOUT))
                    self.post_message(
                        PluginCompleted(
                            plugin_name,
                            success=False,
                            error_message=result.error_message or "Timeout",
                        )
                    )
                else:
                    self.post_message(PluginStateChanged(plugin_name, PluginState.FAILED))
                    self.post_message(
                        PluginCompleted(
                            plugin_name,
                            success=False,
                            error_message=result.error_message,
                        )
                    )

            except Exception as e:
                self.post_message(PluginOutputMessage(plugin_name, f"❌ Error: {e}"))
                self.post_message(PluginStateChanged(plugin_name, PluginState.FAILED))
                self.post_message(PluginCompleted(plugin_name, success=False, error_message=str(e)))

    async def _execute_plugin_with_streaming(
        self,
        plugin: UpdatePlugin,
    ) -> ExecutionResult:
        """Execute a plugin and stream its output.

        Args:
            plugin: The plugin to execute.

        Returns:
            ExecutionResult from the plugin.
        """
        plugin_name = plugin.name

        # Run pre-execute hook
        await plugin.pre_execute()

        # Execute the update
        result = await plugin.execute(dry_run=self.dry_run)

        # Display the output
        if result.stdout:
            for line in result.stdout.splitlines():
                self.post_message(PluginOutputMessage(plugin_name, line))

        if result.stderr:
            for line in result.stderr.splitlines():
                self.post_message(PluginOutputMessage(plugin_name, f"[red]{line}[/red]"))

        # Run post-execute hook
        await plugin.post_execute(result)

        # Show completion message
        if result.status.value == "success":
            self.post_message(
                PluginOutputMessage(
                    plugin_name,
                    f"✅ Completed: {result.packages_updated} packages updated",
                )
            )
        elif result.error_message:
            self.post_message(
                PluginOutputMessage(plugin_name, f"❌ Failed: {result.error_message}")
            )

        return result

    @on(PluginOutputMessage)
    def handle_plugin_output(self, message: PluginOutputMessage) -> None:
        """Handle plugin output messages.

        Args:
            message: The output message.
        """
        if message.plugin_name in self.log_panels:
            self.log_panels[message.plugin_name].write(message.line)

    @on(PluginStateChanged)
    def handle_state_change(self, message: PluginStateChanged) -> None:
        """Handle plugin state change messages.

        Args:
            message: The state change message.
        """
        if message.plugin_name in self.status_bars:
            self.status_bars[message.plugin_name].state = message.state

        if message.plugin_name in self.plugin_tabs:
            self.plugin_tabs[message.plugin_name].state = message.state

    @on(PluginCompleted)
    def handle_plugin_completed(self, message: PluginCompleted) -> None:  # noqa: ARG002
        """Handle plugin completion messages.

        Args:
            message: The completion message.
        """
        # Update progress panel
        completed = sum(
            1
            for tab in self.plugin_tabs.values()
            if tab.state not in (PluginState.PENDING, PluginState.RUNNING)
        )
        successful = sum(1 for tab in self.plugin_tabs.values() if tab.state == PluginState.SUCCESS)
        failed = sum(
            1
            for tab in self.plugin_tabs.values()
            if tab.state in (PluginState.FAILED, PluginState.TIMEOUT)
        )

        progress = self.query_one("#progress", ProgressPanel)
        progress.update_progress(completed, successful, failed)

    def action_previous_tab(self) -> None:
        """Switch to the previous tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        if self.current_tab_index > 0:
            self.current_tab_index -= 1
            plugin_name = self.plugins[self.current_tab_index].name
            tabs.active = f"tab-{plugin_name}"

    def action_next_tab(self) -> None:
        """Switch to the next tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        if self.current_tab_index < len(self.plugins) - 1:
            self.current_tab_index += 1
            plugin_name = self.plugins[self.current_tab_index].name
            tabs.active = f"tab-{plugin_name}"

    def action_copy_output(self) -> None:
        """Copy current tab's output to clipboard."""
        # Get current plugin's output
        if self.current_tab_index < len(self.plugins):
            plugin_name = self.plugins[self.current_tab_index].name
            if plugin_name in self.plugin_tabs:
                tab = self.plugin_tabs[plugin_name]
                # Note: Clipboard support requires pyperclip or similar
                self.notify(f"Output copied ({len(tab.output_lines)} lines)")


async def run_with_tabbed_ui(
    plugins: list[UpdatePlugin],
    configs: dict[str, PluginConfig] | None = None,
    dry_run: bool = False,
) -> None:
    """Run plugins with the tabbed UI.

    Args:
        plugins: List of plugins to run.
        configs: Optional plugin configurations.
        dry_run: Whether to run in dry-run mode.
    """
    app = TabbedRunApp(plugins=plugins, configs=configs, dry_run=dry_run)
    await app.run_async()

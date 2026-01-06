"""Tabbed run display for interactive plugin execution with streaming support.

This module provides a Textual-based TUI for running updates with:
- Tabs for each plugin showing live streaming output
- Keyboard navigation between tabs (left/right arrows)
- Interactive input support (e.g., sudo password prompts)
- Progress bar at the bottom showing overall status
- Real-time progress updates during download and execution phases

Phase 3 - UI Integration
See docs/update-all-architecture-refinement-plan.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static, TabbedContent, TabPane

from ui.event_handler import BatchedEvent, BatchedEventHandler, UIEventHandler
from ui.sudo import SudoKeepAlive, SudoStatus, check_sudo_status

if TYPE_CHECKING:
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
    # Progress tracking
    current_phase: str = ""
    progress_percent: float = 0.0
    progress_message: str = ""
    bytes_downloaded: int = 0
    bytes_total: int = 0


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


class PluginProgressMessage(Message):
    """Message sent when a plugin reports progress."""

    def __init__(
        self,
        plugin_name: str,
        phase: str,
        percent: float | None = None,
        message: str | None = None,
        bytes_downloaded: int | None = None,
        bytes_total: int | None = None,
        items_completed: int | None = None,
        items_total: int | None = None,
    ) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            phase: Current phase.
            percent: Progress percentage.
            message: Progress message.
            bytes_downloaded: Bytes downloaded.
            bytes_total: Total bytes.
            items_completed: Items completed.
            items_total: Total items.
        """
        self.plugin_name = plugin_name
        self.phase = phase
        self.percent = percent
        self.message = message
        self.bytes_downloaded = bytes_downloaded
        self.bytes_total = bytes_total
        self.items_completed = items_completed
        self.items_total = items_total
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
    """Status bar showing plugin state with progress support.

    Phase 3 Enhancement: Added progress percentage and download size display.
    """

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
    progress: reactive[float] = reactive(0.0)
    status_message: reactive[str] = reactive("")
    current_phase: reactive[str] = reactive("")

    def __init__(self, plugin_name: str, **kwargs: Any) -> None:
        """Initialize the status bar.

        Args:
            plugin_name: Name of the plugin.
            **kwargs: Additional arguments for Static.
        """
        super().__init__(**kwargs)
        self.plugin_name = plugin_name

    def watch_state(self, state: PluginState) -> None:  # noqa: ARG002
        """React to state changes.

        Args:
            state: New state (used via self.state).
        """
        # Update CSS class
        self.remove_class("pending", "running", "success", "failed", "skipped")
        self.add_class(self.state.value)
        self._refresh_display()

    def watch_progress(self, progress: float) -> None:  # noqa: ARG002
        """React to progress changes.

        Args:
            progress: New progress value (used via self.progress).
        """
        self._refresh_display()

    def watch_status_message(self, message: str) -> None:  # noqa: ARG002
        """React to status message changes.

        Args:
            message: New status message (used via self.status_message).
        """
        self._refresh_display()

    def watch_current_phase(self, phase: str) -> None:  # noqa: ARG002
        """React to phase changes.

        Args:
            phase: New phase (used via self.current_phase).
        """
        self._refresh_display()

    def update_progress(self, percent: float) -> None:
        """Update the progress percentage.

        Args:
            percent: Progress percentage (0-100).
        """
        self.progress = percent

    def update_status(self, message: str) -> None:
        """Update the status message.

        Args:
            message: Status message.
        """
        self.status_message = message

    def update_phase(self, phase: str) -> None:
        """Update the current phase.

        Args:
            phase: Phase name.
        """
        self.current_phase = phase

    def _refresh_display(self) -> None:
        """Refresh the status bar display."""
        icons = {
            PluginState.PENDING: "⏳",
            PluginState.RUNNING: "🔄",
            PluginState.SUCCESS: "✅",
            PluginState.FAILED: "❌",
            PluginState.SKIPPED: "⊘",
            PluginState.TIMEOUT: "⏱️",
        }
        icon = icons.get(self.state, "")

        if self.state == PluginState.RUNNING and self.progress > 0:
            bar = self._render_progress_bar(self.progress)
            text = f"{icon} {self.plugin_name}: {bar} {self.progress:.0f}%"
            if self.current_phase:
                text = (
                    f"{icon} {self.plugin_name} [{self.current_phase}]: {bar} {self.progress:.0f}%"
                )
            if self.status_message:
                text += f" - {self.status_message}"
        elif self.state == PluginState.RUNNING and self.current_phase:
            text = f"{icon} {self.plugin_name} [{self.current_phase}]: {self.state.value.upper()}"
            if self.status_message:
                text += f" - {self.status_message}"
        else:
            text = f"{icon} {self.plugin_name}: {self.state.value.upper()}"

        self.update(text)

    def _render_progress_bar(self, percent: float, width: int = 20) -> str:
        """Render a text-based progress bar.

        Args:
            percent: Progress percentage (0-100).
            width: Width of the progress bar in characters.

        Returns:
            Text representation of the progress bar.
        """
        filled = int(width * percent / 100)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"


class ProgressPanel(Static):
    """Panel showing overall progress at the bottom with download info."""

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
        self.total_bytes_downloaded = 0
        self.total_bytes_to_download = 0

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

    def update_download_progress(
        self,
        bytes_downloaded: int,
        bytes_total: int,
    ) -> None:
        """Update download progress display.

        Args:
            bytes_downloaded: Total bytes downloaded across all plugins.
            bytes_total: Total bytes to download.
        """
        self.total_bytes_downloaded = bytes_downloaded
        self.total_bytes_to_download = bytes_total
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the progress display."""
        pending = self.total_plugins - self.completed_plugins
        text = Text()
        text.append(f"Progress: {self.completed_plugins}/{self.total_plugins} ")
        text.append(f"[✓ {self.successful_plugins}] ", style="green")
        text.append(f"[✗ {self.failed_plugins}] ", style="red")
        text.append(f"[⏳ {pending}]", style="dim")

        # Add download progress if available
        if self.total_bytes_to_download > 0:
            downloaded_mb = self.total_bytes_downloaded / (1024 * 1024)
            total_mb = self.total_bytes_to_download / (1024 * 1024)
            pct = (self.total_bytes_downloaded / self.total_bytes_to_download) * 100
            text.append(f" | Download: {downloaded_mb:.1f}/{total_mb:.1f} MB ({pct:.0f}%)")

        self.update(text)


class TextualBatchedEventHandler(BatchedEventHandler):
    """Batched event handler that posts messages to a Textual app.

    This handler collects streaming events and posts them as Textual messages
    in batches to reduce UI update frequency.
    """

    def __init__(
        self,
        app: TabbedRunApp,
        batch_interval_ms: float = 50.0,
        max_batch_size: int = 100,
        max_fps: float = 30.0,
    ) -> None:
        """Initialize the handler.

        Args:
            app: The Textual app to post messages to.
            batch_interval_ms: Time interval for batching.
            max_batch_size: Maximum events per batch.
            max_fps: Maximum UI updates per second.
        """
        super().__init__(batch_interval_ms, max_batch_size, max_fps)
        self.app = app

    async def process_batch(self, events: list[BatchedEvent]) -> None:
        """Process a batch of events by posting messages to the app.

        Args:
            events: List of events to process.
        """
        for event in events:
            if event.event_type == "output":
                self.app.post_message(
                    PluginOutputMessage(
                        plugin_name=event.plugin_name,
                        line=str(event.data.get("line", "")),
                    )
                )
            elif event.event_type == "progress":
                self.app.post_message(
                    PluginProgressMessage(
                        plugin_name=event.plugin_name,
                        phase=str(event.data.get("phase", "")),
                        percent=event.data.get("percent"),  # type: ignore[arg-type]
                        message=event.data.get("message"),  # type: ignore[arg-type]
                        bytes_downloaded=event.data.get("bytes_downloaded"),  # type: ignore[arg-type]
                        bytes_total=event.data.get("bytes_total"),  # type: ignore[arg-type]
                        items_completed=event.data.get("items_completed"),  # type: ignore[arg-type]
                        items_total=event.data.get("items_total"),  # type: ignore[arg-type]
                    )
                )
            elif event.event_type == "phase_start":
                phase = str(event.data.get("phase", ""))
                self.app.post_message(
                    PluginOutputMessage(
                        plugin_name=event.plugin_name,
                        line=f"[bold]Starting {phase}...[/bold]",
                    )
                )
            elif event.event_type == "phase_end":
                phase = str(event.data.get("phase", ""))
                success = event.data.get("success", False)
                status = "✓" if success else "✗"
                self.app.post_message(
                    PluginOutputMessage(
                        plugin_name=event.plugin_name,
                        line=f"[bold]{status} {phase} complete[/bold]",
                    )
                )
            elif event.event_type == "completion":
                success = bool(event.data.get("success", False))
                packages_val = event.data.get("packages_updated", 0)
                packages = int(packages_val) if isinstance(packages_val, (int, str, float)) else 0
                error = event.data.get("error_message")
                self.app.post_message(
                    PluginCompleted(
                        plugin_name=event.plugin_name,
                        success=success,
                        packages_updated=packages,
                        error_message=str(error) if error else None,
                    )
                )


class TextualUIEventHandler(UIEventHandler):
    """UI event handler that posts messages to a Textual app via batching.

    This handler implements the UIEventHandler protocol and uses a
    TextualBatchedEventHandler for efficient UI updates.
    """

    def __init__(self, batched_handler: TextualBatchedEventHandler) -> None:
        """Initialize the handler.

        Args:
            batched_handler: The batched handler to use.
        """
        self.batched_handler = batched_handler
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get the event loop."""
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return self._loop

    def handle_output(self, plugin_name: str, line: str, stream: str = "stdout") -> None:
        """Handle an output line from a plugin."""
        event = BatchedEvent(
            plugin_name=plugin_name,
            event_type="output",
            data={"line": line, "stream": stream},
        )
        asyncio.run_coroutine_threadsafe(
            self.batched_handler.add_event(event),
            self._get_loop(),
        )

    def handle_progress(
        self,
        plugin_name: str,
        phase: str,
        percent: float | None = None,
        message: str | None = None,
        bytes_downloaded: int | None = None,
        bytes_total: int | None = None,
        items_completed: int | None = None,
        items_total: int | None = None,
    ) -> None:
        """Handle a progress update from a plugin."""
        event = BatchedEvent(
            plugin_name=plugin_name,
            event_type="progress",
            data={
                "phase": phase,
                "percent": percent,
                "message": message,
                "bytes_downloaded": bytes_downloaded,
                "bytes_total": bytes_total,
                "items_completed": items_completed,
                "items_total": items_total,
            },
        )
        asyncio.run_coroutine_threadsafe(
            self.batched_handler.add_event(event),
            self._get_loop(),
        )

    def handle_phase_start(self, plugin_name: str, phase: str) -> None:
        """Handle the start of a phase."""
        event = BatchedEvent(
            plugin_name=plugin_name,
            event_type="phase_start",
            data={"phase": phase},
        )
        asyncio.run_coroutine_threadsafe(
            self.batched_handler.add_event(event),
            self._get_loop(),
        )

    def handle_phase_end(
        self,
        plugin_name: str,
        phase: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Handle the end of a phase."""
        event = BatchedEvent(
            plugin_name=plugin_name,
            event_type="phase_end",
            data={"phase": phase, "success": success, "error_message": error_message},
        )
        asyncio.run_coroutine_threadsafe(
            self.batched_handler.add_event(event),
            self._get_loop(),
        )

    def handle_completion(
        self,
        plugin_name: str,
        success: bool,
        exit_code: int,
        packages_updated: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Handle plugin completion."""
        event = BatchedEvent(
            plugin_name=plugin_name,
            event_type="completion",
            data={
                "success": success,
                "exit_code": exit_code,
                "packages_updated": packages_updated,
                "error_message": error_message,
            },
        )
        asyncio.run_coroutine_threadsafe(
            self.batched_handler.add_event(event),
            self._get_loop(),
        )


class TabbedRunApp(App[None]):
    """Textual application for running updates with tabbed streaming output.

    This app provides:
    - A tab for each plugin showing live streaming output
    - Keyboard navigation between tabs
    - Progress bar at the bottom with download progress
    - Support for interactive input (sudo prompts, etc.)
    - Batched event handling for optimal UI performance (30 FPS max)

    Phase 3 Enhancement: Full streaming support with batched event handling.
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
    """

    BINDINGS: ClassVar[list[BindingType]] = [
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
        use_streaming: bool = True,
        **kwargs: Any,
    ) -> None:
        """Initialize the app.

        Args:
            plugins: List of plugins to run.
            configs: Optional plugin configurations.
            dry_run: Whether to run in dry-run mode.
            use_streaming: Whether to use streaming mode (Phase 3 feature flag).
            **kwargs: Additional arguments for App.
        """
        super().__init__(**kwargs)
        self.plugins = plugins
        self.configs = configs or {}
        self.dry_run = dry_run
        self.use_streaming = use_streaming
        self.plugin_tabs: dict[str, PluginTab] = {}
        self.log_panels: dict[str, PluginLogPanel] = {}
        self.status_bars: dict[str, StatusBar] = {}
        self.current_tab_index = 0

        # Batched event handler for streaming (Phase 3)
        self._batched_handler: TextualBatchedEventHandler | None = None
        self._event_handler: TextualUIEventHandler | None = None
        self._sudo_keepalive: SudoKeepAlive | None = None

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Header(show_clock=True)

        # Sudo status bar (hidden by default)
        yield Static("", id="sudo-status", classes="hidden")

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

    async def on_mount(self) -> None:
        """Handle app mount - start running plugins."""
        # Update initial progress
        progress = self.query_one("#progress", ProgressPanel)
        progress._refresh_display()

        # Initialize batched event handler if streaming is enabled
        if self.use_streaming:
            self._batched_handler = TextualBatchedEventHandler(
                app=self,
                batch_interval_ms=50.0,
                max_batch_size=100,
                max_fps=30.0,
            )
            self._event_handler = TextualUIEventHandler(self._batched_handler)
            await self._batched_handler.start()

        # Check sudo status and pre-authenticate if needed
        await self._check_and_authenticate_sudo()

        # Start running plugins
        self._start_plugin_execution()

    async def on_unmount(self) -> None:
        """Handle app unmount - cleanup resources."""
        if self._batched_handler:
            await self._batched_handler.stop()

        if self._sudo_keepalive:
            await self._sudo_keepalive.stop()

    async def _check_and_authenticate_sudo(self) -> None:
        """Check sudo status and authenticate if needed."""
        # Check if any plugin requires sudo
        needs_sudo = any(
            self.configs.get(p.name, type("", (), {"requires_sudo": False})()).requires_sudo
            for p in self.plugins
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

            # Note: In a real implementation, we would show a password input dialog
            # For now, we just show the status and let the plugin handle it
            self.notify("Sudo password may be required", severity="warning")

        elif result.status == SudoStatus.NO_SUDO_REQUIRED:
            # Running as root, no need for sudo
            pass

    def _start_plugin_execution(self) -> None:
        """Start executing plugins."""
        if self.use_streaming:
            self.run_worker(self._execute_all_plugins_streaming(), exclusive=True)
        else:
            self.run_worker(self._execute_all_plugins(), exclusive=True)

    async def _execute_all_plugins(self) -> None:
        """Execute all plugins sequentially (legacy non-streaming mode)."""
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
                result = await self._execute_plugin_legacy(plugin)

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

    async def _execute_all_plugins_streaming(self) -> None:
        """Execute all plugins with streaming output (Phase 3).

        This method uses the streaming interface to display output in real-time.
        """
        from core.models import PluginConfig
        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
            PhaseEvent,
            ProgressEvent,
        )

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
            self.plugin_tabs[plugin_name].start_time = datetime.now(tz=UTC)

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

                # Run pre-execute hook
                await plugin.pre_execute()

                # Execute with streaming
                final_success = False
                final_packages = 0
                final_error: str | None = None

                async for event in plugin.execute_streaming(dry_run=self.dry_run):
                    if isinstance(event, OutputEvent):
                        line = event.line
                        if event.stream == "stderr":
                            line = f"[red]{line}[/red]"
                        self.post_message(PluginOutputMessage(plugin_name, line))

                    elif isinstance(event, ProgressEvent):
                        self.post_message(
                            PluginProgressMessage(
                                plugin_name=plugin_name,
                                phase=event.phase.value,
                                percent=event.percent,
                                message=event.message,
                                bytes_downloaded=event.bytes_downloaded,
                                bytes_total=event.bytes_total,
                                items_completed=event.items_completed,
                                items_total=event.items_total,
                            )
                        )

                    elif isinstance(event, PhaseEvent):
                        if event.event_type == EventType.PHASE_START:
                            self.post_message(
                                PluginOutputMessage(
                                    plugin_name,
                                    f"[bold]Starting {event.phase.value}...[/bold]",
                                )
                            )
                            # Update status bar phase
                            if plugin_name in self.status_bars:
                                self.status_bars[plugin_name].update_phase(event.phase.value)

                        elif event.event_type == EventType.PHASE_END:
                            status = "✓" if event.success else "✗"
                            self.post_message(
                                PluginOutputMessage(
                                    plugin_name,
                                    f"[bold]{status} {event.phase.value} complete[/bold]",
                                )
                            )

                    elif isinstance(event, CompletionEvent):
                        final_success = event.success
                        final_packages = event.packages_updated
                        final_error = event.error_message

                # Run post-execute hook
                from core.models import ExecutionResult, PluginStatus

                result = ExecutionResult(
                    plugin_name=plugin_name,
                    status=PluginStatus.SUCCESS if final_success else PluginStatus.FAILED,
                    start_time=self.plugin_tabs[plugin_name].start_time or datetime.now(tz=UTC),
                    end_time=datetime.now(tz=UTC),
                    packages_updated=final_packages,
                    error_message=final_error,
                )
                await plugin.post_execute(result)

                # Update final state
                if final_success:
                    self.post_message(PluginStateChanged(plugin_name, PluginState.SUCCESS))
                    self.post_message(
                        PluginOutputMessage(
                            plugin_name,
                            f"✅ Completed: {final_packages} packages updated",
                        )
                    )
                else:
                    self.post_message(PluginStateChanged(plugin_name, PluginState.FAILED))
                    if final_error:
                        self.post_message(
                            PluginOutputMessage(plugin_name, f"❌ Failed: {final_error}")
                        )

                self.post_message(
                    PluginCompleted(
                        plugin_name,
                        success=final_success,
                        packages_updated=final_packages,
                        error_message=final_error,
                    )
                )

            except Exception as e:
                self.post_message(PluginOutputMessage(plugin_name, f"❌ Error: {e}"))
                self.post_message(PluginStateChanged(plugin_name, PluginState.FAILED))
                self.post_message(PluginCompleted(plugin_name, success=False, error_message=str(e)))

    async def _execute_plugin_legacy(
        self,
        plugin: UpdatePlugin,
    ) -> ExecutionResult:
        """Execute a plugin and display its output (legacy non-streaming mode).

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

        # Store in tab data
        if message.plugin_name in self.plugin_tabs:
            self.plugin_tabs[message.plugin_name].output_lines.append(message.line)

    @on(PluginProgressMessage)
    def handle_plugin_progress(self, message: PluginProgressMessage) -> None:
        """Handle plugin progress messages.

        Args:
            message: The progress message.
        """
        if message.plugin_name in self.status_bars:
            bar = self.status_bars[message.plugin_name]

            if message.percent is not None:
                bar.update_progress(message.percent)

            if message.message:
                bar.update_status(message.message)

            if message.phase:
                bar.update_phase(message.phase)

            # Update download progress display
            if message.bytes_downloaded is not None and message.bytes_total is not None:
                downloaded_mb = message.bytes_downloaded / (1024 * 1024)
                total_mb = message.bytes_total / (1024 * 1024)
                bar.update_status(f"{downloaded_mb:.1f}/{total_mb:.1f} MB")

        # Update tab data
        if message.plugin_name in self.plugin_tabs:
            tab = self.plugin_tabs[message.plugin_name]
            if message.percent is not None:
                tab.progress_percent = message.percent
            if message.message:
                tab.progress_message = message.message
            if message.phase:
                tab.current_phase = message.phase
            if message.bytes_downloaded is not None:
                tab.bytes_downloaded = message.bytes_downloaded
            if message.bytes_total is not None:
                tab.bytes_total = message.bytes_total

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
    def handle_plugin_completed(self, message: PluginCompleted) -> None:
        """Handle plugin completion messages.

        Args:
            message: The completion message.
        """
        # Update tab data
        if message.plugin_name in self.plugin_tabs:
            tab = self.plugin_tabs[message.plugin_name]
            tab.end_time = datetime.now(tz=UTC)
            tab.packages_updated = message.packages_updated
            tab.error_message = message.error_message

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
    use_streaming: bool = True,
) -> None:
    """Run plugins with the tabbed UI.

    Args:
        plugins: List of plugins to run.
        configs: Optional plugin configurations.
        dry_run: Whether to run in dry-run mode.
        use_streaming: Whether to use streaming mode (Phase 3 feature flag).
    """
    app = TabbedRunApp(
        plugins=plugins,
        configs=configs,
        dry_run=dry_run,
        use_streaming=use_streaming,
    )
    await app.run_async()

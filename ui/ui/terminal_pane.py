"""TerminalPane container widget for interactive terminal tabs.

This module provides a TerminalPane widget that combines a TerminalView
with a status bar and manages the connection between the view and a PTY session.

Phase 4 - Integration
See docs/interactive-tabs-implementation-plan.md section 3.2.5

UI Revision Plan - Phase 3 Status Bar
See docs/UI-revision-plan.md section 3.4
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from textual.containers import Container
from textual.events import Resize  # noqa: TC002 - Required at runtime for event dispatch
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from ui.input_router import InputRouter
from ui.key_bindings import KeyBindings
from ui.phase_status_bar import MetricsCollector, PhaseStatusBar
from ui.pty_manager import PTYSessionManager
from ui.pty_session import PTYReadTimeoutError
from ui.terminal_view import TerminalView

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from core.interfaces import UpdatePlugin


class PaneState(str, Enum):
    """State of a terminal pane."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    EXITED = "exited"


@dataclass
class PaneConfig:
    """Configuration for a terminal pane."""

    # Terminal dimensions
    columns: int = 80
    lines: int = 24
    scrollback_lines: int = 10000

    # PTY settings
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    # Display settings
    show_status_bar: bool = True
    show_scrollbar: bool = True

    # Phase 3: Status bar with metrics
    # See docs/UI-revision-plan.md section 3.4
    show_phase_status_bar: bool = True
    metrics_update_interval: float = 1.0


class PaneOutputMessage(Message):
    """Message sent when a pane produces output."""

    def __init__(self, pane_id: str, data: bytes) -> None:
        """Initialize the message.

        Args:
            pane_id: ID of the pane producing output.
            data: Raw output data.
        """
        self.pane_id = pane_id
        self.data = data
        super().__init__()


class PaneStateChanged(Message):
    """Message sent when a pane's state changes."""

    def __init__(self, pane_id: str, state: PaneState, exit_code: int | None = None) -> None:
        """Initialize the message.

        Args:
            pane_id: ID of the pane.
            state: New state of the pane.
            exit_code: Exit code if process exited.
        """
        self.pane_id = pane_id
        self.state = state
        self.exit_code = exit_code
        super().__init__()


class PaneStatusBar(Static):
    """Status bar for a terminal pane."""

    DEFAULT_CSS = """
    PaneStatusBar {
        height: 1;
        dock: top;
        padding: 0 1;
        background: $surface-darken-1;
        color: $text-muted;
    }

    PaneStatusBar.running {
        background: $primary;
        color: $text;
    }

    PaneStatusBar.success {
        background: $success;
        color: $text;
    }

    PaneStatusBar.failed {
        background: $error;
        color: $text;
    }

    PaneStatusBar.exited {
        background: $surface-darken-2;
        color: $text-muted;
    }
    """

    state: reactive[PaneState] = reactive(PaneState.IDLE)
    status_message: reactive[str] = reactive("")

    def __init__(
        self,
        pane_name: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the status bar.

        Args:
            pane_name: Name of the pane to display.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.pane_name = pane_name

    def watch_state(self, state: PaneState) -> None:
        """React to state changes.

        Args:
            state: New state.
        """
        # Update CSS classes
        self.remove_class("idle", "running", "success", "failed", "exited")
        self.add_class(state.value)
        self._refresh_display()

    def watch_status_message(self, message: str) -> None:  # noqa: ARG002
        """React to status message changes.

        Args:
            message: New status message.
        """
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the status bar display."""
        icons = {
            PaneState.IDLE: "⏸️",
            PaneState.RUNNING: "🔄",
            PaneState.SUCCESS: "✅",
            PaneState.FAILED: "❌",
            PaneState.EXITED: "⏹️",
        }
        icon = icons.get(self.state, "")

        text = f"{icon} {self.pane_name}: {self.state.value.upper()}"
        if self.status_message:
            text += f" - {self.status_message}"

        self.update(text)


class TerminalPane(Container):
    """Container widget combining TerminalView with status bar and PTY management.

    This widget provides:
    - A TerminalView for rendering terminal output
    - A status bar showing pane state
    - Connection management between TerminalView and PTY session
    - Input routing to the PTY session
    - Plugin-specific configuration support

    Example:
        pane = TerminalPane(
            pane_id="apt",
            pane_name="APT Updates",
            command=["/bin/bash", "-c", "apt update"],
        )
        await pane.start()
    """

    DEFAULT_CSS = """
    TerminalPane {
        height: 100%;
        width: 100%;
        layout: vertical;
    }

    TerminalPane TerminalView {
        height: 1fr;
        min-height: 10;
        border: solid $primary;
    }

    TerminalPane.focused TerminalView {
        border: solid $accent;
    }
    """

    # Class-level session manager shared across all panes
    _session_manager: ClassVar[PTYSessionManager | None] = None
    _manager_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    # Reactive properties
    is_focused: reactive[bool] = reactive(False)

    def __init__(
        self,
        pane_id: str,
        pane_name: str,
        command: list[str],
        *,
        config: PaneConfig | None = None,
        plugin: UpdatePlugin | None = None,
        key_bindings: KeyBindings | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the terminal pane.

        Args:
            pane_id: Unique identifier for this pane.
            pane_name: Display name for the pane.
            command: Command to run in the PTY.
            config: Pane configuration.
            plugin: Associated plugin (optional).
            key_bindings: Key bindings for input routing.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id or f"pane-{pane_id}", classes=classes)

        self.pane_id = pane_id
        self.pane_name = pane_name
        self.command = command
        self.config = config or PaneConfig()
        self.plugin = plugin
        self.key_bindings = key_bindings or KeyBindings()

        self._state = PaneState.IDLE
        self._exit_code: int | None = None
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._read_task: asyncio.Task[None] | None = None

        # Child widgets - initialized in compose()
        self._terminal_view: TerminalView | None = None
        self._status_bar: PaneStatusBar | None = None
        self._input_router: InputRouter | None = None

        # Phase 3: Status bar with metrics
        self._phase_status_bar: PhaseStatusBar | None = None
        self._metrics_collector: MetricsCollector | None = None
        self._metrics_update_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> PaneState:
        """Get the current pane state."""
        return self._state

    @property
    def exit_code(self) -> int | None:
        """Get the exit code if the process has exited."""
        return self._exit_code

    @property
    def terminal_view(self) -> TerminalView | None:
        """Get the terminal view widget."""
        return self._terminal_view

    @property
    def is_running(self) -> bool:
        """Check if the PTY process is running."""
        return self._state == PaneState.RUNNING

    @property
    def phase_status_bar(self) -> PhaseStatusBar | None:
        """Get the phase status bar widget.

        Returns:
            The PhaseStatusBar widget if enabled, None otherwise.
        """
        return self._phase_status_bar

    @property
    def metrics_collector(self) -> MetricsCollector | None:
        """Get the metrics collector.

        Returns:
            The MetricsCollector if enabled, None otherwise.
        """
        return self._metrics_collector

    @classmethod
    async def get_session_manager(cls) -> PTYSessionManager:
        """Get or create the shared session manager.

        Returns:
            The shared PTYSessionManager instance.
        """
        async with cls._manager_lock:
            if cls._session_manager is None:
                cls._session_manager = PTYSessionManager()
            return cls._session_manager

    @classmethod
    async def cleanup_session_manager(cls) -> None:
        """Clean up the shared session manager."""
        async with cls._manager_lock:
            if cls._session_manager is not None:
                await cls._session_manager.close_all()
                cls._session_manager = None

    def compose(self) -> ComposeResult:
        """Compose the pane layout."""
        if self.config.show_status_bar:
            self._status_bar = PaneStatusBar(
                self.pane_name,
                id=f"status-{self.pane_id}",
            )
            yield self._status_bar

        self._terminal_view = TerminalView(
            columns=self.config.columns,
            lines=self.config.lines,
            scrollback_lines=self.config.scrollback_lines,
            id=f"terminal-{self.pane_id}",
        )
        yield self._terminal_view

        # Phase 3: Add phase status bar with metrics if enabled
        if self.config.show_phase_status_bar:
            self._phase_status_bar = PhaseStatusBar(
                pane_id=self.pane_id,
                id=f"phase-status-{self.pane_id}",
            )
            yield self._phase_status_bar

    async def on_mount(self) -> None:
        """Handle mount event."""
        # Set up input router
        self._input_router = InputRouter(
            key_bindings=self.key_bindings,
            on_pty_input=self._handle_pty_input,
        )
        self._input_router.set_active_tab(self.pane_id)

    async def on_unmount(self) -> None:
        """Handle unmount event."""
        await self.stop()

    async def on_resize(self, event: Resize) -> None:
        """Handle resize events to adjust terminal dimensions.

        When the widget is resized, this calculates the new terminal dimensions
        based on the available space and updates both the terminal screen and
        the PTY session.

        Args:
            event: The resize event containing the new size.
        """
        # Calculate new terminal dimensions from widget size
        # The widget size is in character cells (Textual uses character-based layout)
        new_width = event.size.width
        new_height = event.size.height

        # Account for borders (2 characters: left + right for width, top + bottom for height)
        # The TerminalView has a border defined in CSS
        border_width = 2
        border_height = 2

        # Account for status bar if shown (1 line)
        status_bar_height = 1 if self.config.show_status_bar else 0

        # Calculate available space for terminal content
        columns = max(10, new_width - border_width)
        lines = max(5, new_height - border_height - status_bar_height)

        # Only resize if dimensions actually changed
        if columns != self.config.columns or lines != self.config.lines:
            await self.resize(columns, lines)

    def watch_is_focused(self, focused: bool) -> None:
        """React to focus changes.

        Args:
            focused: Whether the pane is focused.
        """
        if focused:
            self.add_class("focused")
        else:
            self.remove_class("focused")

    async def start(self) -> None:
        """Start the PTY session and begin reading output."""
        if self._state == PaneState.RUNNING:
            return

        self._state = PaneState.RUNNING
        self._start_time = datetime.now(tz=UTC)
        self._update_status_bar()

        # Get session manager
        manager = await self.get_session_manager()

        # Prepare environment
        env = dict(self.config.env)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLUMNS", str(self.config.columns))
        env.setdefault("LINES", str(self.config.lines))

        # Create PTY session
        await manager.create_session(
            command=self.command,
            session_id=self.pane_id,
            env=env,
            cwd=self.config.cwd,
            cols=self.config.columns,
            rows=self.config.lines,
        )

        # Start reading output
        self._read_task = asyncio.create_task(self._read_loop())

        # Phase 3: Start metrics collection if phase status bar is enabled
        if self.config.show_phase_status_bar and self._phase_status_bar:
            session = manager.get_session(self.pane_id)
            pid = session.pid if session else None
            self._metrics_collector = MetricsCollector(
                pid=pid,
                update_interval=self.config.metrics_update_interval,
            )
            self._metrics_collector.start()
            self._metrics_collector.update_status("In Progress")
            self._phase_status_bar.set_metrics_collector(self._metrics_collector)
            self._metrics_update_task = asyncio.create_task(self._metrics_update_loop())

        # Post state change message
        self.post_message(PaneStateChanged(self.pane_id, self._state))

    async def stop(self) -> None:
        """Stop the PTY session."""
        # Phase 3: Stop metrics collection
        if self._metrics_update_task is not None:
            self._metrics_update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._metrics_update_task
            self._metrics_update_task = None

        if self._metrics_collector is not None:
            self._metrics_collector.stop()
            self._metrics_collector = None

        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None

        manager = await self.get_session_manager()
        await manager.close_session(self.pane_id)

    async def write(self, data: bytes) -> None:
        """Write data to the PTY session.

        Args:
            data: Data to write.
        """
        if self._state != PaneState.RUNNING:
            return

        manager = await self.get_session_manager()
        # Session may have closed, so suppress any errors
        with contextlib.suppress(Exception):
            await manager.write_to_session(self.pane_id, data)

    async def resize(self, columns: int, lines: int) -> None:
        """Resize the terminal.

        Args:
            columns: New width in columns.
            lines: New height in lines.
        """
        self.config.columns = columns
        self.config.lines = lines

        if self._terminal_view:
            self._terminal_view.resize_terminal(columns, lines)

        if self._state == PaneState.RUNNING:
            manager = await self.get_session_manager()
            # Session may have closed, so suppress any errors
            with contextlib.suppress(Exception):
                await manager.resize_session(self.pane_id, columns, lines)

    async def _read_loop(self) -> None:
        """Background task to read from PTY and update terminal view."""
        import logging

        logger = logging.getLogger("terminal_pane")

        logger.debug(f"[{self.pane_id}] _read_loop started")
        manager = await self.get_session_manager()
        logger.debug(f"[{self.pane_id}] Got session manager: {manager}")

        try:
            read_count = 0
            # Continue reading while:
            # 1. Our state is RUNNING (we haven't been stopped externally)
            # 2. The PTY session exists and is running, OR there might be buffered data
            session = manager.get_session(self.pane_id)

            while self._state == PaneState.RUNNING:
                try:
                    data = await manager.read_from_session(
                        self.pane_id,
                        timeout=0.1,
                    )
                    if data:
                        read_count += 1
                        logger.debug(
                            f"[{self.pane_id}] Read #{read_count}: {len(data)} bytes: {data[:50]!r}..."
                        )
                        if self._terminal_view:
                            logger.debug(f"[{self.pane_id}] Feeding to terminal_view")
                            self._terminal_view.feed(data)
                            logger.debug(
                                f"[{self.pane_id}] Fed to terminal_view, display[0]={self._terminal_view.terminal_display[0][:40]!r}"
                            )
                        else:
                            logger.warning(f"[{self.pane_id}] terminal_view is None!")
                        self.post_message(PaneOutputMessage(self.pane_id, data))
                    else:
                        # No data received - check if session is still running
                        session = manager.get_session(self.pane_id)
                        if session is None or not session.is_running:
                            logger.debug(f"[{self.pane_id}] Session ended, breaking read loop")
                            break
                except PTYReadTimeoutError:
                    # Timeout is normal - check if session is still running
                    session = manager.get_session(self.pane_id)
                    if session is None or not session.is_running:
                        logger.debug(
                            f"[{self.pane_id}] Session ended during timeout, breaking read loop"
                        )
                        break
                    continue
                except Exception as e:
                    logger.exception(f"[{self.pane_id}] Read error: {e}")
                    break

            logger.debug(f"[{self.pane_id}] _read_loop exited, total reads: {read_count}")

            # Check exit status
            session = manager.get_session(self.pane_id)
            if session:
                self._exit_code = session.exit_code
                if self._exit_code == 0:
                    self._state = PaneState.SUCCESS
                elif self._exit_code is not None:
                    self._state = PaneState.FAILED
                else:
                    self._state = PaneState.EXITED
            else:
                self._state = PaneState.EXITED

            self._end_time = datetime.now(tz=UTC)
            self._update_status_bar()
            self.post_message(PaneStateChanged(self.pane_id, self._state, self._exit_code))

        except asyncio.CancelledError:
            pass

    async def _handle_pty_input(self, data: bytes, tab_id: str | None = None) -> None:
        """Handle input from the input router.

        Args:
            data: Input data to send to PTY.
            tab_id: Optional tab ID (unused, for interface compatibility).
        """
        del tab_id  # Unused, for interface compatibility
        await self.write(data)

    def _update_status_bar(self) -> None:
        """Update the status bar state."""
        if self._status_bar:
            self._status_bar.state = self._state
            if self._exit_code is not None:
                self._status_bar.status_message = f"Exit code: {self._exit_code}"

    async def _metrics_update_loop(self) -> None:
        """Background task to periodically update metrics display.

        This task runs while the PTY session is active and updates the
        phase status bar with current metrics at regular intervals.

        The metrics collection is run in a separate thread using
        asyncio.to_thread() to ensure it continues to run even when
        the main event loop is busy with CPU-bound work. This fixes
        the issue where CPU statistics would not update during
        CPU-intensive operations.
        """
        try:
            while self._state == PaneState.RUNNING:
                if self._metrics_collector and self._phase_status_bar:
                    # Run metrics collection in a thread to avoid blocking
                    # the event loop and ensure updates continue during
                    # CPU-bound operations
                    await asyncio.to_thread(self._collect_metrics_sync)
                await asyncio.sleep(self.config.metrics_update_interval)
        except asyncio.CancelledError:
            pass
        finally:
            # Update final status when loop ends
            if self._metrics_collector:
                status_map = {
                    PaneState.SUCCESS: "Completed",
                    PaneState.FAILED: "Failed",
                    PaneState.EXITED: "Exited",
                }
                final_status = status_map.get(self._state, "Stopped")
                self._metrics_collector.update_status(final_status)
                if self._phase_status_bar:
                    # Final update also in thread for consistency
                    await asyncio.to_thread(self._collect_metrics_sync)

    def _collect_metrics_sync(self) -> None:
        """Synchronously collect metrics and update the status bar.

        This method is designed to be called from a thread via
        asyncio.to_thread() to ensure metrics collection doesn't
        block the event loop.
        """
        if self._phase_status_bar:
            self._phase_status_bar.collect_and_update()

    def update_phase_metrics(
        self,
        *,
        eta_seconds: float | None = None,
        eta_error_seconds: float | None = None,
        items_completed: int | None = None,
        items_total: int | None = None,
        pause_after_phase: bool | None = None,
    ) -> None:
        """Update phase metrics from external sources.

        This method allows external components (like PhaseController) to
        update metrics that cannot be collected automatically.

        Args:
            eta_seconds: Estimated time remaining in seconds.
            eta_error_seconds: Error margin for ETA in seconds.
            items_completed: Number of items processed.
            items_total: Total number of items.
            pause_after_phase: Whether pause is enabled after current phase.
        """
        if self._metrics_collector is None:
            return

        if eta_seconds is not None:
            self._metrics_collector.update_eta(eta_seconds, eta_error_seconds)

        if items_completed is not None:
            self._metrics_collector.update_progress(
                items_completed,
                items_total,
            )

        if pause_after_phase is not None:
            self._metrics_collector._metrics.pause_after_phase = pause_after_phase

        # Trigger immediate update
        if self._phase_status_bar:
            self._phase_status_bar.collect_and_update()

    async def process_key(self, key: str) -> bool:
        """Process a key press and route it to the PTY.

        Args:
            key: Key string to handle.

        Returns:
            True if the key was handled, False otherwise.
        """
        if self._input_router and self.is_focused:
            await self._input_router.route_key(key)
            return True
        return False

    async def process_text(self, text: str) -> None:
        """Process text input and route it to the PTY.

        Args:
            text: Text to send to PTY.
        """
        if self._input_router and self.is_focused:
            await self._input_router.route_text(text)

    async def paste_text(self, text: str) -> None:
        """Paste text to the PTY.

        Args:
            text: Text to paste.
        """
        if self._input_router and self.is_focused:
            await self._input_router.paste(text)

    def scroll_history_up(self, lines: int = 1) -> None:
        """Scroll up in the terminal history.

        Args:
            lines: Number of lines to scroll.
        """
        if self._terminal_view:
            self._terminal_view.scroll_history_up(lines)

    def scroll_history_down(self, lines: int = 1) -> None:
        """Scroll down in the terminal history.

        Args:
            lines: Number of lines to scroll.
        """
        if self._terminal_view:
            self._terminal_view.scroll_history_down(lines)

    def scroll_to_history_top(self) -> None:
        """Scroll to the top of history."""
        if self._terminal_view:
            self._terminal_view.scroll_to_top()

    def scroll_to_history_bottom(self) -> None:
        """Scroll to the bottom (current output)."""
        if self._terminal_view:
            self._terminal_view.scroll_to_bottom()

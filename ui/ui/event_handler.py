"""UI Event Handler protocol for abstracting Textual-specific code.

This module provides a protocol-based abstraction layer between the streaming
event system and the Textual UI framework. This allows:
- Future replacement of Textual if needed
- Easier testing with mock implementations
- Clear separation of concerns

Phase 3 - UI Integration (Section 7.3.1)
See docs/update-all-architecture-refinement-plan.md
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

    from core.streaming import StreamEvent

logger = structlog.get_logger(__name__)


@runtime_checkable
class UIEventHandler(Protocol):
    """Protocol for handling streaming events in the UI.

    Implementations of this protocol receive streaming events from plugins
    and update the UI accordingly. This abstraction allows the streaming
    system to work with different UI frameworks.
    """

    def handle_output(self, plugin_name: str, line: str, stream: str = "stdout") -> None:
        """Handle an output line from a plugin.

        Args:
            plugin_name: Name of the plugin producing output.
            line: The output line text.
            stream: Which stream ("stdout" or "stderr").
        """
        ...

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
        """Handle a progress update from a plugin.

        Args:
            plugin_name: Name of the plugin.
            phase: Current phase ("check", "download", "execute").
            percent: Progress percentage (0-100).
            message: Human-readable progress message.
            bytes_downloaded: Bytes downloaded so far.
            bytes_total: Total bytes to download.
            items_completed: Items completed so far.
            items_total: Total items.
        """
        ...

    def handle_phase_start(self, plugin_name: str, phase: str) -> None:
        """Handle the start of a phase.

        Args:
            plugin_name: Name of the plugin.
            phase: Phase that started ("check", "download", "execute").
        """
        ...

    def handle_phase_end(
        self,
        plugin_name: str,
        phase: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Handle the end of a phase.

        Args:
            plugin_name: Name of the plugin.
            phase: Phase that ended.
            success: Whether the phase succeeded.
            error_message: Error message if failed.
        """
        ...

    def handle_completion(
        self,
        plugin_name: str,
        success: bool,
        exit_code: int,
        packages_updated: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Handle plugin completion.

        Args:
            plugin_name: Name of the plugin.
            success: Whether execution succeeded.
            exit_code: Process exit code.
            packages_updated: Number of packages updated.
            error_message: Error message if failed.
        """
        ...


@dataclass
class BatchedEvent:
    """A batched event for UI updates.

    Batching events reduces the number of UI updates when events arrive rapidly.
    """

    plugin_name: str
    event_type: str
    data: dict[str, object] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class BatchedEventHandler(ABC):
    """Abstract base class for batched event handling.

    This class collects events over a time interval and processes them
    in batches to reduce UI update frequency. Subclasses implement the
    actual UI update logic.

    Attributes:
        batch_interval_ms: Time interval for batching in milliseconds.
        max_batch_size: Maximum events per batch.
        max_fps: Maximum UI updates per second.
    """

    def __init__(
        self,
        batch_interval_ms: float = 50.0,
        max_batch_size: int = 100,
        max_fps: float = 30.0,
    ) -> None:
        """Initialize the batched event handler.

        Args:
            batch_interval_ms: Time interval for batching in milliseconds.
            max_batch_size: Maximum events per batch.
            max_fps: Maximum UI updates per second (rate limiting).
        """
        self.batch_interval_ms = batch_interval_ms
        self.max_batch_size = max_batch_size
        self.max_fps = max_fps
        self._min_update_interval = 1.0 / max_fps

        self._batch: list[BatchedEvent] = []
        self._batch_lock = asyncio.Lock()
        self._last_update_time: float = 0.0
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False
        self._log = logger.bind(component="batched_event_handler")

    async def start(self) -> None:
        """Start the batched event handler."""
        if self._running:
            return

        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._log.debug("started")

    async def stop(self) -> None:
        """Stop the batched event handler and flush remaining events."""
        if not self._running:
            return

        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None

        # Flush any remaining events
        await self._flush_batch()
        self._log.debug("stopped")

    async def add_event(self, event: BatchedEvent) -> None:
        """Add an event to the batch.

        Args:
            event: The event to add.
        """
        async with self._batch_lock:
            self._batch.append(event)

            # If batch is full, flush immediately
            if len(self._batch) >= self.max_batch_size:
                await self._flush_batch_unlocked()

    async def _flush_loop(self) -> None:
        """Background loop that flushes batches at regular intervals."""
        interval = self.batch_interval_ms / 1000.0

        while self._running:
            try:
                await asyncio.sleep(interval)
                await self._flush_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._log.exception("flush_error", error=str(e))

    async def _flush_batch(self) -> None:
        """Flush the current batch of events."""
        async with self._batch_lock:
            await self._flush_batch_unlocked()

    async def _flush_batch_unlocked(self) -> None:
        """Flush the batch without acquiring the lock (must be called with lock held)."""
        if not self._batch:
            return

        # Rate limiting
        now = asyncio.get_event_loop().time()
        time_since_last = now - self._last_update_time

        if time_since_last < self._min_update_interval:
            # Skip this update to maintain FPS limit
            return

        # Take the current batch and clear it
        batch = self._batch
        self._batch = []
        self._last_update_time = now

        # Process the batch
        try:
            await self.process_batch(batch)
        except Exception as e:
            self._log.exception("batch_processing_error", error=str(e), batch_size=len(batch))

    @abstractmethod
    async def process_batch(self, events: list[BatchedEvent]) -> None:
        """Process a batch of events.

        Subclasses implement this method to update the UI with the batched events.

        Args:
            events: List of events to process.
        """
        ...


class StreamEventAdapter:
    """Adapter that converts StreamEvents to UIEventHandler calls.

    This adapter bridges the gap between the core streaming event system
    and the UI event handler protocol.
    """

    def __init__(self, handler: UIEventHandler) -> None:
        """Initialize the adapter.

        Args:
            handler: The UI event handler to delegate to.
        """
        self.handler = handler

    def handle_event(self, event: StreamEvent) -> None:
        """Handle a streaming event by delegating to the appropriate handler method.

        Args:
            event: The streaming event to handle.
        """
        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
            PhaseEvent,
            ProgressEvent,
        )

        if isinstance(event, OutputEvent):
            self.handler.handle_output(
                plugin_name=event.plugin_name,
                line=event.line,
                stream=event.stream,
            )

        elif isinstance(event, ProgressEvent):
            self.handler.handle_progress(
                plugin_name=event.plugin_name,
                phase=event.phase.value,
                percent=event.percent,
                message=event.message,
                bytes_downloaded=event.bytes_downloaded,
                bytes_total=event.bytes_total,
                items_completed=event.items_completed,
                items_total=event.items_total,
            )

        elif isinstance(event, PhaseEvent):
            if event.event_type == EventType.PHASE_START:
                self.handler.handle_phase_start(
                    plugin_name=event.plugin_name,
                    phase=event.phase.value,
                )
            elif event.event_type == EventType.PHASE_END:
                self.handler.handle_phase_end(
                    plugin_name=event.plugin_name,
                    phase=event.phase.value,
                    success=event.success or False,
                    error_message=event.error_message,
                )

        elif isinstance(event, CompletionEvent):
            self.handler.handle_completion(
                plugin_name=event.plugin_name,
                success=event.success,
                exit_code=event.exit_code,
                packages_updated=event.packages_updated,
                error_message=event.error_message,
            )


class CallbackEventHandler:
    """Simple event handler that delegates to callback functions.

    Useful for testing or simple integrations where a full UI is not needed.
    """

    def __init__(
        self,
        on_output: Callable[[str, str, str], None] | None = None,
        on_progress: Callable[[str, str, float | None, str | None], None] | None = None,
        on_phase_start: Callable[[str, str], None] | None = None,
        on_phase_end: Callable[[str, str, bool, str | None], None] | None = None,
        on_completion: Callable[[str, bool, int, int, str | None], None] | None = None,
    ) -> None:
        """Initialize the callback event handler.

        Args:
            on_output: Callback for output events (plugin_name, line, stream).
            on_progress: Callback for progress events (plugin_name, phase, percent, message).
            on_phase_start: Callback for phase start (plugin_name, phase).
            on_phase_end: Callback for phase end (plugin_name, phase, success, error).
            on_completion: Callback for completion (plugin_name, success, exit_code, packages, error).
        """
        self._on_output = on_output
        self._on_progress = on_progress
        self._on_phase_start = on_phase_start
        self._on_phase_end = on_phase_end
        self._on_completion = on_completion

    def handle_output(self, plugin_name: str, line: str, stream: str = "stdout") -> None:
        """Handle an output line from a plugin."""
        if self._on_output:
            self._on_output(plugin_name, line, stream)

    def handle_progress(
        self,
        plugin_name: str,
        phase: str,
        percent: float | None = None,
        message: str | None = None,
        bytes_downloaded: int | None = None,  # noqa: ARG002
        bytes_total: int | None = None,  # noqa: ARG002
        items_completed: int | None = None,  # noqa: ARG002
        items_total: int | None = None,  # noqa: ARG002
    ) -> None:
        """Handle a progress update from a plugin.

        Note: bytes_downloaded, bytes_total, items_completed, items_total are
        intentionally unused - the callback only receives basic progress info.
        """
        if self._on_progress:
            self._on_progress(plugin_name, phase, percent, message)

    def handle_phase_start(self, plugin_name: str, phase: str) -> None:
        """Handle the start of a phase."""
        if self._on_phase_start:
            self._on_phase_start(plugin_name, phase)

    def handle_phase_end(
        self,
        plugin_name: str,
        phase: str,
        success: bool,
        error_message: str | None = None,
    ) -> None:
        """Handle the end of a phase."""
        if self._on_phase_end:
            self._on_phase_end(plugin_name, phase, success, error_message)

    def handle_completion(
        self,
        plugin_name: str,
        success: bool,
        exit_code: int,
        packages_updated: int = 0,
        error_message: str | None = None,
    ) -> None:
        """Handle plugin completion."""
        if self._on_completion:
            self._on_completion(plugin_name, success, exit_code, packages_updated, error_message)

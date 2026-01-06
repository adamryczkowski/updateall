"""Streaming event types and utilities for live output from plugins.

This module defines event types for streaming output from plugins during
update check, download, and execution phases. It enables real-time display
in the tabbed UI.

Event Types:
    - OutputEvent: Raw output line from plugin (stdout/stderr)
    - ProgressEvent: Progress update with percentage, bytes, items
    - PhaseEvent: Phase start/end markers (check, download, execute)
    - CompletionEvent: Plugin execution completed

Helper Utilities:
    - safe_consume_stream: Safely consume an async iterator with cleanup
    - timeout_stream: Wrap a stream with timeout handling
    - batched_stream: Batch events for UI performance
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeVar

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator

logger = structlog.get_logger(__name__)


class EventType(str, Enum):
    """Types of streaming events from plugins."""

    OUTPUT = "output"
    PROGRESS = "progress"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    ERROR = "error"
    COMPLETION = "completion"


class Phase(str, Enum):
    """Execution phases for plugins."""

    CHECK = "check"
    DOWNLOAD = "download"
    EXECUTE = "execute"


# Progress line prefix for JSON progress events in stderr
PROGRESS_PREFIX = "PROGRESS:"


@dataclass(slots=True)
class StreamEvent:
    """Base class for streaming events.

    All streaming events inherit from this class and include:
    - event_type: The type of event
    - plugin_name: Name of the plugin that generated the event
    - timestamp: When the event was generated
    """

    event_type: EventType
    plugin_name: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.event_type.value,
            "plugin": self.plugin_name,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass(slots=True)
class OutputEvent(StreamEvent):
    """Raw output line from plugin.

    Attributes:
        line: The output line text
        stream: Which stream the output came from ("stdout" or "stderr")
    """

    line: str = ""
    stream: str = "stdout"

    def __post_init__(self) -> None:
        """Set event type after initialization."""
        object.__setattr__(self, "event_type", EventType.OUTPUT)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = super().to_dict()
        d.update(
            {
                "line": self.line,
                "stream": self.stream,
            }
        )
        return d


@dataclass(slots=True)
class ProgressEvent(StreamEvent):
    """Progress update from plugin.

    Attributes:
        phase: Current execution phase
        percent: Progress percentage (0-100), or None if unknown
        message: Human-readable progress message
        bytes_downloaded: Bytes downloaded so far
        bytes_total: Total bytes to download
        items_completed: Number of items completed
        items_total: Total number of items
    """

    phase: Phase = Phase.EXECUTE
    percent: float | None = None
    message: str | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    items_completed: int | None = None
    items_total: int | None = None

    def __post_init__(self) -> None:
        """Set event type after initialization."""
        object.__setattr__(self, "event_type", EventType.PROGRESS)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = super().to_dict()
        d.update(
            {
                "phase": self.phase.value,
            }
        )
        # Only include non-None optional fields
        if self.percent is not None:
            d["percent"] = self.percent
        if self.message is not None:
            d["message"] = self.message
        if self.bytes_downloaded is not None:
            d["bytes_downloaded"] = self.bytes_downloaded
        if self.bytes_total is not None:
            d["bytes_total"] = self.bytes_total
        if self.items_completed is not None:
            d["items_completed"] = self.items_completed
        if self.items_total is not None:
            d["items_total"] = self.items_total
        return d


@dataclass(slots=True)
class PhaseEvent(StreamEvent):
    """Phase start/end event.

    Attributes:
        phase: The phase that started or ended
        success: Whether the phase completed successfully (only for phase_end)
        error_message: Error message if the phase failed
    """

    phase: Phase = Phase.EXECUTE
    success: bool | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = super().to_dict()
        d["phase"] = self.phase.value
        if self.success is not None:
            d["success"] = self.success
        if self.error_message:
            d["error"] = self.error_message
        return d


@dataclass(slots=True)
class CompletionEvent(StreamEvent):
    """Plugin execution completed.

    Attributes:
        success: Whether execution was successful
        exit_code: Process exit code
        packages_updated: Number of packages updated
        error_message: Error message if execution failed
    """

    success: bool = False
    exit_code: int = 0
    packages_updated: int = 0
    error_message: str | None = None

    def __post_init__(self) -> None:
        """Set event type after initialization."""
        object.__setattr__(self, "event_type", EventType.COMPLETION)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        d = super().to_dict()
        d.update(
            {
                "success": self.success,
                "exit_code": self.exit_code,
                "packages_updated": self.packages_updated,
            }
        )
        if self.error_message:
            d["error"] = self.error_message
        return d


def parse_progress_line(line: str, plugin_name: str) -> ProgressEvent | None:
    """Parse a JSON progress line into a ProgressEvent.

    Progress lines should be prefixed with PROGRESS: followed by JSON data.
    Example: PROGRESS:{"phase": "download", "percent": 45, "message": "Downloading..."}

    Args:
        line: The line to parse (should start with PROGRESS:)
        plugin_name: Name of the plugin

    Returns:
        ProgressEvent if parsing succeeds, None otherwise
    """
    if not line.startswith(PROGRESS_PREFIX):
        return None

    json_str = line[len(PROGRESS_PREFIX) :].strip()
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    # Parse phase
    phase_str = data.get("phase", "execute")
    try:
        phase = Phase(phase_str)
    except ValueError:
        phase = Phase.EXECUTE

    return ProgressEvent(
        event_type=EventType.PROGRESS,
        plugin_name=plugin_name,
        timestamp=datetime.now(tz=UTC),
        phase=phase,
        percent=data.get("percent"),
        message=data.get("message"),
        bytes_downloaded=data.get("bytes_downloaded"),
        bytes_total=data.get("bytes_total"),
        items_completed=data.get("items_completed"),
        items_total=data.get("items_total"),
    )


def parse_event(data: dict[str, Any], plugin_name: str) -> StreamEvent | None:
    """Parse a dictionary into a StreamEvent.

    Args:
        data: Dictionary with event data.
        plugin_name: Name of the plugin.

    Returns:
        StreamEvent or None if parsing fails.
    """
    event_type = data.get("type")
    timestamp = datetime.now(tz=UTC)

    if event_type == "progress":
        phase_str = data.get("phase", "execute")
        try:
            phase = Phase(phase_str)
        except ValueError:
            phase = Phase.EXECUTE

        return ProgressEvent(
            event_type=EventType.PROGRESS,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=phase,
            percent=data.get("percent"),
            message=data.get("message"),
            bytes_downloaded=data.get("bytes_downloaded"),
            bytes_total=data.get("bytes_total"),
            items_completed=data.get("items_completed"),
            items_total=data.get("items_total"),
        )

    elif event_type == "phase_start":
        phase_str = data.get("phase", "execute")
        try:
            phase = Phase(phase_str)
        except ValueError:
            phase = Phase.EXECUTE

        return PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=phase,
        )

    elif event_type == "phase_end":
        phase_str = data.get("phase", "execute")
        try:
            phase = Phase(phase_str)
        except ValueError:
            phase = Phase.EXECUTE

        return PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=phase,
            success=data.get("success"),
            error_message=data.get("error"),
        )

    elif event_type == "output":
        return OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=plugin_name,
            timestamp=timestamp,
            line=data.get("line", ""),
            stream=data.get("stream", "stdout"),
        )

    elif event_type == "completion":
        return CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=plugin_name,
            timestamp=timestamp,
            success=data.get("success", False),
            exit_code=data.get("exit_code", 0),
            packages_updated=data.get("packages_updated", 0),
            error_message=data.get("error"),
        )

    return None


# Type variable for stream events
T = TypeVar("T", bound=StreamEvent)


async def safe_consume_stream(
    stream: AsyncGenerator[T, None],
) -> AsyncGenerator[T, None]:
    """Safely consume an async generator with proper cleanup.

    Ensures the async generator is properly closed even if iteration
    is interrupted by break or exception.

    Args:
        stream: The async generator to consume

    Yields:
        Events from the stream

    Example:
        async for event in safe_consume_stream(plugin.execute_streaming()):
            process(event)
            if should_stop:
                break  # Generator will be properly closed
    """
    try:
        async for event in stream:
            yield event
    finally:
        await stream.aclose()


async def timeout_stream(
    stream: AsyncGenerator[T, None],
    timeout_seconds: float,
    plugin_name: str,
) -> AsyncGenerator[StreamEvent, None]:
    """Wrap a stream with timeout handling.

    If the stream takes longer than timeout_seconds, yields a CompletionEvent
    with an error message and stops iteration.

    Args:
        stream: The async generator to wrap
        timeout_seconds: Maximum time to wait for the stream
        plugin_name: Name of the plugin (for error events)

    Yields:
        Events from the stream, or a CompletionEvent on timeout
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event in stream:
                yield event
    except TimeoutError:
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=plugin_name,
            timestamp=datetime.now(tz=UTC),
            success=False,
            exit_code=-1,
            error_message=f"Stream timed out after {timeout_seconds}s",
        )
    finally:
        await stream.aclose()


async def batched_stream(
    stream: AsyncGenerator[T, None],
    batch_interval_ms: float = 50.0,
    max_batch_size: int = 100,
) -> AsyncGenerator[list[T], None]:
    """Batch events from a stream for UI performance.

    Collects events over a time interval and yields them as batches.
    This reduces the number of UI updates when events arrive rapidly.

    Args:
        stream: The async generator to batch
        batch_interval_ms: Time interval for batching in milliseconds
        max_batch_size: Maximum events per batch

    Yields:
        Lists of events (batches)
    """
    batch: list[T] = []
    batch_interval = batch_interval_ms / 1000.0  # Convert to seconds
    stream_exhausted = False

    try:
        while not stream_exhausted:
            # Collect events for one batch interval
            try:
                async with asyncio.timeout(batch_interval):
                    while len(batch) < max_batch_size:
                        try:
                            event = await stream.__anext__()
                            batch.append(event)
                        except StopAsyncIteration:
                            stream_exhausted = True
                            break
            except TimeoutError:
                pass  # Timeout is expected - it's how we end the batch interval

            if batch:
                yield batch
                batch = []
            elif stream_exhausted:
                break
    finally:
        await stream.aclose()


# Queue size for bounded event queues (Risk T3 mitigation)
DEFAULT_QUEUE_SIZE = 1000


class StreamEventQueue:
    """Bounded async queue for stream events with backpressure.

    This queue provides a bounded buffer for streaming events, implementing
    backpressure when the queue is full. Events are dropped with a warning
    when the queue overflows.

    Attributes:
        maxsize: Maximum number of events in the queue
        dropped_count: Number of events dropped due to overflow
    """

    def __init__(self, maxsize: int = DEFAULT_QUEUE_SIZE) -> None:
        """Initialize the event queue.

        Args:
            maxsize: Maximum queue size (default: 1000)
        """
        self._queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=maxsize)
        self._maxsize = maxsize
        self._dropped_count = 0
        self._log = logger.bind(component="stream_event_queue")

    @property
    def maxsize(self) -> int:
        """Maximum queue size."""
        return self._maxsize

    @property
    def dropped_count(self) -> int:
        """Number of events dropped due to overflow."""
        return self._dropped_count

    def qsize(self) -> int:
        """Return the current queue size."""
        return self._queue.qsize()

    async def put(self, event: StreamEvent) -> bool:
        """Put an event into the queue.

        If the queue is full, the event is dropped and a warning is logged.

        Args:
            event: The event to add

        Returns:
            True if the event was added, False if dropped
        """
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            self._dropped_count += 1
            if self._dropped_count == 1 or self._dropped_count % 100 == 0:
                self._log.warning(
                    "event_queue_overflow",
                    dropped_count=self._dropped_count,
                    queue_size=self._maxsize,
                    event_type=event.event_type.value,
                )
            return False

    async def get(self) -> StreamEvent | None:
        """Get an event from the queue.

        Returns:
            The next event, or None if the queue is closed
        """
        return await self._queue.get()

    async def close(self) -> None:
        """Signal that no more events will be added."""
        await self._queue.put(None)

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        """Iterate over events in the queue."""
        return self

    async def __anext__(self) -> StreamEvent:
        """Get the next event from the queue."""
        event = await self.get()
        if event is None:
            raise StopAsyncIteration
        return event

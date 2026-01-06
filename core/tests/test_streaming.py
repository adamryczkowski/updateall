"""Tests for the streaming event system.

Phase 1 - Core Streaming Infrastructure tests.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
    StreamEventQueue,
    parse_event,
    parse_progress_line,
    safe_consume_stream,
    timeout_stream,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class TestEventTypes:
    """Tests for streaming event types."""

    def test_output_event_creation(self) -> None:
        """Test creating an OutputEvent."""
        event = OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            line="Hello, world!",
            stream="stdout",
        )
        assert event.event_type == EventType.OUTPUT
        assert event.plugin_name == "test-plugin"
        assert event.line == "Hello, world!"
        assert event.stream == "stdout"

    def test_output_event_to_dict(self) -> None:
        """Test OutputEvent serialization."""
        event = OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            line="Test line",
            stream="stderr",
        )
        d = event.to_dict()
        assert d["type"] == "output"
        assert d["plugin"] == "test-plugin"
        assert d["line"] == "Test line"
        assert d["stream"] == "stderr"
        assert "timestamp" in d

    def test_progress_event_creation(self) -> None:
        """Test creating a ProgressEvent."""
        event = ProgressEvent(
            event_type=EventType.PROGRESS,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            percent=45.5,
            message="Downloading...",
            bytes_downloaded=1000,
            bytes_total=2000,
        )
        assert event.event_type == EventType.PROGRESS
        assert event.phase == Phase.DOWNLOAD
        assert event.percent == 45.5
        assert event.message == "Downloading..."
        assert event.bytes_downloaded == 1000
        assert event.bytes_total == 2000

    def test_progress_event_to_dict_omits_none(self) -> None:
        """Test that ProgressEvent.to_dict() omits None values."""
        event = ProgressEvent(
            event_type=EventType.PROGRESS,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            percent=50.0,
        )
        d = event.to_dict()
        assert "percent" in d
        assert "message" not in d
        assert "bytes_downloaded" not in d

    def test_phase_event_creation(self) -> None:
        """Test creating a PhaseEvent."""
        event = PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
        )
        assert event.event_type == EventType.PHASE_START
        assert event.phase == Phase.CHECK
        assert event.success is None

    def test_phase_event_end_with_success(self) -> None:
        """Test PhaseEvent for phase end."""
        event = PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            success=True,
        )
        d = event.to_dict()
        assert d["type"] == "phase_end"
        assert d["phase"] == "download"
        assert d["success"] is True

    def test_completion_event_creation(self) -> None:
        """Test creating a CompletionEvent."""
        event = CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
            packages_updated=5,
        )
        assert event.event_type == EventType.COMPLETION
        assert event.success is True
        assert event.exit_code == 0
        assert event.packages_updated == 5

    def test_completion_event_with_error(self) -> None:
        """Test CompletionEvent with error."""
        event = CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            success=False,
            exit_code=1,
            error_message="Something went wrong",
        )
        d = event.to_dict()
        assert d["success"] is False
        assert d["exit_code"] == 1
        assert d["error"] == "Something went wrong"

    def test_event_to_json(self) -> None:
        """Test event JSON serialization."""
        event = OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name="test-plugin",
            timestamp=datetime.now(tz=UTC),
            line="Test",
            stream="stdout",
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)
        assert parsed["type"] == "output"
        assert parsed["line"] == "Test"


class TestParseProgressLine:
    """Tests for parse_progress_line function."""

    def test_parse_valid_progress_line(self) -> None:
        """Test parsing a valid progress line."""
        line = 'PROGRESS:{"phase": "download", "percent": 45, "message": "Downloading..."}'
        event = parse_progress_line(line, "test-plugin")
        assert event is not None
        assert event.phase == Phase.DOWNLOAD
        assert event.percent == 45
        assert event.message == "Downloading..."

    def test_parse_progress_line_with_bytes(self) -> None:
        """Test parsing progress line with byte counts."""
        line = 'PROGRESS:{"phase": "download", "bytes_downloaded": 1000, "bytes_total": 2000}'
        event = parse_progress_line(line, "test-plugin")
        assert event is not None
        assert event.bytes_downloaded == 1000
        assert event.bytes_total == 2000

    def test_parse_non_progress_line(self) -> None:
        """Test that non-progress lines return None."""
        line = "Regular output line"
        event = parse_progress_line(line, "test-plugin")
        assert event is None

    def test_parse_invalid_json(self) -> None:
        """Test that invalid JSON returns None."""
        line = "PROGRESS:{invalid json}"
        event = parse_progress_line(line, "test-plugin")
        assert event is None

    def test_parse_unknown_phase(self) -> None:
        """Test that unknown phase defaults to EXECUTE."""
        line = 'PROGRESS:{"phase": "unknown", "percent": 50}'
        event = parse_progress_line(line, "test-plugin")
        assert event is not None
        assert event.phase == Phase.EXECUTE


class TestParseEvent:
    """Tests for parse_event function."""

    def test_parse_progress_event(self) -> None:
        """Test parsing a progress event dict."""
        data = {"type": "progress", "phase": "download", "percent": 75}
        event = parse_event(data, "test-plugin")
        assert isinstance(event, ProgressEvent)
        assert event.phase == Phase.DOWNLOAD
        assert event.percent == 75

    def test_parse_phase_start_event(self) -> None:
        """Test parsing a phase_start event dict."""
        data = {"type": "phase_start", "phase": "check"}
        event = parse_event(data, "test-plugin")
        assert isinstance(event, PhaseEvent)
        assert event.event_type == EventType.PHASE_START
        assert event.phase == Phase.CHECK

    def test_parse_phase_end_event(self) -> None:
        """Test parsing a phase_end event dict."""
        data = {"type": "phase_end", "phase": "execute", "success": True}
        event = parse_event(data, "test-plugin")
        assert isinstance(event, PhaseEvent)
        assert event.event_type == EventType.PHASE_END
        assert event.success is True

    def test_parse_output_event(self) -> None:
        """Test parsing an output event dict."""
        data = {"type": "output", "line": "Hello", "stream": "stdout"}
        event = parse_event(data, "test-plugin")
        assert isinstance(event, OutputEvent)
        assert event.line == "Hello"
        assert event.stream == "stdout"

    def test_parse_completion_event(self) -> None:
        """Test parsing a completion event dict."""
        data = {"type": "completion", "success": True, "exit_code": 0, "packages_updated": 3}
        event = parse_event(data, "test-plugin")
        assert isinstance(event, CompletionEvent)
        assert event.success is True
        assert event.packages_updated == 3

    def test_parse_unknown_event(self) -> None:
        """Test that unknown event types return None."""
        data = {"type": "unknown"}
        event = parse_event(data, "test-plugin")
        assert event is None


class TestStreamEventQueue:
    """Tests for StreamEventQueue class."""

    @pytest.mark.asyncio
    async def test_queue_put_and_get(self) -> None:
        """Test basic put and get operations."""
        queue = StreamEventQueue(maxsize=10)
        event = OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name="test",
            timestamp=datetime.now(tz=UTC),
            line="Test",
        )
        result = await queue.put(event)
        assert result is True
        assert queue.qsize() == 1

        retrieved = await queue.get()
        assert retrieved == event
        assert queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_queue_overflow_drops_events(self) -> None:
        """Test that queue drops events when full."""
        queue = StreamEventQueue(maxsize=2)

        for i in range(5):
            event = OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line=f"Line {i}",
            )
            await queue.put(event)

        assert queue.qsize() == 2
        assert queue.dropped_count == 3

    @pytest.mark.asyncio
    async def test_queue_close(self) -> None:
        """Test queue close signals end of iteration."""
        queue = StreamEventQueue(maxsize=10)
        await queue.close()

        result = await queue.get()
        assert result is None

    @pytest.mark.asyncio
    async def test_queue_iteration(self) -> None:
        """Test async iteration over queue."""
        queue = StreamEventQueue(maxsize=10)

        # Add some events
        for i in range(3):
            output_event = OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line=f"Line {i}",
            )
            await queue.put(output_event)

        # Close the queue
        await queue.close()

        # Iterate
        events: list[StreamEvent] = []
        async for event in queue:
            events.append(event)

        assert len(events) == 3


class TestSafeConsumeStream:
    """Tests for safe_consume_stream helper."""

    @pytest.mark.asyncio
    async def test_safe_consume_stream(self) -> None:
        """Test safely consuming a stream."""

        async def generate_events() -> AsyncGenerator[OutputEvent, None]:
            for i in range(3):
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name="test",
                    timestamp=datetime.now(tz=UTC),
                    line=f"Line {i}",
                )

        events: list[OutputEvent] = []
        async for event in safe_consume_stream(generate_events()):
            events.append(event)

        assert len(events) == 3

    @pytest.mark.asyncio
    async def test_safe_consume_stream_with_break(self) -> None:
        """Test that stream is properly closed on break."""

        async def generate_events() -> AsyncGenerator[OutputEvent, None]:
            for i in range(10):
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name="test",
                    timestamp=datetime.now(tz=UTC),
                    line=f"Line {i}",
                )

        events: list[OutputEvent] = []
        async for event in safe_consume_stream(generate_events()):
            events.append(event)
            if len(events) >= 3:
                break

        assert len(events) == 3


class TestTimeoutStream:
    """Tests for timeout_stream helper."""

    @pytest.mark.asyncio
    async def test_timeout_stream_completes(self) -> None:
        """Test stream that completes before timeout."""

        async def generate_events() -> AsyncGenerator[OutputEvent, None]:
            for i in range(3):
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name="test",
                    timestamp=datetime.now(tz=UTC),
                    line=f"Line {i}",
                )

        events: list[StreamEvent] = []
        async for event in timeout_stream(generate_events(), 5.0, "test"):
            events.append(event)

        assert len(events) == 3
        # No completion event added since stream completed normally
        assert all(isinstance(e, OutputEvent) for e in events)

    @pytest.mark.asyncio
    async def test_timeout_stream_times_out(self) -> None:
        """Test stream that times out."""

        async def slow_generator() -> AsyncGenerator[OutputEvent, None]:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line="First",
            )
            await asyncio.sleep(10)  # This will cause timeout
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line="Never reached",
            )

        events: list[StreamEvent] = []
        async for event in timeout_stream(slow_generator(), 0.1, "test"):
            events.append(event)

        # Should have first event and a completion event with error
        assert len(events) == 2
        assert isinstance(events[0], OutputEvent)
        assert isinstance(events[1], CompletionEvent)
        assert events[1].success is False
        assert "timed out" in (events[1].error_message or "")


class TestPhaseEnum:
    """Tests for Phase enum."""

    def test_phase_values(self) -> None:
        """Test Phase enum values."""
        assert Phase.CHECK.value == "check"
        assert Phase.DOWNLOAD.value == "download"
        assert Phase.EXECUTE.value == "execute"


class TestEventTypeEnum:
    """Tests for EventType enum."""

    def test_event_type_values(self) -> None:
        """Test EventType enum values."""
        assert EventType.OUTPUT.value == "output"
        assert EventType.PROGRESS.value == "progress"
        assert EventType.PHASE_START.value == "phase_start"
        assert EventType.PHASE_END.value == "phase_end"
        assert EventType.ERROR.value == "error"
        assert EventType.COMPLETION.value == "completion"

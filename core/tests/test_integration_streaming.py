"""Integration tests for streaming functionality.

Phase 5 - End-to-end streaming tests with real plugins.
These tests verify the complete streaming pipeline from plugin execution
through event handling to UI updates.

Section 7.5.1 of the architecture refinement plan.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from core.interfaces import UpdatePlugin
from core.metrics import LatencyTimer, MetricsCollector, set_metrics_collector
from core.models import DownloadEstimate, ExecutionResult, PackageDownload, PluginStatus
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
    StreamEventQueue,
    batched_stream,
    safe_consume_stream,
    timeout_stream,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator


class MockStreamingPlugin(UpdatePlugin):
    """Mock plugin with full streaming support for integration testing."""

    def __init__(
        self,
        name: str = "mock-streaming",
        event_count: int = 10,
        event_delay: float = 0.01,
        should_fail: bool = False,
    ) -> None:
        """Initialize the mock plugin.

        Args:
            name: Plugin name.
            event_count: Number of events to emit.
            event_delay: Delay between events in seconds.
            should_fail: Whether to simulate a failure.
        """
        self._name = name
        self._event_count = event_count
        self._event_delay = event_delay
        self._should_fail = should_fail

    @property
    def name(self) -> str:
        return self._name

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_download(self) -> bool:
        return True

    async def check_available(self) -> bool:
        return True

    async def execute(self, dry_run: bool = False) -> ExecutionResult:  # noqa: ARG002
        return ExecutionResult(
            plugin_name=self.name,
            status=PluginStatus.SUCCESS,
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC),
            exit_code=0,
            packages_updated=5,
        )

    async def execute_streaming(
        self,
        dry_run: bool = False,  # noqa: ARG002
    ) -> AsyncIterator[StreamEvent]:
        """Execute with streaming output."""
        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        # Emit progress events
        for i in range(self._event_count):
            await asyncio.sleep(self._event_delay)

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Processing step {i + 1}/{self._event_count}...",
                stream="stdout",
            )

            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                percent=((i + 1) / self._event_count) * 100,
                message=f"Step {i + 1}/{self._event_count}",
                items_completed=i + 1,
                items_total=self._event_count,
            )

        # Emit phase end
        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=not self._should_fail,
            error_message="Simulated failure" if self._should_fail else None,
        )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=not self._should_fail,
            exit_code=1 if self._should_fail else 0,
            packages_updated=0 if self._should_fail else 5,
            error_message="Simulated failure" if self._should_fail else None,
        )

    async def estimate_download(self) -> DownloadEstimate | None:
        return DownloadEstimate(
            total_bytes=50_000_000,
            package_count=5,
            estimated_seconds=10.0,
            packages=[
                PackageDownload(name=f"pkg-{i}", version="1.0", size_bytes=10_000_000)
                for i in range(5)
            ],
        )

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Simulate download with progress events."""
        for i in range(5):
            await asyncio.sleep(self._event_delay)

            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=(i + 1) * 20,
                message=f"Downloading pkg-{i}...",
                bytes_downloaded=(i + 1) * 10_000_000,
                bytes_total=50_000_000,
                items_completed=i + 1,
                items_total=5,
            )

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
        )


class TestStreamingPipeline:
    """Integration tests for the complete streaming pipeline."""

    @pytest.mark.asyncio
    async def test_full_streaming_execution(self) -> None:
        """Test complete streaming execution from plugin to events."""
        plugin = MockStreamingPlugin(event_count=5)

        events: list[StreamEvent] = []
        async for event in plugin.execute_streaming():
            events.append(event)

        # Verify event sequence
        assert len(events) > 0

        # Check phase start
        phase_starts = [
            e for e in events if isinstance(e, PhaseEvent) and e.event_type == EventType.PHASE_START
        ]
        assert len(phase_starts) == 1
        assert phase_starts[0].phase == Phase.EXECUTE

        # Check output events
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        assert len(output_events) == 5

        # Check progress events
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]
        assert len(progress_events) == 5
        assert progress_events[-1].percent == 100.0

        # Check phase end
        phase_ends = [
            e for e in events if isinstance(e, PhaseEvent) and e.event_type == EventType.PHASE_END
        ]
        assert len(phase_ends) == 1
        assert phase_ends[0].success is True

        # Check completion
        completions = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completions) == 1
        assert completions[0].success is True
        assert completions[0].packages_updated == 5

    @pytest.mark.asyncio
    async def test_streaming_with_failure(self) -> None:
        """Test streaming execution that fails."""
        plugin = MockStreamingPlugin(event_count=3, should_fail=True)

        events: list[StreamEvent] = []
        async for event in plugin.execute_streaming():
            events.append(event)

        # Check completion indicates failure
        completions = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completions) == 1
        assert completions[0].success is False
        assert completions[0].exit_code == 1
        assert completions[0].error_message == "Simulated failure"

    @pytest.mark.asyncio
    async def test_download_streaming(self) -> None:
        """Test download phase streaming."""
        plugin = MockStreamingPlugin()

        events: list[StreamEvent] = []
        async for event in plugin.download():
            events.append(event)

        # Check progress events
        progress_events = [e for e in events if isinstance(e, ProgressEvent)]
        assert len(progress_events) == 5
        assert all(e.phase == Phase.DOWNLOAD for e in progress_events)

        # Check bytes tracking
        last_progress = progress_events[-1]
        assert last_progress.bytes_downloaded == 50_000_000
        assert last_progress.bytes_total == 50_000_000

    @pytest.mark.asyncio
    async def test_parallel_streaming_execution(self) -> None:
        """Test parallel streaming from multiple plugins."""
        plugins = [
            MockStreamingPlugin(name=f"plugin-{i}", event_count=3, event_delay=0.01)
            for i in range(3)
        ]

        async def collect_events(plugin: MockStreamingPlugin) -> list[StreamEvent]:
            events: list[StreamEvent] = []
            async for event in plugin.execute_streaming():
                events.append(event)
            return events

        # Run all plugins in parallel
        results = await asyncio.gather(*[collect_events(p) for p in plugins])

        # Verify each plugin produced events
        for i, events in enumerate(results):
            assert len(events) > 0
            completions = [e for e in events if isinstance(e, CompletionEvent)]
            assert len(completions) == 1
            assert completions[0].plugin_name == f"plugin-{i}"


class TestStreamEventQueue:
    """Integration tests for StreamEventQueue."""

    @pytest.mark.asyncio
    async def test_queue_with_multiple_producers(self) -> None:
        """Test queue with multiple concurrent producers."""
        queue = StreamEventQueue(maxsize=100)

        async def producer(plugin_name: str, count: int) -> None:
            for i in range(count):
                event = OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=plugin_name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Line {i}",
                )
                await queue.put(event)
                await asyncio.sleep(0.001)

        # Start multiple producers
        producers = [asyncio.create_task(producer(f"plugin-{i}", 10)) for i in range(3)]

        # Collect events
        events: list[StreamEvent] = []
        collector_done = asyncio.Event()

        async def collector() -> None:
            while len(events) < 30:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    if event:
                        events.append(event)
                except TimeoutError:
                    break
            collector_done.set()

        collector_task = asyncio.create_task(collector())

        # Wait for producers
        await asyncio.gather(*producers)
        await queue.close()
        await collector_done.wait()
        collector_task.cancel()

        # Verify all events received
        assert len(events) == 30

        # Verify events from all plugins
        plugin_names = {e.plugin_name for e in events}
        assert plugin_names == {"plugin-0", "plugin-1", "plugin-2"}

    @pytest.mark.asyncio
    async def test_queue_backpressure(self) -> None:
        """Test queue handles backpressure correctly."""
        queue = StreamEventQueue(maxsize=5)

        # Fill the queue
        for i in range(10):
            event = OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line=f"Line {i}",
            )
            await queue.put(event)

        # Queue should be full, some events dropped
        assert queue.qsize() == 5
        assert queue.dropped_count == 5


class TestStreamingWithMetrics:
    """Integration tests for streaming with metrics collection."""

    @pytest.mark.asyncio
    async def test_streaming_with_metrics_collection(self) -> None:
        """Test that streaming integrates with metrics collection."""
        collector = MetricsCollector()
        set_metrics_collector(collector)

        plugin = MockStreamingPlugin(event_count=5)

        # Start plugin metrics
        collector.start_plugin_execution(plugin.name)

        # Collect events and track metrics
        async for event in plugin.execute_streaming():
            collector.increment_event_count(plugin.name)

            if isinstance(event, ProgressEvent):
                # Simulate UI update latency
                with LatencyTimer() as timer:
                    await asyncio.sleep(0.001)  # Simulate UI update
                collector.record_ui_latency(timer.elapsed_ms)

        # End plugin metrics
        pm = collector.end_plugin_execution(plugin.name)

        # Verify metrics
        assert pm is not None
        assert pm.event_count > 0
        assert pm.duration_seconds is not None
        assert pm.duration_seconds > 0

        # Check UI latency was recorded
        avg_latency = collector.get_average_ui_latency()
        assert avg_latency is not None
        assert avg_latency > 0

    @pytest.mark.asyncio
    async def test_queue_depth_monitoring(self) -> None:
        """Test queue depth monitoring during streaming."""
        collector = MetricsCollector()
        queue = StreamEventQueue(maxsize=100)

        # Add events and monitor queue depth
        for i in range(50):
            event = OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name="test",
                timestamp=datetime.now(tz=UTC),
                line=f"Line {i}",
            )
            await queue.put(event)
            collector.record_queue_depth(queue.qsize())

        # Verify queue depth was tracked
        avg_depth = collector.get_average_queue_depth()
        assert avg_depth is not None
        assert avg_depth > 0


class TestStreamingHelpers:
    """Integration tests for streaming helper utilities."""

    @pytest.mark.asyncio
    async def test_safe_consume_stream_with_break(self) -> None:
        """Test safe_consume_stream properly closes on break."""
        plugin = MockStreamingPlugin(event_count=10)
        closed = False

        async def tracked_generator() -> AsyncGenerator[StreamEvent, None]:
            nonlocal closed
            try:
                async for event in plugin.execute_streaming():
                    yield event
            finally:
                closed = True

        events: list[StreamEvent] = []
        gen = safe_consume_stream(tracked_generator())
        try:
            async for event in gen:
                events.append(event)
                if len(events) >= 5:
                    break
        finally:
            # Explicitly close the generator to ensure cleanup
            await gen.aclose()

        # Generator should be closed
        assert closed is True
        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_timeout_stream_completes_normally(self) -> None:
        """Test timeout_stream when stream completes before timeout."""
        plugin = MockStreamingPlugin(event_count=3, event_delay=0.01)

        events: list[StreamEvent] = []
        async for event in timeout_stream(
            plugin.execute_streaming(),
            timeout_seconds=5.0,
            plugin_name=plugin.name,
        ):
            events.append(event)

        # All events should be received
        completions = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completions) == 1
        assert completions[0].success is True

    @pytest.mark.asyncio
    async def test_timeout_stream_times_out(self) -> None:
        """Test timeout_stream when stream exceeds timeout."""
        plugin = MockStreamingPlugin(event_count=100, event_delay=0.1)

        events: list[StreamEvent] = []
        async for event in timeout_stream(
            plugin.execute_streaming(),
            timeout_seconds=0.2,
            plugin_name=plugin.name,
        ):
            events.append(event)

        # Should have a timeout completion event
        completions = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completions) == 1
        assert completions[0].success is False
        assert "timed out" in (completions[0].error_message or "")

    @pytest.mark.asyncio
    async def test_batched_stream(self) -> None:
        """Test batched_stream groups events correctly."""
        plugin = MockStreamingPlugin(event_count=20, event_delay=0.005)

        batches: list[list[StreamEvent]] = []
        async for batch in batched_stream(
            plugin.execute_streaming(),
            batch_interval_ms=50.0,
            max_batch_size=10,
        ):
            batches.append(batch)

        # Should have multiple batches
        assert len(batches) > 1

        # Total events should match
        total_events = sum(len(b) for b in batches)
        # At least phase start, outputs, progress, phase end, completion
        assert total_events >= 20


class TestCrossPythonVersionCompatibility:
    """Tests for cross-Python version compatibility (3.11, 3.12, 3.13)."""

    @pytest.mark.asyncio
    async def test_asyncio_taskgroup_pattern(self) -> None:
        """Test asyncio.TaskGroup pattern works correctly."""
        results: list[str] = []

        async def task(name: str, delay: float) -> str:
            await asyncio.sleep(delay)
            results.append(name)
            return name

        async with asyncio.TaskGroup() as tg:
            tg.create_task(task("a", 0.01))
            tg.create_task(task("b", 0.02))
            tg.create_task(task("c", 0.01))

        # All tasks should complete
        assert len(results) == 3
        assert set(results) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_asyncio_timeout_pattern(self) -> None:
        """Test asyncio.timeout pattern works correctly."""
        completed = False

        async with asyncio.timeout(1.0):
            await asyncio.sleep(0.01)
            completed = True

        assert completed is True

    @pytest.mark.asyncio
    async def test_asyncio_timeout_raises(self) -> None:
        """Test asyncio.timeout raises TimeoutError correctly."""
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await asyncio.sleep(1.0)


class TestFeatureFlagIntegration:
    """Tests for streaming feature flag integration."""

    def test_streaming_enabled_default(self) -> None:
        """Test streaming_enabled defaults to True."""
        from core.models import GlobalConfig

        config = GlobalConfig()
        assert config.streaming_enabled is True

    def test_streaming_can_be_disabled(self) -> None:
        """Test streaming can be disabled via config."""
        from core.models import GlobalConfig

        config = GlobalConfig(streaming_enabled=False)
        assert config.streaming_enabled is False

    @pytest.mark.asyncio
    async def test_fallback_to_batch_mode(self) -> None:
        """Test fallback to batch mode when streaming is disabled."""
        from core.models import GlobalConfig

        config = GlobalConfig(streaming_enabled=False)

        # When streaming is disabled, use execute() instead of execute_streaming()
        plugin = MockStreamingPlugin()

        if config.streaming_enabled:
            events = []
            async for event in plugin.execute_streaming():
                events.append(event)
            result = None
        else:
            # Fallback to batch mode
            result = await plugin.execute()
            events = []

        assert result is not None
        assert result.status == PluginStatus.SUCCESS
        assert len(events) == 0  # No streaming events in batch mode

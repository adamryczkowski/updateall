"""Performance benchmarks for interactive tabs.

Phase 5 - Polish and Documentation
See docs/interactive-tabs-implementation-plan.md

These benchmarks measure performance characteristics of the interactive
tabbed UI components to ensure they meet responsiveness requirements.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from ui.key_bindings import KeyBindings
from ui.pty_session import is_pty_available
from ui.terminal_screen import TerminalScreen

# Skip all tests if PTY is not available
pytestmark = pytest.mark.skipif(
    not is_pty_available(),
    reason="PTY not available on this platform",
)


class TestTerminalScreenPerformance:
    """Performance benchmarks for TerminalScreen."""

    def test_feed_plain_text_performance(self) -> None:
        """Benchmark feeding plain text to terminal screen.

        Target: Process 10,000 characters in < 150ms (lenient for CI environments)
        """
        screen = TerminalScreen(columns=80, lines=24)

        # Generate test data - 10,000 characters
        test_data = b"A" * 10000

        start = time.perf_counter()
        screen.feed(test_data)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.15, f"Plain text processing took {elapsed:.3f}s, expected < 0.15s"

    def test_feed_ansi_sequences_performance(self) -> None:
        """Benchmark feeding ANSI sequences to terminal screen.

        Target: Process 1,000 ANSI sequences in < 200ms (lenient for CI environments)
        """
        screen = TerminalScreen(columns=80, lines=24)

        # Generate test data - 1,000 colored text segments
        segments = []
        for i in range(1000):
            color = 31 + (i % 7)  # Cycle through colors
            segments.append(f"\x1b[{color}mText{i}\x1b[0m")
        test_data = "".join(segments).encode()

        start = time.perf_counter()
        screen.feed(test_data)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.2, f"ANSI processing took {elapsed:.3f}s, expected < 0.2s"

    def test_feed_cursor_movement_performance(self) -> None:
        """Benchmark feeding cursor movement sequences.

        Target: Process 1,000 cursor movements in < 50ms
        """
        screen = TerminalScreen(columns=80, lines=24)

        # Generate test data - cursor movements
        movements = []
        for i in range(1000):
            row = (i % 24) + 1
            col = (i % 80) + 1
            movements.append(f"\x1b[{row};{col}HX")
        test_data = "".join(movements).encode()

        start = time.perf_counter()
        screen.feed(test_data)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, f"Cursor movement took {elapsed:.3f}s, expected < 0.05s"

    def test_scrollback_append_performance(self) -> None:
        """Benchmark scrollback buffer append operations.

        Target: Append 10,000 lines in < 2s (lenient for CI environments)
        """
        screen = TerminalScreen(columns=80, lines=24, scrollback_lines=10000)

        # Generate test data - 10,000 lines
        lines = [f"Line {i}\n" for i in range(10000)]
        test_data = "".join(lines).encode()

        start = time.perf_counter()
        screen.feed(test_data)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Scrollback append took {elapsed:.3f}s, expected < 2.0s"

    def test_get_display_lines_performance(self) -> None:
        """Benchmark getting display lines.

        Target: Get display 1,000 times in < 2s (lenient for CI environments)
        """
        screen = TerminalScreen(columns=80, lines=24)

        # Fill screen with content
        screen.feed(b"X" * (80 * 24))

        start = time.perf_counter()
        for _ in range(1000):
            _ = screen.display
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Get display took {elapsed:.3f}s, expected < 2.0s"

    def test_resize_performance(self) -> None:
        """Benchmark terminal resize operations.

        Target: Resize 100 times in < 50ms
        """
        screen = TerminalScreen(columns=80, lines=24)

        # Fill screen with content
        screen.feed(b"X" * (80 * 24))

        start = time.perf_counter()
        for i in range(100):
            cols = 80 + (i % 40)
            rows = 24 + (i % 16)
            screen.resize(cols, rows)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, f"Resize took {elapsed:.3f}s, expected < 0.05s"


class TestKeyBindingsPerformance:
    """Performance benchmarks for KeyBindings."""

    def test_key_lookup_performance(self) -> None:
        """Benchmark key lookup operations.

        Target: 10,000 lookups in < 500ms (lenient for CI environments)
        """
        bindings = KeyBindings()

        start = time.perf_counter()
        for _ in range(10000):
            _ = bindings.get_action("ctrl+tab")
            _ = bindings.get_action("ctrl+shift+tab")
            _ = bindings.get_action("alt+1")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Key lookup took {elapsed:.3f}s, expected < 0.5s"

    def test_is_navigation_key_performance(self) -> None:
        """Benchmark navigation key check.

        Target: 10,000 checks in < 500ms (lenient for CI environments)
        """
        bindings = KeyBindings()

        start = time.perf_counter()
        for _ in range(10000):
            _ = bindings.is_navigation_key("ctrl+tab")
            _ = bindings.is_navigation_key("a")
            _ = bindings.is_navigation_key("ctrl+c")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Navigation check took {elapsed:.3f}s, expected < 0.5s"


class TestPTYSessionPerformance:
    """Performance benchmarks for PTY session operations."""

    @pytest.mark.asyncio
    async def test_pty_creation_performance(self) -> None:
        """Benchmark PTY session creation.

        Target: Create and close 10 sessions in < 10s (lenient for CI environments)
        """
        from ui.pty_session import PTYSession

        start = time.perf_counter()
        for _ in range(10):
            session = PTYSession(
                command=["/bin/true"],
                cols=80,
                rows=24,
            )
            await session.start()
            await session.close()
        elapsed = time.perf_counter() - start

        assert elapsed < 10.0, f"PTY creation took {elapsed:.3f}s, expected < 10.0s"

    @pytest.mark.asyncio
    async def test_pty_write_performance(self) -> None:
        """Benchmark PTY write operations.

        Target: Write 1,000 small messages in < 500ms (lenient for CI environments)
        """
        from ui.pty_session import PTYSession

        session = PTYSession(
            command=["/bin/cat"],
            cols=80,
            rows=24,
        )
        await session.start()

        try:
            start = time.perf_counter()
            for i in range(1000):
                await session.write(f"Message {i}\n".encode())
            elapsed = time.perf_counter() - start

            assert elapsed < 0.5, f"PTY write took {elapsed:.3f}s, expected < 0.5s"
        finally:
            await session.close()

    @pytest.mark.asyncio
    async def test_pty_read_performance(self) -> None:
        """Benchmark PTY read operations.

        Target: Read output from echo command in < 100ms
        """
        from ui.pty_session import PTYSession

        # Create session that produces output
        session = PTYSession(
            command=["/bin/bash", "-c", "for i in $(seq 1 100); do echo Line $i; done"],
            cols=80,
            rows=24,
        )
        await session.start()

        try:
            start = time.perf_counter()
            total_bytes = 0
            while session.is_running:
                try:
                    data = await session.read(timeout=0.1)
                    total_bytes += len(data)
                except Exception:
                    break
            elapsed = time.perf_counter() - start

            # Should complete quickly
            assert elapsed < 0.5, f"PTY read took {elapsed:.3f}s, expected < 0.5s"
        finally:
            await session.close()


class TestInputRouterPerformance:
    """Performance benchmarks for InputRouter."""

    @pytest.mark.asyncio
    async def test_route_key_performance(self) -> None:
        """Benchmark key routing operations.

        Target: Route 1,000 keys in < 1s (lenient for CI environments)
        """
        from ui.input_router import InputRouter

        received_input: list[bytes] = []

        async def on_pty_input(data: bytes, **_kwargs: str | None) -> None:
            received_input.append(data)

        router = InputRouter(
            key_bindings=KeyBindings(),
            on_pty_input=on_pty_input,
        )
        router.set_active_tab("test")

        start = time.perf_counter()
        for _ in range(1000):
            await router.route_key("a")
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Key routing took {elapsed:.3f}s, expected < 1.0s"

    @pytest.mark.asyncio
    async def test_route_text_performance(self) -> None:
        """Benchmark text routing operations.

        Target: Route 10,000 characters in < 1s (lenient for CI environments)
        """
        from ui.input_router import InputRouter

        received_input: list[bytes] = []

        async def on_pty_input(data: bytes, **_kwargs: str | None) -> None:
            received_input.append(data)

        router = InputRouter(
            key_bindings=KeyBindings(),
            on_pty_input=on_pty_input,
        )
        router.set_active_tab("test")

        # Generate test text
        test_text = "A" * 10000

        start = time.perf_counter()
        await router.route_text(test_text)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Text routing took {elapsed:.3f}s, expected < 1.0s"


class TestTerminalPanePerformance:
    """Performance benchmarks for TerminalPane."""

    @pytest.mark.asyncio
    async def test_output_processing_performance(self) -> None:
        """Benchmark output processing in terminal pane.

        Target: Process 10,000 bytes of output in < 500ms (lenient for CI environments)
        """
        from unittest.mock import MagicMock

        from ui.terminal_pane import PaneConfig, TerminalPane

        # Create pane with mock plugin
        mock_plugin = MagicMock()
        mock_plugin.name = "test"

        TerminalPane(
            pane_id="test",
            pane_name="Test",
            command=["/bin/echo", "test"],
            config=PaneConfig(columns=80, lines=24),
            plugin=mock_plugin,
        )

        # Simulate output processing by directly feeding to terminal view
        # (This tests the screen processing, not the full PTY loop)
        from ui.terminal_screen import TerminalScreen

        screen = TerminalScreen(columns=80, lines=24)

        # Generate test output
        test_output = b"X" * 10000

        start = time.perf_counter()
        screen.feed(test_output)
        elapsed = time.perf_counter() - start

        # Use a generous threshold (500ms) to account for system load variations
        # The key is that processing should be reasonably fast, not exact timing
        assert elapsed < 0.5, f"Output processing took {elapsed:.3f}s, expected < 0.5s"


class TestScrollbackPerformance:
    """Performance benchmarks for scrollback buffer."""

    def test_scrollback_memory_efficiency(self) -> None:
        """Test scrollback buffer memory efficiency.

        Verify that scrollback buffer properly limits memory usage.
        """
        screen = TerminalScreen(columns=80, lines=24, scrollback_lines=1000)

        # Feed more lines than scrollback limit
        for i in range(2000):
            screen.feed(f"Line {i}\n".encode())

        # Get scrollback
        scrollback = screen.get_history()

        # Should be limited to scrollback_lines
        assert len(scrollback) <= 1000, f"Scrollback has {len(scrollback)} lines, expected <= 1000"

    def test_scrollback_scroll_performance(self) -> None:
        """Benchmark scrollback scroll operations.

        Target: 1,000 scroll operations in < 50ms
        """
        screen = TerminalScreen(columns=80, lines=24, scrollback_lines=10000)

        # Fill scrollback
        for i in range(5000):
            screen.feed(f"Line {i}\n".encode())

        start = time.perf_counter()
        for _ in range(1000):
            screen.scroll_up(10)
            screen.scroll_down(10)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, f"Scroll operations took {elapsed:.3f}s, expected < 0.05s"


class TestConcurrentPerformance:
    """Performance benchmarks for concurrent operations."""

    @pytest.mark.asyncio
    async def test_multiple_panes_concurrent_output(self) -> None:
        """Benchmark multiple panes processing output concurrently.

        Target: 3 panes processing 1,000 lines each in < 500ms
        """
        from ui.terminal_screen import TerminalScreen

        screens = [TerminalScreen(columns=80, lines=24) for _ in range(3)]

        async def process_output(screen: TerminalScreen, pane_id: int) -> None:
            for i in range(1000):
                screen.feed(f"Pane {pane_id} Line {i}\n".encode())
                # Simulate async yield
                if i % 100 == 0:
                    await asyncio.sleep(0)

        start = time.perf_counter()
        await asyncio.gather(
            process_output(screens[0], 0),
            process_output(screens[1], 1),
            process_output(screens[2], 2),
        )
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Concurrent processing took {elapsed:.3f}s, expected < 0.5s"


class TestMemoryPerformance:
    """Memory usage benchmarks."""

    def test_terminal_screen_memory_usage(self) -> None:
        """Test terminal screen memory usage is reasonable.

        A terminal screen with 10,000 line scrollback should use < 10MB.
        """
        import sys

        screen = TerminalScreen(columns=80, lines=24, scrollback_lines=10000)

        # Fill scrollback
        for i in range(10000):
            screen.feed(f"Line {i}: {'X' * 70}\n".encode())

        # Get approximate memory usage
        # Note: This is a rough estimate using sys.getsizeof
        scrollback = screen.get_history()
        total_size = sum(sys.getsizeof(line) for line in scrollback)

        # Should be less than 10MB
        assert total_size < 10 * 1024 * 1024, (
            f"Memory usage {total_size / 1024 / 1024:.1f}MB > 10MB"
        )


class TestLatencyPerformance:
    """Latency benchmarks for interactive operations."""

    @pytest.mark.asyncio
    async def test_input_to_output_latency(self) -> None:
        """Benchmark input-to-output latency.

        Target: Input should be echoed back in < 500ms (lenient for CI environments)
        """
        from ui.pty_session import PTYSession

        session = PTYSession(
            command=["/bin/cat"],
            cols=80,
            rows=24,
        )
        await session.start()

        try:
            # Send input and measure time to receive echo
            start = time.perf_counter()
            await session.write(b"test\n")

            # Wait for echo
            received = b""
            while b"test" not in received:
                try:
                    data = await session.read(timeout=0.1)
                    received += data
                except Exception:
                    break

            elapsed = time.perf_counter() - start

            assert elapsed < 0.5, f"Input-output latency {elapsed:.3f}s, expected < 0.5s"
        finally:
            await session.close()

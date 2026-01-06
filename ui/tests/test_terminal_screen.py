"""Tests for TerminalScreen wrapper around pyte.

Phase 2 - Terminal Emulation
See docs/interactive-tabs-implementation-plan.md section 5.2.2
"""

from __future__ import annotations

from ui.terminal_screen import TerminalScreen


class TestTerminalScreenCreation:
    """Tests for TerminalScreen creation and initialization."""

    def test_create_screen_with_default_size(self) -> None:
        """Test creating a TerminalScreen with default size."""
        screen = TerminalScreen()
        assert screen.columns == 80
        assert screen.lines == 24

    def test_create_screen_with_custom_size(self) -> None:
        """Test creating a TerminalScreen with custom size."""
        screen = TerminalScreen(columns=120, lines=40)
        assert screen.columns == 120
        assert screen.lines == 40

    def test_create_screen_with_scrollback(self) -> None:
        """Test creating a TerminalScreen with scrollback buffer."""
        screen = TerminalScreen(columns=80, lines=24, scrollback_lines=1000)
        assert screen.scrollback_lines == 1000

    def test_default_scrollback_lines(self) -> None:
        """Test that default scrollback is 10000 lines."""
        screen = TerminalScreen()
        assert screen.scrollback_lines == 10000


class TestTerminalScreenRendering:
    """Tests for terminal screen rendering."""

    def test_render_plain_text(self) -> None:
        """Test rendering plain text output."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello, World!")
        display = screen.display
        assert "Hello, World!" in display[0]

    def test_render_multiple_lines(self) -> None:
        """Test rendering multiple lines of text."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Line 1\r\nLine 2\r\nLine 3")
        display = screen.display
        assert "Line 1" in display[0]
        assert "Line 2" in display[1]
        assert "Line 3" in display[2]

    def test_render_ansi_colors(self) -> None:
        """Test rendering ANSI color codes."""
        screen = TerminalScreen(columns=80, lines=24)
        # Red text: ESC[31m
        screen.feed(b"\x1b[31mRed Text\x1b[0m")
        display = screen.display
        assert "Red Text" in display[0]
        # Check that color information is preserved in buffer
        styled_line = screen.get_styled_line(0)
        assert len(styled_line) > 0
        # Find the 'R' character and check its color
        for char in styled_line:
            if char.data == "R":
                assert char.fg == "red"
                break

    def test_render_cursor_movement(self) -> None:
        """Test rendering cursor movement sequences."""
        screen = TerminalScreen(columns=80, lines=24)
        # Move cursor to position (5, 10) using ESC[row;colH
        screen.feed(b"\x1b[10;5HX")
        display = screen.display
        # Line 9 (0-indexed), column 4 (0-indexed)
        assert display[9][4] == "X"

    def test_render_screen_clear(self) -> None:
        """Test rendering screen clear sequences."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Some content")
        # Clear screen: ESC[2J
        screen.feed(b"\x1b[2J")
        display = screen.display
        # All lines should be empty (spaces)
        assert all(line.strip() == "" for line in display)

    def test_cursor_position(self) -> None:
        """Test cursor position tracking."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello")
        assert screen.cursor_x == 5
        assert screen.cursor_y == 0

    def test_cursor_position_after_newline(self) -> None:
        """Test cursor position after newline."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello\r\nWorld")
        assert screen.cursor_x == 5
        assert screen.cursor_y == 1


class TestTerminalScreenScrollback:
    """Tests for scrollback buffer."""

    def test_scrollback_buffer_stores_history(self) -> None:
        """Test that scrollback buffer stores line history."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=100)
        # Write more lines than screen height
        for i in range(10):
            screen.feed(f"Line {i}\r\n".encode())
        # The first lines should be in history
        history = screen.get_history()
        assert len(history) >= 5

    def test_scrollback_buffer_limit(self) -> None:
        """Test scrollback buffer size limit."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=10)
        # Write many more lines than scrollback limit
        for i in range(50):
            screen.feed(f"Line {i}\r\n".encode())
        # History should be limited
        history = screen.get_history()
        assert len(history) <= 10

    def test_scroll_up_in_history(self) -> None:
        """Test scrolling up in history."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=100)
        # Write more lines than screen height
        for i in range(20):
            screen.feed(f"Line {i}\r\n".encode())
        # Scroll up
        screen.scroll_up()
        # Should show older content - scroll_offset should be > 0
        assert screen.scroll_offset > 0
        # Verify display is still accessible
        assert len(screen.display) == 5

    def test_scroll_down_in_history(self) -> None:
        """Test scrolling down in history."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=100)
        # Write more lines than screen height
        for i in range(20):
            screen.feed(f"Line {i}\r\n".encode())
        # Scroll up first
        screen.scroll_up()
        screen.scroll_up()
        old_offset = screen.scroll_offset
        # Then scroll down
        screen.scroll_down()
        assert screen.scroll_offset < old_offset

    def test_scroll_to_bottom(self) -> None:
        """Test scrolling to bottom of history."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=100)
        # Write more lines than screen height
        for i in range(20):
            screen.feed(f"Line {i}\r\n".encode())
        # Scroll up multiple times
        for _ in range(5):
            screen.scroll_up()
        # Scroll to bottom
        screen.scroll_to_bottom()
        assert screen.scroll_offset == 0


class TestTerminalScreenResize:
    """Tests for terminal screen resize."""

    def test_resize_terminal(self) -> None:
        """Test resizing the terminal."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello")
        screen.resize(columns=120, lines=40)
        assert screen.columns == 120
        assert screen.lines == 40

    def test_resize_preserves_content(self) -> None:
        """Test that resize preserves existing content."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello, World!")
        screen.resize(columns=120, lines=40)
        display = screen.display
        assert "Hello, World!" in display[0]

    def test_resize_smaller_clips_content(self) -> None:
        """Test that resizing smaller clips content appropriately."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"A" * 80)  # Fill first line
        screen.resize(columns=40, lines=24)
        # Content should be clipped or wrapped
        assert screen.columns == 40
        # Verify display is still accessible
        assert len(screen.display) == 24


class TestTerminalScreenStyling:
    """Tests for ANSI styling support."""

    def test_bold_text(self) -> None:
        """Test bold text rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # Bold: ESC[1m
        screen.feed(b"\x1b[1mBold\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "B":
                assert char.bold is True
                break

    def test_italic_text(self) -> None:
        """Test italic text rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # Italic: ESC[3m
        screen.feed(b"\x1b[3mItalic\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "I":
                assert char.italics is True
                break

    def test_underline_text(self) -> None:
        """Test underline text rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # Underline: ESC[4m
        screen.feed(b"\x1b[4mUnderline\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "U":
                assert char.underscore is True
                break

    def test_foreground_colors(self) -> None:
        """Test foreground color rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # Green: ESC[32m
        screen.feed(b"\x1b[32mGreen\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "G":
                assert char.fg == "green"
                break

    def test_background_colors(self) -> None:
        """Test background color rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # Blue background: ESC[44m
        screen.feed(b"\x1b[44mBlue BG\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "B":
                assert char.bg == "blue"
                break

    def test_256_colors(self) -> None:
        """Test 256-color mode rendering."""
        screen = TerminalScreen(columns=80, lines=24)
        # 256-color foreground: ESC[38;5;196m (bright red)
        screen.feed(b"\x1b[38;5;196mRed256\x1b[0m")
        styled_line = screen.get_styled_line(0)
        for char in styled_line:
            if char.data == "R":
                # pyte stores 256 colors as strings like "196"
                assert char.fg is not None
                break


class TestTerminalScreenReset:
    """Tests for terminal screen reset."""

    def test_reset_clears_screen(self) -> None:
        """Test that reset clears the screen."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Some content")
        screen.reset()
        display = screen.display
        assert all(line.strip() == "" for line in display)

    def test_reset_clears_scrollback(self) -> None:
        """Test that reset clears the scrollback buffer."""
        screen = TerminalScreen(columns=80, lines=5, scrollback_lines=100)
        for i in range(20):
            screen.feed(f"Line {i}\r\n".encode())
        screen.reset()
        history = screen.get_history()
        assert len(history) == 0

    def test_reset_resets_cursor(self) -> None:
        """Test that reset moves cursor to home position."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello\r\nWorld")
        screen.reset()
        assert screen.cursor_x == 0
        assert screen.cursor_y == 0


class TestTerminalScreenDirtyTracking:
    """Tests for dirty line tracking."""

    def test_dirty_lines_after_write(self) -> None:
        """Test that dirty lines are tracked after write."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.clear_dirty()
        screen.feed(b"Hello")
        dirty = screen.get_dirty_lines()
        assert 0 in dirty

    def test_clear_dirty(self) -> None:
        """Test clearing dirty line tracking."""
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello")
        screen.clear_dirty()
        dirty = screen.get_dirty_lines()
        assert len(dirty) == 0


class TestTerminalScreenErrorHandling:
    """Tests for error handling in terminal screen."""

    def test_invalid_escape_sequence_handled(self) -> None:
        """Test that invalid escape sequences don't crash."""
        screen = TerminalScreen(columns=80, lines=24)
        # Invalid escape sequence
        screen.feed(b"\x1b[999999999m")
        # Should not raise, just ignore or handle gracefully
        display = screen.display
        assert display is not None

    def test_malformed_utf8_handled(self) -> None:
        """Test that malformed UTF-8 is handled gracefully."""
        screen = TerminalScreen(columns=80, lines=24)
        # Invalid UTF-8 sequence
        screen.feed(b"\xff\xfe")
        # Should not raise
        display = screen.display
        assert display is not None

    def test_binary_data_handled(self) -> None:
        """Test that binary data is handled gracefully."""
        screen = TerminalScreen(columns=80, lines=24)
        # Random binary data
        screen.feed(bytes(range(256)))
        # Should not raise
        display = screen.display
        assert display is not None

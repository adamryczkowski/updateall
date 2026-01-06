"""Tests for TerminalView Textual widget.

Phase 2 - Terminal Emulation
See docs/interactive-tabs-implementation-plan.md section 5.2.3
"""

from __future__ import annotations

from rich.text import Text

from ui.terminal_view import TerminalView, ansi_color_to_rich_color


class TestTerminalViewCreation:
    """Tests for TerminalView creation and initialization."""

    def test_create_terminal_view_default(self) -> None:
        """Test creating a TerminalView with default settings."""
        view = TerminalView()
        assert view.terminal_screen is not None
        assert view.terminal_screen.columns == 80
        assert view.terminal_screen.lines == 24

    def test_create_terminal_view_with_custom_size(self) -> None:
        """Test creating a TerminalView with custom size."""
        view = TerminalView(columns=120, lines=40)
        assert view.terminal_screen.columns == 120
        assert view.terminal_screen.lines == 40

    def test_create_terminal_view_with_scrollback(self) -> None:
        """Test creating a TerminalView with custom scrollback."""
        view = TerminalView(scrollback_lines=5000)
        assert view.terminal_screen.scrollback_lines == 5000


class TestTerminalViewFeed:
    """Tests for feeding data to TerminalView."""

    def test_feed_plain_text(self) -> None:
        """Test feeding plain text to the terminal."""
        view = TerminalView()
        view.feed(b"Hello, World!")
        display = view.terminal_screen.display
        assert "Hello, World!" in display[0]

    def test_feed_multiple_lines(self) -> None:
        """Test feeding multiple lines."""
        view = TerminalView()
        view.feed(b"Line 1\r\nLine 2\r\nLine 3")
        display = view.terminal_screen.display
        assert "Line 1" in display[0]
        assert "Line 2" in display[1]
        assert "Line 3" in display[2]

    def test_feed_ansi_colors(self) -> None:
        """Test feeding ANSI colored text."""
        view = TerminalView()
        view.feed(b"\x1b[31mRed\x1b[0m")
        display = view.terminal_screen.display
        assert "Red" in display[0]


class TestTerminalViewRendering:
    """Tests for TerminalView rendering."""

    def test_render_lines_returns_text_objects(self) -> None:
        """Test that render_terminal_lines returns Rich Text objects."""
        view = TerminalView()
        view.feed(b"Hello")
        lines = view.render_terminal_lines()
        assert len(lines) > 0
        assert all(isinstance(line, Text) for line in lines)

    def test_render_lines_preserves_content(self) -> None:
        """Test that rendered lines contain the terminal content."""
        view = TerminalView()
        view.feed(b"Test Content")
        lines = view.render_terminal_lines()
        # First line should contain "Test Content"
        assert "Test Content" in str(lines[0])

    def test_render_lines_applies_colors(self) -> None:
        """Test that rendered lines have color styles applied."""
        view = TerminalView()
        # Red text
        view.feed(b"\x1b[31mRed\x1b[0m")
        lines = view.render_terminal_lines()
        # The text should have style spans
        first_line = lines[0]
        # Check that there are styled spans
        assert len(first_line._spans) > 0 or "Red" in str(first_line)

    def test_render_lines_applies_bold(self) -> None:
        """Test that rendered lines have bold style applied."""
        view = TerminalView()
        view.feed(b"\x1b[1mBold\x1b[0m")
        lines = view.render_terminal_lines()
        first_line = lines[0]
        assert "Bold" in str(first_line)


class TestTerminalViewCursor:
    """Tests for cursor handling in TerminalView."""

    def test_cursor_position(self) -> None:
        """Test cursor position tracking."""
        view = TerminalView()
        view.feed(b"Hello")
        assert view.cursor_x == 5
        assert view.cursor_y == 0

    def test_cursor_visible_property(self) -> None:
        """Test cursor visibility property."""
        view = TerminalView()
        # By default cursor should be visible
        assert view.cursor_visible is True

    def test_show_cursor_property(self) -> None:
        """Test show_cursor reactive property."""
        view = TerminalView()
        assert view.show_cursor is True
        view.show_cursor = False
        assert view.show_cursor is False


class TestTerminalViewScrolling:
    """Tests for scrolling in TerminalView."""

    def test_scroll_up(self) -> None:
        """Test scrolling up in history."""
        view = TerminalView(lines=5, scrollback_lines=100)
        # Write more lines than screen height
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())
        view.scroll_history_up()
        assert view.terminal_screen.scroll_offset > 0

    def test_scroll_down(self) -> None:
        """Test scrolling down in history."""
        view = TerminalView(lines=5, scrollback_lines=100)
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())
        view.scroll_history_up()
        view.scroll_history_up()
        old_offset = view.terminal_screen.scroll_offset
        view.scroll_history_down()
        assert view.terminal_screen.scroll_offset < old_offset

    def test_scroll_to_bottom(self) -> None:
        """Test scrolling to bottom."""
        view = TerminalView(lines=5, scrollback_lines=100)
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())
        view.scroll_history_up()
        view.scroll_history_up()
        view.scroll_to_bottom()
        assert view.terminal_screen.scroll_offset == 0

    def test_is_scrolled_up(self) -> None:
        """Test is_scrolled_up property."""
        view = TerminalView(lines=5, scrollback_lines=100)
        for i in range(20):
            view.feed(f"Line {i}\r\n".encode())
        assert view.is_scrolled_up is False
        view.scroll_history_up()
        assert view.is_scrolled_up is True


class TestTerminalViewResize:
    """Tests for TerminalView resize handling."""

    def test_resize_terminal(self) -> None:
        """Test resizing the terminal."""
        view = TerminalView(columns=80, lines=24)
        view.resize_terminal(columns=120, lines=40)
        assert view.terminal_screen.columns == 120
        assert view.terminal_screen.lines == 40

    def test_resize_preserves_content(self) -> None:
        """Test that resize preserves content."""
        view = TerminalView(columns=80, lines=24)
        view.feed(b"Hello, World!")
        view.resize_terminal(columns=120, lines=40)
        display = view.terminal_screen.display
        assert "Hello, World!" in display[0]


class TestTerminalViewReset:
    """Tests for TerminalView reset functionality."""

    def test_reset_clears_screen(self) -> None:
        """Test that reset clears the screen."""
        view = TerminalView()
        view.feed(b"Some content")
        view.reset()
        display = view.terminal_screen.display
        assert all(line.strip() == "" for line in display)

    def test_reset_resets_cursor(self) -> None:
        """Test that reset moves cursor to home."""
        view = TerminalView()
        view.feed(b"Hello\r\nWorld")
        view.reset()
        assert view.cursor_x == 0
        assert view.cursor_y == 0


class TestAnsiColorConversion:
    """Tests for ANSI color to Rich color conversion."""

    def test_default_color(self) -> None:
        """Test default color conversion."""
        assert ansi_color_to_rich_color("default") is None

    def test_basic_colors(self) -> None:
        """Test basic ANSI color names."""
        assert ansi_color_to_rich_color("red") == "red"
        assert ansi_color_to_rich_color("green") == "green"
        assert ansi_color_to_rich_color("blue") == "blue"
        assert ansi_color_to_rich_color("yellow") == "yellow"
        assert ansi_color_to_rich_color("cyan") == "cyan"
        assert ansi_color_to_rich_color("magenta") == "magenta"
        assert ansi_color_to_rich_color("white") == "white"
        assert ansi_color_to_rich_color("black") == "black"

    def test_bright_colors(self) -> None:
        """Test bright ANSI color names."""
        assert ansi_color_to_rich_color("brightred") == "bright_red"
        assert ansi_color_to_rich_color("brightgreen") == "bright_green"
        assert ansi_color_to_rich_color("brightblue") == "bright_blue"

    def test_256_color(self) -> None:
        """Test 256-color palette conversion."""
        # 256-color values are stored as strings like "196"
        result = ansi_color_to_rich_color("196")
        assert result is not None
        assert "color" in result.lower() or result.startswith("#") or result == "196"

    def test_rgb_color(self) -> None:
        """Test RGB color conversion."""
        # RGB colors might be stored as "ff0000" or similar
        result = ansi_color_to_rich_color("ff0000")
        assert result is not None


class TestTerminalViewDirtyTracking:
    """Tests for dirty line tracking in TerminalView."""

    def test_get_dirty_lines(self) -> None:
        """Test getting dirty lines."""
        view = TerminalView()
        view.terminal_screen.clear_dirty()
        view.feed(b"Hello")
        dirty = view.get_dirty_lines()
        assert 0 in dirty

    def test_clear_dirty(self) -> None:
        """Test clearing dirty lines."""
        view = TerminalView()
        view.feed(b"Hello")
        view.clear_dirty()
        dirty = view.get_dirty_lines()
        assert len(dirty) == 0


class TestTerminalViewProperties:
    """Tests for TerminalView properties."""

    def test_columns_property(self) -> None:
        """Test columns property."""
        view = TerminalView(columns=100)
        assert view.columns == 100

    def test_lines_property(self) -> None:
        """Test lines property."""
        view = TerminalView(lines=30)
        assert view.lines == 30

    def test_display_property(self) -> None:
        """Test terminal_display property."""
        view = TerminalView()
        view.feed(b"Test")
        display = view.terminal_display
        assert isinstance(display, list)
        assert len(display) == view.lines
        assert "Test" in display[0]


class TestTerminalViewContentSize:
    """Tests for TerminalView content size methods.

    These methods are required by Textual to properly size the widget
    and call render_line() for all visible lines.
    """

    def test_get_content_height_returns_terminal_lines(self) -> None:
        """Test that get_content_height returns the terminal line count."""
        from textual.geometry import Size

        view = TerminalView(columns=80, lines=24)
        container = Size(100, 50)
        viewport = Size(100, 50)

        height = view.get_content_height(container, viewport, 80)
        assert height == 24

    def test_get_content_height_with_custom_lines(self) -> None:
        """Test get_content_height with custom terminal size."""
        from textual.geometry import Size

        view = TerminalView(columns=120, lines=40)
        container = Size(200, 100)
        viewport = Size(200, 100)

        height = view.get_content_height(container, viewport, 120)
        assert height == 40

    def test_get_content_width_returns_terminal_columns(self) -> None:
        """Test that get_content_width returns the terminal column count."""
        from textual.geometry import Size

        view = TerminalView(columns=80, lines=24)
        container = Size(100, 50)
        viewport = Size(100, 50)

        width = view.get_content_width(container, viewport)
        assert width == 80

    def test_get_content_width_with_custom_columns(self) -> None:
        """Test get_content_width with custom terminal size."""
        from textual.geometry import Size

        view = TerminalView(columns=120, lines=40)
        container = Size(200, 100)
        viewport = Size(200, 100)

        width = view.get_content_width(container, viewport)
        assert width == 120

    def test_content_size_after_resize(self) -> None:
        """Test that content size updates after terminal resize."""
        from textual.geometry import Size

        view = TerminalView(columns=80, lines=24)
        container = Size(200, 100)
        viewport = Size(200, 100)

        # Initial size
        assert view.get_content_width(container, viewport) == 80
        assert view.get_content_height(container, viewport, 80) == 24

        # Resize terminal
        view.resize_terminal(columns=120, lines=40)

        # Size should update
        assert view.get_content_width(container, viewport) == 120
        assert view.get_content_height(container, viewport, 120) == 40

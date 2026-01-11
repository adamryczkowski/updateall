"""TerminalView Textual widget for rendering terminal screen content.

This module provides a Textual widget that renders terminal screen content
from a TerminalScreen (pyte wrapper) with full ANSI color and styling support.

Phase 2 - Terminal Emulation
See docs/interactive-tabs-implementation-plan.md section 3.2.1

Enhanced with mouse wheel and arrow key scrolling support.
Enhanced with text selection support (click-drag to select, auto-copy to clipboard).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.style import Style
from rich.text import Text
from textual import events  # noqa: TC002 - Required at runtime for mouse event handlers
from textual.events import MouseScrollDown, MouseScrollUp  # noqa: TC002 - Required at runtime
from textual.reactive import reactive
from textual.strip import Strip
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import RenderResult
    from textual.geometry import Size

from ui.terminal_screen import StyledChar, TerminalScreen

# ANSI color name mapping to Rich color names
ANSI_TO_RICH_COLORS: dict[str, str] = {
    "black": "black",
    "red": "red",
    "green": "green",
    "yellow": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightyellow": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
    # Also handle lowercase variants
    "brown": "yellow",  # Some terminals use brown for yellow
}


def ansi_color_to_rich_color(color: str) -> str | None:
    """Convert an ANSI color name to a Rich color name.

    Args:
        color: ANSI color name from pyte (e.g., "red", "brightgreen", "196").

    Returns:
        Rich color name or None for default color.
    """
    if color == "default":
        return None

    # Check direct mapping
    if color in ANSI_TO_RICH_COLORS:
        return ANSI_TO_RICH_COLORS[color]

    # Handle 256-color palette (stored as string numbers like "196")
    if color.isdigit():
        color_num = int(color)
        if 0 <= color_num <= 255:
            return f"color({color_num})"

    # Handle hex colors (e.g., "ff0000")
    if len(color) == 6:
        try:
            int(color, 16)
            return f"#{color}"
        except ValueError:
            pass

    # Return as-is for unknown colors (Rich might handle it)
    return color


class TerminalView(Static):
    """Textual widget for rendering terminal screen content.

    This widget provides:
    - Rendering of terminal screen buffer from pyte
    - ANSI color and styling support
    - Cursor display
    - Scrollback buffer navigation
    - Resize handling
    - Mouse wheel scrolling support
    - Text selection with auto-copy to clipboard

    The widget is focusable (can_focus=True) to ensure it receives mouse
    events for scrolling. This is necessary because Static widgets don't
    receive mouse events by default in Textual.

    Text selection works via click-and-drag. Selected text is automatically
    copied to the clipboard (like Windows Terminal behavior).

    Example:
        view = TerminalView(columns=80, lines=24)
        view.feed(b"Hello, World!")
        # Widget will render the terminal content
    """

    # Reactive properties
    show_cursor: reactive[bool] = reactive(True)

    # Enable focus to receive mouse events
    # This is a class variable that Textual checks
    can_focus = True

    # Disable Textual's built-in selection system - we use our own custom implementation
    # for better performance and to properly clear selection when content changes
    ALLOW_SELECT = False

    # CSS styling
    DEFAULT_CSS = """
    TerminalView {
        background: $surface;
        color: $text;
        min-height: 10;
    }

    TerminalView:focus {
        border: solid $accent;
    }
    """

    def __init__(
        self,
        columns: int = 80,
        lines: int = 24,
        scrollback_lines: int | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the TerminalView widget.

        Args:
            columns: Terminal width in columns.
            lines: Terminal height in lines.
            scrollback_lines: Number of lines to keep in scrollback buffer.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)

        self._terminal_screen = TerminalScreen(
            columns=columns,
            lines=lines,
            scrollback_lines=scrollback_lines,
        )

        # Selection state (custom implementation, not using Textual's selection system)
        self._selection_start: tuple[int, int] | None = None  # (col, row)
        self._selection_end: tuple[int, int] | None = None  # (col, row)
        self._is_selecting: bool = False

    @property
    def terminal_screen(self) -> TerminalScreen:
        """Get the underlying terminal screen."""
        return self._terminal_screen

    @property
    def columns(self) -> int:
        """Get the terminal width in columns."""
        return self._terminal_screen.columns

    @property
    def lines(self) -> int:
        """Get the terminal height in lines."""
        return self._terminal_screen.lines

    @property
    def cursor_x(self) -> int:
        """Get the cursor X position (column)."""
        return self._terminal_screen.cursor_x

    @property
    def cursor_y(self) -> int:
        """Get the cursor Y position (row)."""
        return self._terminal_screen.cursor_y

    @property
    def cursor_visible(self) -> bool:
        """Check if the cursor should be visible."""
        return self._terminal_screen.get_cursor_visible() and self.show_cursor

    @property
    def terminal_display(self) -> list[str]:
        """Get the current terminal display as a list of strings."""
        return self._terminal_screen.display

    @property
    def is_scrolled_up(self) -> bool:
        """Check if the view is scrolled up in history."""
        return self._terminal_screen.scroll_offset > 0

    def feed(self, data: bytes) -> None:
        """Feed data to the terminal screen.

        Args:
            data: Bytes to feed (may contain ANSI escape sequences).
        """
        # Clear selection when new content arrives (selection doesn't travel with text)
        if self.has_selection:
            self._selection_start = None
            self._selection_end = None
            self._is_selecting = False

        self._terminal_screen.feed(data)

        # Update the Static widget's content with the rendered terminal lines
        lines = self.render_terminal_lines()
        content = Group(*lines)
        self.update(content)

    def resize_terminal(self, columns: int, lines: int) -> None:
        """Resize the terminal screen.

        Args:
            columns: New terminal width.
            lines: New terminal height.
        """
        self._terminal_screen.resize(columns=columns, lines=lines)
        self.refresh()

    def reset(self) -> None:
        """Reset the terminal to its initial state."""
        self._terminal_screen.reset()
        self.refresh()

    def scroll_history_up(self, lines: int = 1) -> None:
        """Scroll up in the history buffer.

        Args:
            lines: Number of lines to scroll.
        """
        self._terminal_screen.scroll_up(lines)
        self._update_display()

    def scroll_history_down(self, lines: int = 1) -> None:
        """Scroll down in the history buffer.

        Args:
            lines: Number of lines to scroll.
        """
        self._terminal_screen.scroll_down(lines)
        self._update_display()

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom (current output)."""
        self._terminal_screen.scroll_to_bottom()
        self._update_display()

    def scroll_to_top(self) -> None:
        """Scroll to the top of history."""
        self._terminal_screen.scroll_to_top()
        self._update_display()

    def _update_display(self) -> None:
        """Update the widget's display content.

        This re-renders the terminal lines and calls update() to set the
        new content. This is necessary after scrolling because refresh()
        only repaints the cached content, it doesn't re-render.
        """
        from rich.console import Group

        rendered_lines = self.render_terminal_lines()
        content = Group(*rendered_lines)
        self.update(content)

    def get_dirty_lines(self) -> set[int]:
        """Get the set of dirty line numbers."""
        return self._terminal_screen.get_dirty_lines()

    def clear_dirty(self) -> None:
        """Clear the dirty line tracking."""
        self._terminal_screen.clear_dirty()

    def render(self) -> RenderResult:
        """Render the terminal content.

        This method is called by Textual to get the widget's content.
        We return the visual set by update(), not our own rendering.

        Returns:
            The visual content set by update().
        """
        # Let Static handle rendering - it uses the visual set by update()
        return super().render()

    def render_terminal_lines(self) -> list[Text]:
        """Render the terminal screen as Rich Text objects.

        Returns:
            List of Rich Text objects, one per line.
        """
        result: list[Text] = []

        for line_num in range(self._terminal_screen.lines):
            styled_chars = self._terminal_screen.get_styled_line(line_num)
            text = self._render_styled_line(styled_chars, line_num)
            result.append(text)

        return result

    def _render_styled_line(self, styled_chars: list[StyledChar], line_num: int) -> Text:
        """Render a line of styled characters as Rich Text.

        Args:
            styled_chars: List of styled characters.
            line_num: Line number (for cursor rendering).

        Returns:
            Rich Text object with styling applied.
        """
        text = Text()

        # Get selection range for this line (only if selecting)
        select_start_col, select_end_col = self._get_line_selection(line_num)

        for col, char in enumerate(styled_chars):
            # Build style from character attributes
            style = self._build_style(char)

            # Selection highlighting (applied first, before cursor)
            if (
                select_start_col is not None
                and select_end_col is not None
                and select_start_col <= col < select_end_col
            ):
                style = style + Style(reverse=True)

            # Check if cursor is at this position
            if (
                self.cursor_visible
                and not self.is_scrolled_up
                and line_num == self._terminal_screen.cursor_y
                and col == self._terminal_screen.cursor_x
            ):
                # Invert colors for cursor (applied after selection)
                style = style + Style(reverse=True)

            text.append(char.data, style=style)

        return text

    def _build_style(self, char: StyledChar) -> Style:
        """Build a Rich Style from a StyledChar.

        Args:
            char: Styled character from terminal screen.

        Returns:
            Rich Style object.
        """
        fg = ansi_color_to_rich_color(char.fg)
        bg = ansi_color_to_rich_color(char.bg)

        return Style(
            color=fg,
            bgcolor=bg,
            bold=char.bold,
            italic=char.italics,
            underline=char.underscore,
            strike=char.strikethrough,
            reverse=char.reverse,
            blink=char.blink,
        )

    def render_line(self, y: int) -> Strip:
        """Render a single line for the Textual framework.

        Args:
            y: Line number to render.

        Returns:
            Strip object for rendering.
        """
        if y < 0 or y >= self._terminal_screen.lines:
            return Strip.blank(self._terminal_screen.columns)

        styled_chars = self._terminal_screen.get_styled_line(y)
        text = self._render_styled_line(styled_chars, y)

        # Convert Text to Strip - use a default console if app not available
        console = self.app.console if self.app else Console()
        segments = list(text.render(console))
        return Strip(segments)

    def get_content_width(self, _container: Size, _viewport: Size) -> int:
        """Get the width of the terminal content.

        Called by Textual to determine the widget's content width.

        Args:
            _container: Size of the container (immediate parent) widget.
            _viewport: Size of the viewport.

        Returns:
            The terminal width in columns.
        """
        return self._terminal_screen.columns

    def get_content_height(self, _container: Size, _viewport: Size, _width: int) -> int:
        """Get the height of the terminal content.

        Called by Textual to determine the widget's content height.

        Args:
            _container: Size of the container (immediate parent) widget.
            _viewport: Size of the viewport.
            _width: Width of renderable.

        Returns:
            The terminal height in lines.
        """
        return self._terminal_screen.lines

    # Mouse scroll event handlers for Task 2
    def on_mouse_scroll_up(self, event: MouseScrollUp) -> None:
        """Handle mouse scroll up event.

        Scrolls the terminal history up when the mouse wheel scrolls up
        while the cursor is over the terminal view.

        Args:
            event: The mouse scroll up event.
        """
        self.scroll_history_up(lines=3)
        event.stop()

    def on_mouse_scroll_down(self, event: MouseScrollDown) -> None:
        """Handle mouse scroll down event.

        Scrolls the terminal history down when the mouse wheel scrolls down
        while the cursor is over the terminal view.

        Args:
            event: The mouse scroll down event.
        """
        self.scroll_history_down(lines=3)
        event.stop()

    # Custom text selection implementation (performance-optimized)
    # We use our own selection system instead of Textual's built-in one
    # to properly clear selection when content changes (selection doesn't travel with text)
    @property
    def has_selection(self) -> bool:
        """Check if there is an active selection.

        Returns:
            True if there is a selection, False otherwise.
        """
        return self._selection_start is not None and self._selection_end is not None

    def _screen_to_terminal(self, x: int, y: int) -> tuple[int, int]:
        """Convert screen coordinates to terminal (col, row).

        This is a direct calculation - no offset metadata needed.

        Args:
            x: Screen X coordinate (relative to widget).
            y: Screen Y coordinate (relative to widget).

        Returns:
            Tuple of (col, row) clamped to terminal bounds.
        """
        col = max(0, min(x, self._terminal_screen.columns - 1))
        row = max(0, min(y, self._terminal_screen.lines - 1))
        return col, row

    def _get_line_selection(self, line_num: int) -> tuple[int | None, int | None]:
        """Get the selection range for a specific line.

        Args:
            line_num: The line number to check.

        Returns:
            Tuple of (start_col, end_col) or (None, None) if line not selected.
        """
        if self._selection_start is None or self._selection_end is None:
            return None, None

        start_col, start_row = self._selection_start
        end_col, end_row = self._selection_end

        # Normalize so start <= end
        if (start_row, start_col) > (end_row, end_col):
            start_col, start_row, end_col, end_row = end_col, end_row, start_col, start_row

        # Check if this line is in the selection range
        if line_num < start_row or line_num > end_row:
            return None, None

        # Calculate column range for this line
        if line_num == start_row == end_row:
            return start_col, end_col
        elif line_num == start_row:
            return start_col, self._terminal_screen.columns
        elif line_num == end_row:
            return 0, end_col
        else:
            return 0, self._terminal_screen.columns

    def _get_selected_text(self) -> str:
        """Extract the selected text from the terminal.

        Returns:
            The selected text as a string, or empty string if no selection.
        """
        if self._selection_start is None or self._selection_end is None:
            return ""

        start_col, start_row = self._selection_start
        end_col, end_row = self._selection_end

        # Normalize so start <= end
        if (start_row, start_col) > (end_row, end_col):
            start_col, start_row, end_col, end_row = end_col, end_row, start_col, start_row

        lines = []
        for row in range(start_row, end_row + 1):
            styled_chars = self._terminal_screen.get_styled_line(row)
            line_text = "".join(char.data for char in styled_chars)

            if row == start_row == end_row:
                lines.append(line_text[start_col:end_col])
            elif row == start_row:
                lines.append(line_text[start_col:].rstrip())
            elif row == end_row:
                lines.append(line_text[:end_col])
            else:
                lines.append(line_text.rstrip())

        return "\n".join(lines)

    def _clear_selection(self) -> None:
        """Clear the current selection."""
        if self._selection_start is not None or self._selection_end is not None:
            self._selection_start = None
            self._selection_end = None
            self._is_selecting = False
            self._update_display()

    # Mouse event handlers for text selection
    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Start text selection on mouse down.

        Args:
            event: The mouse down event.
        """
        if event.button == 1:  # Left button
            # Convert screen coordinates to terminal coordinates
            col, row = self._screen_to_terminal(event.x, event.y)
            self._selection_start = (col, row)
            self._selection_end = (col, row)
            self._is_selecting = True
            self.capture_mouse()
            # Must use _update_display() to re-render with selection highlighting
            self._update_display()
            event.stop()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Update selection during drag.

        Args:
            event: The mouse move event.
        """
        if self._is_selecting:
            col, row = self._screen_to_terminal(event.x, event.y)
            # Only update if selection actually changed
            if self._selection_end != (col, row):
                self._selection_end = (col, row)
                # Must use _update_display() to re-render with selection highlighting
                self._update_display()
            event.stop()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """End selection and copy to clipboard.

        Args:
            event: The mouse up event.
        """
        if self._is_selecting and event.button == 1:
            self._is_selecting = False
            self.release_mouse()

            # Copy selected text to clipboard
            selected_text = self._get_selected_text()
            if selected_text and self.app:
                self.app.copy_to_clipboard(selected_text)
            event.stop()

    def on_key(self, event: events.Key) -> None:
        """Handle key events.

        Args:
            event: The key event.
        """
        if event.key == "escape" and self.has_selection:
            self._clear_selection()
            event.stop()

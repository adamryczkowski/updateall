"""TerminalView Textual widget for rendering terminal screen content.

This module provides a Textual widget that renders terminal screen content
from a TerminalScreen (pyte wrapper) with full ANSI color and styling support.

Phase 2 - Terminal Emulation
See docs/interactive-tabs-implementation-plan.md section 3.2.1

Enhanced with mouse wheel and arrow key scrolling support.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console, Group
from rich.style import Style
from rich.text import Text
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

    Example:
        view = TerminalView(columns=80, lines=24)
        view.feed(b"Hello, World!")
        # Widget will render the terminal content
    """

    # Reactive properties
    show_cursor: reactive[bool] = reactive(True)

    # CSS styling
    DEFAULT_CSS = """
    TerminalView {
        background: $surface;
        color: $text;
        min-height: 10;
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
        import logging

        logger = logging.getLogger("terminal_view")

        self._terminal_screen.feed(data)
        logger.debug(f"[{self.id}] feed() called with {len(data)} bytes, updating content")

        # Update the Static widget's content with the rendered terminal lines
        lines = self.render_terminal_lines()
        content = Group(*lines)
        self.update(content)
        logger.debug(f"[{self.id}] update() called, size={self.size}, region={self.region}")

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
        self.refresh()

    def scroll_history_down(self, lines: int = 1) -> None:
        """Scroll down in the history buffer.

        Args:
            lines: Number of lines to scroll.
        """
        self._terminal_screen.scroll_down(lines)
        self.refresh()

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom (current output)."""
        self._terminal_screen.scroll_to_bottom()
        self.refresh()

    def scroll_to_top(self) -> None:
        """Scroll to the top of history."""
        self._terminal_screen.scroll_to_top()
        self.refresh()

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

        for col, char in enumerate(styled_chars):
            # Build style from character attributes
            style = self._build_style(char)

            # Check if cursor is at this position
            if (
                self.cursor_visible
                and not self.is_scrolled_up
                and line_num == self._terminal_screen.cursor_y
                and col == self._terminal_screen.cursor_x
            ):
                # Invert colors for cursor
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

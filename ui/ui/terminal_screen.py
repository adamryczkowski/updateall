"""Terminal screen wrapper around pyte for terminal emulation.

This module provides a TerminalScreen class that wraps pyte's HistoryScreen
to provide terminal emulation with scrollback buffer support.

Phase 2 - Terminal Emulation
See docs/interactive-tabs-implementation-plan.md section 3.2.1
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

import pyte


@dataclass(frozen=True)
class StyledChar:
    """A styled character with text attributes.

    This is a simplified representation of pyte.screens.Char for external use.
    """

    data: str
    fg: str
    bg: str
    bold: bool = False
    italics: bool = False
    underscore: bool = False
    strikethrough: bool = False
    reverse: bool = False
    blink: bool = False


class TerminalScreen:
    """Terminal screen with pyte-based terminal emulation.

    This class provides:
    - Terminal screen buffer management via pyte
    - Scrollback buffer with configurable size
    - ANSI escape sequence parsing
    - Cursor position tracking
    - Dirty line tracking for efficient rendering

    Example:
        screen = TerminalScreen(columns=80, lines=24)
        screen.feed(b"Hello, World!")
        display = screen.display
        print(display[0])  # "Hello, World!..."
    """

    # Default scrollback buffer size (10,000 lines as per implementation plan)
    DEFAULT_SCROLLBACK_LINES = 10000

    def __init__(
        self,
        columns: int = 80,
        lines: int = 24,
        scrollback_lines: int | None = None,
    ) -> None:
        """Initialize a terminal screen.

        Args:
            columns: Terminal width in columns.
            lines: Terminal height in lines.
            scrollback_lines: Number of lines to keep in scrollback buffer.
                Defaults to 10,000 lines.
        """
        self._columns = columns
        self._lines = lines
        self._scrollback_lines = (
            scrollback_lines if scrollback_lines is not None else self.DEFAULT_SCROLLBACK_LINES
        )

        # Create pyte screen with history support
        self._screen = pyte.HistoryScreen(
            columns=columns,
            lines=lines,
            history=self._scrollback_lines,
            ratio=0.5,  # Scroll half a page at a time
        )

        # Create stream to parse input and dispatch to screen
        self._stream = pyte.Stream(self._screen)

        # Track scroll offset for viewing history
        self._scroll_offset = 0

        # Track dirty lines manually (pyte's dirty tracking resets on access)
        self._dirty_lines: set[int] = set()

    @property
    def columns(self) -> int:
        """Get the terminal width in columns."""
        return self._columns

    @property
    def lines(self) -> int:
        """Get the terminal height in lines."""
        return self._lines

    @property
    def scrollback_lines(self) -> int:
        """Get the scrollback buffer size in lines."""
        return self._scrollback_lines

    @property
    def cursor_x(self) -> int:
        """Get the cursor X position (column, 0-indexed)."""
        return self._screen.cursor.x

    @property
    def cursor_y(self) -> int:
        """Get the cursor Y position (row, 0-indexed)."""
        return self._screen.cursor.y

    @property
    def scroll_offset(self) -> int:
        """Get the current scroll offset (0 = at bottom/current)."""
        return self._scroll_offset

    @property
    def display(self) -> list[str]:
        """Get the current screen display as a list of strings.

        If scrolled up, returns historical content.
        Otherwise, returns the current screen content.
        """
        if self._scroll_offset > 0:
            return self._get_scrolled_display()
        return list(self._screen.display)

    def _get_scrolled_display(self) -> list[str]:
        """Get display content when scrolled up in history."""
        # Get history from top
        history_top = list(self._screen.history.top)
        history_bottom = list(self._screen.history.bottom)

        # Combine history with current screen
        all_lines: list[str] = []

        # Add top history (older lines)
        for line_dict in history_top:
            all_lines.append(self._line_dict_to_string(line_dict))

        # Add current screen lines
        all_lines.extend(self._screen.display)

        # Add bottom history (if any)
        for line_dict in history_bottom:
            all_lines.append(self._line_dict_to_string(line_dict))

        # Calculate which lines to show based on scroll offset
        total_lines = len(all_lines)
        if total_lines <= self._lines:
            return list(self._screen.display)

        # Calculate start position
        # scroll_offset is how many lines we've scrolled up from the bottom
        end_pos = total_lines - self._scroll_offset
        start_pos = max(0, end_pos - self._lines)

        return all_lines[start_pos:end_pos]

    def _line_dict_to_string(self, line_dict: dict[int, pyte.screens.Char]) -> str:
        """Convert a pyte line dictionary to a string."""
        if not line_dict:
            return " " * self._columns

        max_col = max(line_dict.keys()) if line_dict else 0
        chars = []
        for col in range(max(max_col + 1, self._columns)):
            if col in line_dict:
                chars.append(line_dict[col].data)
            else:
                chars.append(" ")
        return "".join(chars)

    def feed(self, data: bytes) -> None:
        """Feed data to the terminal screen.

        Args:
            data: Bytes to feed to the terminal (may contain ANSI escape sequences).
        """
        # Decode bytes to string, handling invalid sequences gracefully
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            # Fallback for any decoding issues
            text = data.decode("latin-1", errors="replace")

        # Track which lines were dirty before feeding
        old_dirty = set(self._screen.dirty)

        # Feed to pyte stream (ignore parsing errors for malformed sequences)
        with contextlib.suppress(Exception):
            self._stream.feed(text)

        # Update our dirty tracking
        self._dirty_lines.update(self._screen.dirty)
        self._dirty_lines.update(old_dirty)

        # If we're scrolled up and new content arrives, optionally scroll to bottom
        # (This is a policy decision - we keep the current position)

    def get_styled_line(self, line_number: int) -> list[StyledChar]:
        """Get a line with full styling information.

        If scrolled up, returns styled characters from the scrolled view.
        Otherwise, returns styled characters from the current screen buffer.

        Args:
            line_number: Line number (0-indexed) in the visible display.

        Returns:
            List of StyledChar objects for the line.
        """
        if line_number < 0 or line_number >= self._lines:
            return []

        # If scrolled up, we need to get the line from the scrolled view
        if self._scroll_offset > 0:
            return self._get_styled_line_scrolled(line_number)

        # Not scrolled - get from current buffer
        return self._get_styled_line_from_buffer(line_number)

    def _get_styled_line_from_buffer(self, line_number: int) -> list[StyledChar]:
        """Get styled line from the current screen buffer.

        Args:
            line_number: Line number (0-indexed).

        Returns:
            List of StyledChar objects for the line.
        """
        buffer_line = self._screen.buffer[line_number]
        styled_chars: list[StyledChar] = []

        for col in range(self._columns):
            if col in buffer_line:
                char = buffer_line[col]
                styled_chars.append(
                    StyledChar(
                        data=char.data,
                        fg=char.fg,
                        bg=char.bg,
                        bold=char.bold,
                        italics=char.italics,
                        underscore=char.underscore,
                        strikethrough=char.strikethrough,
                        reverse=char.reverse,
                        blink=char.blink,
                    )
                )
            else:
                # Empty cell
                styled_chars.append(
                    StyledChar(
                        data=" ",
                        fg="default",
                        bg="default",
                    )
                )

        return styled_chars

    def _get_styled_line_scrolled(self, line_number: int) -> list[StyledChar]:
        """Get styled line from the scrolled view (history + current).

        Args:
            line_number: Line number (0-indexed) in the visible display.

        Returns:
            List of StyledChar objects for the line.
        """
        # Build the complete line list (history + current screen)
        history_top = list(self._screen.history.top)
        history_bottom = list(self._screen.history.bottom)

        # Calculate which absolute line we need
        total_history_top = len(history_top)
        total_lines = total_history_top + self._lines + len(history_bottom)

        if total_lines <= self._lines:
            # Not enough content to scroll, return from buffer
            return self._get_styled_line_from_buffer(line_number)

        # Calculate the absolute line index based on scroll offset
        # scroll_offset is how many lines we've scrolled up from the bottom
        end_pos = total_lines - self._scroll_offset
        start_pos = max(0, end_pos - self._lines)
        absolute_line = start_pos + line_number

        # Determine which source the line comes from
        if absolute_line < total_history_top:
            # Line is from top history
            line_dict = history_top[absolute_line]
            return self._styled_chars_from_line_dict(line_dict)
        elif absolute_line < total_history_top + self._lines:
            # Line is from current screen buffer
            buffer_line_num = absolute_line - total_history_top
            return self._get_styled_line_from_buffer(buffer_line_num)
        else:
            # Line is from bottom history
            bottom_index = absolute_line - total_history_top - self._lines
            if bottom_index < len(history_bottom):
                line_dict = history_bottom[bottom_index]
                return self._styled_chars_from_line_dict(line_dict)
            else:
                # Out of range, return empty line
                return [
                    StyledChar(data=" ", fg="default", bg="default") for _ in range(self._columns)
                ]

    def _styled_chars_from_line_dict(
        self, line_dict: dict[int, pyte.screens.Char]
    ) -> list[StyledChar]:
        """Convert a pyte line dictionary to a list of StyledChar.

        Args:
            line_dict: Dictionary mapping column index to pyte Char.

        Returns:
            List of StyledChar objects for the line.
        """
        styled_chars: list[StyledChar] = []

        for col in range(self._columns):
            if col in line_dict:
                char = line_dict[col]
                styled_chars.append(
                    StyledChar(
                        data=char.data,
                        fg=char.fg,
                        bg=char.bg,
                        bold=char.bold,
                        italics=char.italics,
                        underscore=char.underscore,
                        strikethrough=char.strikethrough,
                        reverse=char.reverse,
                        blink=char.blink,
                    )
                )
            else:
                # Empty cell
                styled_chars.append(
                    StyledChar(
                        data=" ",
                        fg="default",
                        bg="default",
                    )
                )

        return styled_chars

    def get_history(self) -> list[str]:
        """Get the scrollback history as a list of strings.

        Returns:
            List of historical lines (oldest first).
        """
        history_lines: list[str] = []

        # Get top history (lines that scrolled off the top)
        for line_dict in self._screen.history.top:
            history_lines.append(self._line_dict_to_string(line_dict))

        return history_lines

    def scroll_up(self, lines: int = 1) -> None:
        """Scroll up in the history buffer.

        Args:
            lines: Number of lines to scroll up.
        """
        max_scroll = len(list(self._screen.history.top))
        self._scroll_offset = min(self._scroll_offset + lines, max_scroll)

    def scroll_down(self, lines: int = 1) -> None:
        """Scroll down in the history buffer.

        Args:
            lines: Number of lines to scroll down.
        """
        self._scroll_offset = max(0, self._scroll_offset - lines)

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom (current output)."""
        self._scroll_offset = 0

    def scroll_to_top(self) -> None:
        """Scroll to the top of history."""
        self._scroll_offset = len(list(self._screen.history.top))

    def resize(self, columns: int, lines: int) -> None:
        """Resize the terminal screen.

        Args:
            columns: New terminal width in columns.
            lines: New terminal height in lines.
        """
        self._columns = columns
        self._lines = lines
        self._screen.resize(lines=lines, columns=columns)
        # Mark all lines as dirty after resize
        self._dirty_lines = set(range(lines))

    def reset(self) -> None:
        """Reset the terminal to its initial state.

        This clears the screen, scrollback buffer, and resets cursor position.
        """
        self._screen.reset()
        # Clear history manually
        self._screen.history.top.clear()
        self._screen.history.bottom.clear()
        self._scroll_offset = 0
        self._dirty_lines = set(range(self._lines))

    def get_dirty_lines(self) -> set[int]:
        """Get the set of dirty line numbers.

        Returns:
            Set of line numbers that have changed since last clear.
        """
        # Combine our tracking with pyte's current dirty set
        return self._dirty_lines | set(self._screen.dirty)

    def clear_dirty(self) -> None:
        """Clear the dirty line tracking."""
        self._dirty_lines.clear()
        self._screen.dirty.clear()

    def get_cursor_visible(self) -> bool:
        """Check if the cursor should be visible.

        Returns:
            True if cursor is visible, False otherwise.
        """
        # pyte tracks cursor visibility via mode
        return not self._screen.cursor.hidden if hasattr(self._screen.cursor, "hidden") else True

    def get_buffer(self) -> Any:
        """Get the raw screen buffer.

        Returns:
            The pyte screen buffer (lines x columns sparse matrix of Char).
        """
        return self._screen.buffer

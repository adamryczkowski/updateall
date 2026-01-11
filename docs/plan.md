# Text Selection Implementation Plan for TerminalView

## Executive Summary

This document describes the implementation plan for enabling drag-select text copying in the `TerminalView` widget. The feature will allow users to select text with the mouse and copy it to the clipboard using Ctrl+C.

**Date**: 2026-01-11
**Status**: Planning
**Estimated Effort**: 2-4 hours

---

## 1. Problem Statement

The `TerminalView` widget currently has `ALLOW_SELECT = True` and implements `get_selection()` and `selection_updated()` methods, but text selection does not work. Users cannot drag-select text in the terminal view.

### Root Cause

The widget is missing the critical step that enables Textual's selection system to determine text positions: the `strip.apply_offsets(x, y)` call in the `render_line()` method.

Without offset metadata embedded in rendered segments, the compositor's `get_widget_and_offset_at()` method returns `None` for the offset, which prevents the selection system from tracking mouse positions within the text.

---

## 2. Performance Considerations

### ⚠️ CRITICAL: UI Latency Concerns

The UI is already described as having "borderline disastrous" latency. Any implementation must minimize additional overhead.

### Current Rendering Overhead

The current `TerminalView` rendering is already expensive:

| Operation | Per-Render Cost |
|-----------|-----------------|
| `render_terminal_lines()` | Iterates 24+ lines |
| `_render_styled_line()` | Iterates 80+ chars per line |
| `_build_style()` | Creates 1 Style object per char |
| **Total Style objects** | **~1,920 per render** |

### Standard Approach: `apply_offsets()` - **NOT RECOMMENDED**

The standard Textual approach (`strip.apply_offsets()`) would add significant overhead:

```python
# From strip.py:791-816
def apply_offsets(self, x: int, y: int) -> Strip:
    for segment in segments:
        offset_style = Style.from_meta({"offset": (x, y)})  # New Style
        Segment(text, style + offset_style if style else offset_style)  # Another new Style
```

**Impact**: Roughly **doubles Style object creation** - creating ~3,840 Style objects per render instead of ~1,920.

### Recommended Approach: Direct Coordinate Mapping

Instead of embedding offset metadata in every render, implement **direct coordinate mapping** that bypasses Textual's selection system:

1. **No per-render overhead** - don't call `apply_offsets()`
2. **Handle mouse events directly** - map screen coordinates to terminal positions
3. **Custom selection tracking** - maintain selection state internally
4. **On-demand highlighting** - only modify rendering when selection is active

---

## 3. Technical Background

### 3.1 How Textual Text Selection Works (Standard Approach)

Textual's text selection system operates through the following flow:

1. **Mouse Events** (`screen.py:1703-1724`): When the user clicks and drags, the Screen captures mouse events and calls `get_widget_and_offset_at()` to determine which widget and text position is under the cursor.

2. **Offset Detection** (`_compositor.py:900-965`): The compositor examines rendered segments for `{"offset": (x, y)}` metadata in the segment styles. This metadata maps screen positions to text positions.

3. **Selection Tracking** (`screen.py:246-260`): The Screen maintains a `selections: dict[Widget, Selection]` reactive variable that tracks which widgets have active selections.

4. **Visual Highlighting**: When `selections` changes, the Screen calls `widget.selection_updated()` which should trigger a re-render with selection highlighting.

5. **Copy to Clipboard** (`screen.py:954-960`): When Ctrl+C is pressed, `action_copy_text()` calls `get_selected_text()` which iterates through selected widgets and calls `widget.get_selection()` to extract text.

### 3.2 Why Standard Approach Is Problematic for TerminalView

The standard approach requires `strip.apply_offsets()` on every render, which:
- Creates 2 new Style objects per segment
- Iterates through all segments twice (once for rendering, once for offsets)
- Has no benefit when selection is not active (99% of the time)

---

## 4. Implementation Plan: Performance-Optimized Approach

### 4.1 Strategy: Custom Mouse-Based Selection

Instead of using Textual's built-in selection system, implement a custom selection mechanism that:

1. **Handles mouse events directly** in `TerminalView`
2. **Maps screen coordinates to terminal positions** without offset metadata
3. **Tracks selection state internally** with minimal overhead
4. **Only modifies rendering when selection is active**

### 4.2 Files to Modify

| File | Changes |
|------|---------|
| `ui/ui/terminal_view.py` | Add mouse event handlers and selection logic |
| `ui/tests/test_terminal_view.py` | Unit tests for selection |

### 4.3 Implementation Steps

#### Step 1: Add Selection State Variables

```python
class TerminalView(Static):
    # ... existing code ...

    # Selection state (internal, not using Textual's selection system)
    _selection_start: tuple[int, int] | None = None  # (col, row)
    _selection_end: tuple[int, int] | None = None    # (col, row)
    _is_selecting: bool = False
```

#### Step 2: Add Mouse Event Handlers

```python
def on_mouse_down(self, event: events.MouseDown) -> None:
    """Start text selection on mouse down."""
    if event.button == 1:  # Left button
        # Convert screen coordinates to terminal coordinates
        col, row = self._screen_to_terminal(event.x, event.y)
        self._selection_start = (col, row)
        self._selection_end = (col, row)
        self._is_selecting = True
        self.capture_mouse()
        event.stop()

def on_mouse_move(self, event: events.MouseMove) -> None:
    """Update selection during drag."""
    if self._is_selecting:
        col, row = self._screen_to_terminal(event.x, event.y)
        self._selection_end = (col, row)
        self._update_display()  # Only re-render during active selection
        event.stop()

def on_mouse_up(self, event: events.MouseUp) -> None:
    """End selection and copy to clipboard."""
    if self._is_selecting and event.button == 1:
        self._is_selecting = False
        self.release_mouse()

        # Copy selected text to clipboard
        selected_text = self._get_selected_text()
        if selected_text:
            self.app.copy_to_clipboard(selected_text)
        event.stop()

def _screen_to_terminal(self, x: int, y: int) -> tuple[int, int]:
    """Convert screen coordinates to terminal (col, row).

    This is a direct calculation - no offset metadata needed.
    """
    # Account for widget position and borders
    col = max(0, min(x, self._terminal_screen.columns - 1))
    row = max(0, min(y, self._terminal_screen.lines - 1))
    return col, row
```

#### Step 3: Modify Rendering for Selection Highlighting

Only apply selection highlighting when there's an active selection:

```python
def _render_styled_line(self, styled_chars: list[StyledChar], line_num: int) -> Text:
    """Render a line of styled characters as Rich Text."""
    text = Text()

    # Get selection range for this line (only if selecting)
    select_start_col, select_end_col = self._get_line_selection(line_num)

    for col, char in enumerate(styled_chars):
        style = self._build_style(char)

        # Cursor highlighting
        if (
            self.cursor_visible
            and not self.is_scrolled_up
            and line_num == self._terminal_screen.cursor_y
            and col == self._terminal_screen.cursor_x
        ):
            style = style + Style(reverse=True)

        # Selection highlighting (only when active)
        if select_start_col is not None and select_start_col <= col < select_end_col:
            style = style + Style(reverse=True)  # Simple reverse for selection

        text.append(char.data, style=style)

    return text

def _get_line_selection(self, line_num: int) -> tuple[int | None, int | None]:
    """Get the selection range for a specific line.

    Returns (start_col, end_col) or (None, None) if line not selected.
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
```

#### Step 4: Extract Selected Text

```python
def _get_selected_text(self) -> str:
    """Extract the selected text from the terminal."""
    if self._selection_start is None or self._selection_end is None:
        return ""

    start_col, start_row = self._selection_start
    end_col, end_row = self._selection_end

    # Normalize
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
```

#### Step 5: Clear Selection on Escape or Click Outside

```python
def on_key(self, event: events.Key) -> None:
    """Handle key events."""
    if event.key == "escape" and self._selection_start is not None:
        self._clear_selection()
        event.stop()

def _clear_selection(self) -> None:
    """Clear the current selection."""
    if self._selection_start is not None:
        self._selection_start = None
        self._selection_end = None
        self._update_display()
```

### 4.4 Performance Comparison

| Aspect | Standard Approach | Custom Approach |
|--------|-------------------|-----------------|
| Per-render overhead | +~1,920 Style objects | 0 (when not selecting) |
| During selection | Same | +1 Style per selected char |
| Memory | Higher (offset metadata) | Lower |
| Complexity | Lower | Higher |
| Textual integration | Full | Partial (custom clipboard) |

### 4.5 Testing Plan

```python
# ui/tests/test_terminal_view_selection.py

import pytest
from ui.terminal_view import TerminalView


class TestTerminalViewSelection:
    """Tests for TerminalView text selection support."""

    def test_screen_to_terminal_conversion(self):
        """Verify coordinate conversion works correctly."""
        view = TerminalView(columns=80, lines=24)

        assert view._screen_to_terminal(0, 0) == (0, 0)
        assert view._screen_to_terminal(79, 23) == (79, 23)
        assert view._screen_to_terminal(100, 30) == (79, 23)  # Clamped

    def test_get_line_selection_single_line(self):
        """Test selection within a single line."""
        view = TerminalView()
        view._selection_start = (5, 0)
        view._selection_end = (10, 0)

        assert view._get_line_selection(0) == (5, 10)
        assert view._get_line_selection(1) == (None, None)

    def test_get_line_selection_multi_line(self):
        """Test selection spanning multiple lines."""
        view = TerminalView(columns=80, lines=24)
        view._selection_start = (5, 1)
        view._selection_end = (10, 3)

        assert view._get_line_selection(0) == (None, None)
        assert view._get_line_selection(1) == (5, 80)
        assert view._get_line_selection(2) == (0, 80)
        assert view._get_line_selection(3) == (0, 10)
        assert view._get_line_selection(4) == (None, None)

    def test_get_selected_text(self):
        """Test text extraction from selection."""
        view = TerminalView()
        view.feed(b"Hello, World!\nSecond line")
        view._selection_start = (7, 0)
        view._selection_end = (12, 0)

        assert view._get_selected_text() == "World"

    def test_clear_selection(self):
        """Test selection clearing."""
        view = TerminalView()
        view._selection_start = (0, 0)
        view._selection_end = (10, 0)

        view._clear_selection()

        assert view._selection_start is None
        assert view._selection_end is None
```

---

## 5. Dependencies

### 5.1 Textual Version

The project uses `textual>=7.0.0,<8.0.0`. The custom approach does not rely on Textual's selection API, only on:
- `app.copy_to_clipboard()` for clipboard access
- Mouse event handling (standard Textual feature)

### 5.2 Required Imports

```python
from textual import events
from rich.style import Style
```

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ~~Performance impact from offset metadata~~ | N/A | N/A | Custom approach avoids this entirely |
| Selection highlighting conflicts with cursor | Medium | Low | Cursor style applied after selection style |
| Scrollback buffer selection | Medium | Medium | Account for scroll offset in coordinate conversion |
| Terminal resize during selection | Low | Low | Clear selection on resize |
| Mouse capture conflicts | Medium | Medium | Properly release mouse on selection end |
| Coordinate calculation errors | Medium | High | Thorough testing of edge cases |

---

## 7. Alternative Approaches Considered

### 7.1 Standard Textual Selection (Rejected)

**Approach**: Use `strip.apply_offsets()` as the Log widget does.

**Why Rejected**:
- Adds ~1,920 extra Style object creations per render
- UI latency is already problematic
- Overhead occurs even when selection is not active

### 7.2 Lazy Offset Application (Considered)

**Approach**: Only call `apply_offsets()` when selection is active.

**Why Not Chosen**:
- Still requires Textual's selection system to initiate
- Textual calls `get_widget_and_offset_at()` on mouse down, before we know if user will select
- Would need to re-render immediately after mouse down

### 7.3 Custom Selection (Chosen)

**Approach**: Bypass Textual's selection system entirely with custom mouse handling.

**Why Chosen**:
- Zero overhead when not selecting
- Full control over performance characteristics
- Direct coordinate mapping is simpler than offset metadata

---

## 8. Future Enhancements

1. **Auto-copy on selection end**: ✅ Already included in the plan
2. **Box selection**: Support Shift+drag for rectangular selection
3. **Double-click word selection**: Select entire word on double-click
4. **Triple-click line selection**: Select entire line on triple-click
5. **Selection persistence**: Keep selection visible after mouse release
6. **Keyboard-based selection**: Shift+arrow keys for selection

---

## 9. References

### Source Files Analyzed

| File | Description |
|------|-------------|
| `ref/textual/src/textual/widgets/_log.py` | Working text selection example (standard approach) |
| `ref/textual/src/textual/strip.py:791-816` | `apply_offsets()` implementation (performance analysis) |
| `ref/textual/src/textual/_compositor.py:900-965` | Offset metadata reading |
| `ref/textual/src/textual/screen.py:1703-1724` | Mouse selection handling |
| `ref/textual/src/textual/screen.py:954-960` | Copy to clipboard action |
| `ref/textual/src/textual/widget.py:680-683` | `text_selection` property |
| `ref/textual/src/textual/selection.py` | Selection data structure |
| `ui/ui/terminal_view.py` | Current TerminalView implementation |

### Documentation

- Textual Documentation: https://textual.textualize.io/
- Rich Text Documentation: https://rich.readthedocs.io/

---

## 10. Approval

- [ ] Technical review completed
- [ ] Performance impact verified acceptable
- [ ] Implementation approved
- [ ] Test plan approved

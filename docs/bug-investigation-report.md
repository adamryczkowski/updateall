# Bug Investigation Report: Interactive Tabbed UI Issues

**Date:** January 10, 2026
**Author:** Claude (AI Assistant)
**Status:** UNRESOLVED - Architectural Analysis Required

## Executive Summary

After 6+ attempts to fix three related bugs in the interactive tabbed UI, all fixes have failed to resolve the issues. This document analyzes why the fixes didn't work and identifies potential architectural problems that may require a more fundamental redesign.

---

## Issue 1: CPU Statistics Reset to Zero

### Symptom
CPU counters in the status bar reset to zero after each action (e.g., after "Checking repository..." completes).

### Attempted Fixes (All Failed)

1. **Added `_collect_process_tree_metrics()` method** to aggregate CPU time from child processes using `process.children(recursive=True)`.
   - **Why it failed:** The method correctly collects from child processes, but when those processes exit, their CPU time is lost because `psutil.Process.cpu_times()` only returns data for running processes.

2. **Added `_max_cpu_time_seen` tracking** to remember the maximum CPU time ever observed.
   - **Why it failed:** The fix was applied but the symptom persists, suggesting the issue is elsewhere.

### Root Cause Analysis

The fundamental problem is that **we're monitoring the wrong PID**. Looking at the code flow:

1. In [`terminal_pane.py:468-471`](../ui/ui/terminal_pane.py:468), the `MetricsCollector` is created with `pid=session.pid`
2. `session.pid` is the PID of the PTY shell process (e.g., `/bin/bash`)
3. The shell spawns child processes to do actual work
4. When child processes exit, their CPU time is gone

**But the deeper issue is:** Even with `_max_cpu_time_seen`, the CPU time still resets. This suggests:

1. **The `MetricsCollector` might be recreated** for each phase, resetting `_max_cpu_time_seen`
2. **The display might be reading from a different source** than where we're storing the max value
3. **There might be multiple `MetricsCollector` instances** that aren't sharing state

### Architectural Problems Identified

1. **Metrics Collection is Tied to PTY Session Lifecycle**
   - Each phase may create a new PTY session with a new PID
   - This creates a new `MetricsCollector` instance
   - All accumulated metrics are lost

2. **No Persistent Metrics Accumulator**
   - There's no central place that accumulates metrics across phase transitions
   - Each phase starts fresh

3. **Phase Stats vs. Metrics Collector Disconnect**
   - `PhaseStats` in `phase_status_bar.py` tracks per-phase statistics
   - But the display reads from `MetricsCollector.collect()` which returns current process tree metrics
   - These two sources can be out of sync

---

## Issue 2: Phase Counters Reset When Transitioning

### Symptom
When transitioning from one phase (e.g., CHECK) to another (e.g., DOWNLOAD), the counters for the previous phase reset.

### Attempted Fixes (All Failed)

1. **Added `is_complete` check** in `update_phase_stats()` to prevent updating completed phases.
   - **Why it failed:** The check exists at line 340, but the reset still happens.

2. **Relied on `_max_cpu_time_seen`** to preserve CPU time across phase transitions.
   - **Why it failed:** Same reasons as Issue 1.

### Root Cause Analysis

Looking at the phase transition flow:

1. [`interactive_tabbed_run.py:921-935`](../ui/ui/interactive_tabbed_run.py:921) - When a phase completes:
   ```python
   self._phase_controller.complete_phase_sync(plugin_name, current_phase, success=True)
   pane.metrics_collector.complete_phase(phase_name)
   ```

2. [`interactive_tabbed_run.py:768-786`](../ui/ui/interactive_tabbed_run.py:768) - When starting a new phase:
   ```python
   self._phase_controller.start_phase_sync(plugin_name, current_phase)
   pane.metrics_collector.start_phase(phase_name)
   ```

3. In `start_phase()` at [`phase_status_bar.py:276-289`](../ui/ui/phase_status_bar.py:276):
   ```python
   self._phase_start_cpu_time = self._metrics.cpu_time_seconds
   ```

**The problem:** When `start_phase()` is called, `self._metrics.cpu_time_seconds` may already be reset (due to Issue 1), so the new phase starts with a baseline of 0 instead of the accumulated value.

### Architectural Problems Identified

1. **Circular Dependency Between Issues 1 and 2**
   - Issue 2 depends on Issue 1 being fixed first
   - The phase delta calculation uses `self._metrics.cpu_time_seconds` which is affected by Issue 1

2. **Phase State is Fragile**
   - Phase completion and start are separate operations
   - If anything goes wrong between them, state is lost

3. **No Snapshot/Checkpoint Mechanism**
   - When a phase completes, we should snapshot its final metrics
   - Currently, we rely on the metrics collector to preserve them, but it doesn't

---

## Issue 3: Scrolling Not Working

### Symptom
Mouse wheel scrolling, arrow keys, PageUp/PageDown don't scroll the terminal content.

### Attempted Fixes (All Failed)

1. **Added mouse scroll handlers to `TerminalPane`** at lines 784-808.
   - **Why it failed:** The handlers exist but events don't reach them.

2. **Added mouse scroll handlers to `TerminalView`** at lines 395-417.
   - **Why it failed:** Same issue - events don't reach the handlers.

3. **Added `can_focus = True`** to `TerminalView`.
   - **Why it failed:** Focus alone doesn't guarantee mouse event delivery.

4. **Modified `on_key()` in `InteractiveTabbedApp`** to directly call scroll actions.
   - **Why it failed:** The scroll actions are called, but the terminal doesn't scroll.

### Root Cause Analysis

The scrolling architecture has multiple layers:

1. **Event Flow:**
   ```
   User Input → Textual App → on_key() → scroll_key_actions → action_scroll_*() →
   active_pane.scroll_history_up() → terminal_view.scroll_history_up() →
   terminal_screen.scroll_up() → refresh()
   ```

2. **Looking at `scroll_history_up()` in `terminal_view.py:229-236`:**
   ```python
   def scroll_history_up(self, lines: int = 1) -> None:
       self._terminal_screen.scroll_up(lines)
       self.refresh()
   ```

3. **Looking at `TerminalScreen.scroll_up()` in `terminal_screen.py`:**
   - This should modify `scroll_offset`
   - But does `refresh()` actually re-render with the new offset?

**Potential issues:**

1. **`refresh()` might not trigger re-render** - In Textual, `refresh()` marks the widget as needing a repaint, but the actual rendering might not use the updated `scroll_offset`.

2. **The `render()` method might not respect `scroll_offset`** - Looking at `terminal_view.py:265-275`, `render()` just calls `super().render()` which uses the content set by `update()`. But `update()` is only called in `feed()`, not in `scroll_history_up()`.

3. **Content is set by `update()`, not by `render()`** - The terminal content is set via `self.update(content)` in `feed()`. When we scroll, we call `refresh()` but don't call `update()` with new content.

### Architectural Problems Identified

1. **Rendering Model Mismatch**
   - `TerminalView` extends `Static`, which uses `update()` to set content
   - Scrolling changes `scroll_offset` but doesn't update the content
   - `refresh()` repaints the same content, not the scrolled view

2. **`scroll_offset` is Not Used in Rendering**
   - `render_terminal_lines()` at line 277 iterates `range(self._terminal_screen.lines)`
   - It doesn't account for `scroll_offset`
   - The scrollback buffer exists but isn't being displayed

3. **Mouse Events May Not Bubble Correctly**
   - Textual's event bubbling depends on widget hierarchy
   - `TerminalView` is inside `TerminalPane` which is inside `TabPane`
   - Events might be captured by parent containers

---

## Architectural Recommendations

### For Issues 1 & 2 (Metrics/Phase Counters)

1. **Create a Persistent Metrics Store**
   - Separate from `MetricsCollector` which is tied to PTY sessions
   - Accumulates metrics across phase transitions
   - Survives PTY session restarts

2. **Snapshot Metrics on Phase Completion**
   - When a phase completes, save a snapshot of its final metrics
   - Don't rely on the live metrics collector for historical data

3. **Use Wall Clock Time for CPU Estimation**
   - Instead of trying to track child process CPU time (which is lost when they exit)
   - Estimate CPU time based on wall clock time and CPU percentage samples

### For Issue 3 (Scrolling)

1. **Fix the Rendering Model**
   - `scroll_history_up/down` should call `update()` with the scrolled content
   - Or override `render()` to use `scroll_offset` when generating content

2. **Verify Event Delivery**
   - Add logging to mouse scroll handlers to confirm events are received
   - Check if `can_focus` is sufficient or if other properties are needed

3. **Consider Using ScrollableContainer**
   - Instead of implementing custom scrolling on `Static`
   - Wrap `TerminalView` in a `ScrollableContainer`
   - Let Textual handle scroll events natively

---

## Why Tests Pass But Bugs Persist

The existing tests verify:
- Methods exist and can be called
- Data structures are updated correctly
- No exceptions are thrown

But they don't verify:
- Visual output matches expected state
- Events are delivered correctly in a running app
- Metrics persist across phase transitions in real usage

**Recommendation:** Add end-to-end tests that:
1. Run the actual app with mock plugins
2. Simulate user interactions (scroll, phase transitions)
3. Verify the visual output matches expectations

---

## Conclusion

The three bugs are interconnected and stem from architectural issues:

1. **Metrics are tied to ephemeral PTY sessions** instead of being accumulated persistently
2. **Phase transitions don't properly snapshot and preserve metrics**
3. **Scrolling implementation doesn't update the rendered content**

Fixing these issues requires:
1. Redesigning the metrics collection architecture
2. Adding proper state management for phase transitions
3. Fixing the rendering model for scrolling

The current approach of patching individual methods hasn't worked because the problems are architectural, not implementational.

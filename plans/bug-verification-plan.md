# Bug Verification Plan

## Overview

This document outlines the plan to create proper E2E tests that demonstrate the bugs in the actual running Textual GUI, rather than just testing that methods don't crash.

## Current State

The existing tests in `ui/tests/test_e2e_interactive_tabs.py` use `app.run_test()` to run the Textual app in a test environment. However, these tests have a critical flaw: **they only verify that methods don't crash, not that they work correctly**.

For example:
- `TestE2EScrollback.test_scroll_up_and_down` just calls scroll actions and checks for no crash
- `TestE2EPhaseStatusBar.test_status_bar_displays_metrics` just waits and checks for no crash
- None of the tests verify that **statistics are actually preserved** or that **scrolling actually changes visible content**

## Bugs to Verify

### Bug 1 & 2: Statistics Zeroed After Each Phase

**Symptom:** When a phase completes and a new phase starts, the previous phase's statistics (CPU time, wall time, data bytes) are reset to zero.

**Suspected Root Causes:**
1. `MetricsCollector` may be recreated for each phase with a new PID
2. Phase transitions may not properly preserve completed phase stats
3. The `is_complete` check in `update_phase_stats()` may not be working as expected

**Verification Approach:**
1. Create a plugin that runs a CPU-intensive task
2. Start the "Update" phase and collect metrics
3. Complete the "Update" phase
4. Start the "Download" phase
5. **Assert that Update phase stats are NOT zero**

### Bug 3: Scrolling Doesn't Work

**Symptom:** Mouse wheel scrolling and keyboard navigation (PageUp/PageDown, arrow keys) don't change the visible content in the terminal tab.

**Suspected Root Causes:**
1. `scroll_history_up/down()` may call `refresh()` instead of `update()` - FIXED in recent changes
2. `get_styled_line()` may not respect `scroll_offset` - FIXED in recent changes
3. Mouse/keyboard events may not reach the terminal view widget
4. The rendered content may not actually change despite scroll offset changing

**Verification Approach:**
1. Create a plugin that produces lots of output (100+ lines)
2. Wait for output to be captured
3. Get the visible content before scrolling
4. Scroll up
5. Get the visible content after scrolling
6. **Assert that the content is DIFFERENT**

## POC Script Design

Create `scripts/poc_bug_verification.py` that:

```python
async def test_statistics_preserved_across_phases():
    """
    1. Create plugin with CPU-intensive task
    2. Start plugin and wait for processing
    3. Get MetricsCollector from pane
    4. Start "Update" phase
    5. Collect metrics during phase
    6. Complete "Update" phase
    7. Start "Download" phase
    8. Collect metrics during new phase
    9. ASSERT: Update phase stats are NOT zero
    """
    pass

async def test_scrolling_changes_content():
    """
    1. Create plugin that produces 100+ lines of output
    2. Start plugin and wait for output
    3. Get terminal_display content BEFORE scrolling
    4. Call scroll_history_up(10)
    5. Get terminal_display content AFTER scrolling
    6. ASSERT: Content is DIFFERENT
    7. ASSERT: scroll_offset changed
    """
    pass

async def test_keyboard_scroll_keys():
    """
    1. Create plugin that produces 100+ lines of output
    2. Start plugin and wait for output
    3. Get scroll_offset BEFORE
    4. Press PageUp key via pilot
    5. Get scroll_offset AFTER
    6. ASSERT: scroll_offset changed
    7. ASSERT: Content changed
    """
    pass
```

## Implementation Steps

1. **Switch to Code mode** to create the POC script
2. **Run the POC script** to verify current bug status
3. **Analyze results** to understand actual root causes
4. **Fix the bugs** based on actual evidence
5. **Re-run POC** to verify fixes work

## Key Insights from Code Analysis

### MetricsCollector Lifecycle

From `ui/ui/terminal_pane.py`:
- `MetricsCollector` is created in `_start_session()` with the PTY session's PID
- It's stored in `self._metrics_collector`
- The same instance should persist across phases

From `ui/ui/phase_status_bar.py`:
- `_phase_stats` is a dict with "Update", "Download", "Upgrade" keys
- `complete_phase()` sets `is_complete = True`
- `update_phase_stats()` checks `if stats.is_complete and not force: return`
- This SHOULD prevent completed phases from being overwritten

### Scrolling Implementation

From `ui/ui/terminal_view.py`:
- `scroll_history_up()` now calls `_update_display()` which calls `update()`
- `render_terminal_lines()` calls `get_styled_line()` for each line

From `ui/ui/terminal_screen.py`:
- `get_styled_line()` now checks `if self._scroll_offset > 0` and calls `_get_styled_line_scrolled()`
- `_get_styled_line_scrolled()` calculates the correct line from history

### Potential Issues

1. **MetricsCollector recreation**: If the pane is stopped and restarted for a new phase, a new `MetricsCollector` may be created, losing all previous stats.

2. **Phase stats not linked to display**: The `PhaseStatusBar._refresh_display()` reads from `self._metrics_collector.phase_stats`, but if the collector is recreated, the stats are lost.

3. **Scrolling content not updating**: Even though `_update_display()` is called, the `render_terminal_lines()` method may not be producing different content if `get_styled_line()` is still reading from the wrong source.

## Next Steps

1. Create the POC script in Code mode
2. Run it to get actual evidence of bug behavior
3. Add debug logging to trace the actual data flow
4. Fix based on evidence, not assumptions

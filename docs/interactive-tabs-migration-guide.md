# Interactive Tabs Migration Guide

**Date:** January 6, 2026
**Version:** 1.0
**Status:** Final

---

## Overview

This guide helps you migrate from the legacy `TabbedRunApp` (streaming mode) to the new `InteractiveTabbedApp` (PTY-based interactive mode).

The new interactive mode provides:
- Full terminal emulation with ANSI escape sequence support
- Interactive input handling (sudo prompts, confirmations, etc.)
- Independent scrollback buffer per tab
- Configurable keyboard shortcuts
- Better support for progress bars and cursor-based output

---

## Quick Migration

### Before (Legacy Streaming Mode)

```python
from ui.tabbed_run import run_with_tabbed_ui

await run_with_tabbed_ui(
    plugins=plugins,
    configs=configs,
    dry_run=False,
    use_streaming=True,
)
```

### After (Interactive Mode)

```python
from ui.interactive_tabbed_run import run_with_interactive_tabbed_ui

await run_with_interactive_tabbed_ui(
    plugins=plugins,
    configs=configs,
    dry_run=False,
)
```

---

## API Changes

### Function Signature Changes

| Legacy API | New API |
|------------|---------|
| `run_with_tabbed_ui(plugins, configs, dry_run, use_streaming)` | `run_with_interactive_tabbed_ui(plugins, configs, dry_run, key_bindings)` |
| `TabbedRunApp(plugins, configs, dry_run, use_streaming)` | `InteractiveTabbedApp(plugins, configs, dry_run, key_bindings, auto_start)` |

### New Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `key_bindings` | `KeyBindings` | Custom keyboard shortcuts |
| `auto_start` | `bool` | Whether to start plugins automatically (default: `True`) |

### Removed Parameters

| Parameter | Replacement |
|-----------|-------------|
| `use_streaming` | Always uses PTY streaming in interactive mode |

---

## Plugin Interface Changes

### New Plugin Methods

Plugins should implement these methods for full interactive support:

```python
class MyPlugin(UpdatePlugin):
    @property
    def supports_interactive(self) -> bool:
        """Return True to enable interactive mode for this plugin.

        Default implementation returns False for backward compatibility.
        """
        return True

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Return the command to run in the PTY.

        Args:
            dry_run: Whether to run in dry-run mode.

        Returns:
            Command and arguments as a list.

        Raises:
            NotImplementedError: If interactive mode is not supported.
        """
        if dry_run:
            return ["/usr/bin/apt", "update", "--dry-run"]
        return ["/usr/bin/apt", "update"]
```

### Backward Compatibility

Plugins that don't implement `get_interactive_command()` will use a fallback:

```python
# Fallback command (placeholder)
["/bin/bash", "-c", f"echo 'Running {plugin.name}...' && sleep 2 && echo 'Done'"]
```

---

## Keyboard Shortcut Changes

### Navigation Keys

| Legacy | Interactive | Action |
|--------|-------------|--------|
| `←` (Left Arrow) | `Ctrl+Shift+Tab` | Previous tab |
| `→` (Right Arrow) | `Ctrl+Tab` | Next tab |
| `q` | `Ctrl+Q` | Quit |
| N/A | `Alt+1` to `Alt+9` | Direct tab access |

### Scrolling Keys

| Legacy | Interactive | Action |
|--------|-------------|--------|
| Mouse scroll | `Shift+PageUp` | Scroll up |
| Mouse scroll | `Shift+PageDown` | Scroll down |
| N/A | `Shift+Home` | Scroll to top |
| N/A | `Shift+End` | Scroll to bottom |

### Why the Change?

In interactive mode, arrow keys need to be sent to the PTY for command-line editing (e.g., bash history navigation). Therefore, tab navigation uses modifier keys that are less likely to conflict with terminal applications.

---

## State Management Changes

### Legacy States

```python
class PluginState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
```

### Interactive States

```python
class PaneState(str, Enum):
    IDLE = "idle"       # Not started
    RUNNING = "running" # PTY process running
    SUCCESS = "success" # Exit code 0
    FAILED = "failed"   # Non-zero exit code
    EXITED = "exited"   # Process exited (unknown status)
```

### State Mapping

| Legacy State | Interactive State |
|--------------|-------------------|
| `PENDING` | `IDLE` |
| `RUNNING` | `RUNNING` |
| `SUCCESS` | `SUCCESS` |
| `FAILED` | `FAILED` |
| `SKIPPED` | `EXITED` (with error message) |
| `TIMEOUT` | `FAILED` (with timeout error) |

---

## Message Changes

### Legacy Messages

```python
PluginOutputMessage(plugin_name, line)
PluginStateChanged(plugin_name, state)
PluginProgressMessage(plugin_name, phase, percent, ...)
PluginCompleted(plugin_name, success, packages_updated, error_message)
```

### Interactive Messages

```python
PaneOutputMessage(pane_id, data)  # Raw bytes instead of string
PaneStateChanged(pane_id, state, exit_code)
AllPluginsCompleted(total, successful, failed)
```

### Key Differences

1. **Output is bytes**: Interactive mode uses raw bytes (`data: bytes`) instead of strings, preserving ANSI escape sequences.

2. **Exit code included**: State changes include the process exit code.

3. **No progress messages**: Progress is displayed directly in the terminal output, not as separate messages.

---

## Widget Changes

### Legacy Widgets

| Widget | Purpose |
|--------|---------|
| `PluginLogPanel` | RichLog for output display |
| `StatusBar` | Plugin state with progress |
| `ProgressPanel` | Overall progress at bottom |

### Interactive Widgets

| Widget | Purpose |
|--------|---------|
| `TerminalView` | Full terminal emulator |
| `TerminalPane` | Container with status bar |
| `PaneStatusBar` | Pane state display |
| `ProgressBar` | Overall progress at bottom |

---

## Configuration Changes

### Legacy Configuration

No configuration file support.

### Interactive Configuration

Key bindings can be configured via `~/.config/update-all/keybindings.toml`:

```toml
[tab_navigation]
next_tab = "ctrl+tab"
prev_tab = "ctrl+shift+tab"
tab_1 = "alt+1"

[terminal]
scroll_up = "shift+pageup"
scroll_down = "shift+pagedown"

[app]
quit = "ctrl+q"
help = "f1"
```

---

## Error Handling Changes

### PTY Availability

Interactive mode requires PTY support. On platforms without PTY (e.g., Windows), the system automatically falls back to the legacy streaming mode:

```python
from ui.interactive_tabbed_run import run_with_interactive_tabbed_ui
from ui.pty_session import is_pty_available

# This function handles fallback automatically
await run_with_interactive_tabbed_ui(plugins=plugins)

# Or check manually
if is_pty_available():
    # Use interactive mode
    app = InteractiveTabbedApp(plugins=plugins)
else:
    # Use legacy mode
    app = TabbedRunApp(plugins=plugins)
```

---

## Testing Changes

### Legacy Test Approach

```python
# Direct message posting
app.post_message(PluginOutputMessage("apt", "Output line"))
app.post_message(PluginStateChanged("apt", PluginState.RUNNING))
```

### Interactive Test Approach

```python
# Use Textual's Pilot for UI testing
async with app.run_test() as pilot:
    # Navigate tabs
    await pilot.press("ctrl+tab")

    # Verify state
    assert app.active_tab_index == 1

    # Access panes
    pane = app.terminal_panes["apt"]
    assert pane.state == PaneState.RUNNING
```

### Mock PTY Session

```python
from ui.tests.conftest import MockPTYSession

# Create mock with predefined responses
mock_session = MockPTYSession(
    responses=[
        b"Hello, World!\r\n",
        b"Done.\r\n",
    ],
    exit_code=0,
)

# Verify input was sent
await mock_session.write(b"test\n")
assert mock_session.get_input_history() == [b"test\n"]
```

---

## Performance Considerations

### Memory Usage

| Aspect | Legacy | Interactive |
|--------|--------|-------------|
| Scrollback buffer | Unlimited (list) | Configurable (default: 10,000 lines) |
| Output storage | String per line | Ring buffer with limit |

### CPU Usage

| Aspect | Legacy | Interactive |
|--------|--------|-------------|
| ANSI parsing | Rich library | Pyte library |
| Rendering | On each message | Batched (30 FPS max) |

### Recommendations

1. **Set appropriate scrollback limit**: Default is 10,000 lines. Reduce for memory-constrained systems.

2. **Use batched rendering**: The system automatically batches output at 30 FPS.

3. **Handle long-running commands**: Interactive mode keeps PTY open for the duration.

---

## Common Migration Issues

### Issue 1: Arrow Keys Don't Navigate Tabs

**Cause**: Arrow keys are now sent to the PTY.

**Solution**: Use `Ctrl+Tab` / `Ctrl+Shift+Tab` for tab navigation.

### Issue 2: Plugin Output Not Showing

**Cause**: Plugin doesn't implement `get_interactive_command()`.

**Solution**: Implement the method or check that `supports_interactive` returns `True`.

### Issue 3: PTY Not Available Error

**Cause**: Running on Windows or in a restricted environment.

**Solution**: The system automatically falls back to legacy mode. No action needed.

### Issue 4: Sudo Prompts Not Working

**Cause**: Sudo credentials not pre-authenticated.

**Solution**: The system pre-authenticates sudo before starting plugins. Ensure `SudoKeepAlive` is running.

---

## Rollback Procedure

If you need to rollback to the legacy mode:

```python
# Option 1: Use legacy function directly
from ui.tabbed_run import run_with_tabbed_ui

await run_with_tabbed_ui(
    plugins=plugins,
    configs=configs,
    dry_run=False,
    use_streaming=True,
)

# Option 2: Force non-interactive mode
from ui.interactive_tabbed_run import run_with_interactive_tabbed_ui
from unittest.mock import patch

with patch("ui.interactive_tabbed_run.is_pty_available", return_value=False):
    await run_with_interactive_tabbed_ui(plugins=plugins)
```

---

## Checklist

Use this checklist when migrating:

- [ ] Update import statements
- [ ] Replace `run_with_tabbed_ui` with `run_with_interactive_tabbed_ui`
- [ ] Implement `get_interactive_command()` in plugins
- [ ] Update keyboard shortcut documentation for users
- [ ] Test on target platforms (Linux, macOS)
- [ ] Verify fallback works on Windows
- [ ] Update any custom event handlers
- [ ] Review scrollback buffer settings
- [ ] Test sudo authentication flow
- [ ] Update integration tests

---

## Support

For issues with migration:

1. Check the [Interactive Tabs Implementation Plan](interactive-tabs-implementation-plan.md)
2. Review the [Risk Analysis](interactive-tabs-risk-analysis.md)
3. Check test files for usage examples:
   - `ui/tests/test_interactive_tabbed_run.py`
   - `ui/tests/test_e2e_interactive_tabs.py`

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-06 | AI Assistant | Initial version |

# Interactive Tabs Implementation Plan

**Date:** January 6, 2026
**Version:** 1.1
**Status:** Draft
**Related Document:** [Interactive Tabs Risk Analysis](interactive-tabs-risk-analysis.md)

---

## Executive Summary

This document outlines the implementation plan for adding rich terminal emulator tabs to the update-all application. Each tab will function as an independent terminal session capable of running subprocesses, capturing their output live, and handling user input independently of other tabs.

The implementation follows a **Test-Driven Development (TDD)** approach, with tests written before implementation for each component.

---

## Table of Contents

1. [Requirements Recap](#1-requirements-recap)
2. [Technology Stack](#2-technology-stack)
3. [Architecture Overview](#3-architecture-overview)
4. [Implementation Phases](#4-implementation-phases)
5. [Test Specifications](#5-test-specifications)
6. [Integration with Existing Codebase](#6-integration-with-existing-codebase)
7. [Risk Mitigation](#7-risk-mitigation)
8. [Timeline](#8-timeline)

---

## 1. Requirements Recap

From the original requirement:

> Make each tab functionally equivalent to a rich terminal emulator, capable of displaying live progress of the update process and capturing user input independently of other tabs.

### Key Requirements

| Requirement | Priority | Complexity |
|-------------|----------|------------|
| PTY-based terminal sessions per tab | **Critical** | High |
| Live output display with ANSI escape handling | **Critical** | High |
| Independent user input capture per tab | **Critical** | High |
| Independent scrollback buffer per tab | **High** | Medium |
| Configurable keyboard shortcuts for tab switching | **Medium** | Low |
| Mouse click tab switching | **Medium** | Low |
| Non-navigation keys routed to active tab only | **High** | Medium |

---

## 2. Technology Stack

Based on research conducted on December 5, 2025:

### Core Libraries

| Library | Version | Purpose | License |
|---------|---------|---------|---------|
| [textual](https://github.com/Textualize/textual) | >=0.40.0 | TUI framework (already in use) | MIT |
| [pyte](https://github.com/selectel/pyte) | >=0.8.0 | Terminal emulator (ANSI parsing) | LGPL-3.0 |
| [ptyprocess](https://github.com/pexpect/ptyprocess) | >=0.7.0 | PTY subprocess management | ISC |

### Testing Libraries

| Library | Purpose |
|---------|---------|
| pytest | Test framework |
| pytest-asyncio | Async test support |
| textual[dev] | Textual testing utilities (Pilot) |

### Alternative Considered

- **textual-terminal** (v0.3.0): A ready-made terminal widget for Textual using Pyte. However, it hasn't been updated since January 2023 and may have compatibility issues with newer Textual versions. We will use it as a reference but implement our own solution for better control and maintainability.

### Research Sources

1. [PyPI - textual-terminal](https://pypi.org/project/textual-terminal/) - Terminal widget for Textual
2. [GitHub - selectel/pyte](https://github.com/selectel/pyte) - Terminal emulator library (715 stars, actively maintained)
3. [GitHub - pexpect/ptyprocess](https://github.com/pexpect/ptyprocess) - PTY management (233 stars)
4. [Python docs - pty module](https://docs.python.org/3/library/pty.html) - Standard library PTY utilities
5. [Textual Testing Guide](https://textual.textualize.io/guide/testing/) - Official testing documentation

---

## 3. Architecture Overview

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    InteractiveTabbedApp (Textual App)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    TabbedContent (Tab Container)                     │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │    │
│  │  │   TerminalPane  │  │   TerminalPane  │  │   TerminalPane  │      │    │
│  │  │     (apt)       │  │    (flatpak)    │  │     (pipx)      │      │    │
│  │  │                 │  │                 │  │                 │      │    │
│  │  │ ┌─────────────┐ │  │ ┌─────────────┐ │  │ ┌─────────────┐ │      │    │
│  │  │ │TerminalView│ │  │ │TerminalView│ │  │ │TerminalView│ │      │    │
│  │  │ │  (pyte)    │ │  │ │  (pyte)    │ │  │ │  (pyte)    │ │      │    │
│  │  │ └─────┬──────┘ │  │ └─────┬──────┘ │  │ └─────┬──────┘ │      │    │
│  │  └───────┼────────┘  └───────┼────────┘  └───────┼────────┘      │    │
│  └──────────┼───────────────────┼───────────────────┼───────────────┘    │
│             │                   │                   │                     │
│             ▼                   ▼                   ▼                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │                      PTYSessionManager                               │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │  │
│  │  │   PTYSession    │  │   PTYSession    │  │   PTYSession    │      │  │
│  │  │ (ptyprocess)    │  │ (ptyprocess)    │  │ (ptyprocess)    │      │  │
│  │  │ stdin/stdout    │  │ stdin/stdout    │  │ stdin/stdout    │      │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘      │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│                           InputRouter                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  - Tab navigation keys (Ctrl+Tab, Ctrl+Shift+Tab) → App navigation   │    │
│  │  - All other keys → Active tab's PTY stdin                           │    │
│  │  - Configurable key bindings                                         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Component Descriptions

#### 3.2.1 TerminalView Widget

A Textual widget that:
- Renders terminal screen buffer from pyte
- Handles terminal resize events (SIGWINCH)
- Maintains independent scrollback buffer
- Displays cursor position
- Supports Rich text styling for ANSI colors

**Location:** `ui/ui/terminal_view.py`

#### 3.2.2 PTYSession

A class that:
- Wraps ptyprocess for PTY management
- Provides async read/write interface
- Handles process lifecycle (start, stop, signal)
- Manages terminal size synchronization

**Location:** `ui/ui/pty_session.py`

#### 3.2.3 PTYSessionManager

A component that:
- Creates and manages PTYSession instances
- Routes I/O between PTY and TerminalView
- Handles concurrent session management
- Provides cleanup on app exit

**Location:** `ui/ui/pty_manager.py`

#### 3.2.4 InputRouter

A component that:
- Intercepts all keyboard input at app level
- Routes navigation keys to app (tab switching)
- Routes other keys to active PTY
- Supports configurable key bindings

**Location:** `ui/ui/input_router.py`

#### 3.2.5 TerminalPane

A container widget that:
- Combines TerminalView with status bar
- Manages the connection between TerminalView and PTYSession
- Handles plugin-specific configuration

**Location:** `ui/ui/terminal_pane.py`

---

## 4. Implementation Phases

### Phase 1: Core PTY Infrastructure (Week 1-2)

**Goal:** Establish PTY session management foundation

**Components:**
1. `PTYSession` class with async I/O
2. `PTYSessionManager` for lifecycle management
3. Unit tests for PTY operations

**Deliverables:**
- [ ] `ui/ui/pty_session.py` - PTY session wrapper
- [ ] `ui/ui/pty_manager.py` - Session manager
- [ ] `ui/tests/test_pty_session.py` - PTY tests
- [ ] `ui/tests/test_pty_manager.py` - Manager tests

### Phase 2: Terminal Emulation (Week 3-4)

**Goal:** Implement terminal screen rendering with pyte

**Components:**
1. `TerminalScreen` class wrapping pyte.Screen
2. `TerminalView` Textual widget
3. Scrollback buffer implementation
4. ANSI color mapping to Rich styles

**Deliverables:**
- [ ] `ui/ui/terminal_screen.py` - Pyte wrapper
- [ ] `ui/ui/terminal_view.py` - Textual widget
- [ ] `ui/tests/test_terminal_screen.py` - Screen tests
- [ ] `ui/tests/test_terminal_view.py` - Widget tests

### Phase 3: Input Handling (Week 5-6)

**Goal:** Implement keyboard input routing

**Components:**
1. `InputRouter` for key routing
2. Configurable key bindings
3. Special key handling (Ctrl+C, Ctrl+D, etc.)
4. Tab switching shortcuts

**Deliverables:**
- [ ] `ui/ui/input_router.py` - Input routing
- [ ] `ui/ui/key_bindings.py` - Key binding configuration
- [ ] `ui/tests/test_input_router.py` - Input tests
- [ ] `ui/tests/test_key_bindings.py` - Binding tests

### Phase 4: Integration (Week 7-8)

**Goal:** Integrate components into tabbed UI

**Components:**
1. `TerminalPane` container widget
2. `InteractiveTabbedApp` main application
3. Plugin interface updates
4. Integration with existing streaming infrastructure

**Deliverables:**
- [ ] `ui/ui/terminal_pane.py` - Pane container
- [ ] `ui/ui/interactive_tabbed_run.py` - Main app
- [ ] `ui/tests/test_terminal_pane.py` - Pane tests
- [ ] `ui/tests/test_interactive_tabbed_run.py` - Integration tests

### Phase 5: Polish and Documentation (Week 9-10)

**Goal:** Finalize implementation and documentation

**Components:**
1. Performance optimization
2. Error handling improvements
3. Documentation updates
4. End-to-end testing

**Deliverables:**
- [ ] Performance benchmarks
- [ ] Updated README and docs
- [ ] E2E test suite
- [ ] Migration guide from old tabbed UI

---

## 5. Test Specifications

### 5.1 Testing Strategy

Following TDD principles, tests are written **before** implementation:

1. **Unit Tests:** Test individual components in isolation
2. **Integration Tests:** Test component interactions
3. **E2E Tests:** Test complete user workflows
4. **Snapshot Tests:** Verify terminal rendering output

### 5.2 Test Categories

#### 5.2.1 PTY Session Tests (`ui/tests/test_pty_session.py`)

```python
# Test specifications for PTYSession

class TestPTYSessionCreation:
    """Tests for PTY session creation and initialization."""

    async def test_create_session_with_command(self) -> None:
        """Test creating a PTY session with a command."""
        # Given: A command to run
        # When: Creating a PTY session
        # Then: Session should be created with PTY allocated

    async def test_create_session_with_environment(self) -> None:
        """Test creating a PTY session with custom environment."""
        # Given: Custom environment variables
        # When: Creating a PTY session
        # Then: Environment should be passed to subprocess

    async def test_create_session_with_working_directory(self) -> None:
        """Test creating a PTY session with custom working directory."""
        # Given: A working directory path
        # When: Creating a PTY session
        # Then: Process should start in specified directory


class TestPTYSessionIO:
    """Tests for PTY session I/O operations."""

    async def test_read_output_from_command(self) -> None:
        """Test reading output from a running command."""
        # Given: A PTY session running 'echo hello'
        # When: Reading from the session
        # Then: Should receive 'hello' in output

    async def test_write_input_to_command(self) -> None:
        """Test writing input to a running command."""
        # Given: A PTY session running 'cat'
        # When: Writing 'test' to stdin
        # Then: Should receive 'test' echoed back

    async def test_read_timeout_handling(self) -> None:
        """Test handling read timeout."""
        # Given: A PTY session with no output
        # When: Reading with timeout
        # Then: Should raise TimeoutError or return empty

    async def test_concurrent_read_write(self) -> None:
        """Test concurrent read and write operations."""
        # Given: A PTY session running interactive command
        # When: Reading and writing concurrently
        # Then: Both operations should complete without deadlock


class TestPTYSessionLifecycle:
    """Tests for PTY session lifecycle management."""

    async def test_session_cleanup_on_close(self) -> None:
        """Test that resources are cleaned up on close."""
        # Given: An active PTY session
        # When: Closing the session
        # Then: PTY and process should be terminated

    async def test_session_handles_process_exit(self) -> None:
        """Test handling of process exit."""
        # Given: A PTY session running 'exit 0'
        # When: Process exits
        # Then: Session should report exit status

    async def test_send_signal_to_process(self) -> None:
        """Test sending signals to the subprocess."""
        # Given: A PTY session running 'sleep 100'
        # When: Sending SIGTERM
        # Then: Process should terminate


class TestPTYSessionResize:
    """Tests for PTY terminal resize."""

    async def test_resize_terminal(self) -> None:
        """Test resizing the terminal."""
        # Given: A PTY session with 80x24 size
        # When: Resizing to 120x40
        # Then: PTY should report new size

    async def test_resize_sends_sigwinch(self) -> None:
        """Test that resize sends SIGWINCH to process."""
        # Given: A PTY session running a size-aware program
        # When: Resizing the terminal
        # Then: Process should receive SIGWINCH
```

#### 5.2.2 Terminal Screen Tests (`ui/tests/test_terminal_screen.py`)

```python
# Test specifications for TerminalScreen

class TestTerminalScreenRendering:
    """Tests for terminal screen rendering."""

    async def test_render_plain_text(self) -> None:
        """Test rendering plain text output."""
        # Given: A terminal screen
        # When: Writing 'Hello, World!'
        # Then: Screen buffer should contain the text

    async def test_render_ansi_colors(self) -> None:
        """Test rendering ANSI color codes."""
        # Given: A terminal screen
        # When: Writing text with ANSI color codes
        # Then: Screen should parse colors correctly

    async def test_render_cursor_movement(self) -> None:
        """Test rendering cursor movement sequences."""
        # Given: A terminal screen
        # When: Writing cursor movement escape sequences
        # Then: Cursor position should update correctly

    async def test_render_screen_clear(self) -> None:
        """Test rendering screen clear sequences."""
        # Given: A terminal screen with content
        # When: Writing clear screen sequence
        # Then: Screen buffer should be cleared


class TestTerminalScreenScrollback:
    """Tests for scrollback buffer."""

    async def test_scrollback_buffer_stores_history(self) -> None:
        """Test that scrollback buffer stores line history."""
        # Given: A terminal screen with scrollback enabled
        # When: Writing more lines than screen height
        # Then: Scrollback buffer should contain old lines

    async def test_scrollback_buffer_limit(self) -> None:
        """Test scrollback buffer size limit."""
        # Given: A terminal screen with 1000 line scrollback limit
        # When: Writing 2000 lines
        # Then: Only last 1000 lines should be in scrollback

    async def test_scroll_up_in_history(self) -> None:
        """Test scrolling up in history."""
        # Given: A terminal screen with scrollback content
        # When: Scrolling up
        # Then: Should display older content

    async def test_scroll_down_in_history(self) -> None:
        """Test scrolling down in history."""
        # Given: A terminal screen scrolled up
        # When: Scrolling down
        # Then: Should display newer content
```

#### 5.2.3 Terminal View Widget Tests (`ui/tests/test_terminal_view.py`)

```python
# Test specifications for TerminalView widget

class TestTerminalViewWidget:
    """Tests for TerminalView Textual widget."""

    async def test_widget_renders_screen_content(self) -> None:
        """Test that widget renders terminal screen content."""
        # Given: A TerminalView with screen content
        # When: Rendering the widget
        # Then: Content should be visible in widget

    async def test_widget_handles_resize(self) -> None:
        """Test widget resize handling."""
        # Given: A TerminalView widget
        # When: Widget is resized
        # Then: Terminal screen should be resized accordingly

    async def test_widget_displays_cursor(self) -> None:
        """Test cursor display in widget."""
        # Given: A TerminalView with cursor at position (5, 10)
        # When: Rendering the widget
        # Then: Cursor should be visible at correct position

    async def test_widget_applies_ansi_styles(self) -> None:
        """Test ANSI style application."""
        # Given: A TerminalView with colored content
        # When: Rendering the widget
        # Then: Colors should be applied correctly


class TestTerminalViewInteraction:
    """Tests for TerminalView user interaction."""

    async def test_focus_activates_input(self) -> None:
        """Test that focusing widget activates input."""
        # Given: A TerminalView widget
        # When: Widget receives focus
        # Then: Widget should accept keyboard input

    async def test_mouse_scroll_navigates_history(self) -> None:
        """Test mouse scroll for history navigation."""
        # Given: A TerminalView with scrollback content
        # When: Mouse scroll up
        # Then: Should scroll through history

    async def test_mouse_click_positions_cursor(self) -> None:
        """Test mouse click for cursor positioning."""
        # Given: A TerminalView widget
        # When: Mouse click at position
        # Then: Should send appropriate escape sequence
```

#### 5.2.4 Input Router Tests (`ui/tests/test_input_router.py`)

```python
# Test specifications for InputRouter

class TestInputRouterKeyRouting:
    """Tests for key routing logic."""

    async def test_navigation_keys_go_to_app(self) -> None:
        """Test that navigation keys are routed to app."""
        # Given: An InputRouter with Ctrl+Tab as navigation key
        # When: Pressing Ctrl+Tab
        # Then: Key should be handled by app, not PTY

    async def test_regular_keys_go_to_active_pty(self) -> None:
        """Test that regular keys go to active PTY."""
        # Given: An InputRouter with active PTY session
        # When: Pressing 'a'
        # Then: 'a' should be sent to active PTY

    async def test_special_keys_go_to_pty(self) -> None:
        """Test that special keys (Ctrl+C) go to PTY."""
        # Given: An InputRouter with active PTY session
        # When: Pressing Ctrl+C
        # Then: SIGINT should be sent to PTY process

    async def test_inactive_tab_does_not_receive_input(self) -> None:
        """Test that inactive tabs don't receive input."""
        # Given: Multiple tabs with tab 2 active
        # When: Pressing keys
        # Then: Only tab 2's PTY should receive input


class TestInputRouterConfiguration:
    """Tests for key binding configuration."""

    async def test_custom_tab_switch_binding(self) -> None:
        """Test custom tab switching key binding."""
        # Given: Custom binding Alt+1 for tab 1
        # When: Pressing Alt+1
        # Then: Should switch to tab 1

    async def test_binding_override(self) -> None:
        """Test overriding default bindings."""
        # Given: Override Ctrl+Tab to do nothing
        # When: Pressing Ctrl+Tab
        # Then: Key should be ignored

    async def test_binding_persistence(self) -> None:
        """Test that bindings persist across sessions."""
        # Given: Custom bindings saved to config
        # When: Restarting app
        # Then: Custom bindings should be loaded
```

#### 5.2.5 Integration Tests (`ui/tests/test_interactive_tabbed_run.py`)

```python
# Test specifications for InteractiveTabbedApp integration

class TestInteractiveTabbedAppBasic:
    """Basic integration tests for the interactive tabbed app."""

    async def test_app_creates_tabs_for_plugins(self) -> None:
        """Test that app creates a tab for each plugin."""
        # Given: A list of 3 plugins
        # When: Starting the app
        # Then: 3 tabs should be created

    async def test_app_starts_pty_sessions(self) -> None:
        """Test that app starts PTY sessions for each tab."""
        # Given: An app with 3 tabs
        # When: App is mounted
        # Then: 3 PTY sessions should be running

    async def test_app_displays_live_output(self) -> None:
        """Test that app displays live output from PTY."""
        # Given: A running app with 'echo hello' command
        # When: Command produces output
        # Then: Output should appear in terminal view


class TestInteractiveTabbedAppNavigation:
    """Tests for tab navigation."""

    async def test_ctrl_tab_switches_to_next_tab(self) -> None:
        """Test Ctrl+Tab switches to next tab."""
        # Given: App with 3 tabs, tab 1 active
        # When: Pressing Ctrl+Tab
        # Then: Tab 2 should become active

    async def test_ctrl_shift_tab_switches_to_previous_tab(self) -> None:
        """Test Ctrl+Shift+Tab switches to previous tab."""
        # Given: App with 3 tabs, tab 2 active
        # When: Pressing Ctrl+Shift+Tab
        # Then: Tab 1 should become active

    async def test_mouse_click_switches_tab(self) -> None:
        """Test mouse click on tab header switches tab."""
        # Given: App with 3 tabs, tab 1 active
        # When: Clicking on tab 3 header
        # Then: Tab 3 should become active

    async def test_arrow_keys_switch_tabs(self) -> None:
        """Test left/right arrow keys switch tabs."""
        # Given: App with 3 tabs, tab 2 active
        # When: Pressing left arrow
        # Then: Tab 1 should become active


class TestInteractiveTabbedAppInput:
    """Tests for input handling in tabs."""

    async def test_input_goes_to_active_tab_only(self) -> None:
        """Test that input only goes to active tab."""
        # Given: App with 2 tabs running 'cat', tab 1 active
        # When: Typing 'hello'
        # Then: Only tab 1 should show 'hello'

    async def test_ctrl_c_sends_sigint_to_active_tab(self) -> None:
        """Test Ctrl+C sends SIGINT to active tab's process."""
        # Given: App with tab running 'sleep 100'
        # When: Pressing Ctrl+C
        # Then: Process should be interrupted

    async def test_password_input_is_hidden(self) -> None:
        """Test that password input is not echoed."""
        # Given: App with tab running 'sudo' prompt
        # When: Typing password
        # Then: Password should not be visible


class TestInteractiveTabbedAppScrollback:
    """Tests for scrollback functionality."""

    async def test_scroll_up_shows_history(self) -> None:
        """Test scrolling up shows command history."""
        # Given: App with tab that has produced lots of output
        # When: Scrolling up
        # Then: Earlier output should be visible

    async def test_scroll_down_returns_to_current(self) -> None:
        """Test scrolling down returns to current output."""
        # Given: App with tab scrolled up
        # When: Scrolling down
        # Then: Current output should be visible

    async def test_each_tab_has_independent_scrollback(self) -> None:
        """Test that each tab has its own scrollback buffer."""
        # Given: App with 2 tabs with different output
        # When: Scrolling in tab 1
        # Then: Tab 2's scroll position should be unchanged
```

#### 5.2.6 E2E Tests (`ui/tests/test_e2e_interactive_tabs.py`)

```python
# End-to-end test specifications

class TestE2EPluginExecution:
    """E2E tests for plugin execution in interactive tabs."""

    async def test_apt_update_displays_progress(self) -> None:
        """Test that apt update shows live progress."""
        # Given: App with apt plugin
        # When: Running apt update (dry-run)
        # Then: Progress should be displayed live

    async def test_sudo_prompt_accepts_password(self) -> None:
        """Test that sudo prompts work correctly."""
        # Given: App with plugin requiring sudo
        # When: Sudo prompt appears
        # Then: User can enter password and continue

    async def test_interactive_prompt_works(self) -> None:
        """Test that interactive prompts (Y/n) work."""
        # Given: App with plugin showing Y/n prompt
        # When: User types 'Y'
        # Then: Plugin should continue execution

    async def test_multiple_plugins_run_independently(self) -> None:
        """Test that multiple plugins run independently."""
        # Given: App with 3 plugins
        # When: All plugins are running
        # Then: Each should progress independently
```

### 5.3 Test Utilities

Create test utilities in `ui/tests/conftest.py`:

```python
# Test fixtures and utilities

import pytest
from textual.pilot import Pilot

@pytest.fixture
def mock_pty_session():
    """Create a mock PTY session for testing."""
    ...

@pytest.fixture
def mock_terminal_screen():
    """Create a mock terminal screen for testing."""
    ...

@pytest.fixture
async def app_with_mock_plugins():
    """Create an app with mock plugins for testing."""
    ...

@pytest.fixture
def sample_ansi_output():
    """Sample ANSI-formatted output for testing."""
    return "\x1b[31mRed\x1b[0m \x1b[32mGreen\x1b[0m \x1b[34mBlue\x1b[0m"
```

---

## 6. Integration with Existing Codebase

### 6.1 Files to Modify

| File | Changes |
|------|---------|
| `ui/pyproject.toml` | Add pyte, ptyprocess dependencies |
| `ui/ui/__init__.py` | Export new components |
| `core/core/interfaces.py` | Add `supports_interactive` property to UpdatePlugin |
| `plugins/plugins/base.py` | Add `execute_interactive()` method |

### 6.2 New Files to Create

| File | Purpose |
|------|---------|
| `ui/ui/pty_session.py` | PTY session wrapper |
| `ui/ui/pty_manager.py` | PTY session manager |
| `ui/ui/terminal_screen.py` | Pyte screen wrapper |
| `ui/ui/terminal_view.py` | Textual terminal widget |
| `ui/ui/terminal_pane.py` | Terminal pane container |
| `ui/ui/input_router.py` | Keyboard input router |
| `ui/ui/key_bindings.py` | Key binding configuration |
| `ui/ui/interactive_tabbed_run.py` | Main interactive app |

### 6.3 Backward Compatibility

The existing `TabbedRunApp` in `ui/ui/tabbed_run.py` will be preserved for:
- Non-interactive mode (when PTY is not needed)
- Fallback when PTY allocation fails
- Simpler use cases

A feature flag `use_interactive_mode` will control which mode is used:

```python
async def run_with_tabbed_ui(
    plugins: list[UpdatePlugin],
    configs: dict[str, PluginConfig] | None = None,
    dry_run: bool = False,
    use_streaming: bool = True,
    use_interactive_mode: bool = False,  # New flag
) -> None:
    if use_interactive_mode:
        app = InteractiveTabbedApp(...)
    else:
        app = TabbedRunApp(...)
    await app.run_async()
```

### 6.4 Plugin Interface Changes

Add to `core/core/interfaces.py`:

```python
class UpdatePlugin(ABC):
    # ... existing methods ...

    @property
    def supports_interactive(self) -> bool:
        """Check if this plugin supports interactive mode with PTY."""
        return False

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command to run in interactive mode.

        Returns:
            Command and arguments as a list.
        """
        raise NotImplementedError
```

---

## 7. Risk Mitigation

This section documents the chosen mitigation strategies for each identified risk.
For the complete risk analysis, see [Interactive Tabs Risk Analysis](interactive-tabs-risk-analysis.md).

### 7.1 Critical Risks

#### 7.1.1 T1: PTY Allocation Failure

**Severity:** Critical
**Chosen Strategies:**
1. Implement graceful fallback to non-PTY mode (existing `TabbedRunApp`)
2. Add PTY availability check at startup (`is_pty_available()` function)
3. Provide clear error messages when PTY allocation fails

**Implementation:**

```python
import sys
import os

def is_pty_available() -> bool:
    """Check if PTY is available on this platform.

    Returns:
        True if PTY can be allocated, False otherwise.
    """
    if sys.platform == "win32":
        # Windows: PTY not supported, fall back to non-interactive mode
        return False

    # Unix-like systems: check if we can allocate a PTY
    try:
        import pty
        master, slave = pty.openpty()
        os.close(master)
        os.close(slave)
        return True
    except (ImportError, OSError):
        return False
```

**Fallback Behavior:**
1. Log warning message with reason for fallback
2. Fall back to existing `TabbedRunApp` from [`ui/ui/tabbed_run.py`](../ui/ui/tabbed_run.py)
3. Display notification to user that interactive mode is not available

#### 7.1.2 I4: Sudo Handling in PTY Mode

**Severity:** Critical
**Chosen Strategies:**
1. Pre-authenticate sudo before starting PTY sessions (current approach)
2. Coordinate sudo across tabs to prevent multiple prompts

**Implementation:**

The existing [`SudoKeepAlive`](../ui/ui/sudo.py:268) class already provides:
- Pre-authentication via `ensure_sudo_authenticated()`
- Background refresh via `SudoKeepAlive` context manager
- Non-interactive credential validation via `sudo -n -v`

**Additional Requirements for PTY Mode:**
```python
class PTYSudoCoordinator:
    """Coordinates sudo authentication across multiple PTY sessions."""

    def __init__(self) -> None:
        self._authenticated = False
        self._lock = asyncio.Lock()
        self._keepalive: SudoKeepAlive | None = None

    async def ensure_authenticated(self) -> bool:
        """Ensure sudo is authenticated before any PTY session starts."""
        async with self._lock:
            if self._authenticated:
                return True

            result = await ensure_sudo_authenticated()
            if result.status == SudoStatus.AUTHENTICATED:
                self._authenticated = True
                self._keepalive = SudoKeepAlive()
                await self._keepalive.start()
                return True
            return False

    async def cleanup(self) -> None:
        """Stop the keepalive when all PTY sessions are done."""
        if self._keepalive:
            await self._keepalive.stop()
```

#### 7.1.3 S1: Underestimated Complexity

**Severity:** Critical
**Chosen Strategies:**
1. Add 30% buffer to all time estimates
2. Implement in phases with working milestones
3. Track progress weekly with velocity measurement

**Implementation:**
- Each phase produces a working, testable deliverable
- Phase 1-2 focus on core infrastructure that can be tested independently
- Phase 3-4 integrate components incrementally
- Phase 5 reserved for polish and unexpected issues

### 7.2 High Risks

#### 7.2.1 T2: ANSI Escape Sequence Parsing

**Severity:** High
**Chosen Strategies:**
1. Create comprehensive test suite with real-world output samples
2. Implement fallback rendering for unrecognized sequences
3. Log unhandled sequences for debugging

**Implementation:**
```python
class SafeTerminalScreen:
    """Terminal screen with fallback rendering for unknown sequences."""

    def __init__(self, columns: int, lines: int) -> None:
        self._screen = pyte.Screen(columns, lines)
        self._stream = pyte.Stream(self._screen)
        self._unhandled_sequences: list[str] = []
        self._log = structlog.get_logger(__name__)

    def feed(self, data: str) -> None:
        """Feed data to the terminal, catching unhandled sequences."""
        try:
            self._stream.feed(data)
        except Exception as e:
            # Log and continue - don't crash on unknown sequences
            self._log.warning(
                "unhandled_escape_sequence",
                data_preview=data[:50],
                error=str(e),
            )
            self._unhandled_sequences.append(data)
```

#### 7.2.2 T3: Input Routing Complexity

**Severity:** High
**Chosen Strategies:**
1. Clear separation between navigation keys and PTY input
2. Use Textual's key binding system for navigation
3. Document which keys are reserved for navigation

**Reserved Navigation Keys:**
| Key Combination | Action |
|-----------------|--------|
| `Ctrl+Tab` | Next tab |
| `Ctrl+Shift+Tab` | Previous tab |
| `Alt+1` to `Alt+9` | Switch to tab N |
| `Ctrl+Q` | Quit application |
| `F1` | Help |

All other keys are forwarded to the active PTY session.

#### 7.2.3 T6: Concurrent PTY I/O Handling

**Severity:** High
**Chosen Strategies:**
1. Use `asyncio.TaskGroup` for concurrent stream reading (pattern from [`base.py`](../plugins/plugins/base.py:400))
2. Use bounded queues with backpressure (pattern from [`streaming.py`](../core/core/streaming.py:469))

**Implementation:**
The existing `StreamEventQueue` class provides:
- Bounded queue with configurable size (default: 1000 events)
- Backpressure via `put_nowait()` with overflow handling
- Warning logs when events are dropped
- Async iteration support

#### 7.2.4 D2: textual-terminal Compatibility

**Severity:** High
**Chosen Strategy:** Build custom terminal widget from scratch

**Rationale:** The `textual-terminal` package (v0.3.0) hasn't been updated since January 2023 and is incompatible with Textual >=7.0.0. We will:
1. Use `textual-terminal` as reference for architecture patterns only
2. Build our own `TerminalView` widget using pyte directly
3. Ensure compatibility with current Textual version (>=7.0.0,<8.0.0)

#### 7.2.5 D4: Textual API Stability

**Severity:** High
**Chosen Strategies:**
1. Pin Textual version range (already done: `>=7.0.0,<8.0.0` in [`ui/pyproject.toml`](../ui/pyproject.toml:40))
2. Maintain comprehensive test suite that catches API breakage

#### 7.2.6 I1: Conflict with Streaming Infrastructure

**Severity:** High
**Chosen Strategies:**
1. Design PTY mode as alternative to streaming, not replacement
2. Use feature flag (`use_interactive_mode`) to select mode
3. Create adapter between PTY output and StreamEvent types

**Implementation:**
```python
class PTYStreamAdapter:
    """Adapts PTY output to StreamEvent types for compatibility."""

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name

    def output_to_event(self, data: bytes) -> OutputEvent:
        """Convert raw PTY output to OutputEvent."""
        return OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.plugin_name,
            timestamp=datetime.now(tz=UTC),
            line=data.decode("utf-8", errors="replace"),
            stream="stdout",
        )
```

#### 7.2.7 I2: Plugin Interface Changes

**Severity:** High
**Chosen Strategies:**
1. Add new methods with default implementations (return False/raise NotImplementedError)
2. Make interactive mode opt-in per plugin
3. Provide base class implementation in `BasePlugin`

**Interface Changes:**
```python
# In core/core/interfaces.py
class UpdatePlugin(ABC):
    # ... existing methods ...

    @property
    def supports_interactive(self) -> bool:
        """Check if this plugin supports interactive mode with PTY.

        Default implementation returns False for backward compatibility.
        """
        return False

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command to run in interactive mode.

        Raises:
            NotImplementedError: If interactive mode is not supported.
        """
        raise NotImplementedError(
            f"Plugin '{self.name}' does not support interactive mode"
        )
```

#### 7.2.8 P2: Memory Leaks in Long-Running Sessions

**Severity:** High
**Chosen Strategies:**
1. Implement configurable scrollback buffer limits (default: 10,000 lines)
2. Use bounded queues (already in [`streaming.py`](../core/core/streaming.py:469))

**Implementation:**
```python
class ScrollbackBuffer:
    """Ring buffer for terminal scrollback with configurable limit."""

    def __init__(self, max_lines: int = 10_000) -> None:
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._max_lines = max_lines

    def append(self, line: str) -> None:
        """Append a line to the buffer (oldest lines are dropped)."""
        self._buffer.append(line)

    @property
    def lines(self) -> list[str]:
        """Get all lines in the buffer."""
        return list(self._buffer)
```

#### 7.2.9 P3: UI Responsiveness During Heavy Output

**Severity:** High
**Chosen Strategies:**
1. Prioritize input handling over rendering
2. Use batched rendering (existing 50ms batching in [`streaming.py`](../core/core/streaming.py:419))

**Implementation:**
- Use `batched_stream()` function for output processing
- Implement frame skipping when output rate exceeds 30 FPS
- Process input events in separate high-priority task

#### 7.2.10 C1: Windows PTY Support

**Severity:** High
**Chosen Strategies:**
1. Focus on Linux first (primary target)
2. Implement platform detection in `is_pty_available()`
3. Fall back to non-PTY mode on Windows

**Rationale:** Windows support can be added in a future release using `pywinpty`. For now, Windows users will use the existing `TabbedRunApp`.

#### 7.2.11 Q1: Difficulty Testing Interactive Behavior

**Severity:** High
**Chosen Strategies:**
1. Use Textual's Pilot for UI testing
2. Create mock PTY sessions for unit tests
3. Implement deterministic test scenarios

**Test Infrastructure:**
```python
# In ui/tests/conftest.py

class MockPTYSession:
    """Mock PTY session for testing without real PTY allocation."""

    def __init__(self, responses: list[bytes] | None = None) -> None:
        self._responses = responses or []
        self._response_index = 0
        self._input_buffer: list[bytes] = []

    async def read(self, size: int = 1024) -> bytes:
        """Return next mock response."""
        if self._response_index < len(self._responses):
            response = self._responses[self._response_index]
            self._response_index += 1
            return response
        return b""

    async def write(self, data: bytes) -> None:
        """Record input for verification."""
        self._input_buffer.append(data)

@pytest.fixture
def mock_pty_session() -> MockPTYSession:
    """Create a mock PTY session for testing."""
    return MockPTYSession()
```

### 7.3 Medium Risks

#### 7.3.1 I3: Mutex System Interaction

**Chosen Strategy:** Extend mutex timeout for interactive sessions

The existing [`MutexManager`](../core/core/mutex.py:92) already supports:
- Configurable deadlock timeout (default: 60s)
- Deadlock detection with cycle detection
- Comprehensive logging

For interactive mode, increase timeout to accommodate user input delays:
```python
# Use longer timeout for interactive sessions
INTERACTIVE_MUTEX_TIMEOUT = 600.0  # 10 minutes
```

#### 7.3.2 I5: Configuration System Integration

**Chosen Strategy:** Extend existing configuration schema

Add to [`core/core/config.py`](../core/core/config.py):
```python
@dataclass
class InteractiveConfig:
    """Configuration for interactive mode."""
    enabled: bool = False
    scrollback_lines: int = 10_000
    key_bindings: dict[str, str] = field(default_factory=lambda: {
        "next_tab": "ctrl+tab",
        "prev_tab": "ctrl+shift+tab",
        "quit": "ctrl+q",
    })
```

### 7.4 Fallback Strategy

If critical risks materialize during implementation:

**Level 1: Graceful Degradation**
- Fall back to existing `TabbedRunApp` for non-PTY environments
- Disable interactive features, maintain streaming output

**Level 2: Hybrid Approach**
- Use PTY only for plugins that require interaction (e.g., sudo prompts)
- Use streaming for non-interactive plugins

**Level 3: Feature Deferral**
- Defer interactive tabs to future release
- Focus on improving existing streaming UI

---

## 8. Timeline

### Week 1-2: Phase 1 - Core PTY Infrastructure

| Day | Task |
|-----|------|
| 1-2 | Write PTYSession tests |
| 3-4 | Implement PTYSession |
| 5-6 | Write PTYSessionManager tests |
| 7-8 | Implement PTYSessionManager |
| 9-10 | Integration testing, bug fixes |

### Week 3-4: Phase 2 - Terminal Emulation

| Day | Task |
|-----|------|
| 1-2 | Write TerminalScreen tests |
| 3-4 | Implement TerminalScreen with pyte |
| 5-6 | Write TerminalView tests |
| 7-8 | Implement TerminalView widget |
| 9-10 | Scrollback buffer, styling |

### Week 5-6: Phase 3 - Input Handling

| Day | Task |
|-----|------|
| 1-2 | Write InputRouter tests |
| 3-4 | Implement InputRouter |
| 5-6 | Write key binding tests |
| 7-8 | Implement configurable bindings |
| 9-10 | Special key handling |

### Week 7-8: Phase 4 - Integration

| Day | Task |
|-----|------|
| 1-2 | Write TerminalPane tests |
| 3-4 | Implement TerminalPane |
| 5-6 | Write InteractiveTabbedApp tests |
| 7-8 | Implement InteractiveTabbedApp |
| 9-10 | Plugin interface updates |

### Week 9-10: Phase 5 - Polish

| Day | Task |
|-----|------|
| 1-2 | E2E testing |
| 3-4 | Performance optimization |
| 5-6 | Error handling improvements |
| 7-8 | Documentation |
| 9-10 | Final review, bug fixes |

---

## Appendix A: Dependencies to Add

Add to `ui/pyproject.toml`:

```toml
[tool.poetry.dependencies]
pyte = "^0.8.0"
ptyprocess = "^0.7.0"

[tool.poetry.group.dev.dependencies]
pytest-asyncio = "^0.23.0"
```

---

## Appendix B: Configuration Schema

Key bindings configuration in `~/.config/update-all/keybindings.toml`:

```toml
[tab_navigation]
next_tab = "ctrl+tab"
prev_tab = "ctrl+shift+tab"
tab_1 = "alt+1"
tab_2 = "alt+2"
tab_3 = "alt+3"
# ... up to tab_9

[terminal]
scroll_up = "shift+pageup"
scroll_down = "shift+pagedown"
scroll_top = "shift+home"
scroll_bottom = "shift+end"

[app]
quit = "ctrl+q"
help = "f1"
```

---

## Appendix C: References

1. [Textual Framework Documentation](https://textual.textualize.io/)
2. [Textual Testing Guide](https://textual.textualize.io/guide/testing/)
3. [pyte - Terminal Emulator](https://github.com/selectel/pyte)
4. [ptyprocess - PTY Management](https://github.com/pexpect/ptyprocess)
5. [Python pty module](https://docs.python.org/3/library/pty.html)
6. [textual-terminal (reference)](https://github.com/mitosch/textual-terminal)
7. [Update-All Architecture Evaluation](interactive-tabs-architecture-evaluation.md)
8. [Interactive Tabs Risk Analysis](interactive-tabs-risk-analysis.md)

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-12-05 | AI Assistant | Initial version |
| 1.1 | 2026-01-06 | AI Assistant | Updated Risk Mitigation section (Section 7) with chosen strategies verified against current codebase. Added cross-references to risk analysis document. Expanded mitigation strategies with implementation details and code examples. |

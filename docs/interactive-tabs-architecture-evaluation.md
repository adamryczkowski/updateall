# Interactive Tabs Architecture Evaluation

**Date:** December 5, 2025
**Version:** 1.0
**Status:** Final

---

## Executive Summary

This document evaluates whether the requirement for "rich terminal emulator tabs with independent subprocess control and user input capture" justifies a re-evaluation of the update-all project's architecture.

**Verdict: YES — Architecture re-evaluation is justified.**

The requirement introduces fundamental changes to the execution model that go beyond the current streaming architecture. While the existing architecture supports live output streaming, it does **not** support:
- Independent PTY (pseudo-terminal) sessions per tab
- Interactive user input capture per subprocess
- Independent scrollback buffers per tab
- True terminal emulation with ANSI escape sequence handling

These capabilities require significant architectural changes to the UI layer and potentially the plugin execution layer.

---

## Table of Contents

1. [Requirement Analysis](#1-requirement-analysis)
2. [Current Architecture Assessment](#2-current-architecture-assessment)
3. [Gap Analysis](#3-gap-analysis)
4. [Architectural Impact Assessment](#4-architectural-impact-assessment)
5. [Recommendation](#5-recommendation)
6. [Proposed Architecture Changes](#6-proposed-architecture-changes)

---

## 1. Requirement Analysis

### 1.1 Requirement Statement

> Make each tab functionally equivalent to a rich terminal emulator, capable of displaying live progress of the update process and capturing user input independently of other tabs. They should be implemented to look and feel as different threads of a single application, but in reality each tab should be an independent terminal session, capable of running its own subprocesses, capturing their output and displaying it live in the tab. If the subprocess requires user input, the tab should capture it and send it to the subprocess without interrupting other tabs.
>
> User should be able to switch between tabs using configurable keyboard shortcuts (e.g. Ctrl+Tab, Ctrl+Shift+Tab) or mouse clicks, and each tab should maintain its own scrollback buffer, allowing the user to scroll through the output history of each tab independently. All the keypresses other than those used for tab switching should be sent to the active tab only.

### 1.2 Key Requirements Breakdown

| Requirement | Category | Complexity |
|-------------|----------|------------|
| Rich terminal emulator per tab | UI/Terminal | **High** |
| Live progress display | Already implemented | Low |
| Independent subprocess per tab | Execution | **Medium** |
| User input capture per tab | UI/Terminal | **High** |
| Independent scrollback buffer per tab | UI/Terminal | **Medium** |
| Configurable keyboard shortcuts | UI | Low |
| Tab switching (Ctrl+Tab, mouse) | UI | Low |
| Keypresses routed to active tab only | UI/Terminal | **High** |
| PTY-based terminal sessions | Execution | **High** |

### 1.3 Critical New Capabilities Required

1. **PTY (Pseudo-Terminal) Support**: Each tab needs a real PTY to handle:
   - ANSI escape sequences (colors, cursor movement, clearing)
   - Terminal size negotiation (SIGWINCH)
   - Raw mode input handling
   - Line discipline (cooked vs raw mode)

2. **Interactive Input Handling**:
   - Capture keystrokes and send to subprocess stdin
   - Handle special keys (Ctrl+C, Ctrl+D, Ctrl+Z)
   - Support password prompts (sudo, SSH)
   - Handle interactive prompts (apt "Do you want to continue?")

3. **Independent Terminal State**:
   - Each tab maintains its own terminal state (cursor position, colors, modes)
   - Independent scrollback buffer
   - Terminal size per tab

---

## 2. Current Architecture Assessment

### 2.1 Current UI Architecture

The current implementation in [`ui/ui/tabbed_run.py`](../ui/ui/tabbed_run.py) uses:

- **Textual Framework**: TUI framework with widget-based UI
- **TabbedContent**: Textual's built-in tab container
- **RichLog**: Text log widget for displaying output (NOT a terminal emulator)
- **Streaming Events**: Async event-based output streaming

```
Current Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TabbedRunApp (Textual)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    TabbedContent (Tab Container)                     │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │    │
│  │  │   TabPane   │  │   TabPane   │  │   TabPane   │                  │    │
│  │  │  (apt)      │  │  (flatpak)  │  │  (pipx)     │                  │    │
│  │  │             │  │             │  │             │                  │    │
│  │  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │                  │    │
│  │  │ │RichLog  │ │  │ │RichLog  │ │  │ │RichLog  │ │  ← Text output   │    │
│  │  │ │(output) │ │  │ │(output) │ │  │ │(output) │ │    only, no PTY  │    │
│  │  │ └─────────┘ │  │ └─────────┘ │  │ └─────────┘ │                  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                         Plugin Execution Layer                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  asyncio.create_subprocess_exec() with PIPE stdout/stderr           │    │
│  │  - Output captured as text lines                                     │    │
│  │  - No stdin handling                                                 │    │
│  │  - No PTY allocation                                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Current Streaming Architecture

From [`core/core/streaming.py`](../core/core/streaming.py):

- **StreamEvent types**: OutputEvent, ProgressEvent, PhaseEvent, CompletionEvent
- **Batched event handling**: 50ms batching, 30 FPS max
- **Bounded queues**: 1000 event max with backpressure

From [`plugins/plugins/base.py`](../plugins/plugins/base.py):

- **Subprocess execution**: `asyncio.create_subprocess_exec()` with PIPE
- **Output capture**: Line-by-line text capture
- **No stdin**: No mechanism to send input to running subprocess

### 2.3 Current Capabilities

| Capability | Status | Implementation |
|------------|--------|----------------|
| Live output streaming | ✅ Implemented | StreamEvent + BatchedEventHandler |
| Progress display | ✅ Implemented | ProgressEvent + StatusBar |
| Tab navigation | ✅ Implemented | Left/Right arrows, TabbedContent |
| Output scrolling | ✅ Implemented | RichLog with scroll |
| User input capture | ❌ Not implemented | No stdin handling |
| PTY sessions | ❌ Not implemented | Uses PIPE, not PTY |
| ANSI escape handling | ⚠️ Partial | Rich markup only |
| Independent terminal state | ❌ Not implemented | Shared app state |

---

## 3. Gap Analysis

### 3.1 Critical Gaps

#### Gap 1: No PTY Support

**Current**: Subprocesses are created with `stdout=PIPE, stderr=PIPE`
**Required**: Subprocesses need PTY allocation for proper terminal behavior

**Impact**:
- Programs detect they're not running in a terminal and disable colors/progress
- Interactive prompts may not work correctly
- Terminal-specific features (cursor movement, clearing) don't work

#### Gap 2: No Stdin Handling

**Current**: No mechanism to send input to running subprocesses
**Required**: Each tab must capture keystrokes and send to its subprocess

**Impact**:
- Cannot respond to "Do you want to continue?" prompts
- Cannot enter sudo passwords
- Cannot interact with any interactive program

#### Gap 3: No Terminal Emulation

**Current**: RichLog displays text with Rich markup
**Required**: Full terminal emulator with ANSI escape sequence parsing

**Impact**:
- Cannot display programs that use cursor positioning
- Cannot handle terminal clearing/scrolling commands
- Cannot display progress bars that use carriage return

#### Gap 4: Shared Input Focus

**Current**: All keyboard input goes to Textual app
**Required**: Non-navigation keys go to active tab's subprocess

**Impact**:
- Cannot type in one tab while another runs
- Cannot send Ctrl+C to specific subprocess

### 3.2 Gap Severity Assessment

| Gap | Severity | Workaround Possible? |
|-----|----------|---------------------|
| No PTY support | **Critical** | No - fundamental limitation |
| No stdin handling | **Critical** | No - fundamental limitation |
| No terminal emulation | **High** | Partial - can parse some ANSI |
| Shared input focus | **High** | No - requires architecture change |

---

## 4. Architectural Impact Assessment

### 4.1 Components Requiring Changes

| Component | Change Required | Scope |
|-----------|-----------------|-------|
| `ui/ui/tabbed_run.py` | **Major rewrite** | Replace RichLog with terminal widget |
| `plugins/plugins/base.py` | **Major changes** | Add PTY-based execution |
| `core/core/streaming.py` | Minor changes | Add raw byte events |
| `core/core/interfaces.py` | Minor changes | Add stdin method to plugin interface |
| New: Terminal widget | **New component** | Full terminal emulator widget |
| New: PTY manager | **New component** | PTY allocation and management |

### 4.2 Dependency Changes

Current dependencies:
- `textual` - TUI framework
- `rich` - Text formatting

New dependencies required:
- `pyte` or `vt100` - Terminal emulator library (for parsing ANSI sequences)
- `ptyprocess` or native `pty` module - PTY management

### 4.3 Complexity Assessment

| Aspect | Current | After Change | Increase |
|--------|---------|--------------|----------|
| UI complexity | Medium | **High** | +50% |
| Execution complexity | Medium | **High** | +40% |
| Testing complexity | Medium | **High** | +60% |
| Maintenance burden | Low | **Medium** | +30% |

### 4.4 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Textual doesn't support terminal widgets | Medium | High | May need custom widget or different framework |
| PTY handling complexity | High | Medium | Use established libraries (ptyprocess) |
| Cross-platform issues | Medium | Medium | Linux-first, test on other platforms |
| Performance with multiple PTYs | Low | Medium | Limit concurrent tabs |
| Input routing bugs | Medium | High | Comprehensive testing |

---

## 5. Recommendation

### 5.1 Verdict: Architecture Re-evaluation Required

The interactive tabs requirement represents a **fundamental shift** in the application's execution model:

1. **From**: Text-based output display with streaming
2. **To**: Full terminal emulation with bidirectional I/O

This is not an incremental enhancement but a **paradigm change** that affects:
- How subprocesses are created and managed
- How output is captured and displayed
- How user input is handled
- The fundamental UI widget architecture

### 5.2 Justification

1. **Core Assumption Invalidated**: The current architecture assumes plugins produce text output that is displayed after processing. The new requirement assumes plugins are interactive terminal sessions.

2. **Interface Changes Required**: The `UpdatePlugin` interface needs new methods for stdin handling, which affects all plugins.

3. **UI Framework Evaluation Needed**: Textual may or may not support the required terminal emulation. This needs investigation.

4. **New Components Required**: PTY manager, terminal emulator widget, input router - these are substantial new components.

### 5.3 Recommended Next Steps

1. **Investigate Textual Terminal Support**: Research if Textual supports embedding terminal emulators or if a custom widget is needed.

2. **Prototype PTY Execution**: Create a proof-of-concept that runs a plugin with PTY and captures output.

3. **Evaluate Alternative Approaches**:
   - Option A: Full terminal emulation per tab
   - Option B: Hybrid approach (terminal for interactive, RichLog for non-interactive)
   - Option C: External terminal multiplexer integration (tmux-like)

4. **Update Architecture Documents**: Create a new architecture plan for the interactive tabs feature.

5. **Revise Timeline**: The 12-week implementation plan in the architecture refinement document needs revision.

---

## 6. Proposed Architecture Changes

### 6.1 High-Level Architecture (Proposed)

```
Proposed Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                      InteractiveTabbedApp (Textual)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    TabbedContent (Tab Container)                     │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │    │
│  │  │   TabPane   │  │   TabPane   │  │   TabPane   │                  │    │
│  │  │  (apt)      │  │  (flatpak)  │  │  (pipx)     │                  │    │
│  │  │             │  │             │  │             │                  │    │
│  │  │ ┌─────────┐ │  │ ┌─────────┐ │  │ ┌─────────┐ │                  │    │
│  │  │ │Terminal │ │  │ │Terminal │ │  │ │Terminal │ │  ← Full terminal │    │
│  │  │ │Widget   │ │  │ │Widget   │ │  │ │Widget   │ │    emulation     │    │
│  │  │ │(pyte)   │ │  │ │(pyte)   │ │  │ │(pyte)   │ │                  │    │
│  │  │ └────┬────┘ │  │ └────┬────┘ │  │ └────┬────┘ │                  │    │
│  │  └──────┼──────┘  └──────┼──────┘  └──────┼──────┘                  │    │
│  └─────────┼────────────────┼───────────────┼──────────────────────────┘    │
│            │                │               │                                │
│            ▼                ▼               ▼                                │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      PTY Session Manager                             │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │    │
│  │  │ PTY Session │  │ PTY Session │  │ PTY Session │                  │    │
│  │  │ (apt)       │  │ (flatpak)   │  │ (pipx)      │                  │    │
│  │  │ stdin/out   │  │ stdin/out   │  │ stdin/out   │                  │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                         Input Router                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  - Tab navigation keys → App                                         │    │
│  │  - All other keys → Active tab's PTY stdin                           │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 New Components Required

#### 6.2.1 Terminal Widget

A Textual widget that:
- Renders terminal screen buffer (from pyte)
- Handles resize events
- Supports scrollback buffer
- Displays cursor

#### 6.2.2 PTY Session Manager

A component that:
- Allocates PTY for each plugin
- Manages PTY lifecycle
- Handles resize signals (SIGWINCH)
- Routes I/O between PTY and terminal widget

#### 6.2.3 Input Router

A component that:
- Intercepts all keyboard input
- Routes navigation keys to app
- Routes other keys to active PTY
- Handles special key combinations

### 6.3 Plugin Interface Changes

```python
# Proposed additions to UpdatePlugin interface

class UpdatePlugin(ABC):
    # ... existing methods ...

    @property
    def supports_interactive(self) -> bool:
        """Check if this plugin supports interactive mode with PTY."""
        return False

    async def execute_interactive(
        self,
        pty_master_fd: int,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute with PTY for interactive mode.

        Args:
            pty_master_fd: File descriptor for PTY master
            dry_run: If True, simulate the update

        Yields:
            StreamEvent objects (for progress tracking)
        """
        raise NotImplementedError
```

### 6.4 Estimated Additional Effort

| Component | Estimated Effort |
|-----------|------------------|
| Terminal Widget | 2-3 weeks |
| PTY Session Manager | 1-2 weeks |
| Input Router | 1 week |
| Plugin Interface Changes | 1 week |
| Testing & Integration | 2-3 weeks |
| Documentation | 1 week |
| **Total Additional** | **8-11 weeks** |

This is **in addition to** the existing 12-week plan, bringing the total to approximately **20-23 weeks**.

---

## Appendix A: Research Topics

The following topics require web research before implementation:

1. **Textual Terminal Widget Support**: Does Textual have built-in terminal emulation or examples?
2. **pyte Library Current State**: Is pyte still maintained? Any alternatives?
3. **ptyprocess vs pty module**: Which is better for async PTY management?
4. **Cross-platform PTY**: How to handle Windows (ConPTY)?
5. **Textual Input Handling**: How to intercept and route keyboard input?

---

## Appendix B: References

1. [Update-All Architecture Refinement Plan](update-all-architecture-refinement-plan.md)
2. [Update-All Python Implementation Plan](update-all-python-plan.md)
3. [Textual Framework Documentation](https://textual.textualize.io/)
4. [pyte - Terminal Emulator](https://github.com/selectel/pyte)
5. [ptyprocess - PTY Management](https://github.com/pexpect/ptyprocess)

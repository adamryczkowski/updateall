# UI Revision Plan: Phase-Based Interactive Updates

**Date:** January 9, 2026
**Version:** 1.0
**Status:** Draft
**Related Documents:**
- [Interactive Tabs Implementation Plan](interactive-tabs-implementation-plan.md)
- [Interactive Tabs Architecture Evaluation](interactive-tabs-architecture-evaluation.md)

---

## Executive Summary

This document outlines the implementation plan for enhancing the interactive UI with phase-based execution, visual status indicators, comprehensive metrics display, and improved user control. The plan builds upon the existing interactive tabs infrastructure (Phase 4 complete) and introduces new features for better visibility and control of the update process.

---

## Table of Contents

1. [Requirements Overview](#1-requirements-overview)
2. [Architecture Changes](#2-architecture-changes)
3. [Feature Specifications](#3-feature-specifications)
4. [Implementation Phases](#4-implementation-phases)
5. [Test Specifications](#5-test-specifications)
6. [Risk Analysis](#6-risk-analysis)
7. [Timeline](#7-timeline)

---

## 1. Requirements Overview

### 1.1 Feature Summary

| # | Feature | Priority | Complexity |
|---|---------|----------|------------|
| 1 | Phase labels on tabs (Update/Download/Upgrade) | **High** | Low |
| 2 | `--pause-phases` command-line switch | **High** | Medium |
| 3 | Color-coded tab status indicators | **High** | Medium |
| 4 | Per-tab status bar with metrics | **High** | High |
| 5 | Hot keys for control actions | **Medium** | Medium |
| 6 | `--concurrency` command-line switch | **Medium** | Low |

### 1.2 Phase Definitions

The update process consists of three distinct phases as defined in [`core/core/streaming.py`](../core/core/streaming.py):

| Phase | Description | Typical Operations |
|-------|-------------|-------------------|
| **CHECK** | Version checking and update detection | Query package managers for available updates |
| **DOWNLOAD** | Package download | Download packages to cache |
| **EXECUTE** | Installation/upgrade | Apply updates to the system |

**Note:** The current codebase uses `Phase.CHECK`, `Phase.DOWNLOAD`, and `Phase.EXECUTE`. The user-facing labels will be "Update", "Download", and "Upgrade" respectively for clarity.

---

## 2. Architecture Changes

### 2.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    InteractiveTabbedApp (Enhanced)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    PhaseAwareTabbedContent                           │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │    │
│  │  │   PhaseTab       │  │   PhaseTab       │  │   PhaseTab       │    │    │
│  │  │ [🟢 apt]        │  │ [🟡 flatpak]    │  │ [⬜ pipx]        │    │    │
│  │  │ Phase: Upgrade  │  │ Phase: Download │  │ Phase: Pending  │    │    │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    PhaseStatusBar (New)                              │    │
│  │  Status: In Progress | ETA: 2m 30s | CPU: 45% | Mem: 128MB          │    │
│  │  Items: 15/42 | Net: 150MB ↓ | Disk: 45MB | Peak Mem: 256MB         │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    PhaseController (New)                             │    │
│  │  - Pause/Resume phase transitions                                    │    │
│  │  - Coordinate phase execution across tabs                            │    │
│  │  - Track cumulative metrics per phase                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `PhaseController` | `ui/ui/phase_controller.py` | Manages phase transitions and pause/resume |
| `PhaseStatusBar` | `ui/ui/phase_status_bar.py` | Displays per-tab metrics and status |
| `PhaseTab` | `ui/ui/phase_tab.py` | Enhanced tab with phase label and color |
| `MetricsAggregator` | `ui/ui/metrics_aggregator.py` | Collects and aggregates runtime metrics |

### 2.3 Modified Components

| Component | Changes |
|-----------|---------|
| [`InteractiveTabbedApp`](../ui/ui/interactive_tabbed_run.py) | Add phase controller, status bar, hot keys |
| [`TerminalPane`](../ui/ui/terminal_pane.py) | Add phase tracking, metrics collection |
| [`KeyBindings`](../ui/ui/key_bindings.py) | Add new hot key bindings |
| [`cli/main.py`](../cli/cli/main.py) | Add `--pause-phases` and `--concurrency` options |

---

## 3. Feature Specifications

### 3.1 Feature 1: Phase Labels on Tabs

**Requirement:** Each tab should clearly indicate the phase of the process ("Update", "Download", "Upgrade").

**Implementation:**

```python
# ui/ui/phase_tab.py

from enum import Enum

class DisplayPhase(str, Enum):
    """User-facing phase names."""
    UPDATE = "Update"      # Maps to Phase.CHECK
    DOWNLOAD = "Download"  # Maps to Phase.DOWNLOAD
    UPGRADE = "Upgrade"    # Maps to Phase.EXECUTE
    PENDING = "Pending"    # Not yet started
    COMPLETE = "Complete"  # All phases done

PHASE_MAPPING = {
    Phase.CHECK: DisplayPhase.UPDATE,
    Phase.DOWNLOAD: DisplayPhase.DOWNLOAD,
    Phase.EXECUTE: DisplayPhase.UPGRADE,
}
```

**Tab Label Format:**
```
[status_icon] plugin_name (phase_name)
```

Example: `🟢 apt (Upgrade)` or `🟡 flatpak (Download)`

### 3.2 Feature 2: `--pause-phases` Command-Line Switch

**Requirement:** Add a command-line switch that starts each phase paused, requiring user confirmation to proceed to the next phase, starting with "Update".

**CLI Interface:**

```python
# cli/cli/main.py

@app.command()
def run(
    # ... existing options ...
    pause_phases: Annotated[
        bool,
        typer.Option(
            "--pause-phases",
            "-P",
            help="Pause before each phase, requiring confirmation to proceed.",
        ),
    ] = False,
) -> None:
    ...
```

**Behavior:**

1. When `--pause-phases` is enabled:
   - Before starting the CHECK phase: Display "Press Enter to start Update phase..."
   - After CHECK completes: Display "Update phase complete. Press Enter to start Download phase..."
   - After DOWNLOAD completes: Display "Download phase complete. Press Enter to start Upgrade phase..."

2. The pause applies globally to all plugins in that phase.

3. Status bar shows: `Status: Paused (waiting for confirmation)` with indication of next phase.

**Implementation:**

```python
# ui/ui/phase_controller.py

@dataclass
class PhaseController:
    """Controls phase transitions with optional pause points."""

    pause_between_phases: bool = False
    current_phase: Phase | None = None
    phase_paused: bool = False

    async def request_phase_transition(self, next_phase: Phase) -> bool:
        """Request transition to next phase.

        Returns:
            True if transition approved, False if paused.
        """
        if self.pause_between_phases:
            self.phase_paused = True
            # Wait for user confirmation
            await self._wait_for_confirmation()
            self.phase_paused = False

        self.current_phase = next_phase
        return True
```

### 3.3 Feature 3: Color-Coded Tab Status

**Requirement:** Color-coding of tabs to indicate their status.

**Color Scheme:**

| Status | Color | CSS Class | Description |
|--------|-------|-----------|-------------|
| Completed | Green (`#00ff00`) | `.tab-completed` | Phase finished successfully |
| Current/Running | Yellow (`#ffff00`) | `.tab-running` | Currently executing |
| Error | Red (`#ff0000`) | `.tab-error` | Phase encountered an error |
| Pending (Ready) | Grey (`#808080`) | `.tab-pending` | Ready to start, dependencies met |
| Locked | Dark Grey (`#404040`) | `.tab-locked` | Cannot start due to unmet dependencies/mutexes |

**Implementation:**

```python
# ui/ui/phase_tab.py

class TabStatus(str, Enum):
    """Visual status of a tab."""
    COMPLETED = "completed"
    RUNNING = "running"
    ERROR = "error"
    PENDING = "pending"
    LOCKED = "locked"

TAB_STATUS_COLORS = {
    TabStatus.COMPLETED: "green",
    TabStatus.RUNNING: "yellow",
    TabStatus.ERROR: "red",
    TabStatus.PENDING: "grey",
    TabStatus.LOCKED: "dim grey",
}

TAB_STATUS_ICONS = {
    TabStatus.COMPLETED: "🟢",
    TabStatus.RUNNING: "🟡",
    TabStatus.ERROR: "🔴",
    TabStatus.PENDING: "⬜",
    TabStatus.LOCKED: "🔒",
}
```

**CSS Styling:**

```css
/* ui/ui/interactive_tabbed_run.py CSS section */

.tab-completed {
    background: $success;
    color: $text;
}

.tab-running {
    background: $warning;
    color: $text;
}

.tab-error {
    background: $error;
    color: $text;
}

.tab-pending {
    background: $surface-darken-1;
    color: $text-muted;
}

.tab-locked {
    background: $surface-darken-2;
    color: $text-disabled;
}
```

**Dependency/Mutex Status Determination:**

The locked status is determined by checking:
1. Plugin dependencies via [`PluginConfig.dependencies`](../core/core/models.py:53)
2. Mutex constraints via [`MutexManager`](../core/core/mutex.py)
3. Resource availability via [`ResourceController`](../core/core/resource.py)

```python
def determine_tab_status(
    plugin_name: str,
    pane_state: PaneState,
    phase_controller: PhaseController,
    mutex_manager: MutexManager,
    dependency_graph: ExecutionDAG,
) -> TabStatus:
    """Determine the visual status of a tab."""

    # Check completion states
    if pane_state == PaneState.SUCCESS:
        return TabStatus.COMPLETED
    if pane_state == PaneState.FAILED:
        return TabStatus.ERROR
    if pane_state == PaneState.RUNNING:
        return TabStatus.RUNNING

    # Check if locked due to dependencies
    unmet_deps = dependency_graph.get_unmet_dependencies(plugin_name)
    if unmet_deps:
        return TabStatus.LOCKED

    # Check if locked due to mutex
    if not mutex_manager.can_acquire(plugin_name):
        return TabStatus.LOCKED

    return TabStatus.PENDING
```

### 3.4 Feature 4: Per-Tab Status Bar

**Requirement:** Add per-tab information in the bottom status bar.

**Status Bar Layout:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Status: In Progress [⏸ Pause after phase] | ETA: 2m 30s (±15s)             │
│ CPU: 45% | Mem: 128/256MB (peak) | Items: 15/42 packages                   │
│ Network: 150.2 MB ↓ | Disk I/O: 45.8 MB | CPU Time: 1m 23s                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Metrics Tracked:**

| Metric | Source | Update Frequency |
|--------|--------|------------------|
| Status | `PaneState` + `PhaseController` | Real-time |
| Pause indicator | `PhaseController.pause_between_phases` | Real-time |
| ETA | `stats.estimator` + historical data | Every 5s |
| CPU usage | `psutil.Process.cpu_percent()` | Every 1s |
| Memory usage | `psutil.Process.memory_info()` | Every 1s |
| Peak memory | Max of memory samples | Cumulative |
| Items processed | `ProgressEvent.items_completed/items_total` | Real-time |
| Network bandwidth | `psutil.net_io_counters()` delta | Cumulative |
| Disk I/O | `psutil.disk_io_counters()` delta | Cumulative |
| CPU time | `psutil.Process.cpu_times()` | Cumulative |

**Implementation:**

```python
# ui/ui/phase_status_bar.py

@dataclass
class PhaseMetrics:
    """Metrics for a single phase execution."""

    # Status
    status: str = "Pending"
    pause_after_phase: bool = False

    # Time estimates
    eta_seconds: float | None = None
    eta_error_seconds: float | None = None

    # Resource usage (current)
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_peak_mb: float = 0.0

    # Progress
    items_completed: int = 0
    items_total: int | None = None

    # Cumulative metrics
    network_bytes: int = 0
    disk_io_bytes: int = 0
    cpu_time_seconds: float = 0.0


class PhaseStatusBar(Static):
    """Status bar widget showing per-tab metrics."""

    DEFAULT_CSS = """
    PhaseStatusBar {
        height: 3;
        dock: bottom;
        padding: 0 1;
        background: $surface;
        border-top: solid $primary;
    }
    """

    def __init__(self, pane_id: str) -> None:
        super().__init__()
        self.pane_id = pane_id
        self.metrics = PhaseMetrics()
        self._metrics_aggregator: MetricsAggregator | None = None

    def update_metrics(self, metrics: PhaseMetrics) -> None:
        """Update the displayed metrics."""
        self.metrics = metrics
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the status bar content."""
        m = self.metrics

        # Line 1: Status and ETA
        pause_indicator = " [⏸ Pause after phase]" if m.pause_after_phase else ""
        eta_str = self._format_eta(m.eta_seconds, m.eta_error_seconds)
        line1 = f"Status: {m.status}{pause_indicator} | ETA: {eta_str}"

        # Line 2: Resource usage
        items_str = self._format_items(m.items_completed, m.items_total)
        line2 = f"CPU: {m.cpu_percent:.0f}% | Mem: {m.memory_mb:.0f}/{m.memory_peak_mb:.0f}MB (peak) | {items_str}"

        # Line 3: Cumulative metrics
        net_str = self._format_bytes(m.network_bytes)
        disk_str = self._format_bytes(m.disk_io_bytes)
        cpu_time_str = self._format_duration(m.cpu_time_seconds)
        line3 = f"Network: {net_str} ↓ | Disk I/O: {disk_str} | CPU Time: {cpu_time_str}"

        self.update(f"{line1}\n{line2}\n{line3}")
```

**Error Indication:**

When metrics cannot be collected (e.g., process not accessible), display with error indicator:

```
ETA: N/A (error) | CPU: N/A | Mem: N/A
```

### 3.5 Feature 5: Hot Keys

**Requirement:** Hot keys for pause/resume, retry, save logs, and help.

**Key Bindings:**

| Action | Primary Key | Alternative | Description |
|--------|-------------|-------------|-------------|
| Pause/Resume next phase | `Ctrl+P` | `F8` | Toggle pause before next phase |
| Retry current phase | `Ctrl+R` | `F9` | Retry if phase encountered error |
| Save logs | `Ctrl+S` | `F10` | Save current tab's logs to file |
| Help/Documentation | `Ctrl+H` | `F1` | Show help overlay |

**Implementation:**

```python
# ui/ui/key_bindings.py (additions)

class KeyBindings:
    """Configurable key bindings for the interactive UI."""

    # ... existing bindings ...

    # Phase control bindings
    pause_resume: str = "ctrl+p"
    pause_resume_alt: str = "f8"

    retry_phase: str = "ctrl+r"
    retry_phase_alt: str = "f9"

    save_logs: str = "ctrl+s"
    save_logs_alt: str = "f10"

    show_help: str = "ctrl+h"
    show_help_alt: str = "f1"
```

**Action Handlers:**

```python
# ui/ui/interactive_tabbed_run.py (additions)

class InteractiveTabbedApp(App[None]):

    BINDINGS: ClassVar[list[BindingType]] = [
        # ... existing bindings ...
        Binding("ctrl+p", "toggle_pause", "Pause/Resume", show=True),
        Binding("f8", "toggle_pause", "Pause/Resume", show=False),
        Binding("ctrl+r", "retry_phase", "Retry", show=True),
        Binding("f9", "retry_phase", "Retry", show=False),
        Binding("ctrl+s", "save_logs", "Save Logs", show=True),
        Binding("f10", "save_logs", "Save Logs", show=False),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("f1", "show_help", "Help", show=False),
    ]

    def action_toggle_pause(self) -> None:
        """Toggle pause before next phase."""
        if self._phase_controller:
            self._phase_controller.toggle_pause()
            status = "enabled" if self._phase_controller.pause_between_phases else "disabled"
            self.notify(f"Phase pause {status}")

    async def action_retry_phase(self) -> None:
        """Retry the current phase if it encountered an error."""
        if self.active_pane and self.active_pane.state == PaneState.FAILED:
            await self.active_pane.retry()
            self.notify("Retrying phase...")
        else:
            self.notify("No failed phase to retry", severity="warning")

    async def action_save_logs(self) -> None:
        """Save logs for the current tab."""
        if self.active_pane:
            log_path = await self.active_pane.save_logs()
            self.notify(f"Logs saved to {log_path}")

    def action_show_help(self) -> None:
        """Show help overlay."""
        help_text = """
        Keyboard Shortcuts:

        Navigation:
          Ctrl+Tab / Ctrl+Shift+Tab  - Next/Previous tab
          Alt+1-9                    - Go to tab N
          Shift+PgUp/PgDn            - Scroll history

        Phase Control:
          Ctrl+P / F8               - Toggle pause before next phase
          Ctrl+R / F9               - Retry failed phase
          Ctrl+S / F10              - Save logs to file
          Ctrl+H / F1               - Show this help

        Application:
          Ctrl+Q                    - Quit
        """
        self.notify(help_text, title="Help", timeout=10)
```

### 3.6 Feature 6: `--concurrency` Command-Line Switch

**Requirement:** Command-line switch to limit the concurrency level for phases that support parallel processing.

**CLI Interface:**

```python
# cli/cli/main.py

import os

@app.command()
def run(
    # ... existing options ...
    concurrency: Annotated[
        int | None,
        typer.Option(
            "--concurrency",
            "-j",
            help="Maximum concurrent operations. Default: number of CPU cores.",
            min=1,
            max=32,
        ),
    ] = None,
) -> None:
    # Default to CPU count if not specified
    max_concurrent = concurrency or os.cpu_count() or 4
    ...
```

**Integration with Existing Infrastructure:**

The concurrency limit integrates with:
1. [`ResourceLimits.max_parallel_tasks`](../core/core/resource.py) - Already supports this
2. [`ParallelOrchestrator`](../core/core/parallel_orchestrator.py) - Uses ResourceController
3. [`GlobalConfig.max_parallel`](../core/core/models.py:67) - Configuration model

```python
# core/core/resource.py (existing)

@dataclass
class ResourceLimits:
    """Resource limits for parallel execution."""
    max_parallel_tasks: int = 4  # Will be set from --concurrency
    max_memory_mb: int = 1024
    max_cpu_percent: float = 80.0
```

---

## 4. Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)

**Goal:** Establish phase controller and metrics aggregation

**Deliverables:**
- [ ] `ui/ui/phase_controller.py` - Phase transition management
- [ ] `ui/ui/metrics_aggregator.py` - Runtime metrics collection
- [ ] `ui/tests/test_phase_controller.py` - Unit tests
- [ ] `ui/tests/test_metrics_aggregator.py` - Unit tests

### Phase 2: Visual Enhancements (Week 3-4)

**Goal:** Implement tab coloring and phase labels

**Deliverables:**
- [ ] `ui/ui/phase_tab.py` - Enhanced tab widget
- [ ] Update `ui/ui/interactive_tabbed_run.py` - Integrate phase tabs
- [ ] `ui/tests/test_phase_tab.py` - Widget tests
- [ ] CSS styling for tab states

### Phase 3: Status Bar (Week 5-6)

**Goal:** Implement per-tab status bar with metrics

**Deliverables:**
- [ ] `ui/ui/phase_status_bar.py` - Status bar widget
- [ ] Integration with `TerminalPane`
- [ ] `ui/tests/test_phase_status_bar.py` - Widget tests
- [ ] Error handling for unavailable metrics

### Phase 4: Hot Keys and CLI (Week 7-8)

**Goal:** Add hot keys and command-line options

**Deliverables:**
- [ ] Update `ui/ui/key_bindings.py` - New bindings
- [ ] Update `cli/cli/main.py` - New CLI options
- [ ] Log saving functionality
- [ ] Help overlay
- [ ] `ui/tests/test_hot_keys.py` - Key binding tests
- [ ] `cli/tests/test_cli_options.py` - CLI tests

### Phase 5: Integration and Polish (Week 9-10)

**Goal:** Full integration and documentation

**Deliverables:**
- [ ] End-to-end integration testing
- [ ] Performance optimization
- [ ] Documentation updates
- [ ] Migration guide for existing users

---

## 5. Test Specifications

### 5.1 Phase Controller Tests

```python
class TestPhaseController:
    """Tests for PhaseController."""

    async def test_phase_transition_without_pause(self) -> None:
        """Test normal phase transition."""
        # Given: Controller with pause disabled
        # When: Requesting transition
        # Then: Transition should proceed immediately

    async def test_phase_transition_with_pause(self) -> None:
        """Test paused phase transition."""
        # Given: Controller with pause enabled
        # When: Requesting transition
        # Then: Should wait for confirmation

    async def test_toggle_pause(self) -> None:
        """Test toggling pause state."""
        # Given: Controller
        # When: Toggling pause
        # Then: State should change
```

### 5.2 Tab Status Tests

```python
class TestTabStatus:
    """Tests for tab status determination."""

    def test_completed_status(self) -> None:
        """Test completed tab shows green."""

    def test_running_status(self) -> None:
        """Test running tab shows yellow."""

    def test_error_status(self) -> None:
        """Test error tab shows red."""

    def test_locked_due_to_dependency(self) -> None:
        """Test tab locked by unmet dependency shows dark grey."""

    def test_locked_due_to_mutex(self) -> None:
        """Test tab locked by mutex shows dark grey."""
```

### 5.3 Status Bar Tests

```python
class TestPhaseStatusBar:
    """Tests for PhaseStatusBar widget."""

    def test_displays_status(self) -> None:
        """Test status is displayed."""

    def test_displays_eta_with_error(self) -> None:
        """Test ETA with error margin is displayed."""

    def test_displays_resource_usage(self) -> None:
        """Test CPU/memory usage is displayed."""

    def test_handles_unavailable_metrics(self) -> None:
        """Test graceful handling of unavailable metrics."""
```

---

## 6. Risk Analysis

### 6.1 High Risks

| Risk | Mitigation |
|------|------------|
| **Metrics collection overhead** | Use sampling (1s intervals), async collection |
| **PTY process metrics access** | Fall back to N/A display if inaccessible |
| **Phase coordination complexity** | Use existing `PhaseEvent` infrastructure |

### 6.2 Medium Risks

| Risk | Mitigation |
|------|------------|
| **Key binding conflicts** | Allow user customization via config |
| **Status bar space constraints** | Responsive layout, abbreviations |
| **Color accessibility** | Use icons in addition to colors |

### 6.3 Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| `psutil` | ^5.9.0 | Process metrics collection |
| `textual` | >=7.0.0,<8.0.0 | Already in use |

---

## 7. Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1-2 | Core Infrastructure | PhaseController, MetricsAggregator |
| 3-4 | Visual Enhancements | PhaseTab, color coding |
| 5-6 | Status Bar | PhaseStatusBar, metrics display |
| 7-8 | Hot Keys and CLI | Key bindings, CLI options |
| 9-10 | Integration | E2E tests, documentation |

---

## Appendix A: Dependencies to Add

Add to `ui/pyproject.toml`:

```toml
[tool.poetry.dependencies]
psutil = "^5.9.0"  # For process metrics collection
```

---

## Appendix B: Configuration Schema

Add to `~/.config/update-all/config.toml`:

```toml
[ui]
# Phase control
pause_between_phases = false

# Concurrency
max_concurrent = 4  # Or "auto" for CPU count

[ui.colors]
# Custom tab colors (optional)
completed = "#00ff00"
running = "#ffff00"
error = "#ff0000"
pending = "#808080"
locked = "#404040"

[ui.keybindings]
# Custom key bindings (optional)
pause_resume = "ctrl+p"
retry_phase = "ctrl+r"
save_logs = "ctrl+s"
show_help = "ctrl+h"
```

---

## Appendix C: Log File Format

When saving logs via `Ctrl+S`:

```
Filename: update-all-{plugin_name}-{timestamp}.log
Location: ~/.local/share/update-all/logs/

Content:
========================================
Update-All Log: {plugin_name}
Date: {timestamp}
Phase: {current_phase}
Status: {status}
========================================

--- Terminal Output ---
{full terminal output with ANSI codes stripped}

--- Metrics Summary ---
Duration: {duration}
CPU Time: {cpu_time}
Peak Memory: {peak_memory}
Network: {network_bytes}
Disk I/O: {disk_io_bytes}
Items Processed: {items_completed}/{items_total}
Exit Code: {exit_code}
```

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-09 | AI Assistant | Initial version |

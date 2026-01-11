# UI Latency Improvement Implementation Plan

This document provides a detailed implementation plan for improving UI latency in the interactive update screen, based on the recommendations in [`docs/ui-latency-study.md`](ui-latency-study.md).

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current Architecture Analysis](#current-architecture-analysis)
3. [Target Architecture](#target-architecture)
4. [Implementation Milestones](#implementation-milestones)
5. [Testing Strategy](#testing-strategy)
6. [Risk Mitigation](#risk-mitigation)
7. [Appendix: File Reference](#appendix-file-reference)

---

## Executive Summary

### Problem Statement

The current UI refresh rate is **1 Hz** (1 update per second), causing a perceptible lag in the status bar and metrics display. This is because UI updates are coupled to metrics collection, which uses expensive `psutil` calls.

### Solution Overview

Decouple UI rendering from metrics collection:
- **Metrics Collection**: Keep at 0.5-1.0 Hz (expensive `psutil` calls)
- **UI Rendering**: Increase to 30 Hz using Textual's `auto_refresh` mechanism

### Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| Status bar refresh rate | 1 Hz | 30 Hz |
| Perceived UI latency | 1000ms | ~33ms |
| Metrics collection rate | 1 Hz | 0.5-1.0 Hz (unchanged) |
| CPU overhead | Low | Slightly higher |

---

## Current Architecture Analysis

### Component Overview

The UI latency issue stems from the tight coupling between metrics collection and UI updates in the following components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Current Architecture                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  TerminalPane._metrics_update_loop()                        │
│       │                                                      │
│       ├──► MetricsCollector.collect()  [psutil calls]       │
│       │         │                                            │
│       │         └──► Updates _metrics and _cached_metrics   │
│       │                                                      │
│       ├──► PhaseStatusBar.collect_and_update()              │
│       │         │                                            │
│       │         └──► _refresh_display()                     │
│       │                                                      │
│       └──► asyncio.sleep(1.0)  ◄── BOTTLENECK               │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Component | Role |
|------|-----------|------|
| [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py) | `TerminalPane` | Container widget, manages PTY and metrics loop |
| [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py) | `PhaseStatusBar` | Status bar widget with metrics display |
| [`ui/ui/metrics.py`](../ui/ui/metrics.py) | `MetricsCollector` | Collects CPU, memory, network metrics via psutil |
| [`ui/ui/interactive_tabbed_run.py`](../ui/ui/interactive_tabbed_run.py) | `InteractiveTabbedApp` | Main application class |

### Current Implementation Details

1. **[`PaneConfig`](../ui/ui/terminal_pane.py:56)**: Contains `metrics_update_interval` (default 1.0s) and `ui_refresh_rate` (default 30.0 Hz)

2. **[`MetricsCollector`](../ui/ui/metrics.py:432)**: Has `MIN_UPDATE_INTERVAL` of 0.5s, collects metrics via psutil

3. **[`PhaseStatusBar`](../ui/ui/phase_status_bar.py:88)**: Already has `auto_refresh` support and `automatic_refresh()` method

4. **[`TerminalPane._metrics_update_loop()`](../ui/ui/terminal_pane.py:646)**: Currently runs metrics collection in a thread but still controls UI update timing

### Partial Implementation Status

The codebase already has **partial implementation** of the decoupled architecture:

- ✅ `PhaseStatusBar` has `auto_refresh` and `automatic_refresh()` implemented
- ✅ `MetricsCollector` has `cached_metrics` property for fast reads
- ✅ `PaneConfig` has `ui_refresh_rate` configuration
- ⚠️ `_metrics_update_loop` still calls `collect_and_update()` which triggers UI refresh
- ⚠️ UI refresh is still tied to the metrics collection interval

---

## Target Architecture

### Design Principles

1. **Separation of Concerns**: Metrics collection and UI rendering are independent
2. **Modularity**: Each component has a single, well-defined purpose
3. **Maintainability**: Simple, testable code with clear interfaces
4. **Backward Compatibility**: Existing functionality preserved

### Target Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Target Architecture                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Background Thread (0.5-1.0 Hz)                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  TerminalPane._metrics_update_loop()                │    │
│  │       │                                              │    │
│  │       ├──► MetricsCollector.collect()               │    │
│  │       │         │                                    │    │
│  │       │         └──► Updates _cached_metrics        │    │
│  │       │                                              │    │
│  │       └──► asyncio.sleep(1.0)                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          │ (shared data)                     │
│                          ▼                                   │
│  Main Thread (30 Hz via auto_refresh)                       │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  PhaseStatusBar.automatic_refresh()                 │    │
│  │       │                                              │    │
│  │       ├──► Read MetricsCollector.cached_metrics     │    │
│  │       │                                              │    │
│  │       └──► _refresh_display()                       │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Key Changes

1. **Remove UI update from metrics loop**: `_metrics_update_loop()` only collects metrics
2. **Enable auto_refresh on PhaseStatusBar**: Already implemented, just needs verification
3. **Use cached_metrics for display**: `automatic_refresh()` reads from cache

---

## Implementation Milestones

### Milestone 1: Verify and Complete Decoupled Architecture

**Goal**: Ensure the existing partial implementation is working correctly

**Duration**: 1-2 days

#### Tasks

- [ ] **1.1 Audit current implementation**
  - Review `PhaseStatusBar.on_mount()` to verify `auto_refresh` is set
  - Review `PhaseStatusBar.automatic_refresh()` to verify it reads from `cached_metrics`
  - Review `_metrics_update_loop()` to verify it only collects metrics

- [ ] **1.2 Fix any gaps in the implementation**
  - Ensure `_metrics_update_loop()` does NOT call `collect_and_update()`
  - Ensure `automatic_refresh()` reads from `_metrics_collector.cached_metrics`
  - Ensure `auto_refresh` is set to `1.0 / ui_refresh_rate`

- [ ] **1.3 Add logging for debugging**
  - Add debug logging to track refresh rates
  - Log when metrics are collected vs when UI is refreshed

#### Files to Modify

| File | Changes |
|------|---------|
| [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py) | Verify `_metrics_update_loop()` doesn't trigger UI updates |
| [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py) | Verify `automatic_refresh()` uses cached metrics |

#### Test Criteria

- [ ] `PhaseStatusBar.auto_refresh` is set to ~0.033s (30 Hz)
- [ ] UI refreshes at 30 Hz independent of metrics collection
- [ ] Metrics are collected at 1 Hz in background thread
- [ ] All existing tests pass (`just validate`)

---

### Milestone 2: Add UI Latency Tests

**Goal**: Create automated tests to measure and verify UI latency

**Duration**: 1-2 days

#### Tasks

- [ ] **2.1 Create latency measurement test file**
  - Create `ui/tests/test_ui_latency_measurement.py`
  - Implement `LatencyReport` dataclass for statistics
  - Implement `measure_render_latency()` helper function
  - Implement `measure_input_latency()` helper function

- [ ] **2.2 Implement idle latency test**
  - Test: `test_measure_latency_during_idle()`
  - Target: Mean idle latency < 10ms

- [ ] **2.3 Implement input response latency test**
  - Test: `test_measure_input_response_latency()`
  - Target: P95 input latency < 100ms

- [ ] **2.4 Implement during-run latency test**
  - Test: `test_measure_latency_during_plugin_execution()`
  - Target: P95 latency < 100ms, max < 500ms

- [ ] **2.5 Add just action for latency tests**
  - Add `test-ui-latency` action to `ui/justfile`

#### Files to Create/Modify

| File | Changes |
|------|---------|
| `ui/tests/test_ui_latency_measurement.py` | New file with latency tests |
| `ui/justfile` | Add `test-ui-latency` action |

#### Test Criteria

- [ ] All latency tests pass with target thresholds
- [ ] Tests can be run with `just test-ui-latency`
- [ ] Tests are marked with `@pytest.mark.slow` for CI optimization

---

### Milestone 3: Create Latency Monitoring Script

**Goal**: Provide a script for manual latency measurement and monitoring

**Duration**: 0.5-1 day

#### Tasks

- [ ] **3.1 Create latency measurement script**
  - Create `scripts/measure_ui_latency.py`
  - Run app with mock plugins
  - Measure latency throughout execution
  - Generate statistics report

- [ ] **3.2 Add just action for the script**
  - Add `measure-latency` action to root `justfile`

#### Files to Create/Modify

| File | Changes |
|------|---------|
| `scripts/measure_ui_latency.py` | New script for latency measurement |
| `justfile` | Add `measure-latency` action |

#### Test Criteria

- [ ] Script runs successfully with `just measure-latency`
- [ ] Script produces readable latency report
- [ ] Report includes mean, median, P95, max latency

---

### Milestone 4: Optimize Thread Worker Usage

**Goal**: Use Textual's `@work` decorator for cleaner thread management

**Duration**: 1-2 days

#### Tasks

- [ ] **4.1 Research Textual worker best practices**
  - Review Textual documentation for workers
  - Review `ref/textual/src/textual/worker.py` for implementation details
  - Understand `thread=True` parameter and `call_from_thread()`

- [ ] **4.2 Refactor metrics collection to use @work decorator**
  - Replace `asyncio.create_task()` with `@work(thread=True)`
  - Use `get_current_worker()` for cancellation checks
  - Use `call_from_thread()` for thread-safe updates

- [ ] **4.3 Update TerminalPane to use workers**
  - Replace `_metrics_update_task` with worker
  - Ensure proper cancellation on unmount

#### Files to Modify

| File | Changes |
|------|---------|
| [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py) | Refactor to use `@work` decorator |
| [`ui/ui/metrics.py`](../ui/ui/metrics.py) | Ensure thread-safety of cached_metrics |

#### Test Criteria

- [ ] Metrics collection runs in worker thread
- [ ] Worker is properly cancelled on pane unmount
- [ ] No race conditions in cached_metrics access
- [ ] All existing tests pass

---

### Milestone 5: Documentation and Cleanup

**Goal**: Document the new architecture and clean up code

**Duration**: 0.5-1 day

**Status**: ✅ COMPLETED

#### Tasks

- [x] **5.1 Update architecture documentation**
  - Updated `docs/UI-revision-plan.md` with new section 8 "UI Latency Improvement Architecture"
  - Added diagrams showing decoupled refresh architecture

- [x] **5.2 Update code comments**
  - Updated `ui/ui/terminal_pane.py` module docstring with architecture overview
  - Updated `ui/ui/phase_status_bar.py` module docstring with decoupled refresh explanation
  - Added detailed docstrings explaining the flow in key methods

- [x] **5.3 Clean up deprecated code**
  - Removed unused `_collect_metrics_sync()` method from `TerminalPane`
  - Kept debug logging (at DEBUG level) as it's useful for future debugging

- [x] **5.4 Update test documentation**
  - Updated `ui/tests/test_ui_latency_measurement.py` module docstring
  - Documented latency test thresholds (aspirational vs CI thresholds)
  - Added comments explaining test methodology and categories

#### Files Modified

| File | Changes |
|------|---------|
| `docs/UI-revision-plan.md` | Added section 8 with architecture diagrams and documentation |
| `ui/ui/terminal_pane.py` | Updated module docstring, removed deprecated `_collect_metrics_sync()` |
| `ui/ui/phase_status_bar.py` | Updated module docstring with decoupled architecture explanation |
| `ui/tests/test_ui_latency_measurement.py` | Added comprehensive module documentation |

#### Test Criteria

- [x] Documentation accurately reflects implementation
- [x] All code has appropriate docstrings
- [ ] `just validate` passes (to be verified)

---

## Testing Strategy

### Test-Driven Development Approach

For each milestone, follow this TDD workflow:

1. **Write failing test first**: Define expected behavior
2. **Implement minimal code**: Make the test pass
3. **Refactor**: Clean up while keeping tests green
4. **Run full validation**: `just validate` after each change

### Test Categories

#### Unit Tests

| Test | File | Purpose |
|------|------|---------|
| `test_auto_refresh_is_configured` | `test_ui_refresh_rate.py` | Verify auto_refresh is set |
| `test_cached_metrics_returns_last_collected` | `test_metrics.py` | Verify cache behavior |
| `test_metrics_collection_in_thread` | `test_terminal_pane.py` | Verify thread usage |

#### Integration Tests

| Test | File | Purpose |
|------|------|---------|
| `test_ui_updates_independently_of_metrics` | `test_ui_latency_measurement.py` | Verify decoupling |
| `test_measure_latency_during_plugin_execution` | `test_ui_latency_measurement.py` | Measure real latency |

#### Performance Tests

| Test | File | Target |
|------|------|--------|
| `test_measure_latency_during_idle` | `test_ui_latency_measurement.py` | Mean < 10ms |
| `test_measure_input_response_latency` | `test_ui_latency_measurement.py` | P95 < 100ms |
| `test_measure_latency_during_plugin_execution` | `test_ui_latency_measurement.py` | P95 < 100ms |

### Validation Commands

```bash
# Run all tests
just validate

# Run UI-specific tests
cd ui && poetry run pytest tests/ -v

# Run latency tests specifically
cd ui && poetry run pytest tests/test_ui_latency_measurement.py -v -s

# Run with coverage
cd ui && poetry run pytest tests/ --cov=ui --cov-report=term-missing
```

---

## Risk Mitigation

### Risk 1: Race Conditions in Cached Metrics

**Risk**: Multiple threads accessing `_cached_metrics` simultaneously

**Mitigation**:
- Use atomic operations for cache updates
- Consider using `threading.Lock` if needed
- Test with concurrent access patterns

### Risk 2: Increased CPU Usage

**Risk**: 30 Hz UI refresh may increase CPU usage noticeably

**Mitigation**:
- Profile CPU usage before and after changes
- Consider reducing to 15 Hz if CPU impact is significant
- Make refresh rate configurable via `PaneConfig`

### Risk 3: Breaking Existing Functionality

**Risk**: Changes may break existing tests or functionality

**Mitigation**:
- Run `just validate` after every change
- Keep changes minimal and focused
- Use feature flags if needed for gradual rollout

### Risk 4: Stale Metrics Display

**Risk**: UI may show stale metrics if collection fails

**Mitigation**:
- Add error handling in `automatic_refresh()`
- Show error indicator if metrics are stale
- Log collection failures for debugging

---

## Appendix: File Reference

### Core Files

| File | Purpose |
|------|---------|
| [`ui/ui/terminal_pane.py`](../ui/ui/terminal_pane.py) | Terminal pane container with PTY management |
| [`ui/ui/phase_status_bar.py`](../ui/ui/phase_status_bar.py) | Status bar widget with metrics display |
| [`ui/ui/metrics.py`](../ui/ui/metrics.py) | Metrics collection and storage |
| [`ui/ui/interactive_tabbed_run.py`](../ui/ui/interactive_tabbed_run.py) | Main application class |

### Test Files

| File | Purpose |
|------|---------|
| [`ui/tests/test_ui_refresh_rate.py`](../ui/tests/test_ui_refresh_rate.py) | Existing refresh rate tests |
| `ui/tests/test_ui_latency_measurement.py` | New latency measurement tests |
| [`ui/tests/test_terminal_pane.py`](../ui/tests/test_terminal_pane.py) | Terminal pane tests |
| [`ui/tests/test_phase_status_bar.py`](../ui/tests/test_phase_status_bar.py) | Status bar tests |

### Documentation

| File | Purpose |
|------|---------|
| [`docs/ui-latency-study.md`](ui-latency-study.md) | Analysis and recommendations |
| [`plans/ui-latency-improvement-plan.md`](../plans/ui-latency-improvement-plan.md) | Existing improvement plan |
| [`docs/UI-revision-plan.md`](UI-revision-plan.md) | Overall UI revision plan |

### Textual Reference

| File | Purpose |
|------|---------|
| [`ref/textual/src/textual/worker.py`](../ref/textual/src/textual/worker.py) | Worker implementation |
| [`ref/textual/src/textual/dom.py`](../ref/textual/src/textual/dom.py) | `auto_refresh` and `run_worker()` |
| [`ref/textual/src/textual/app.py`](../ref/textual/src/textual/app.py) | `call_from_thread()` implementation |

---

## Summary

This plan provides a structured approach to improving UI latency from 1 Hz to 30 Hz by:

1. **Verifying** the existing partial implementation
2. **Testing** with automated latency measurements
3. **Monitoring** with a dedicated script
4. **Optimizing** with Textual's worker system
5. **Documenting** the new architecture

Each milestone is designed to be completed independently, with clear test criteria and minimal risk to existing functionality. The TDD approach ensures that changes are validated at each step.

**Estimated Total Duration**: 4-7 days

**Key Success Metrics**:
- Status bar refresh rate: 30 Hz
- P95 input latency: < 100ms
- All existing tests passing

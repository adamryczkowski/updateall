# Step-Based Execution for Complex Plugins - Implementation Plan

**Proposal:** 4 (from `docs/update-plugins-api-rewrite.md`)
**Date:** January 7, 2026
**Status:** Draft
**Approach:** Test-Driven Development (TDD)

## Executive Summary

This document provides a detailed implementation plan for Proposal 4: Step-Based Execution for Complex Plugins. The proposal introduces an `UpdateStep` abstraction that allows complex plugins to declare logical steps that can be tracked, resumed, and potentially split into separate plugins.

### Key Benefits

1. **Clear progress reporting per step** — Users see which step is executing
2. **Resume from failed step** — Ability to restart from a specific step
3. **Easy to split into separate plugins later** — Steps are self-contained
4. **Mutex declarations per step** — Enables safe parallel execution
5. **Idempotent step checking** — Skip steps that are already done

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Proposed API Design](#proposed-api-design)
3. [Implementation Phases](#implementation-phases)
4. [Test Plan (TDD Approach)](#test-plan-tdd-approach)
5. [Migration Plan](#migration-plan)
6. [Documentation Updates](#documentation-updates)
7. [Risk Analysis](#risk-analysis)
8. [Timeline](#timeline)

---

## Current State Analysis

### Existing Patterns in Complex Plugins

Based on analysis of the current plugin implementations, the following plugins have multi-step update processes:

| Plugin | Steps | Current Implementation |
|--------|-------|------------------------|
| `apt.py` | 2 (update, upgrade) | Uses `get_update_commands()` with step_number/total_steps |
| `texlive_self.py` | 1 (self-update) | Uses `_execute_update_streaming()` |
| `texlive_packages.py` | 1 (update all) | Uses `_execute_update_streaming()` |
| `conda_self.py` | 1 (update conda) | Uses `get_update_commands()` |
| `go_runtime.py` | 5 (check, download, extract, install, symlink) | Uses shell script in `_execute_update()` |
| `waterfox.py` | 4 (check, download, extract, install) | Uses `_execute_update()` with manual steps |

### Current Declarative API

The existing `UpdateCommand` dataclass already supports multi-step execution:

```python
@dataclass(frozen=True)
class UpdateCommand:
    cmd: list[str]
    description: str = ""
    sudo: bool = False
    timeout_seconds: int | None = None
    phase: Phase = Phase.EXECUTE
    step_name: str | None = None
    step_number: int | None = None
    total_steps: int | None = None
    ignore_exit_codes: tuple[int, ...] = ()
    error_patterns: tuple[str, ...] = ()
    success_patterns: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    cwd: str | None = None
```

### Gap Analysis

The current `UpdateCommand` approach works well for simple command sequences but lacks:

1. **Custom async functions** — Cannot run Python code between commands
2. **Step dependencies** — No way to declare dependencies between steps
3. **Mutex declarations** — No per-step mutex support
4. **Idempotent checking** — No way to skip already-completed steps
5. **Resume capability** — Cannot resume from a specific step

---

## Proposed API Design

### New Data Structures

#### UpdateStep Dataclass

```python
from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING
from collections.abc import AsyncIterator

if TYPE_CHECKING:
    from core.streaming import StreamEvent

@dataclass
class UpdateStep:
    """A logical step in a complex update process.

    Attributes:
        name: Unique identifier for this step within the plugin.
        description: Human-readable description shown in UI.
        commands: List of UpdateCommand objects to execute.
        execute_fn: Async function for custom logic.
        depends_on: List of step names that must complete before this step.
        mutexes: List of mutex names this step requires during execution.
        idempotent: Whether this step can be safely re-run.
        check_fn: Optional function that returns True if step is already done.
        timeout_seconds: Optional timeout for this step.
        sudo: Whether this step requires sudo.
    """

    name: str
    description: str

    # Either commands or execute_fn (mutually exclusive)
    commands: list[UpdateCommand] | None = None
    execute_fn: Callable[[], AsyncIterator[StreamEvent]] | None = None

    # Dependencies and mutexes
    depends_on: list[str] = field(default_factory=list)
    mutexes: list[str] = field(default_factory=list)

    # Idempotency
    idempotent: bool = True
    check_fn: Callable[[], bool] | None = None

    # Execution options
    timeout_seconds: int | None = None
    sudo: bool = False
```

#### StepResult Dataclass

```python
@dataclass
class StepResult:
    """Result of executing a single step."""

    step_name: str
    success: bool
    skipped: bool = False
    output: str = ""
    error_message: str | None = None
    duration_seconds: float = 0.0
    packages_updated: int = 0
```

#### StepExecutionState Dataclass

```python
@dataclass
class StepExecutionState:
    """State of step-based execution for resume capability."""

    plugin_name: str
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    step_results: dict[str, StepResult] = field(default_factory=dict)
    started_at: datetime | None = None
    last_updated: datetime | None = None
```

### New Stream Events

```python
@dataclass
class StepStartEvent(StreamEvent):
    """Event emitted when a step starts execution."""

    event_type: EventType = EventType.STEP_START
    step_name: str = ""
    step_number: int = 0
    total_steps: int = 0
    step_description: str = ""


@dataclass
class StepEndEvent(StreamEvent):
    """Event emitted when a step completes."""

    event_type: EventType = EventType.STEP_END
    step_name: str = ""
    success: bool = True
    skipped: bool = False
    error_message: str | None = None
    duration_seconds: float = 0.0
```

### BasePlugin API Extensions

```python
class BasePlugin(UpdatePlugin):

    def get_update_steps(self) -> list[UpdateStep]:
        """Return list of steps for complex updates.

        Override this method to use step-based execution.
        Returns empty list by default (uses command-based or legacy API).
        """
        return []

    async def _execute_steps_streaming(
        self,
        steps: list[UpdateStep],
        *,
        resume_from: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Execute a list of steps with streaming output."""
        ...

    def get_step_state(self) -> StepExecutionState | None:
        """Get the current step execution state for resume capability."""
        return None

    async def resume_from_step(self, step_name: str) -> AsyncIterator[StreamEvent]:
        """Resume execution from a specific step."""
        steps = self.get_update_steps()
        async for event in self._execute_steps_streaming(steps, resume_from=step_name):
            yield event
```

---

## Implementation Phases

### Phase 1: Core Data Structures (Week 1)

**Goal:** Implement the core data structures without changing plugin behavior.

**Tasks:**
1. Add `UpdateStep` dataclass to `core/models.py`
2. Add `StepResult` dataclass to `core/models.py`
3. Add `StepExecutionState` dataclass to `core/models.py`
4. Add `StepStartEvent` and `StepEndEvent` to `core/streaming.py`
5. Add `EventType.STEP_START` and `EventType.STEP_END` enum values
6. Write unit tests for all new data structures

**Files to modify:**
- `core/core/models.py`
- `core/core/streaming.py`

### Phase 2: BasePlugin Extensions (Week 2)

**Goal:** Add step-based execution methods to BasePlugin.

**Tasks:**
1. Add `get_update_steps()` method to `BasePlugin`
2. Implement `_execute_steps_streaming()` method
3. Implement step dependency resolution
4. Implement idempotent step checking
5. Update `execute_streaming()` to use steps when available
6. Write unit tests for step execution

**Files to modify:**
- `plugins/plugins/base.py`

### Phase 3: Resume Capability (Week 3)

**Goal:** Add ability to resume from a failed step.

**Tasks:**
1. Add `StepExecutionState` persistence (JSON file)
2. Implement `get_step_state()` method
3. Implement `resume_from_step()` method
4. Add CLI support for resume (`--resume-from` flag)
5. Write integration tests for resume capability

**Files to modify:**
- `plugins/plugins/base.py`
- `cli/cli/main.py`

### Phase 4: Mutex Integration (Week 4)

**Goal:** Integrate step mutexes with the orchestrator for parallel execution.

**Tasks:**
1. Add mutex tracking to step execution
2. Integrate with orchestrator's parallel execution
3. Add mutex conflict detection
4. Write tests for mutex behavior

**Files to modify:**
- `plugins/plugins/base.py`
- `core/core/orchestrator.py` (if exists)

### Phase 5: Plugin Migration (Weeks 5-6)

**Goal:** Migrate complex plugins to use step-based execution.

**Tasks:**
1. Migrate `go_runtime.py` (highest complexity)
2. Migrate `waterfox.py` (download + install steps)
3. Migrate `texlive_self.py` and `texlive_packages.py`
4. Update tests for migrated plugins

**Files to modify:**
- `plugins/plugins/go_runtime.py`
- `plugins/plugins/waterfox.py`
- `plugins/plugins/texlive_self.py`
- `plugins/plugins/texlive_packages.py`

### Phase 6: Documentation (Week 7)

**Goal:** Update documentation to reflect new API.

**Tasks:**
1. Update `docs/plugin-development.md`
2. Add step-based execution examples
3. Document migration guide
4. Add API reference for new classes

**Files to modify:**
- `docs/plugin-development.md`

---

## Test Plan (TDD Approach)

Following TDD principles, tests should be written **before** implementation.

### 1. UpdateStep Data Structure Tests

**File:** `core/tests/test_update_step.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| US-001 | `test_create_step_with_commands` | Create step with commands list |
| US-002 | `test_create_step_with_execute_fn` | Create step with custom async function |
| US-003 | `test_step_requires_name` | Step must have a name |
| US-004 | `test_step_requires_description` | Step must have a description |
| US-005 | `test_step_commands_and_execute_fn_mutually_exclusive` | Cannot specify both |
| US-006 | `test_step_requires_commands_or_execute_fn` | Must specify one |
| US-007 | `test_step_with_dependencies` | Step can declare dependencies |
| US-008 | `test_step_with_mutexes` | Step can declare mutexes |
| US-009 | `test_step_with_check_fn` | Step can have idempotent check |
| US-010 | `test_step_default_values` | Step has sensible defaults |

### 2. StepResult and StepExecutionState Tests

**File:** `core/tests/test_step_state.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| SR-001 | `test_success_result` | Create successful step result |
| SR-002 | `test_skipped_result` | Create skipped step result |
| SR-003 | `test_failed_result` | Create failed step result |
| SES-001 | `test_initial_state` | Create initial execution state |
| SES-002 | `test_track_completed_steps` | Track completed steps |
| SES-003 | `test_store_step_results` | Store results for each step |

### 3. Stream Event Tests

**File:** `core/tests/test_step_events.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| SE-001 | `test_step_start_event` | Create step start event |
| SE-002 | `test_step_end_event_success` | Create successful step end event |
| SE-003 | `test_step_end_event_skipped` | Create skipped step end event |
| SE-004 | `test_step_end_event_failure` | Create failed step end event |

### 4. BasePlugin Step Execution Tests

**File:** `plugins/tests/test_step_execution.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| GUS-001 | `test_default_returns_empty` | Base class returns empty list |
| GUS-002 | `test_override_returns_steps` | Subclass can return steps |
| ESS-001 | `test_execute_single_step` | Execute a single step |
| ESS-002 | `test_execute_steps_in_order` | Execute steps in declared order |
| ESS-003 | `test_respect_dependencies` | Execute steps respecting dependencies |
| ESS-004 | `test_skip_idempotent_steps` | Skip steps where check_fn returns True |
| ESS-005 | `test_stop_on_failure` | Stop execution on first failed step |
| ESS-006 | `test_execute_custom_function` | Execute step with custom async function |
| ESS-007 | `test_report_step_progress` | StepStartEvent includes progress info |
| ESS-008 | `test_resume_from_step` | Resume execution from a specific step |
| ESS-009 | `test_collect_output_for_counting` | Output collected for package counting |
| ESS-010 | `test_track_mutexes` | Mutexes are tracked during execution |

### 5. Dependency Resolution Tests

**File:** `plugins/tests/test_step_dependencies.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| DEP-001 | `test_linear_dependencies` | Resolve linear dependency chain |
| DEP-002 | `test_diamond_dependencies` | Resolve diamond dependency pattern |
| DEP-003 | `test_circular_dependency_detection` | Detect circular dependencies |
| DEP-004 | `test_missing_dependency_detection` | Detect missing dependencies |
| DEP-005 | `test_no_dependencies` | Steps without dependencies maintain order |

### 6. Integration Tests

**File:** `plugins/tests/test_step_integration.py`

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| INT-001 | `test_uses_steps_when_available` | execute_streaming uses steps |
| INT-002 | `test_falls_back_to_commands` | Falls back when no steps |
| INT-003 | `test_falls_back_to_legacy` | Falls back to legacy API |
| SINT-001 | `test_real_command_execution` | Execute real commands in steps |
| SINT-002 | `test_step_with_sudo` | Execute step with sudo |
| SINT-003 | `test_step_timeout` | Step respects timeout |

---

## Migration Plan

### Eligible Plugins for Migration

| Plugin | Priority | Complexity | Steps |
|--------|----------|------------|-------|
| `go_runtime.py` | High | High | check, download, extract, install, symlink |
| `waterfox.py` | High | High | check, download, extract, install |
| `texlive_self.py` | Medium | Low | check, update |
| `texlive_packages.py` | Medium | Low | update |
| `calibre.py` | Medium | Medium | check, download, install |
| `spack.py` | Low | Medium | git-pull, update |

### Migration Strategy

#### Step 1: Identify Steps

For each plugin, identify the logical steps:

```python
# go_runtime.py example
def get_update_steps(self) -> list[UpdateStep]:
    return [
        UpdateStep(
            name="check-version",
            description="Check for new Go version",
            execute_fn=self._check_version_step,
            mutexes=["network"],
        ),
        UpdateStep(
            name="download",
            description="Download Go tarball",
            execute_fn=self._download_step,
            depends_on=["check-version"],
            mutexes=["network"],
            idempotent=True,
            check_fn=lambda: self._download_path.exists(),
        ),
        UpdateStep(
            name="extract",
            description="Extract Go tarball",
            commands=[
                UpdateCommand(cmd=["tar", "-C", str(self._apps_dir), "-xzf", str(self._download_path)]),
            ],
            depends_on=["download"],
        ),
        UpdateStep(
            name="install",
            description="Install Go to apps directory",
            commands=[UpdateCommand(cmd=["mv", ...])],
            depends_on=["extract"],
        ),
        UpdateStep(
            name="symlink",
            description="Create symlink",
            commands=[UpdateCommand(cmd=["ln", "-sf", ...])],
            depends_on=["install"],
        ),
    ]
```

#### Step 2: Implement Step Functions

For steps that require custom logic, implement async generator functions.

#### Step 3: Add Idempotent Checks

For steps that can be skipped, add check functions.

#### Step 4: Update Tests

Update plugin tests to verify step-based execution.

### Backward Compatibility

The migration maintains backward compatibility:

1. **`get_update_steps()` returns empty by default** — Existing plugins continue to work
2. **Fallback chain preserved** — Steps → Commands → Legacy API
3. **No breaking changes to public API** — All existing methods remain
4. **Gradual migration** — Plugins can be migrated one at a time

---

## Documentation Updates

### Updates to `docs/plugin-development.md`

Add a new section after "Declarative Command Execution API":

```markdown
### Step-Based Execution API

The **Step-Based Execution API** is the recommended way to implement complex plugins
with multiple logical steps. Instead of implementing a single update command or
sequence of commands, you declare logical steps that can be:

- Tracked for progress reporting
- Resumed if the overall update fails
- Skipped if already completed (idempotent)
- Split into separate plugins later

#### When to Use Step-Based Execution

Use step-based execution when your plugin:

- Has multiple distinct phases (check, download, install)
- Needs to resume from a failed step
- Has steps that can be skipped if already done
- Requires different mutexes for different phases

#### `get_update_steps() -> list[UpdateStep]`

Override this method to use step-based execution.

#### UpdateStep

The `UpdateStep` dataclass defines a logical step with:
- `name`: Unique step identifier
- `description`: Human-readable description
- `commands` or `execute_fn`: What to execute
- `depends_on`: Steps that must complete first
- `mutexes`: Mutexes required during execution
- `idempotent`: Whether step can be re-run
- `check_fn`: Function to check if step is done
```

---

## Risk Analysis

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Dependency resolution complexity | Medium | Low | Use well-tested topological sort |
| State persistence for resume | Medium | Medium | Use simple JSON, handle corruption |
| Breaking existing plugins | High | Low | Maintain backward compatibility |
| Performance overhead | Low | Low | Steps add minimal overhead |

### Migration Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Incorrect step boundaries | Medium | Medium | Review each plugin carefully |
| Missing idempotent checks | Low | Medium | Default to non-idempotent |
| Mutex conflicts | Medium | Low | Start with conservative mutexes |

---

## Timeline

| Week | Phase | Deliverables |
|------|-------|--------------|
| 1 | Core Data Structures | `UpdateStep`, `StepResult`, `StepExecutionState`, events |
| 2 | BasePlugin Extensions | `get_update_steps()`, `_execute_steps_streaming()` |
| 3 | Resume Capability | State persistence, `resume_from_step()`, CLI flag |
| 4 | Mutex Integration | Mutex tracking, orchestrator integration |
| 5-6 | Plugin Migration | Migrate go_runtime, waterfox, texlive plugins |
| 7 | Documentation | Update plugin-development.md, add examples |

**Total Estimated Time:** 7 weeks

---

## Appendix: Test Helper Functions

```python
# plugins/tests/conftest.py

def create_step_plugin(steps: list[UpdateStep]) -> BasePlugin:
    """Create a test plugin with the given steps."""

    class TestStepPlugin(BasePlugin):
        @property
        def name(self) -> str:
            return "test-step-plugin"

        @property
        def command(self) -> str:
            return "echo"

        def get_update_steps(self) -> list[UpdateStep]:
            return steps

        async def _execute_update(self, _config: object) -> tuple[str, str | None]:
            return "", None

    return TestStepPlugin()


def resolve_step_order(steps: list[UpdateStep]) -> list[UpdateStep]:
    """Resolve step execution order based on dependencies.

    Uses Kahn's algorithm for topological sorting.
    """
    step_map = {s.name: s for s in steps}
    in_degree = {s.name: 0 for s in steps}

    for step in steps:
        for dep in step.depends_on:
            if dep not in step_map:
                raise ValueError(f"Unknown dependency: {dep}")
            in_degree[step.name] += 1

    queue = [name for name, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        name = queue.pop(0)
        result.append(step_map[name])

        for step in steps:
            if name in step.depends_on:
                in_degree[step.name] -= 1
                if in_degree[step.name] == 0:
                    queue.append(step.name)

    if len(result) != len(steps):
        raise ValueError("Circular dependency detected")

    return result
```

---

## Conclusion

This implementation plan provides a comprehensive roadmap for adding step-based execution to the update-all plugin system. The TDD approach ensures that all functionality is well-tested before implementation, and the phased rollout minimizes risk while allowing for incremental delivery.

Key success factors:
1. **Maintain backward compatibility** — Existing plugins continue to work
2. **Follow TDD** — Write tests before implementation
3. **Migrate gradually** — Start with highest-value plugins
4. **Document thoroughly** — Update plugin-development.md with examples

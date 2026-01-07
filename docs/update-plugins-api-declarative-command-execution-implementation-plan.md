# Declarative Command Execution - Implementation Plan

**Date:** January 7, 2026
**Status:** Draft
**Proposal Reference:** Proposal 1 from `update-plugins-api-rewrite.md`

## Executive Summary

This document provides a detailed implementation plan for Proposal 1: Declarative Command Execution. This proposal aims to reduce plugin boilerplate by 60-80% by allowing plugins to declare their commands instead of implementing complex streaming logic.

The implementation follows a Test-Driven Development (TDD) approach, with tests written first and implementation following to satisfy those tests.

---

## Table of Contents

1. [Goals and Non-Goals](#goals-and-non-goals)
2. [Architecture Overview](#architecture-overview)
3. [Implementation Phases](#implementation-phases)
4. [Test Plan](#test-plan)
5. [Plugin Migration Plan](#plugin-migration-plan)
6. [Documentation Updates](#documentation-updates)
7. [Risk Mitigation](#risk-mitigation)
8. [Success Criteria](#success-criteria)

---

## Goals and Non-Goals

### Goals

1. **Reduce boilerplate** — Simple plugins should be 10-30 lines instead of 100+
2. **Automatic streaming** — Base class handles streaming, output collection, and completion events
3. **Consistent error handling** — Success/error patterns, ignored exit codes handled uniformly
4. **Multi-step support** — Plugins can declare multiple commands with step progress
5. **Backward compatibility** — Existing plugins continue to work without modification
6. **TDD approach** — All features have tests written before implementation

### Non-Goals

1. **Download API changes** — Proposal 2 (Centralized Download Manager) is out of scope
2. **Version checking protocol** — Proposal 3 is out of scope
3. **Step-based execution** — Proposal 4 (UpdateStep) is out of scope for this plan
4. **Sudo declaration** — Proposal 5 is out of scope
5. **Mutex/dependency system** — Proposal 6 is out of scope
6. **Estimation API** — Proposal 7 is out of scope

---

## Architecture Overview

### New Data Model: UpdateCommand

```python
@dataclass
class UpdateCommand:
    """A single command in an update sequence."""

    cmd: list[str]                              # Command and arguments
    description: str = ""                       # Human-readable description
    sudo: bool = False                          # Whether to prepend sudo
    timeout_seconds: int | None = None          # Custom timeout (None = use default)
    phase: Phase = Phase.EXECUTE                # Execution phase

    # For multi-step updates
    step_name: str | None = None                # Logical step name
    step_number: int | None = None              # Step number (1-based)
    total_steps: int | None = None              # Total number of steps

    # Error handling
    ignore_exit_codes: tuple[int, ...] = ()     # Exit codes that are not errors
    error_patterns: tuple[str, ...] = ()        # Patterns indicating error (even with exit 0)
    success_patterns: tuple[str, ...] = ()      # Patterns indicating success (even with non-zero exit)

    # Environment
    env: dict[str, str] | None = None           # Additional environment variables
    cwd: str | None = None                      # Working directory
```

### New BasePlugin Methods

```python
class BasePlugin:
    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        """Return list of commands to execute for update.

        Override this instead of _execute_update_streaming() for simple plugins.
        Default implementation returns empty list (falls back to legacy API).
        """
        return []

    async def _execute_commands_streaming(
        self,
        commands: list[UpdateCommand]
    ) -> AsyncIterator[StreamEvent]:
        """Execute a list of commands with streaming output.

        This method is called by execute_streaming() when get_update_commands()
        returns a non-empty list. It handles:
        - Sequential command execution
        - Output collection for package counting
        - Success/error pattern matching
        - Step progress reporting
        - Final CompletionEvent with package count
        """
        ...
```

### Integration with Existing API

The [`execute_streaming()`](plugins/plugins/base.py:495) method will be modified to:

1. Call [`get_update_commands()`](plugins/plugins/base.py:231) first
2. If non-empty list returned, call [`_execute_commands_streaming()`](plugins/plugins/base.py:625)
3. Otherwise, fall back to existing [`_execute_update_streaming()`](plugins/plugins/base.py:625) behavior

This ensures 100% backward compatibility with existing plugins.

---

## Implementation Phases

### Phase 1: Core Data Model (Week 1)

**Objective:** Define the `UpdateCommand` dataclass and add it to core models.

#### Tasks

1. **Create UpdateCommand dataclass** in [`core/core/models.py`](core/core/models.py)
   - All fields as specified in architecture
   - Proper type hints and documentation
   - Immutable (frozen=True for dataclass)

2. **Export from core package**
   - Add to [`core/core/__init__.py`](core/core/__init__.py) exports

3. **Write unit tests for UpdateCommand**
   - Field defaults
   - Immutability
   - Serialization (if needed)

#### Deliverables

- `UpdateCommand` dataclass in `core/core/models.py`
- Unit tests in `core/tests/test_models.py`

---

### Phase 2: Base Plugin Methods (Week 1-2)

**Objective:** Implement `get_update_commands()` and `_execute_commands_streaming()` in BasePlugin.

#### Tasks

1. **Add `get_update_commands()` method** to [`BasePlugin`](plugins/plugins/base.py:61)
   - Default implementation returns empty list
   - Accepts `dry_run` parameter

2. **Implement `_execute_commands_streaming()`** in [`BasePlugin`](plugins/plugins/base.py:61)
   - Sequential command execution
   - Header output for each command
   - Output collection for package counting
   - Success/error pattern matching
   - Ignored exit code handling
   - Step progress reporting
   - Final CompletionEvent generation

3. **Modify `execute_streaming()`** in [`BasePlugin`](plugins/plugins/base.py:495)
   - Check if `get_update_commands()` returns non-empty list
   - If yes, delegate to `_execute_commands_streaming()`
   - Otherwise, use existing `_execute_update_streaming()` flow

4. **Write comprehensive tests**
   - Tests already exist in [`plugins/tests/test_declarative_execution.py`](plugins/tests/test_declarative_execution.py)
   - Ensure all tests pass

#### Deliverables

- Updated [`plugins/plugins/base.py`](plugins/plugins/base.py) with new methods
- All tests in [`test_declarative_execution.py`](plugins/tests/test_declarative_execution.py) passing

---

### Phase 3: Plugin Migration (Week 2-3)

**Objective:** Migrate eligible plugins to the new declarative API.

See [Plugin Migration Plan](#plugin-migration-plan) for detailed migration order and approach.

#### Deliverables

- All eligible plugins migrated
- All existing tests passing
- New tests for migrated plugins

---

### Phase 4: Documentation Updates (Week 3)

**Objective:** Update documentation to reflect the new API.

See [Documentation Updates](#documentation-updates) for detailed changes.

#### Deliverables

- Updated [`docs/plugin-development.md`](docs/plugin-development.md)
- Migration guide for external plugin authors

---

## Test Plan

### Existing Tests (Already Written)

The following tests already exist in [`plugins/tests/test_declarative_execution.py`](plugins/tests/test_declarative_execution.py) and define the expected behavior:

#### Tests for `get_update_commands()` (GUC-*)

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| GUC-001 | `test_get_update_commands_default_empty` | Base class returns empty list by default |
| GUC-002 | `test_get_update_commands_dry_run_flag` | `dry_run` parameter is passed correctly |
| GUC-003 | `test_get_update_commands_returns_list` | Return type is list of UpdateCommand |

#### Tests for `_execute_commands_streaming()` (ECS-*)

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| ECS-001 | `test_execute_single_command` | Single command execution works |
| ECS-002 | `test_execute_multiple_commands` | Sequential command execution works |
| ECS-003 | `test_execute_with_sudo` | Sudo is prepended correctly |
| ECS-004 | `test_execute_with_timeout` | Custom timeout is used |
| ECS-005 | `test_execute_emits_header` | Header OutputEvent is emitted for each command |
| ECS-006 | `test_execute_collects_output` | Output is collected for package counting |
| ECS-007 | `test_execute_success_patterns` | Success patterns override exit code |
| ECS-008 | `test_execute_error_patterns` | Error patterns override exit code |
| ECS-009 | `test_execute_ignore_exit_codes` | Ignored exit codes don't fail |
| ECS-010 | `test_execute_step_progress` | Step progress is reported in output |
| ECS-011 | `test_execute_completion_event` | Final CompletionEvent is correct |
| ECS-012 | `test_execute_package_count` | Package count is in CompletionEvent |
| ECS-013 | `test_execute_stops_on_failure` | Stops on first failed command |
| ECS-014 | `test_execute_with_env` | Environment variables are passed |
| ECS-015 | `test_execute_with_cwd` | Working directory is used |

#### Integration Tests (INT-*)

| Test ID | Test Name | Description |
|---------|-----------|-------------|
| INT-001 | `test_declarative_plugin_execution` | Full execution flow with declarative plugin |
| INT-002 | `test_declarative_plugin_dry_run` | Dry run mode works with declarative plugin |
| INT-004 | `test_declarative_plugin_fallback` | Falls back to legacy if get_update_commands returns empty |

### New Tests to Add

#### UpdateCommand Model Tests (UCM-*)

| Test ID | Test Name | Description | Location |
|---------|-----------|-------------|----------|
| UCM-001 | `test_update_command_defaults` | Default values are correct | `core/tests/test_models.py` |
| UCM-002 | `test_update_command_required_fields` | `cmd` is required | `core/tests/test_models.py` |
| UCM-003 | `test_update_command_immutable` | Dataclass is frozen | `core/tests/test_models.py` |
| UCM-004 | `test_update_command_tuple_fields` | Tuple fields work correctly | `core/tests/test_models.py` |

#### Plugin Migration Tests (PMT-*)

For each migrated plugin, add tests to verify:

| Test ID Pattern | Test Name Pattern | Description |
|-----------------|-------------------|-------------|
| PMT-{plugin}-001 | `test_{plugin}_get_update_commands` | Returns correct commands |
| PMT-{plugin}-002 | `test_{plugin}_get_update_commands_dry_run` | Dry run returns different commands |
| PMT-{plugin}-003 | `test_{plugin}_streaming_execution` | Streaming execution works |
| PMT-{plugin}-004 | `test_{plugin}_package_count` | Package counting still works |

#### Edge Case Tests (ECT-*)

| Test ID | Test Name | Description | Location |
|---------|-----------|-------------|----------|
| ECT-001 | `test_empty_command_list` | Empty command list handled gracefully | `test_declarative_execution.py` |
| ECT-002 | `test_command_with_empty_cmd` | Command with empty cmd list raises error | `test_declarative_execution.py` |
| ECT-003 | `test_timeout_during_command` | Timeout is handled correctly | `test_declarative_execution.py` |
| ECT-004 | `test_mixed_success_error_patterns` | Both patterns work together | `test_declarative_execution.py` |
| ECT-005 | `test_step_numbers_optional` | Step numbers are optional | `test_declarative_execution.py` |
| ECT-006 | `test_partial_step_info` | Partial step info (only step_name) works | `test_declarative_execution.py` |

---

## Plugin Migration Plan

### Migration Categories

Based on analysis of existing plugins, they fall into these categories:

#### Category A: Simple Single-Command Plugins (Immediate Migration)

These plugins run a single command and can be migrated immediately:

| Plugin | Current Lines | Expected Lines | Reduction |
|--------|---------------|----------------|-----------|
| [`snap.py`](plugins/plugins/snap.py) | 81 | ~25 | 69% |
| [`rustup.py`](plugins/plugins/rustup.py) | 86 | ~25 | 71% |
| [`cargo.py`](plugins/plugins/cargo.py) | 97 | ~30 | 69% |

**Migration Pattern:**

```python
# Before (snap.py - 81 lines)
class SnapPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "snap"

    @property
    def command(self) -> str:
        return "snap"

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        return_code, stdout, stderr = await self._run_command(
            ["snap", "refresh"],
            timeout=config.timeout_seconds,
            sudo=True,
        )
        output = f"=== snap refresh ===\n{stdout}"
        if return_code != 0:
            if "All snaps up to date" in stdout or "All snaps up to date" in stderr:
                return output, None
            return output, f"snap refresh failed: {stderr}"
        return output, None

    def _count_updated_packages(self, output: str) -> int:
        # ... counting logic ...

# After (snap.py - ~25 lines)
class SnapPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "snap"

    @property
    def command(self) -> str:
        return "snap"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["snap", "list"], description="List installed snaps")]
        return [
            UpdateCommand(
                cmd=["snap", "refresh"],
                description="Refresh all snaps",
                sudo=True,
                success_patterns=("All snaps up to date",),
            )
        ]

    def _count_updated_packages(self, output: str) -> int:
        # ... counting logic unchanged ...
```

#### Category B: Multi-Step Plugins (Week 2)

These plugins run multiple commands in sequence:

| Plugin | Current Lines | Expected Lines | Reduction | Steps |
|--------|---------------|----------------|-----------|-------|
| [`apt.py`](plugins/plugins/apt.py) | 223 | ~40 | 82% | 2 |
| [`npm.py`](plugins/plugins/npm.py) | 99 | ~35 | 65% | 2 |
| [`pipx.py`](plugins/plugins/pipx.py) | 162 | ~30 | 81% | 1 |
| [`flatpak.py`](plugins/plugins/flatpak.py) | 162 | ~30 | 81% | 1 |

**Migration Pattern (apt.py):**

```python
# After (apt.py - ~40 lines)
class AptPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "apt"

    @property
    def command(self) -> str:
        return "apt"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [
                UpdateCommand(cmd=["apt", "update"], sudo=True, step_name="refresh"),
                UpdateCommand(cmd=["apt", "upgrade", "--dry-run"], sudo=True, step_name="check"),
            ]
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                description="Refresh package lists",
                sudo=True,
                step_name="refresh",
                step_number=1,
                total_steps=2,
            ),
            UpdateCommand(
                cmd=["apt", "upgrade", "-y"],
                description="Upgrade packages",
                sudo=True,
                step_name="upgrade",
                step_number=2,
                total_steps=2,
            ),
        ]

    def _count_updated_packages(self, output: str) -> int:
        # ... counting logic unchanged ...
```

#### Category C: Plugins with Streaming Override (Week 2-3)

These plugins have custom `_execute_update_streaming()` implementations:

| Plugin | Current Lines | Expected Lines | Reduction |
|--------|---------------|----------------|-----------|
| [`texlive.py`](plugins/plugins/texlive.py) | 260 | ~50 | 81% |
| [`poetry.py`](plugins/plugins/poetry.py) | ~224 | ~40 | 82% |

#### Category D: Complex Plugins (Deferred or Partial)

These plugins have complex logic that may not fully benefit from declarative API:

| Plugin | Reason | Recommendation |
|--------|--------|----------------|
| [`waterfox.py`](plugins/plugins/waterfox.py) | Download + version checking + extraction | Partial migration (install steps only) |
| [`go.py`](plugins/plugins/go.py) | Shell script execution, version checking | Keep legacy API |
| [`conda.py`](plugins/plugins/conda.py) | Dynamic environment list, multiple commands per env | Keep legacy API |
| [`calibre.py`](plugins/plugins/calibre.py) | Download + extraction | Partial migration |

### Migration Order

1. **Week 2, Day 1-2:** Category A plugins (snap, rustup, cargo)
2. **Week 2, Day 3-5:** Category B plugins (apt, npm, pipx, flatpak)
3. **Week 3, Day 1-3:** Category C plugins (texlive, poetry)
4. **Week 3, Day 4-5:** Category D partial migrations (waterfox install steps)

### Migration Checklist Per Plugin

For each plugin migration:

- [ ] Write new tests (PMT-{plugin}-001 through PMT-{plugin}-004)
- [ ] Implement `get_update_commands()` method
- [ ] Remove or simplify `_execute_update()` method
- [ ] Remove `_execute_update_streaming()` method if present
- [ ] Verify `_count_updated_packages()` still works
- [ ] Run existing tests to ensure no regression
- [ ] Run new tests to verify declarative behavior
- [ ] Update plugin docstring

---

## Documentation Updates

### Updates to [`docs/plugin-development.md`](docs/plugin-development.md)

#### New Section: Declarative Command Execution (Add after "Quick Start Tutorial")

```markdown
## Declarative Command Execution (Recommended)

For most plugins, you can use the declarative API instead of implementing
`_execute_update()` directly. This approach:

- Reduces boilerplate by 60-80%
- Provides automatic streaming output
- Handles error patterns consistently
- Reports step progress automatically

### Simple Plugin Example

```python
from core.models import UpdateCommand
from plugins.base import BasePlugin


class MyPkgPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "mypkg"

    @property
    def command(self) -> str:
        return "mypkg"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["mypkg", "list"])]
        return [
            UpdateCommand(
                cmd=["mypkg", "upgrade", "-y"],
                description="Upgrade all packages",
                success_patterns=("Nothing to upgrade",),
            )
        ]

    def _count_updated_packages(self, output: str) -> int:
        return output.count("Upgraded:")
```

### Multi-Step Plugin Example

```python
def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
    if dry_run:
        return [
            UpdateCommand(cmd=["apt", "update"], sudo=True),
            UpdateCommand(cmd=["apt", "upgrade", "--dry-run"], sudo=True),
        ]
    return [
        UpdateCommand(
            cmd=["apt", "update"],
            description="Refresh package lists",
            sudo=True,
            step_name="refresh",
            step_number=1,
            total_steps=2,
        ),
        UpdateCommand(
            cmd=["apt", "upgrade", "-y"],
            description="Upgrade packages",
            sudo=True,
            step_name="upgrade",
            step_number=2,
            total_steps=2,
        ),
    ]
```

### UpdateCommand Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cmd` | `list[str]` | Required | Command and arguments |
| `description` | `str` | `""` | Human-readable description |
| `sudo` | `bool` | `False` | Prepend sudo to command |
| `timeout_seconds` | `int \| None` | `None` | Custom timeout (None = use default) |
| `step_name` | `str \| None` | `None` | Logical step name |
| `step_number` | `int \| None` | `None` | Step number (1-based) |
| `total_steps` | `int \| None` | `None` | Total number of steps |
| `ignore_exit_codes` | `tuple[int, ...]` | `()` | Exit codes that are not errors |
| `error_patterns` | `tuple[str, ...]` | `()` | Patterns indicating error |
| `success_patterns` | `tuple[str, ...]` | `()` | Patterns indicating success |
| `env` | `dict[str, str] \| None` | `None` | Additional environment variables |
| `cwd` | `str \| None` | `None` | Working directory |

### When to Use Legacy API

Use the legacy `_execute_update()` method when:

- You need to run shell scripts (not individual commands)
- Commands depend on output of previous commands
- You need complex conditional logic
- You're downloading files and need custom handling
```

#### Update "API Reference" Section

Add `get_update_commands()` to the "Optional Methods" subsection.

#### Update "Examples" Section

Replace the "Minimal Plugin" example with a declarative version.

---

## Risk Mitigation

### Risk 1: Breaking Existing Plugins

**Mitigation:**
- Default `get_update_commands()` returns empty list
- Empty list triggers fallback to legacy `_execute_update_streaming()`
- All existing tests must pass before merging

### Risk 2: Package Counting Regression

**Mitigation:**
- `_count_updated_packages()` method is unchanged
- Output is collected and passed to counting method
- Add specific tests for package counting per plugin

### Risk 3: Streaming Behavior Changes

**Mitigation:**
- Header output format matches existing plugins
- CompletionEvent structure unchanged
- Integration tests verify end-to-end behavior

### Risk 4: Performance Regression

**Mitigation:**
- No additional async overhead
- Same underlying `_run_command_streaming()` method used
- Benchmark tests for streaming performance

---

## Success Criteria

### Phase 1 Complete When:

- [ ] `UpdateCommand` dataclass exists in `core/core/models.py`
- [ ] All UCM-* tests pass
- [ ] `UpdateCommand` is exported from core package

### Phase 2 Complete When:

- [ ] `get_update_commands()` method exists in BasePlugin
- [ ] `_execute_commands_streaming()` method exists in BasePlugin
- [ ] `execute_streaming()` delegates to new methods when appropriate
- [ ] All GUC-*, ECS-*, INT-* tests pass
- [ ] All ECT-* tests pass

### Phase 3 Complete When:

- [ ] Category A plugins migrated (snap, rustup, cargo)
- [ ] Category B plugins migrated (apt, npm, pipx, flatpak)
- [ ] Category C plugins migrated (texlive, poetry)
- [ ] All PMT-* tests pass
- [ ] All existing plugin tests pass
- [ ] Code reduction metrics verified

### Phase 4 Complete When:

- [ ] `docs/plugin-development.md` updated with declarative API section
- [ ] Migration guide for external plugins written
- [ ] All documentation reviewed and accurate

### Overall Success Metrics:

| Metric | Target |
|--------|--------|
| Average plugin code reduction | ≥ 60% |
| Test coverage for new code | ≥ 90% |
| Existing test pass rate | 100% |
| New test pass rate | 100% |

---

## Appendix: Full Test List

### Core Model Tests (`core/tests/test_models.py`)

```python
class TestUpdateCommand:
    def test_update_command_defaults(self) -> None:
        """UCM-001: Default values are correct."""
        cmd = UpdateCommand(cmd=["echo", "test"])
        assert cmd.description == ""
        assert cmd.sudo is False
        assert cmd.timeout_seconds is None
        assert cmd.phase == Phase.EXECUTE
        assert cmd.step_name is None
        assert cmd.step_number is None
        assert cmd.total_steps is None
        assert cmd.ignore_exit_codes == ()
        assert cmd.error_patterns == ()
        assert cmd.success_patterns == ()
        assert cmd.env is None
        assert cmd.cwd is None

    def test_update_command_required_fields(self) -> None:
        """UCM-002: cmd is required."""
        with pytest.raises(TypeError):
            UpdateCommand()  # type: ignore

    def test_update_command_immutable(self) -> None:
        """UCM-003: Dataclass is frozen."""
        cmd = UpdateCommand(cmd=["echo", "test"])
        with pytest.raises(FrozenInstanceError):
            cmd.description = "new description"  # type: ignore

    def test_update_command_tuple_fields(self) -> None:
        """UCM-004: Tuple fields work correctly."""
        cmd = UpdateCommand(
            cmd=["echo"],
            ignore_exit_codes=(1, 2),
            error_patterns=("ERROR", "FATAL"),
            success_patterns=("OK", "SUCCESS"),
        )
        assert 1 in cmd.ignore_exit_codes
        assert "ERROR" in cmd.error_patterns
        assert "OK" in cmd.success_patterns
```

### Edge Case Tests (`plugins/tests/test_declarative_execution.py`)

```python
class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_command_list(self) -> None:
        """ECT-001: Empty command list handled gracefully."""
        plugin = SimpleDeclarativePlugin()
        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming([]):
            events.append(event)

        # Should emit a completion event with success
        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is True
        assert completion.packages_updated == 0

    def test_command_with_empty_cmd(self) -> None:
        """ECT-002: Command with empty cmd list raises error."""
        with pytest.raises(ValueError):
            UpdateCommand(cmd=[])

    @pytest.mark.asyncio
    async def test_timeout_during_command(self) -> None:
        """ECT-003: Timeout is handled correctly."""
        plugin = SimpleDeclarativePlugin()

        async def mock_run_command_streaming(*args, **kwargs):
            raise TimeoutError("Command timed out")
            yield  # Make it a generator

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(
                [UpdateCommand(cmd=["sleep", "100"])]
            ):
                events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is False
        assert "timeout" in completion.error_message.lower()

    @pytest.mark.asyncio
    async def test_mixed_success_error_patterns(self) -> None:
        """ECT-004: Both patterns work together."""
        # Error pattern takes precedence over success pattern
        ...

    def test_step_numbers_optional(self) -> None:
        """ECT-005: Step numbers are optional."""
        cmd = UpdateCommand(cmd=["echo"], step_name="test")
        assert cmd.step_name == "test"
        assert cmd.step_number is None
        assert cmd.total_steps is None

    def test_partial_step_info(self) -> None:
        """ECT-006: Partial step info (only step_name) works."""
        cmd = UpdateCommand(cmd=["echo"], step_name="test", step_number=1)
        assert cmd.step_name == "test"
        assert cmd.step_number == 1
        assert cmd.total_steps is None
```

---

## Timeline Summary

| Week | Phase | Deliverables |
|------|-------|--------------|
| Week 1 | Phase 1 + Phase 2 Start | UpdateCommand model, base plugin methods |
| Week 2 | Phase 2 Complete + Phase 3 Start | All tests passing, Category A+B plugins migrated |
| Week 3 | Phase 3 Complete + Phase 4 | Category C plugins migrated, documentation updated |

**Total Duration:** 3 weeks

**Dependencies:**
- No external dependencies
- Can be developed in parallel with other proposals

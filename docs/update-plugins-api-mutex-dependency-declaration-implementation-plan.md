# Proposal 6: Mutex and Dependency Declaration - Implementation Plan

**Date:** January 7, 2026
**Status:** Draft
**Author:** Implementation Team

## Executive Summary

This document provides a detailed implementation plan for Proposal 6 from the Update Plugins API Rewrite document. Proposal 6 introduces a **Mutex and Dependency Declaration API** that enables plugins to declare their dependencies on other plugins and the mutexes (resource locks) they require for each execution phase.

### Goals

1. Enable safe parallel execution of plugins by declaring resource requirements
2. Allow plugins to declare dependencies on other plugins
3. Support per-phase mutex declarations (CHECK, DOWNLOAD, EXECUTE)
4. Integrate with the existing `MutexManager` and `Scheduler` infrastructure
5. Provide a clean, declarative API that reduces boilerplate

### Non-Goals

- Changing the existing `MutexManager` implementation (already robust)
- Modifying the `Scheduler` DAG-building algorithm (already supports dependencies and mutexes)
- Implementing dynamic mutex discovery (out of scope for this proposal)

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Proposed API Design](#proposed-api-design)
3. [Implementation Phases](#implementation-phases)
4. [Test-Driven Development Plan](#test-driven-development-plan)
5. [Plugin Migration Plan](#plugin-migration-plan)
6. [Documentation Updates](#documentation-updates)
7. [Risk Assessment](#risk-assessment)

---

## Current State Analysis

### Existing Infrastructure

The codebase already has robust infrastructure for mutex management and scheduling:

1. **`MutexManager`** ([`core/core/mutex.py`](../core/core/mutex.py)):
   - Manages mutex acquisition and release
   - Implements deadlock detection with configurable timeout
   - Uses ordered mutex acquisition to prevent deadlocks
   - Provides standard mutex names via `StandardMutexes` class

2. **`Scheduler`** ([`core/core/scheduler.py`](../core/core/scheduler.py)):
   - Builds execution DAG from plugin dependencies and mutexes
   - Groups plugins into execution waves for parallel execution
   - Detects circular dependencies

3. **`ParallelOrchestrator`** ([`core/core/parallel_orchestrator.py`](../core/core/parallel_orchestrator.py)):
   - Executes plugins in waves based on DAG
   - Acquires/releases mutexes around plugin execution
   - Currently receives mutexes via external `plugin_mutexes` dict parameter

### Current Limitations

1. **No plugin-level mutex declaration**: Mutexes are passed externally to `ParallelOrchestrator.run_all()` via `plugin_mutexes` dict, not declared by plugins themselves.

2. **No per-phase mutex support**: The current API only supports a single list of mutexes per plugin, not per-phase (CHECK, DOWNLOAD, EXECUTE).

3. **No plugin-level dependency declaration**: Dependencies are passed externally, not declared by plugins.

4. **`PluginConfig.dependencies`** exists but is not used: The model has a `dependencies` field, but plugins don't populate it.

### Plugins Analyzed

| Plugin | Potential Dependencies | Potential Mutexes |
|--------|----------------------|-------------------|
| `apt` | None | `pkgmgr:apt`, `pkgmgr:dpkg` |
| `snap` | None | `pkgmgr:snap` |
| `flatpak` | None | `pkgmgr:flatpak` |
| `pipx` | None | `pkgmgr:pipx` |
| `cargo` | None | `pkgmgr:cargo` |
| `rustup` | None | `pkgmgr:rustup`, `runtime:rust` |
| `npm` | None | `pkgmgr:npm`, `runtime:node` |
| `conda-self` | None | `pkgmgr:conda` |
| `conda-packages` | `conda-self` | `pkgmgr:conda` |
| `texlive-self` | None | `pkgmgr:texlive` |
| `texlive-packages` | `texlive-self` | `pkgmgr:texlive` |
| `calibre` | None | `system:network` (download) |
| `waterfox` | None | `system:network` (download) |
| `go-runtime` | None | `runtime:go`, `system:network` |
| `go-packages` | `go-runtime` | `runtime:go` |
| `julia-runtime` | None | `runtime:julia`, `system:network` |
| `julia-packages` | `julia-runtime` | `runtime:julia` |

---

## Proposed API Design

### New Properties in `BasePlugin`

```python
class BasePlugin(UpdatePlugin):
    """Base class for all update plugins."""

    @property
    def dependencies(self) -> list[str]:
        """Plugin names that must run before this plugin.

        Override this property to declare dependencies on other plugins.
        The orchestrator will ensure dependent plugins complete successfully
        before this plugin starts.

        Returns:
            List of plugin names that must complete before this plugin.
            Return empty list if no dependencies.

        Example:
            @property
            def dependencies(self) -> list[str]:
                return ["conda-self"]  # Must run after conda-self
        """
        return []

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Mutexes required for each execution phase.

        Override this property to declare mutex requirements per phase.
        The orchestrator will acquire these mutexes before each phase
        and release them after the phase completes.

        Phases:
            - Phase.CHECK: Version checking / update estimation
            - Phase.DOWNLOAD: Downloading updates
            - Phase.EXECUTE: Applying updates

        Returns:
            Dict mapping Phase to list of mutex names.
            Return empty dict if no mutexes needed.

        Example:
            @property
            def mutexes(self) -> dict[Phase, list[str]]:
                return {
                    Phase.DOWNLOAD: ["system:network"],
                    Phase.EXECUTE: ["pkgmgr:apt", "pkgmgr:dpkg"],
                }
        """
        return {}

    @property
    def all_mutexes(self) -> list[str]:
        """Get all mutexes across all phases (convenience property).

        Returns:
            Deduplicated list of all mutex names.
        """
        all_mutex_set: set[str] = set()
        for phase_mutexes in self.mutexes.values():
            all_mutex_set.update(phase_mutexes)
        return sorted(all_mutex_set)
```

### Extended `StandardMutexes` Class

```python
class StandardMutexes:
    """Standard mutex names for common resources."""

    # Package manager locks
    APT_LOCK = "pkgmgr:apt"
    DPKG_LOCK = "pkgmgr:dpkg"
    SNAP_LOCK = "pkgmgr:snap"
    FLATPAK_LOCK = "pkgmgr:flatpak"
    PIPX_LOCK = "pkgmgr:pipx"
    CARGO_LOCK = "pkgmgr:cargo"
    NPM_LOCK = "pkgmgr:npm"
    RUSTUP_LOCK = "pkgmgr:rustup"
    CONDA_LOCK = "pkgmgr:conda"
    TEXLIVE_LOCK = "pkgmgr:texlive"

    # Runtime locks
    PYTHON_RUNTIME = "runtime:python"
    NODE_RUNTIME = "runtime:node"
    RUST_RUNTIME = "runtime:rust"
    GO_RUNTIME = "runtime:go"
    JULIA_RUNTIME = "runtime:julia"

    # System resources
    NETWORK = "system:network"
    DISK = "system:disk"
```

### Helper Functions

```python
# In core/core/mutex.py

def collect_plugin_mutexes(
    plugins: list[UpdatePlugin],
    phase: Phase | None = None,
) -> dict[str, list[str]]:
    """Collect mutex declarations from plugins.

    Args:
        plugins: List of plugins to collect from.
        phase: If specified, only collect mutexes for this phase.
               If None, collect all mutexes (union of all phases).

    Returns:
        Dict mapping plugin names to their mutex lists.
    """
    result: dict[str, list[str]] = {}
    for plugin in plugins:
        if phase is not None:
            mutexes = plugin.mutexes.get(phase, [])
        else:
            mutexes = plugin.all_mutexes
        if mutexes:
            result[plugin.name] = mutexes
    return result


def collect_plugin_dependencies(
    plugins: list[UpdatePlugin],
) -> dict[str, list[str]]:
    """Collect dependency declarations from plugins.

    Args:
        plugins: List of plugins to collect from.

    Returns:
        Dict mapping plugin names to their dependency lists.
    """
    result: dict[str, list[str]] = {}
    for plugin in plugins:
        deps = plugin.dependencies
        if deps:
            result[plugin.name] = deps
    return result
```

### Updated `ParallelOrchestrator`

```python
class ParallelOrchestrator:
    """Orchestrates parallel execution of update plugins."""

    async def run_all(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
        plugin_mutexes: dict[str, list[str]] | None = None,  # Deprecated
        plugin_dependencies: dict[str, list[str]] | None = None,  # Deprecated
    ) -> ExecutionSummary:
        """Run all plugins with parallel execution.

        Args:
            plugins: List of plugins to execute.
            configs: Optional plugin configurations.
            plugin_mutexes: DEPRECATED. Use plugin.mutexes property instead.
            plugin_dependencies: DEPRECATED. Use plugin.dependencies property instead.
        """
        # Collect from plugins if not provided externally
        if plugin_mutexes is None:
            plugin_mutexes = collect_plugin_mutexes(plugins)

        if plugin_dependencies is None:
            plugin_dependencies = collect_plugin_dependencies(plugins)

        # ... rest of implementation
```

---

## Implementation Phases

### Phase 1: Core API Implementation (2-3 days)

**Objective:** Add the new properties to `BasePlugin` and helper functions.

**Files to modify:**
1. [`plugins/plugins/base.py`](../plugins/plugins/base.py) - Add `dependencies` and `mutexes` properties
2. [`core/core/mutex.py`](../core/core/mutex.py) - Add helper functions and extend `StandardMutexes`
3. [`core/core/interfaces.py`](../core/core/interfaces.py) - Add abstract properties to `UpdatePlugin` interface

**Tasks:**
1. Add `dependencies` property to `BasePlugin` (default: empty list)
2. Add `mutexes` property to `BasePlugin` (default: empty dict)
3. Add `all_mutexes` convenience property to `BasePlugin`
4. Add `collect_plugin_mutexes()` helper function
5. Add `collect_plugin_dependencies()` helper function
6. Extend `StandardMutexes` with additional mutex names
7. Add abstract property declarations to `UpdatePlugin` interface

### Phase 2: Orchestrator Integration (1-2 days)

**Objective:** Update `ParallelOrchestrator` to use plugin-declared mutexes and dependencies.

**Files to modify:**
1. [`core/core/parallel_orchestrator.py`](../core/core/parallel_orchestrator.py) - Use plugin declarations
2. [`core/core/scheduler.py`](../core/core/scheduler.py) - Accept plugin list directly

**Tasks:**
1. Update `ParallelOrchestrator.run_all()` to collect from plugins
2. Add deprecation warnings for external `plugin_mutexes` and `plugin_dependencies` parameters
3. Update `Scheduler.build_execution_dag()` to accept plugins directly (optional)
4. Add per-phase mutex acquisition in `_run_plugin_with_resources()`

### Phase 3: Plugin Migration (2-3 days)

**Objective:** Migrate all eligible plugins to use the new API.

**Files to modify:**
- All plugin files in [`plugins/plugins/`](../plugins/plugins/)

**Tasks:**
1. Migrate `apt.py` - Add `mutexes` for `pkgmgr:apt`, `pkgmgr:dpkg`
2. Migrate `snap.py` - Add `mutexes` for `pkgmgr:snap`
3. Migrate `flatpak.py` - Add `mutexes` for `pkgmgr:flatpak`
4. Migrate `pipx.py` - Add `mutexes` for `pkgmgr:pipx`
5. Migrate `cargo.py` - Add `mutexes` for `pkgmgr:cargo`
6. Migrate `rustup.py` - Add `mutexes` for `pkgmgr:rustup`, `runtime:rust`
7. Migrate `npm.py` - Add `mutexes` for `pkgmgr:npm`
8. Migrate `conda_self.py` - Add `mutexes` for `pkgmgr:conda`
9. Migrate `conda_packages.py` - Add `dependencies` for `conda-self`, `mutexes` for `pkgmgr:conda`
10. Migrate `texlive_self.py` - Add `mutexes` for `pkgmgr:texlive`
11. Migrate `texlive_packages.py` - Add `dependencies` for `texlive-self`, `mutexes` for `pkgmgr:texlive`
12. Migrate `calibre.py` - Add `mutexes` for `system:network` (download phase)
13. Migrate `waterfox.py` - Add `mutexes` for `system:network` (download phase)
14. Migrate remaining plugins as applicable

### Phase 4: Documentation (1 day)

**Objective:** Update documentation to reflect the new API.

**Files to modify:**
1. [`docs/plugin-development.md`](../docs/plugin-development.md) - Add new section on mutex/dependency declaration

**Tasks:**
1. Add "Mutex and Dependency Declaration" section to plugin development guide
2. Document `StandardMutexes` class and naming conventions
3. Add examples for common patterns
4. Update existing examples to show mutex declarations

---

## Test-Driven Development Plan

### Test Categories

#### 1. Unit Tests for `BasePlugin` Properties

**File:** `plugins/tests/test_mutex_dependency_declaration.py`

```python
"""Tests for mutex and dependency declaration API."""

import pytest
from core.streaming import Phase
from plugins.base import BasePlugin


class TestDependenciesProperty:
    """Tests for the dependencies property."""

    def test_default_dependencies_empty(self) -> None:
        """Test that default dependencies is an empty list."""

    def test_dependencies_returns_list(self) -> None:
        """Test that dependencies returns a list of strings."""

    def test_dependencies_can_be_overridden(self) -> None:
        """Test that subclasses can override dependencies."""

    def test_dependencies_with_single_dependency(self) -> None:
        """Test plugin with a single dependency."""

    def test_dependencies_with_multiple_dependencies(self) -> None:
        """Test plugin with multiple dependencies."""


class TestMutexesProperty:
    """Tests for the mutexes property."""

    def test_default_mutexes_empty(self) -> None:
        """Test that default mutexes is an empty dict."""

    def test_mutexes_returns_dict(self) -> None:
        """Test that mutexes returns a dict mapping Phase to list."""

    def test_mutexes_can_be_overridden(self) -> None:
        """Test that subclasses can override mutexes."""

    def test_mutexes_for_single_phase(self) -> None:
        """Test plugin with mutexes for a single phase."""

    def test_mutexes_for_multiple_phases(self) -> None:
        """Test plugin with mutexes for multiple phases."""

    def test_mutexes_with_standard_mutex_names(self) -> None:
        """Test using StandardMutexes constants."""


class TestAllMutexesProperty:
    """Tests for the all_mutexes convenience property."""

    def test_all_mutexes_empty_when_no_mutexes(self) -> None:
        """Test all_mutexes returns empty list when no mutexes declared."""

    def test_all_mutexes_single_phase(self) -> None:
        """Test all_mutexes with single phase."""

    def test_all_mutexes_multiple_phases(self) -> None:
        """Test all_mutexes combines mutexes from all phases."""

    def test_all_mutexes_deduplicates(self) -> None:
        """Test all_mutexes removes duplicates across phases."""

    def test_all_mutexes_sorted(self) -> None:
        """Test all_mutexes returns sorted list."""
```

#### 2. Unit Tests for Helper Functions

**File:** `core/tests/test_mutex_helpers.py`

```python
"""Tests for mutex helper functions."""

import pytest
from core.mutex import (
    collect_plugin_mutexes,
    collect_plugin_dependencies,
    StandardMutexes,
)
from core.streaming import Phase


class TestCollectPluginMutexes:
    """Tests for collect_plugin_mutexes function."""

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""

    def test_plugins_without_mutexes(self) -> None:
        """Test with plugins that have no mutexes."""

    def test_plugins_with_mutexes(self) -> None:
        """Test with plugins that have mutexes."""

    def test_filter_by_phase(self) -> None:
        """Test filtering mutexes by specific phase."""

    def test_all_phases_when_phase_none(self) -> None:
        """Test collecting all mutexes when phase is None."""

    def test_mixed_plugins(self) -> None:
        """Test with mix of plugins with and without mutexes."""


class TestCollectPluginDependencies:
    """Tests for collect_plugin_dependencies function."""

    def test_empty_plugin_list(self) -> None:
        """Test with empty plugin list."""

    def test_plugins_without_dependencies(self) -> None:
        """Test with plugins that have no dependencies."""

    def test_plugins_with_dependencies(self) -> None:
        """Test with plugins that have dependencies."""

    def test_mixed_plugins(self) -> None:
        """Test with mix of plugins with and without dependencies."""


class TestStandardMutexes:
    """Tests for StandardMutexes constants."""

    def test_package_manager_mutexes_exist(self) -> None:
        """Test that package manager mutex constants exist."""

    def test_runtime_mutexes_exist(self) -> None:
        """Test that runtime mutex constants exist."""

    def test_system_mutexes_exist(self) -> None:
        """Test that system mutex constants exist."""

    def test_mutex_naming_convention(self) -> None:
        """Test that mutexes follow naming convention (category:name)."""
```

#### 3. Integration Tests for Orchestrator

**File:** `core/tests/test_parallel_orchestrator_mutex_integration.py`

```python
"""Integration tests for ParallelOrchestrator with mutex/dependency declarations."""

import pytest
from core.parallel_orchestrator import ParallelOrchestrator
from core.streaming import Phase


class TestOrchestratorWithPluginDeclarations:
    """Tests for orchestrator using plugin-declared mutexes/dependencies."""

    @pytest.mark.asyncio
    async def test_collects_mutexes_from_plugins(self) -> None:
        """Test that orchestrator collects mutexes from plugins."""

    @pytest.mark.asyncio
    async def test_collects_dependencies_from_plugins(self) -> None:
        """Test that orchestrator collects dependencies from plugins."""

    @pytest.mark.asyncio
    async def test_respects_plugin_dependencies(self) -> None:
        """Test that dependent plugins run after their dependencies."""

    @pytest.mark.asyncio
    async def test_respects_mutex_conflicts(self) -> None:
        """Test that plugins with shared mutexes don't run in parallel."""

    @pytest.mark.asyncio
    async def test_parallel_execution_without_conflicts(self) -> None:
        """Test that plugins without conflicts run in parallel."""

    @pytest.mark.asyncio
    async def test_external_mutexes_override_plugin_declarations(self) -> None:
        """Test that external plugin_mutexes parameter still works."""

    @pytest.mark.asyncio
    async def test_deprecation_warning_for_external_mutexes(self) -> None:
        """Test that using external plugin_mutexes emits deprecation warning."""


class TestPerPhaseMutexAcquisition:
    """Tests for per-phase mutex acquisition."""

    @pytest.mark.asyncio
    async def test_download_phase_mutexes(self) -> None:
        """Test that download phase acquires correct mutexes."""

    @pytest.mark.asyncio
    async def test_execute_phase_mutexes(self) -> None:
        """Test that execute phase acquires correct mutexes."""

    @pytest.mark.asyncio
    async def test_different_mutexes_per_phase(self) -> None:
        """Test plugin with different mutexes for different phases."""
```

#### 4. Tests for Specific Plugin Migrations

**File:** `plugins/tests/test_plugin_mutex_declarations.py`

```python
"""Tests for plugin mutex and dependency declarations."""

import pytest
from core.streaming import Phase
from core.mutex import StandardMutexes


class TestAptPluginDeclarations:
    """Tests for AptPlugin mutex declarations."""

    def test_apt_has_no_dependencies(self) -> None:
        """Test that apt has no dependencies."""

    def test_apt_declares_apt_mutex(self) -> None:
        """Test that apt declares pkgmgr:apt mutex."""

    def test_apt_declares_dpkg_mutex(self) -> None:
        """Test that apt declares pkgmgr:dpkg mutex."""

    def test_apt_mutexes_for_execute_phase(self) -> None:
        """Test that apt mutexes are for EXECUTE phase."""


class TestCondaPackagesPluginDeclarations:
    """Tests for CondaPackagesPlugin declarations."""

    def test_conda_packages_depends_on_conda_self(self) -> None:
        """Test that conda-packages depends on conda-self."""

    def test_conda_packages_declares_conda_mutex(self) -> None:
        """Test that conda-packages declares pkgmgr:conda mutex."""


class TestTexlivePackagesPluginDeclarations:
    """Tests for TexlivePackagesPlugin declarations."""

    def test_texlive_packages_depends_on_texlive_self(self) -> None:
        """Test that texlive-packages depends on texlive-self."""

    def test_texlive_packages_declares_texlive_mutex(self) -> None:
        """Test that texlive-packages declares pkgmgr:texlive mutex."""


class TestDownloadPhasePlugins:
    """Tests for plugins with download phase mutexes."""

    def test_calibre_declares_network_mutex_for_download(self) -> None:
        """Test that calibre declares system:network for download phase."""

    def test_waterfox_declares_network_mutex_for_download(self) -> None:
        """Test that waterfox declares system:network for download phase."""
```

#### 5. End-to-End Tests

**File:** `core/tests/test_e2e_parallel_execution.py`

```python
"""End-to-end tests for parallel plugin execution with declarations."""

import pytest


class TestEndToEndParallelExecution:
    """End-to-end tests for parallel execution."""

    @pytest.mark.asyncio
    async def test_full_update_run_with_declarations(self) -> None:
        """Test a full update run using plugin declarations."""

    @pytest.mark.asyncio
    async def test_dependency_chain_execution_order(self) -> None:
        """Test that dependency chains execute in correct order."""

    @pytest.mark.asyncio
    async def test_mutex_prevents_parallel_execution(self) -> None:
        """Test that shared mutexes prevent parallel execution."""

    @pytest.mark.asyncio
    async def test_independent_plugins_run_in_parallel(self) -> None:
        """Test that independent plugins run in parallel."""
```

### Test Implementation Order

1. **First:** Unit tests for `BasePlugin` properties (TDD - write tests before implementation)
2. **Second:** Unit tests for helper functions (TDD)
3. **Third:** Integration tests for orchestrator (after core implementation)
4. **Fourth:** Plugin-specific tests (during migration)
5. **Fifth:** End-to-end tests (after all migrations complete)

---

## Plugin Migration Plan

### Migration Priority

**High Priority (Core package managers):**
1. `apt.py` - Most common, uses dpkg lock
2. `snap.py` - Common on Ubuntu
3. `flatpak.py` - Common desktop apps

**Medium Priority (Language package managers):**
4. `pipx.py` - Python apps
5. `cargo.py` - Rust packages
6. `rustup.py` - Rust toolchain
7. `npm.py` - Node packages

**Medium Priority (Plugins with dependencies):**
8. `conda_self.py` - Must run before conda-packages
9. `conda_packages.py` - Depends on conda-self
10. `texlive_self.py` - Must run before texlive-packages
11. `texlive_packages.py` - Depends on texlive-self

**Lower Priority (Download-heavy plugins):**
12. `calibre.py` - Large downloads
13. `waterfox.py` - Large downloads
14. `go_runtime.py` - Runtime download
15. `go_packages.py` - Depends on go-runtime
16. `julia_runtime.py` - Runtime download
17. `julia_packages.py` - Depends on julia-runtime

### Migration Template

For each plugin, apply this template:

```python
# Before migration
class MyPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "mypkg"

    @property
    def command(self) -> str:
        return "mypkg"

    # ... rest of implementation


# After migration
from core.mutex import StandardMutexes
from core.streaming import Phase


class MyPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "mypkg"

    @property
    def command(self) -> str:
        return "mypkg"

    @property
    def dependencies(self) -> list[str]:
        """Plugins that must run before this plugin."""
        return []  # Or ["other-plugin"] if dependent

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Mutexes required for each execution phase."""
        return {
            Phase.EXECUTE: [StandardMutexes.MYPKG_LOCK],
        }

    # ... rest of implementation
```

### Specific Plugin Migrations

#### `apt.py`

```python
@property
def dependencies(self) -> list[str]:
    return []

@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.EXECUTE: [
            StandardMutexes.APT_LOCK,
            StandardMutexes.DPKG_LOCK,
        ],
    }
```

#### `conda_packages.py`

```python
@property
def dependencies(self) -> list[str]:
    return ["conda-self"]

@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.EXECUTE: [StandardMutexes.CONDA_LOCK],
    }
```

#### `texlive_packages.py`

```python
@property
def dependencies(self) -> list[str]:
    return ["texlive-self"]

@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.EXECUTE: [StandardMutexes.TEXLIVE_LOCK],
    }
```

#### `calibre.py`

```python
@property
def dependencies(self) -> list[str]:
    return []

@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.DOWNLOAD: [StandardMutexes.NETWORK],
        Phase.EXECUTE: [],  # No execute-phase mutexes
    }
```

#### `waterfox.py`

```python
@property
def dependencies(self) -> list[str]:
    return []

@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.DOWNLOAD: [StandardMutexes.NETWORK],
        Phase.EXECUTE: [],  # Installation is local
    }
```

---

## Documentation Updates

### Updates to `docs/plugin-development.md`

Add a new section "Mutex and Dependency Declaration" after the "Plugins Requiring Sudo" section:

```markdown
### Mutex and Dependency Declaration

Plugins can declare their dependencies on other plugins and the mutexes (resource locks)
they require for each execution phase. This enables safe parallel execution.

#### Declaring Dependencies

Override the `dependencies` property to declare that your plugin must run after
other plugins:

```python
from plugins.base import BasePlugin


class CondaPackagesPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "conda-packages"

    @property
    def dependencies(self) -> list[str]:
        """Plugins that must complete before this plugin runs."""
        return ["conda-self"]  # conda-self must update first
```

#### Declaring Mutexes

Override the `mutexes` property to declare resource locks required for each phase:

```python
from core.mutex import StandardMutexes
from core.streaming import Phase
from plugins.base import BasePlugin


class AptPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "apt"

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        """Mutexes required for each execution phase."""
        return {
            Phase.EXECUTE: [
                StandardMutexes.APT_LOCK,
                StandardMutexes.DPKG_LOCK,
            ],
        }
```

#### Standard Mutex Names

Use the `StandardMutexes` class for common resource locks:

| Constant | Value | Description |
|----------|-------|-------------|
| `APT_LOCK` | `pkgmgr:apt` | APT package manager |
| `DPKG_LOCK` | `pkgmgr:dpkg` | dpkg (used by APT) |
| `SNAP_LOCK` | `pkgmgr:snap` | Snap package manager |
| `FLATPAK_LOCK` | `pkgmgr:flatpak` | Flatpak |
| `CONDA_LOCK` | `pkgmgr:conda` | Conda/Mamba |
| `TEXLIVE_LOCK` | `pkgmgr:texlive` | TeX Live (tlmgr) |
| `NETWORK` | `system:network` | Network bandwidth |
| `DISK` | `system:disk` | Disk I/O |

#### Mutex Naming Convention

Custom mutexes should follow the naming convention `category:name`:

- `pkgmgr:*` - Package manager locks
- `runtime:*` - Language runtime locks
- `system:*` - System resource locks
- `app:*` - Application-specific locks

#### Per-Phase Mutexes

Different phases may require different mutexes:

```python
@property
def mutexes(self) -> dict[Phase, list[str]]:
    return {
        Phase.DOWNLOAD: [StandardMutexes.NETWORK],  # Limit concurrent downloads
        Phase.EXECUTE: [StandardMutexes.APT_LOCK],  # Exclusive package manager access
    }
```

#### Convenience Property

Use `all_mutexes` to get all mutexes across all phases:

```python
plugin = AptPlugin()
print(plugin.all_mutexes)  # ['pkgmgr:apt', 'pkgmgr:dpkg']
```
```

---

## Risk Assessment

### Low Risk

1. **Backward Compatibility**: The new properties have sensible defaults (empty list/dict), so existing plugins continue to work without modification.

2. **Incremental Migration**: Plugins can be migrated one at a time without breaking the system.

3. **Existing Infrastructure**: The `MutexManager` and `Scheduler` already support the required functionality.

### Medium Risk

1. **Incorrect Mutex Declarations**: Plugins might declare incorrect mutexes, leading to unnecessary serialization or missed conflicts.
   - **Mitigation**: Comprehensive documentation and code review during migration.

2. **Circular Dependencies**: Plugins might accidentally create circular dependencies.
   - **Mitigation**: The `Scheduler` already detects and reports circular dependencies.

3. **Per-Phase Mutex Complexity**: Per-phase mutex acquisition adds complexity to the orchestrator.
   - **Mitigation**: Start with execute-phase only, add download-phase support later.

### High Risk

None identified. The proposal is well-aligned with existing infrastructure.

---

## Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Core API | 2-3 days | None |
| Phase 2: Orchestrator Integration | 1-2 days | Phase 1 |
| Phase 3: Plugin Migration | 2-3 days | Phase 2 |
| Phase 4: Documentation | 1 day | Phase 3 |
| **Total** | **6-9 days** | |

---

## Appendix: Complete Test List

### Unit Tests (plugins/tests/test_mutex_dependency_declaration.py)

1. `test_default_dependencies_empty`
2. `test_dependencies_returns_list`
3. `test_dependencies_can_be_overridden`
4. `test_dependencies_with_single_dependency`
5. `test_dependencies_with_multiple_dependencies`
6. `test_default_mutexes_empty`
7. `test_mutexes_returns_dict`
8. `test_mutexes_can_be_overridden`
9. `test_mutexes_for_single_phase`
10. `test_mutexes_for_multiple_phases`
11. `test_mutexes_with_standard_mutex_names`
12. `test_all_mutexes_empty_when_no_mutexes`
13. `test_all_mutexes_single_phase`
14. `test_all_mutexes_multiple_phases`
15. `test_all_mutexes_deduplicates`
16. `test_all_mutexes_sorted`

### Unit Tests (core/tests/test_mutex_helpers.py)

17. `test_collect_plugin_mutexes_empty_list`
18. `test_collect_plugin_mutexes_without_mutexes`
19. `test_collect_plugin_mutexes_with_mutexes`
20. `test_collect_plugin_mutexes_filter_by_phase`
21. `test_collect_plugin_mutexes_all_phases`
22. `test_collect_plugin_mutexes_mixed`
23. `test_collect_plugin_dependencies_empty_list`
24. `test_collect_plugin_dependencies_without_deps`
25. `test_collect_plugin_dependencies_with_deps`
26. `test_collect_plugin_dependencies_mixed`
27. `test_standard_mutexes_package_managers`
28. `test_standard_mutexes_runtimes`
29. `test_standard_mutexes_system`
30. `test_standard_mutexes_naming_convention`

### Integration Tests (core/tests/test_parallel_orchestrator_mutex_integration.py)

31. `test_orchestrator_collects_mutexes`
32. `test_orchestrator_collects_dependencies`
33. `test_orchestrator_respects_dependencies`
34. `test_orchestrator_respects_mutex_conflicts`
35. `test_orchestrator_parallel_without_conflicts`
36. `test_external_mutexes_override`
37. `test_deprecation_warning`
38. `test_download_phase_mutexes`
39. `test_execute_phase_mutexes`
40. `test_different_mutexes_per_phase`

### Plugin-Specific Tests (plugins/tests/test_plugin_mutex_declarations.py)

41. `test_apt_no_dependencies`
42. `test_apt_apt_mutex`
43. `test_apt_dpkg_mutex`
44. `test_apt_execute_phase`
45. `test_conda_packages_depends_on_self`
46. `test_conda_packages_conda_mutex`
47. `test_texlive_packages_depends_on_self`
48. `test_texlive_packages_texlive_mutex`
49. `test_calibre_network_mutex_download`
50. `test_waterfox_network_mutex_download`

### End-to-End Tests (core/tests/test_e2e_parallel_execution.py)

51. `test_full_update_run`
52. `test_dependency_chain_order`
53. `test_mutex_prevents_parallel`
54. `test_independent_plugins_parallel`

**Total: 54 tests**

# Update-All Python Implementation Plan

**Date:** January 5, 2026
**Version:** 1.0
**Status:** Draft

---

## Executive Summary

This document provides a comprehensive implementation plan for "update-all", a plugin-driven system update tool written in Python. The plan builds upon the research in `update-all-python-metaplan.md` and addresses all risks, gaps, and challenges identified in `update-all-implementation-plan-analysis.md`.

**Key Design Principles:**
1. **Plugin-driven architecture** - Each updatable component is handled by a standalone executable plugin
2. **Language-agnostic plugins** - Plugins can be written in any language (Python, Bash, Go, etc.)
3. **Parallel execution with resource control** - Maximize throughput while respecting CPU, memory, and network limits
4. **Dynamic mutex system** - Prevent conflicts between plugins updating shared resources
5. **Comprehensive logging and statistics** - Enable accurate time estimation and debugging
6. **Remote update support** - Update multiple machines via SSH
7. **Scheduled updates** - Automatic updates via systemd timers

---

## Table of Contents

1. [MVP Definition and Phased Rollout](#1-mvp-definition-and-phased-rollout)
2. [Architecture Overview](#2-architecture-overview)
3. [Plugin System Design](#3-plugin-system-design)
4. [Plugin CLI API Specification](#4-plugin-cli-api-specification)
5. [Mutex and Scheduling System](#5-mutex-and-scheduling-system)
6. [Resource Control](#6-resource-control)
7. [State Management and Recovery](#7-state-management-and-recovery)
8. [Remote Update Architecture](#8-remote-update-architecture)
9. [Scheduled Updates via systemd](#9-scheduled-updates-via-systemd)
10. [User Interface Design](#10-user-interface-design)
11. [Logging and Statistics](#11-logging-and-statistics)
12. [Time Estimation System](#12-time-estimation-system)
13. [Security Model](#13-security-model)
14. [Error Handling Strategy](#14-error-handling-strategy)
15. [Configuration Management](#15-configuration-management)
16. [Code Organization](#16-code-organization)
17. [Testing Strategy](#17-testing-strategy)
18. [Implementation Timeline](#18-implementation-timeline)

---

## 1. MVP Definition and Phased Rollout

### 1.1 MVP Scope (Phase 1 - Weeks 1-8)

The Minimum Viable Product focuses on core functionality without advanced features:

**Included in MVP:**
- Sequential plugin execution (no parallelism initially)
- 3 core plugins: apt, pipx, flatpak
- Basic Rich progress display
- Configuration via YAML files
- Local execution only
- Basic time estimation (historical average)
- Structured logging with structlog

**Excluded from MVP:**
- Parallel execution with mutex system
- Remote updates via SSH
- Scheduled updates via systemd
- Advanced statistical modeling
- Plugin self-update mechanism
- Resource limiting (CPU/memory/network)

### 1.2 Phase 2 - Parallel Execution (Weeks 9-14)

- Mutex system implementation
- DAG-based scheduler
- Resource controller (CPU, memory, network limits)
- Additional plugins: snap, cargo, npm, rustup

### 1.3 Phase 3 - Remote and Scheduled Updates (Weeks 15-20)

- SSH-based remote execution
- systemd timer integration
- Plugin self-update mechanism
- Desktop notifications

### 1.4 Phase 4 - Advanced Features (Weeks 21-26)

- Advanced statistical modeling for time estimation
- Plugin signing and verification
- Plugin repository system
- Rollback support for failed updates

### 1.5 Rollout Strategy

| Stage | Audience | Duration | Exit Criteria |
|-------|----------|----------|---------------|
| Alpha | Developer only | 4 weeks | All MVP features work |
| Beta | Trusted users | 4 weeks | No critical bugs, positive feedback |
| GA | Public | Ongoing | Stable API, documentation complete |

---

## 2. Architecture Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              update-all CLI                                  │
│                          (Typer + Rich Progress)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                            Core Orchestrator                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │    Plugin    │  │   Scheduler  │  │   Resource   │  │    State     │    │
│  │   Manager    │  │  (DAG-based) │  │  Controller  │  │   Manager    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                           Plugin Interface Layer                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Discovery   │  │   Executor   │  │   Metrics    │  │    Output    │    │
│  │              │  │  (Subprocess)│  │  Collector   │  │    Parser    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────────┤
│                              Plugins (External Executables)                  │
│  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐   │
│  │  apt   │  │flatpak │  │  snap  │  │  pipx  │  │ cargo  │  │  ...   │   │
│  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘  └────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Execution Model

The orchestrator uses an **async event loop** with subprocess-based plugin execution:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Async Event Loop (asyncio)                           │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │           Plugin Executor Pool (asyncio.Semaphore for concurrency)    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │  Plugin 1   │  │  Plugin 2   │  │  Plugin 3   │  │  Plugin 4   │  │  │
│  │  │ (async      │  │ (async      │  │ (async      │  │ (async      │  │  │
│  │  │  subprocess)│  │  subprocess)│  │  subprocess)│  │  subprocess)│  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Key Components:                                                             │
│  • asyncio.create_subprocess_exec() for non-blocking subprocess calls       │
│  • asyncio.Semaphore for limiting concurrent plugin executions              │
│  • asyncio.Queue for work distribution                                       │
│  • asyncio.Event for signaling and coordination                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Core Components

| Component | Responsibility | Key Classes |
|-----------|----------------|-------------|
| **Plugin Manager** | Discovery, loading, validation, registry | `PluginManager`, `PluginRegistry` |
| **Scheduler** | DAG construction, topological sort, execution order | `Scheduler`, `ExecutionDAG` |
| **Resource Controller** | CPU/memory/network limits, semaphores | `ResourceController`, `ResourceLimits` |
| **State Manager** | Persistence, resume, state transitions | `StateManager`, `ExecutionState` |
| **Plugin Executor** | Subprocess management, timeout, output capture | `PluginExecutor`, `ExecutionResult` |
| **Metrics Collector** | CPU, memory, I/O, network stats per plugin | `MetricsCollector`, `PluginMetrics` |
| **Output Parser** | JSON parsing, progress extraction | `OutputParser`, `PluginOutput` |

### 2.4 Data Flow

```
1. Discovery Phase
   ├── Load plugin manifests from config directories
   ├── Validate plugin interface compliance
   └── Build plugin registry

2. Estimation Phase (can be parallel, respects estimate-mutexes)
   ├── Run `is-applicable` for each plugin
   ├── Run `estimate-update` for applicable plugins
   ├── Query dynamic mutexes from each plugin
   └── Build execution DAG with dependencies and mutexes

3. Download Phase (parallel where allowed)
   ├── Execute downloads according to DAG order
   ├── Respect network bandwidth limits (max 2 parallel)
   └── Track progress and update UI

4. Update Phase (parallel where allowed)
   ├── Execute updates according to DAG order
   ├── Handle mutex acquisition/release
   ├── Collect metrics for each plugin
   └── Persist state after each plugin completes

5. Completion Phase
   ├── Generate summary report
   ├── Store statistics for future estimation
   └── Send notifications (if configured)
```

---

## 3. Plugin System Design

### 3.1 Plugin Types

Plugins are **external executables** that follow a defined CLI API. This design choice enables:
- Language-agnostic implementation (Python, Bash, Go, Rust, etc.)
- Full process isolation
- Easy testing and debugging
- Simple interface (exit codes + stdout/stderr)

### 3.2 Plugin Discovery Order

Plugins are discovered in the following order (later sources override earlier):

1. **Built-in plugins** - Shipped with update-all, installed in `<package>/plugins/builtin/`
2. **System plugins** - `/etc/update-all/plugins.d/*.yaml`
3. **User plugins** - `~/.config/update-all/plugins.d/*.yaml`
4. **Entry points** - pip-installed plugins via `update_all.plugins` entry point group

### 3.3 Plugin Manifest Format

Each plugin is defined by a YAML manifest:

```yaml
# ~/.config/update-all/plugins.d/apt.yaml
plugin:
  # Required fields
  name: apt
  version: "1.0.0"
  description: "APT package manager updates for Debian/Ubuntu"
  executable: /usr/local/lib/update-all/plugins/apt-plugin

  # Static capability declarations
  requires_sudo: true
  can_separate_download: true
  supports_self_update: false
  supports_dynamic_mutexes: true

  # Static mutex declarations (minimum set, extended by dynamic queries)
  static_mutexes:
    estimate: []
    download: [network]
    update: [apt-lock, dpkg-lock]

  static_dependencies:
    estimate: []
    download: []
    update: []

  # Plugin execution order (runs-after relationships)
  runs_after: []  # e.g., ["apt"] for pipx plugin

  # Timeouts (seconds) - per phase
  timeouts:
    is_applicable: 10
    estimate_update: 120
    download: 1800
    update: 3600

  # Resources this plugin can potentially affect (documentation)
  potential_affects:
    - python
    - perl
    - system-libraries

  # Plugin-specific settings (passed to plugin as environment variables)
  settings:
    auto_remove: true
    dist_upgrade: false
```

### 3.4 Plugin Validation

On discovery, each plugin is validated:

```python
class PluginValidator:
    """Validates plugin manifest and executable."""

    def validate(self, manifest: PluginManifest) -> ValidationResult:
        errors = []
        warnings = []

        # Check executable exists and is executable
        if not manifest.executable.exists():
            errors.append(f"Executable not found: {manifest.executable}")
        elif not os.access(manifest.executable, os.X_OK):
            errors.append(f"Executable not executable: {manifest.executable}")

        # Validate required commands are implemented
        for cmd in ["is-applicable", "estimate-update", "update"]:
            if not self._test_command(manifest.executable, cmd):
                errors.append(f"Plugin does not implement required command: {cmd}")

        # Validate optional commands
        if manifest.can_separate_download:
            if not self._test_command(manifest.executable, "download"):
                errors.append("Plugin declares can_separate_download but doesn't implement 'download'")

        # Check for sudo requirements
        if manifest.requires_sudo:
            if not self._test_command(manifest.executable, "sudo-programs-paths"):
                warnings.append("Plugin requires sudo but doesn't implement 'sudo-programs-paths'")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
```

### 3.5 Plugin Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Plugin Lifecycle                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ Discover │───►│ Validate │───►│ Register │───►│  Ready   │              │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘              │
│                        │                              │                      │
│                        ▼                              ▼                      │
│                  ┌──────────┐                   ┌──────────┐                │
│                  │ Invalid  │                   │ Execute  │                │
│                  │ (skip)   │                   │          │                │
│                  └──────────┘                   └──────────┘                │
│                                                      │                       │
│                              ┌───────────────────────┼───────────────────┐  │
│                              ▼                       ▼                   ▼  │
│                        ┌──────────┐           ┌──────────┐        ┌──────┐ │
│                        │ Success  │           │ Failed   │        │Timeout│ │
│                        └──────────┘           └──────────┘        └──────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.6 Plugin Isolation

Each plugin execution is isolated:

```python
class PluginExecutor:
    """Executes plugins with proper isolation."""

    async def execute(
        self,
        plugin: Plugin,
        command: str,
        timeout: float,
    ) -> ExecutionResult:
        # Create isolated environment
        env = self._create_isolated_env(plugin)

        # Create temporary directory for plugin
        with tempfile.TemporaryDirectory(prefix=f"update-all-{plugin.name}-") as tmpdir:
            env["TMPDIR"] = tmpdir
            env["UPDATE_ALL_PLUGIN_TMPDIR"] = tmpdir

            # Execute plugin
            process = await asyncio.create_subprocess_exec(
                str(plugin.executable),
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=tmpdir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    success=False,
                    exit_code=-1,
                    error="Plugin execution timed out",
                    timed_out=True,
                )

            return ExecutionResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                stdout=stdout.decode("utf-8"),
                stderr=stderr.decode("utf-8"),
            )

    def _create_isolated_env(self, plugin: Plugin) -> dict[str, str]:
        """Create isolated environment for plugin execution."""
        # Start with minimal environment
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/root"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

        # Add plugin-specific settings as environment variables
        for key, value in plugin.settings.items():
            env[f"UPDATE_ALL_{plugin.name.upper()}_{key.upper()}"] = str(value)

        return env
```

---

## 4. Plugin CLI API Specification

### 4.1 Command Overview

Each plugin must implement the following CLI commands:

| Command | Required | Description | Exit Codes |
|---------|----------|-------------|------------|
| `is-applicable` | Yes | Check if plugin applies to this system | 0=yes, 1=no |
| `estimate-update` | Yes | Discover updates, estimate time/size | 0=success, 1=not applicable, 2=error |
| `can-separate-download` | Yes | Check if download/update can be separated | 0=yes, 1=no |
| `download` | Conditional | Download updates without applying | 0=success, 1=error |
| `update` | Yes | Apply updates | 0=success, 1=error |
| `self-update` | No | Update plugin to latest version | 0=success, 1=not supported, 2=error |
| `self-upgrade` | No | Upgrade plugin (major version) | 0=success, 1=not supported, 2=error |
| `does-require-sudo` | Yes | Check if sudo is needed | 0=yes, 1=no |
| `sudo-programs-paths` | Conditional | List programs needing sudo | 0=success, stdout=paths |
| `version` | Yes | Report plugin version | 0=success, stdout=version |
| `validate` | No | Self-check plugin health | 0=healthy, 1=unhealthy |

### 4.2 Dynamic Mutex Commands

These commands are called AFTER `estimate-update` to discover runtime dependencies:

| Command | Description | Output Format |
|---------|-------------|---------------|
| `estimate-update-mutexes` | Mutexes held during estimate phase | One mutex per line |
| `download-mutexes` | Mutexes held during download phase | One mutex per line |
| `update-mutexes` | Mutexes held during update phase | One mutex per line |
| `estimate-update-dependency` | Mutexes that must be free for estimate | One mutex per line |
| `download-dependency` | Mutexes that must be free for download | One mutex per line |
| `update-dependency` | Mutexes that must be free for update | One mutex per line |
| `runs-after` | Plugins that must complete first | One plugin name per line |

### 4.3 Output Protocol

All commands should output JSON to stdout for structured data:

```json
{
  "status": "success",
  "data": { },
  "error": null,
  "progress": null
}
```

**Status values:**
- `success` - Command completed successfully
- `error` - Command failed
- `not_applicable` - Plugin doesn't apply to this system

**Error format:**
```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "NETWORK_ERROR",
    "message": "Failed to connect to package repository",
    "details": "Connection timed out after 30 seconds"
  }
}
```

### 4.4 estimate-update Output

The `estimate-update` command must output detailed information:

```json
{
  "status": "success",
  "data": {
    "applicable": true,
    "packages_to_update": [
      {
        "name": "python3.12",
        "current_version": "3.12.1",
        "new_version": "3.12.2",
        "download_size_bytes": 15000000,
        "installed_size_bytes": 45000000
      }
    ],
    "total_download_size_bytes": 95000000,
    "total_installed_size_bytes": 295000000,
    "estimated_time_seconds": 180,
    "affects_runtimes": ["python"],
    "affects_applications": ["firefox"],
    "requires_reboot": false,
    "security_updates": true
  }
}
```

### 4.5 Progress Reporting

For long-running commands, plugins can output progress to stderr:

```json
{"type": "progress", "percent": 45, "message": "Downloading package 3/10..."}
```

The orchestrator reads stderr line-by-line and updates the UI accordingly.

### 4.6 Self-Update vs Self-Upgrade

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `self-update` | Update to latest patch/minor version | Automatic, safe |
| `self-upgrade` | Upgrade to new major version | Manual, may have breaking changes |

### 4.7 Example Plugin Implementation (Bash)

```bash
#!/bin/bash
# apt-plugin - APT package manager plugin for update-all

set -euo pipefail
CACHE_FILE="/tmp/update-all-apt-cache.json"

case "${1:-}" in
    is-applicable)
        command -v apt-get &>/dev/null && exit 0 || exit 1
        ;;

    estimate-update)
        sudo apt-get update -qq 2>/dev/null
        upgradable=$(apt list --upgradable 2>/dev/null | tail -n +2)

        if [[ -z "$upgradable" ]]; then
            echo '{"status": "success", "data": {"applicable": false}}'
            exit 0
        fi

        count=$(echo "$upgradable" | wc -l)
        echo "{\"status\": \"success\", \"data\": {\"applicable\": true, \"package_count\": $count}}"
        echo "$upgradable" > "$CACHE_FILE"
        exit 0
        ;;

    update-mutexes)
        echo "apt-lock"
        echo "dpkg-lock"
        grep -q "python3" "$CACHE_FILE" 2>/dev/null && echo "python"
        exit 0
        ;;

    update)
        sudo apt-get upgrade -y
        exit $?
        ;;

    does-require-sudo)
        exit 0
        ;;

    sudo-programs-paths)
        echo "/usr/bin/apt-get"
        echo "/usr/bin/dpkg"
        exit 0
        ;;

    version)
        echo "1.0.0"
        exit 0
        ;;

    *)
        echo "Unknown command: ${1:-}" >&2
        exit 2
        ;;
esac
```

---

## 5. Mutex and Scheduling System

### 5.1 Mutex Naming Standard

Mutex names follow a structured format to prevent conflicts:

**Format:** `category:resource`

| Category | Examples | Description |
|----------|----------|-------------|
| `pkgmgr` | `pkgmgr:apt`, `pkgmgr:dpkg` | Package manager locks |
| `runtime` | `runtime:python`, `runtime:node` | Language runtime updates |
| `app` | `app:firefox`, `app:vscode` | Application updates |
| `system` | `system:network`, `system:disk` | System resources |

**Rules:**
- Case-insensitive comparison
- Alphanumeric, hyphen, underscore only
- Maximum 64 characters
- Reserved prefixes: `system:`, `internal:`

### 5.2 Mutex Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Mutex Lifecycle                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. Discovery (after estimate-update)                                        │
│     ├── Query static mutexes from manifest                                   │
│     ├── Query dynamic mutexes from plugin CLI                                │
│     └── Merge: final_mutexes = static ∪ dynamic                             │
│                                                                              │
│  2. DAG Construction                                                         │
│     ├── Build dependency graph from runs-after                              │
│     ├── Add mutex constraints as edges                                       │
│     └── Detect and reject cycles                                             │
│                                                                              │
│  3. Execution                                                                │
│     ├── Acquire required mutexes before starting plugin                     │
│     ├── Hold mutexes during execution                                        │
│     └── Release mutexes after completion                                     │
│                                                                              │
│  4. Fallback                                                                 │
│     ├── If dynamic query fails, use static mutexes only                     │
│     └── Log warning for debugging                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Deadlock Prevention

The scheduler uses **topological ordering** to prevent deadlocks:

```python
class Scheduler:
    """DAG-based scheduler with deadlock prevention."""

    def build_execution_dag(self, plugins: list[Plugin]) -> ExecutionDAG:
        """Build execution DAG from dependencies and mutexes."""
        dag = ExecutionDAG()

        # Add all plugins as nodes
        for plugin in plugins:
            dag.add_node(plugin.name, plugin)

        # Add edges from runs-after dependencies
        for plugin in plugins:
            for dep in plugin.runs_after:
                if dep in dag.nodes:
                    dag.add_edge(dep, plugin.name)

        # Add edges from mutex conflicts
        for plugin in plugins:
            for other in plugins:
                if plugin.name == other.name:
                    continue

                # If plugin needs a mutex that other holds, add edge
                for mutex in plugin.update_dependencies:
                    if mutex in other.update_mutexes:
                        dag.add_edge(other.name, plugin.name)

        # Detect cycles
        if dag.has_cycle():
            cycle = dag.find_cycle()
            raise SchedulingError(f"Circular dependency detected: {' -> '.join(cycle)}")

        return dag

    def get_execution_waves(self, dag: ExecutionDAG) -> list[list[str]]:
        """Return plugins grouped by execution wave."""
        waves = []
        remaining = set(dag.nodes.keys())

        while remaining:
            # Find nodes with no unprocessed dependencies
            wave = [
                node for node in remaining
                if all(dep not in remaining for dep in dag.predecessors(node))
            ]

            if not wave:
                raise SchedulingError("Unable to make progress - possible deadlock")

            waves.append(wave)
            remaining -= set(wave)

        return waves
```

### 5.4 Mutex Manager

```python
class MutexManager:
    """Manages mutex acquisition and release."""

    def __init__(self):
        self._held: dict[str, str] = {}  # mutex -> plugin holding it
        self._lock = asyncio.Lock()

    async def acquire(self, plugin: str, mutexes: list[str], timeout: float = 300) -> bool:
        """Acquire all mutexes for a plugin. Returns False on timeout."""
        deadline = time.monotonic() + timeout

        while True:
            async with self._lock:
                # Check if all mutexes are available
                conflicts = [m for m in mutexes if m in self._held]

                if not conflicts:
                    # Acquire all mutexes
                    for mutex in mutexes:
                        self._held[mutex] = plugin
                    return True

            # Wait and retry
            if time.monotonic() > deadline:
                return False

            await asyncio.sleep(0.1)

    async def release(self, plugin: str, mutexes: list[str]):
        """Release mutexes held by a plugin."""
        async with self._lock:
            for mutex in mutexes:
                if self._held.get(mutex) == plugin:
                    del self._held[mutex]

    def get_holder(self, mutex: str) -> str | None:
        """Get the plugin currently holding a mutex."""
        return self._held.get(mutex)
```

### 5.5 Execution Example

```
Given plugins: apt, flatpak, snap, pipx
Dependencies: pipx runs-after apt
Dynamic mutexes: apt holds "runtime:python" (discovered during estimate-update)

Step 1: Build DAG from dependencies
        apt ──────► pipx
        flatpak (independent)
        snap (independent)

Step 2: Add mutex constraints
        apt holds runtime:python
        pipx needs runtime:python free
        → Edge already exists from runs-after

Step 3: Determine execution waves
        Wave 1: apt, flatpak, snap (can start together)
        Wave 2: pipx (must wait for apt)

Step 4: Execute with mutex awareness
        Wave 1:
          - apt starts, acquires [pkgmgr:apt, pkgmgr:dpkg, runtime:python]
          - flatpak starts, acquires [pkgmgr:flatpak]
          - snap starts, acquires [pkgmgr:snap]

        Wave 1 completes, all mutexes released

        Wave 2:
          - pipx starts, acquires [pkgmgr:pipx]
```

---

## 6. Resource Control

### 6.1 Resource Limits Configuration

```yaml
# ~/.config/update-all/config.yaml
resources:
  max_parallel_tasks: 4
  max_parallel_downloads: 2
  max_memory_mb: 4096
  max_cpu_cores: 0  # 0 = all available
```

### 6.2 Resource Controller

```python
import asyncio
import psutil
from dataclasses import dataclass

@dataclass
class ResourceLimits:
    max_parallel_tasks: int = 4
    max_parallel_downloads: int = 2
    max_memory_mb: int = 4096

class ResourceController:
    """Controls resource usage across all plugin executions."""

    def __init__(self, limits: ResourceLimits):
        self.limits = limits
        self._task_semaphore = asyncio.Semaphore(limits.max_parallel_tasks)
        self._download_semaphore = asyncio.Semaphore(limits.max_parallel_downloads)
        self._active_pids: set[int] = set()

    async def acquire_task_slot(self) -> None:
        """Acquire a slot for task execution."""
        await self._task_semaphore.acquire()
        await self._wait_for_memory()

    def release_task_slot(self) -> None:
        self._task_semaphore.release()

    async def acquire_download_slot(self) -> None:
        await self._download_semaphore.acquire()

    def release_download_slot(self) -> None:
        self._download_semaphore.release()

    def register_pid(self, pid: int) -> None:
        self._active_pids.add(pid)

    def unregister_pid(self, pid: int) -> None:
        self._active_pids.discard(pid)

    async def _wait_for_memory(self) -> None:
        """Wait until memory usage is below limit."""
        while self._get_total_memory_mb() >= self.limits.max_memory_mb:
            await asyncio.sleep(1.0)

    def _get_total_memory_mb(self) -> int:
        total = 0
        for pid in list(self._active_pids):
            try:
                proc = psutil.Process(pid)
                total += proc.memory_info().rss // (1024 * 1024)
            except psutil.NoSuchProcess:
                self._active_pids.discard(pid)
        return total
```

### 6.3 Network Bandwidth Control

Network control is achieved through:
1. **Parallel download limiting** - `max_parallel_downloads` setting (default: 2)
2. **Download phase tracking** - Plugins in download phase use download semaphore
3. **External tools** - For true bandwidth limiting, use `trickle` or `tc`

### 6.4 CPU Control

CPU control is achieved through:
1. **Parallel task limiting** - `max_parallel_tasks` setting
2. **Nice values** - Lower priority for update processes
3. **Optional cgroups** - For hard CPU limits (requires root)

```python
async def execute_with_nice(self, plugin: Plugin, command: str):
    process = await asyncio.create_subprocess_exec(
        "nice", "-n", "10",
        str(plugin.executable), command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return process
```

---

## 7. State Management and Recovery

### 7.1 State Machine

Each update run follows a state machine:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Execution State Machine                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────┐    ┌──────────────┐    ┌────────────┐    ┌──────────────┐    │
│  │  INIT    │───►│  ESTIMATING  │───►│ DOWNLOADING│───►│   UPDATING   │    │
│  └──────────┘    └──────────────┘    └────────────┘    └──────────────┘    │
│       │                │                   │                  │             │
│       │                ▼                   ▼                  ▼             │
│       │          ┌──────────┐        ┌──────────┐       ┌──────────┐       │
│       └─────────►│  FAILED  │◄───────│  FAILED  │◄──────│  FAILED  │       │
│                  └──────────┘        └──────────┘       └──────────┘       │
│                        │                   │                  │             │
│                        ▼                   ▼                  ▼             │
│                  ┌─────────────────────────────────────────────────┐       │
│                  │                   COMPLETED                      │       │
│                  │  (with success_count, failure_count, skipped)   │       │
│                  └─────────────────────────────────────────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 State Persistence

State is persisted to disk after each plugin completes:

```python
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json

@dataclass
class PluginState:
    name: str
    phase: str  # estimate, download, update
    status: str  # pending, running, completed, failed, skipped
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

@dataclass
class ExecutionState:
    run_id: str
    started_at: datetime
    phase: str  # estimating, downloading, updating, completed
    plugins: dict[str, PluginState] = field(default_factory=dict)

    def save(self, path: Path):
        data = {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "phase": self.phase,
            "plugins": {
                name: {
                    "name": p.name,
                    "phase": p.phase,
                    "status": p.status,
                    "started_at": p.started_at.isoformat() if p.started_at else None,
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                    "error": p.error,
                }
                for name, p in self.plugins.items()
            }
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "ExecutionState":
        data = json.loads(path.read_text())
        state = cls(
            run_id=data["run_id"],
            started_at=datetime.fromisoformat(data["started_at"]),
            phase=data["phase"],
        )
        for name, p in data["plugins"].items():
            state.plugins[name] = PluginState(
                name=p["name"],
                phase=p["phase"],
                status=p["status"],
                started_at=datetime.fromisoformat(p["started_at"]) if p["started_at"] else None,
                completed_at=datetime.fromisoformat(p["completed_at"]) if p["completed_at"] else None,
                error=p["error"],
            )
        return state
```

### 7.3 Resume Capability

```python
class StateManager:
    """Manages execution state and resume capability."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_file = state_dir / "current_run.json"

    def has_incomplete_run(self) -> bool:
        if not self.state_file.exists():
            return False
        state = ExecutionState.load(self.state_file)
        return state.phase != "completed"

    def get_incomplete_run(self) -> ExecutionState | None:
        if self.has_incomplete_run():
            return ExecutionState.load(self.state_file)
        return None

    def get_pending_plugins(self, state: ExecutionState) -> list[str]:
        """Get plugins that haven't completed yet."""
        return [
            name for name, p in state.plugins.items()
            if p.status in ("pending", "running")
        ]

    def clear_state(self):
        if self.state_file.exists():
            self.state_file.unlink()
```

### 7.4 Interruption Handling

```python
import signal

class Orchestrator:
    def __init__(self):
        self._shutdown_requested = False
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        self._shutdown_requested = True
        # Allow current plugin to complete, then save state

    async def run(self):
        for plugin in self.plugins:
            if self._shutdown_requested:
                self.state.save(self.state_file)
                raise InterruptedError("Update interrupted by user")

            await self.execute_plugin(plugin)
            self.state.save(self.state_file)  # Save after each plugin
```

---

## 8. Remote Update Architecture

### 8.1 Remote Execution Model

Remote updates use a **push model** where the local orchestrator connects to remote hosts via SSH and executes update-all remotely.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Remote Update Architecture                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Local Machine                          Remote Machine                       │
│  ┌─────────────────┐                   ┌─────────────────┐                  │
│  │  update-all     │      SSH          │  update-all     │                  │
│  │  orchestrator   │─────────────────► │  (remote exec)  │                  │
│  │                 │                   │                 │                  │
│  │  - Connects     │   Progress JSON   │  - Runs plugins │                  │
│  │  - Streams      │◄─────────────────│  - Outputs JSON │                  │
│  │  - Displays     │                   │  - Returns code │                  │
│  └─────────────────┘                   └─────────────────┘                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Remote Host Configuration

```yaml
# ~/.config/update-all/hosts.yaml
hosts:
  server1:
    hostname: server1.example.com
    user: admin
    port: 22
    key_file: ~/.ssh/id_ed25519
    update_all_path: /usr/local/bin/update-all

  raspberry-pi:
    hostname: 192.168.1.100
    user: pi
    port: 22
    key_file: ~/.ssh/id_rsa
    sudo_password_env: PI_SUDO_PASS  # Environment variable with sudo password
```

### 8.3 Remote Executor

```python
import asyncio
import asyncssh

class RemoteExecutor:
    """Executes update-all on remote hosts via SSH."""

    def __init__(self, host_config: HostConfig):
        self.config = host_config
        self.connection: asyncssh.SSHClientConnection | None = None

    async def connect(self):
        self.connection = await asyncssh.connect(
            self.config.hostname,
            port=self.config.port,
            username=self.config.user,
            client_keys=[self.config.key_file],
            known_hosts=None,  # Or path to known_hosts
        )

    async def run_update(
        self,
        plugins: list[str] | None = None,
        dry_run: bool = False,
    ) -> AsyncIterator[ProgressEvent]:
        """Run update-all on remote host, streaming progress."""
        cmd = f"{self.config.update_all_path} run --json"
        if plugins:
            cmd += f" --plugins {','.join(plugins)}"
        if dry_run:
            cmd += " --dry-run"

        async with self.connection.create_process(cmd) as process:
            async for line in process.stdout:
                line = line.strip()
                if line:
                    try:
                        event = json.loads(line)
                        yield ProgressEvent.from_dict(event)
                    except json.JSONDecodeError:
                        yield ProgressEvent(type="log", message=line)

            await process.wait()
            if process.returncode != 0:
                raise RemoteUpdateError(
                    f"Remote update failed with code {process.returncode}"
                )

    async def disconnect(self):
        if self.connection:
            self.connection.close()
            await self.connection.wait_closed()
```

### 8.4 Connection Recovery

```python
class ResilientRemoteExecutor(RemoteExecutor):
    """Remote executor with automatic reconnection."""

    def __init__(self, host_config: HostConfig, max_retries: int = 3):
        super().__init__(host_config)
        self.max_retries = max_retries

    async def run_update_with_recovery(self, **kwargs):
        retries = 0
        while retries < self.max_retries:
            try:
                await self.connect()
                async for event in self.run_update(**kwargs):
                    yield event
                return
            except (asyncssh.Error, OSError) as e:
                retries += 1
                if retries >= self.max_retries:
                    raise ConnectionError(f"Failed after {retries} attempts: {e}")
                await asyncio.sleep(2 ** retries)  # Exponential backoff
            finally:
                await self.disconnect()
```

### 8.5 CLI for Remote Updates

```bash
# Update a single remote host
update-all remote server1

# Update multiple hosts in parallel
update-all remote server1 server2 raspberry-pi --parallel

# Check updates on remote host without applying
update-all remote server1 --check-only

# Dry run on remote host
update-all remote server1 --dry-run
```

---

## 9. Scheduled Updates via systemd

### 9.1 systemd Unit Templates

**Timer Unit:**
```ini
# ~/.config/systemd/user/update-all.timer
[Unit]
Description=Scheduled system updates via update-all

[Timer]
OnCalendar=weekly
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
```

**Service Unit:**
```ini
# ~/.config/systemd/user/update-all.service
[Unit]
Description=Run update-all system updates
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/update-all run --scheduled
Environment=UPDATE_ALL_SCHEDULED=1
```

### 9.2 Schedule Management

```python
from pathlib import Path
import subprocess

class ScheduleManager:
    """Manages systemd timer for scheduled updates."""

    TIMER_TEMPLATE = '''[Unit]
Description=Scheduled system updates via update-all

[Timer]
OnCalendar={schedule}
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
'''

    def __init__(self, user_mode: bool = True):
        self.user_mode = user_mode
        if user_mode:
            self.unit_dir = Path.home() / ".config/systemd/user"
        else:
            self.unit_dir = Path("/etc/systemd/system")

    def enable(self, schedule: str = "weekly"):
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        timer_path = self.unit_dir / "update-all.timer"
        timer_path.write_text(self.TIMER_TEMPLATE.format(schedule=schedule))
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", "update-all.timer")

    def disable(self):
        self._systemctl("disable", "--now", "update-all.timer")

    def _systemctl(self, *args):
        cmd = ["systemctl"]
        if self.user_mode:
            cmd.append("--user")
        cmd.extend(args)
        subprocess.run(cmd, check=True)
```

### 9.3 Desktop Notifications

```python
import subprocess

class NotificationManager:
    def notify(self, title: str, message: str, urgency: str = "normal"):
        try:
            subprocess.run([
                "notify-send", "--urgency", urgency,
                "--app-name", "update-all",
                title, message,
            ], check=True)
        except FileNotFoundError:
            pass
```

### 9.4 CLI for Scheduling

```bash
update-all schedule enable --interval weekly
update-all schedule enable --interval monthly
update-all schedule disable
update-all schedule status
```

---

## 10. User Interface Design

### 10.1 Progress Display Layout

```
╭─────────────────────────────────────────────────────────────────╮
│                     update-all v1.0.0                           │
│                   System Update Manager                          │
╰─────────────────────────────────────────────────────────────────╯

Overall Progress ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 45% 0:12:34

┌─────────────────────────────────────────────────────────────────┐
│ Plugin          Status       Progress    ETA      Download      │
├─────────────────────────────────────────────────────────────────┤
│ ✓ apt           Complete     ━━━━━━━━━━  -        245 MB        │
│ ● flatpak       Updating     ━━━━━━━━━━  0:02:15  128 MB        │
│ ○ snap          Pending      ━━━━━━━━━━  -        -             │
│ ✗ pipx          Failed       ━━━━━━━━━━  -        -             │
└─────────────────────────────────────────────────────────────────┘

Current Task: flatpak - Updating org.mozilla.firefox
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67% 12.5 MB/s
```

### 10.2 Rich Progress Implementation

```python
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.live import Live
from rich.panel import Panel

class ProgressDisplay:
    """Rich-based progress display for update-all."""

    def __init__(self):
        self.console = Console()
        self.plugins: dict[str, PluginProgress] = {}

    def create_display(self) -> Live:
        return Live(self._render(), console=self.console, refresh_per_second=4)

    def _render(self):
        # Create plugin table
        table = Table(title="Plugins", box=None)
        table.add_column("Plugin", width=15)
        table.add_column("Status", width=12)
        table.add_column("Progress", width=12)
        table.add_column("ETA", width=10)
        table.add_column("Download", width=12)

        for name, p in self.plugins.items():
            status_icon = {"complete": "✓", "running": "●", "pending": "○", "failed": "✗"}
            table.add_row(
                f"{status_icon.get(p.status, '?')} {name}",
                p.status.title(),
                f"{p.percent}%",
                p.eta or "-",
                p.download_size or "-",
            )

        return Panel(table, title="update-all v1.0.0")
```

### 10.3 Output Levels

| Flag | Level | Output |
|------|-------|--------|
| `--quiet` | Minimal | Errors and final summary only |
| (default) | Normal | Progress display, important messages |
| `--verbose` | Verbose | All messages, debug info |
| `--json` | Machine | JSON output for scripting |

### 10.4 Error Display

```python
def display_error(self, plugin: str, error: str, details: str | None = None):
    self.console.print(f"[red]✗ {plugin}[/red]: {error}")
    if details and self.verbose:
        self.console.print(f"  [dim]{details}[/dim]")
```

### 10.5 Summary Report

```
╭─────────────────────────────────────────────────────────────────╮
│                        Update Summary                            │
├─────────────────────────────────────────────────────────────────┤
│  Total time:     12 minutes 34 seconds                          │
│  Plugins run:    4                                               │
│  Successful:     3                                               │
│  Failed:         1 (pipx)                                        │
│  Downloaded:     373 MB                                          │
│  Packages:       47 updated                                      │
╰─────────────────────────────────────────────────────────────────╯
```

---

## 11. Logging and Statistics

### 11.1 Structured Logging with structlog

```python
import structlog
from pathlib import Path

def configure_logging(verbose: bool = False, log_file: Path | None = None):
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if log_file:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if verbose else logging.INFO
        ),
    )

# Usage
log = structlog.get_logger()
log.info("plugin_started", plugin="apt", phase="update")
log.info("plugin_completed", plugin="apt", duration=115.3, packages=12)
```

### 11.2 Metrics Collection

```python
from dataclasses import dataclass
from datetime import datetime
import psutil

@dataclass
class PluginMetrics:
    plugin: str
    phase: str
    start_time: datetime
    end_time: datetime | None = None
    wall_clock_seconds: float = 0.0
    cpu_user_seconds: float = 0.0
    cpu_kernel_seconds: float = 0.0
    max_rss_bytes: int = 0
    read_bytes: int = 0
    write_bytes: int = 0
    network_bytes_recv: int = 0
    network_bytes_sent: int = 0

class MetricsCollector:
    def __init__(self, plugin: str, phase: str):
        self.metrics = PluginMetrics(plugin=plugin, phase=phase, start_time=datetime.now())
        self.process: psutil.Process | None = None

    def start(self, pid: int):
        self.process = psutil.Process(pid)
        self._initial_io = self.process.io_counters()
        self._initial_net = psutil.net_io_counters()

    def finish(self) -> PluginMetrics:
        self.metrics.end_time = datetime.now()
        self.metrics.wall_clock_seconds = (
            self.metrics.end_time - self.metrics.start_time
        ).total_seconds()

        if self.process:
            cpu = self.process.cpu_times()
            self.metrics.cpu_user_seconds = cpu.user
            self.metrics.cpu_kernel_seconds = cpu.system

            io = self.process.io_counters()
            self.metrics.read_bytes = io.read_bytes - self._initial_io.read_bytes
            self.metrics.write_bytes = io.write_bytes - self._initial_io.write_bytes

        return self.metrics
```

### 11.3 Statistics Database

```python
import sqlite3
from pathlib import Path

class StatsDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plugin_runs (
                    id INTEGER PRIMARY KEY,
                    plugin TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    wall_clock_seconds REAL,
                    cpu_user_seconds REAL,
                    cpu_kernel_seconds REAL,
                    max_rss_bytes INTEGER,
                    read_bytes INTEGER,
                    write_bytes INTEGER,
                    network_bytes_recv INTEGER,
                    network_bytes_sent INTEGER,
                    download_size_bytes INTEGER,
                    package_count INTEGER,
                    success BOOLEAN
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

    def record(self, metrics: PluginMetrics, success: bool):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO plugin_runs
                (plugin, phase, timestamp, wall_clock_seconds,
                 cpu_user_seconds, cpu_kernel_seconds, max_rss_bytes,
                 read_bytes, write_bytes, network_bytes_recv,
                 network_bytes_sent, success)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metrics.plugin, metrics.phase,
                metrics.start_time.isoformat(),
                metrics.wall_clock_seconds,
                metrics.cpu_user_seconds, metrics.cpu_kernel_seconds,
                metrics.max_rss_bytes, metrics.read_bytes, metrics.write_bytes,
                metrics.network_bytes_recv, metrics.network_bytes_sent, success,
            ))

    def get_history(self, plugin: str, phase: str, limit: int = 20) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM plugin_runs
                WHERE plugin = ? AND phase = ? AND success = 1
                ORDER BY timestamp DESC LIMIT ?
            """, (plugin, phase, limit))
            return [dict(row) for row in cursor.fetchall()]
```

### 11.4 Log Rotation

```python
import logging
from logging.handlers import RotatingFileHandler

def setup_file_logging(log_path: Path):
    handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    logging.getLogger().addHandler(handler)
```

---

## 12. Time Estimation System

### 12.1 Estimation Approach

The time estimation system uses **multiple features** for prediction:
- Historical execution times
- Download size
- Package count
- Time of day (network congestion)

### 12.2 Statistical Model

```python
from dataclasses import dataclass
from statistics import mean, stdev, quantiles

@dataclass
class TimeEstimate:
    point_estimate: float  # seconds
    confidence_interval: tuple[float, float]  # (lower, upper)
    confidence_level: float  # e.g., 0.95
    data_points: int

class TimeEstimator:
    def __init__(self, stats_db: StatsDatabase):
        self.stats_db = stats_db

    def estimate(self, plugin: str, phase: str, download_size: int | None = None) -> TimeEstimate:
        history = self.stats_db.get_history(plugin, phase, limit=30)

        if not history:
            return TimeEstimate(300.0, (60.0, 900.0), 0.5, 0)

        times = [h["wall_clock_seconds"] for h in history]

        # Remove outliers
        if len(times) >= 5:
            avg, std = mean(times), stdev(times)
            times = [t for t in times if abs(t - avg) <= 2 * std]

        if len(times) < 3:
            avg = mean(times)
            return TimeEstimate(avg, (avg * 0.5, avg * 2.0), 0.7, len(times))

        avg = mean(times)
        q25, q75 = quantiles(times, n=4)[0], quantiles(times, n=4)[2]

        return TimeEstimate(avg, (q25, q75), 0.5, len(times))
```

### 12.3 Display Format

```python
def format_time_estimate(estimate: TimeEstimate) -> str:
    point = format_duration(estimate.point_estimate)
    if estimate.data_points == 0:
        return f"~{point} (no history)"
    elif estimate.data_points < 5:
        return f"~{point} (limited data)"
    else:
        lower = format_duration(estimate.confidence_interval[0])
        upper = format_duration(estimate.confidence_interval[1])
        return f"{point} ({lower} - {upper})"
```

---

## 13. Security Model

### 13.1 Sudo Configuration

```python
class SudoManager:
    """Manages sudoers configuration for plugins."""

    SUDOERS_TEMPLATE = """# update-all plugin: {plugin}
{user} ALL=(root) NOPASSWD: {programs}
"""

    def generate_sudoers_entry(self, plugin: Plugin, user: str) -> str:
        programs = plugin.get_sudo_programs()
        if not programs:
            return ""

        # Validate paths
        for prog in programs:
            if not Path(prog).is_absolute():
                raise SecurityError(f"Sudo program must be absolute path: {prog}")
            if not Path(prog).exists():
                raise SecurityError(f"Sudo program not found: {prog}")

        return self.SUDOERS_TEMPLATE.format(
            plugin=plugin.name,
            user=user,
            programs=", ".join(programs),
        )

    def install_sudoers(self, plugin: Plugin, user: str):
        entry = self.generate_sudoers_entry(plugin, user)
        sudoers_path = Path(f"/etc/sudoers.d/update-all-{plugin.name}")

        # Write via visudo for safety
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(entry)
            temp_path = f.name

        subprocess.run(
            ["sudo", "visudo", "-c", "-f", temp_path],
            check=True,
        )
        subprocess.run(
            ["sudo", "cp", temp_path, str(sudoers_path)],
            check=True,
        )
        subprocess.run(
            ["sudo", "chmod", "440", str(sudoers_path)],
            check=True,
        )
```

### 13.2 Plugin Trust Model

| Phase | Trust Level | Verification |
|-------|-------------|--------------|
| Phase 1 (MVP) | User-installed only | None |
| Phase 2 | Signed plugins | SHA256 checksum |
| Phase 3 | Repository plugins | GPG signature |

### 13.3 Secrets Management

```python
import keyring

class SecretsManager:
    SERVICE_NAME = "update-all"

    def get_secret(self, key: str) -> str | None:
        return keyring.get_password(self.SERVICE_NAME, key)

    def set_secret(self, key: str, value: str):
        keyring.set_password(self.SERVICE_NAME, key, value)

    def delete_secret(self, key: str):
        keyring.delete_password(self.SERVICE_NAME, key)
```

---

## 14. Error Handling Strategy

### 14.1 Error Categories

| Category | Example | Handling |
|----------|---------|----------|
| **Transient** | Network timeout | Retry with backoff |
| **Plugin Error** | Plugin crashed | Log, continue with next |
| **Configuration** | Invalid manifest | Skip plugin, warn user |
| **Fatal** | No plugins found | Abort with clear message |

### 14.2 Retry Logic

```python
async def execute_with_retry(
    self,
    plugin: Plugin,
    command: str,
    max_retries: int = 3,
) -> ExecutionResult:
    for attempt in range(max_retries):
        result = await self.execute(plugin, command)

        if result.success:
            return result

        if not self._is_transient_error(result):
            return result  # Don't retry non-transient errors

        await asyncio.sleep(2 ** attempt)  # Exponential backoff

    return result  # Return last failed result

def _is_transient_error(self, result: ExecutionResult) -> bool:
    transient_codes = ["NETWORK_ERROR", "TIMEOUT", "TEMPORARY_FAILURE"]
    return result.error_code in transient_codes
```

### 14.3 Continue on Error

```bash
# Continue even if some plugins fail
update-all run --continue-on-error

# Retry failed plugins from previous run
update-all retry
```

---

## 15. Configuration Management

### 15.1 Configuration Hierarchy

1. **Defaults** - Built into application
2. **System** - `/etc/update-all/config.yaml`
3. **User** - `~/.config/update-all/config.yaml`
4. **Environment** - `UPDATE_ALL_*` variables
5. **CLI** - Command-line arguments (highest priority)

### 15.2 Configuration Schema

```python
from pydantic import Field
from pydantic_settings import BaseSettings

class UpdateAllSettings(BaseSettings):
    model_config = {"env_prefix": "UPDATE_ALL_"}

    # Resource limits
    max_parallel_tasks: int = Field(default=4, ge=1, le=32)
    max_parallel_downloads: int = Field(default=2, ge=1, le=8)
    max_memory_mb: int = Field(default=4096, ge=512)

    # Paths
    plugins_dir: Path = Path("~/.config/update-all/plugins.d")
    cache_dir: Path = Path("~/.cache/update-all")
    log_dir: Path = Path("~/.local/share/update-all/logs")

    # Behavior
    dry_run: bool = False
    verbose: bool = False
    continue_on_error: bool = False

    # Timeouts
    plugin_timeout: int = Field(default=3600, ge=60)
```

### 15.3 Configuration File

```yaml
# ~/.config/update-all/config.yaml
plugins:
  enabled: [apt, flatpak, snap, pipx]
  disabled: [experimental-plugin]

resources:
  max_parallel_tasks: 4
  max_parallel_downloads: 2
  max_memory_mb: 4096

logging:
  level: INFO
  file: ~/.local/share/update-all/logs/update-all.log

notifications:
  enabled: true
  on_success: false
  on_failure: true
```

---

## 16. Code Organization

### 16.1 Monorepo with Independent Subprojects

The update-all project uses a **monorepo structure with independent Python subprojects**. Each subproject is a fully independent Poetry project with its own:
- `pyproject.toml` with its own dependencies
- `poetry.lock` for reproducible builds
- `justfile` for local development tasks
- Test suite with pytest
- Virtual environment (`.venv`)

This architecture enables:
- **Team ownership** - Different teams can own different subprojects
- **Independent versioning** - Each subproject can be versioned separately
- **Dependency isolation** - Subprojects can have different dependency versions
- **Faster CI** - Only changed subprojects need to be tested
- **Gradual migration** - New subprojects can be added without affecting existing ones

**Template Source:** The project structure is based on the template at `/home/adam/tmp/updateall`.

### 16.2 Monorepo Structure

```
update-all/                          # Repository root
├── README.adoc                      # Project documentation
├── justfile                         # Root justfile for monorepo operations
├── justfile-common-subproject.just  # Shared justfile for all subprojects
├── codespell_exceptions.txt         # Shared codespell exceptions
├── .pre-commit-config.yaml          # Shared pre-commit configuration
│
├── core/                            # Core library subproject
│   ├── pyproject.toml               # Poetry project definition
│   ├── poetry.lock                  # Locked dependencies
│   ├── poetry.toml                  # Poetry configuration (in-project venv)
│   ├── justfile                     # Subproject-specific tasks
│   ├── README.adoc                  # Subproject documentation
│   ├── core/                        # Python package
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   ├── scheduler.py
│   │   ├── executor.py
│   │   └── resource.py
│   └── tests/
│       ├── pytest.ini
│       └── test_*.py
│
├── cli/                             # CLI application subproject
│   ├── pyproject.toml               # Depends on core via path
│   ├── poetry.lock
│   ├── poetry.toml
│   ├── justfile
│   ├── README.adoc
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── plugins.py
│   │   ├── config.py
│   │   ├── remote.py
│   │   └── schedule.py
│   └── tests/
│       ├── pytest.ini
│       └── test_*.py
│
├── plugins/                         # Plugin management subproject
│   ├── pyproject.toml               # Depends on core via path
│   ├── poetry.lock
│   ├── poetry.toml
│   ├── justfile
│   ├── README.adoc
│   ├── plugins/
│   │   ├── __init__.py
│   │   ├── manager.py
│   │   ├── interface.py
│   │   ├── validator.py
│   │   └── builtin/
│   │       ├── apt.py
│   │       ├── flatpak.py
│   │       └── pipx.py
│   └── tests/
│       └── test_*.py
│
├── ui/                              # UI components subproject
│   ├── pyproject.toml               # Depends on core via path
│   ├── ...
│   └── ui/
│       ├── __init__.py
│       ├── progress.py
│       └── display.py
│
├── stats/                           # Statistics subproject
│   ├── pyproject.toml               # Depends on core via path
│   ├── ...
│   └── stats/
│       ├── __init__.py
│       ├── collector.py
│       ├── database.py
│       └── estimator.py
│
└── docs/                            # Documentation (not a Python project)
    ├── update-all-python-plan.md
    └── ...
```

### 16.3 Subproject pyproject.toml Examples

**Core library (no internal dependencies):**

```toml
# core/pyproject.toml
[tool.poetry]
name = "update-all-core"
version = "0.1.0"
description = "Core library for update-all system"
packages = [{ include = "core" }]
readme = "README.adoc"

[tool.poetry.dependencies]
python = "^3.11"
pydantic = "^2.12"
structlog = "^25.0"
psutil = "^7.0"

[tool.poetry.group.testing.dependencies]
pytest = "^8.3"
coverage = "^7.9"

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"

[tool.pyright]
venvPath = "."
venv = ".venv"

[tool.coverage.report]
show_missing = true
skip_empty = true
fail_under = 80
```

**CLI application (depends on core via path):**

```toml
# cli/pyproject.toml
[tool.poetry]
name = "update-all-cli"
version = "0.1.0"
description = "CLI application for update-all system"
packages = [{ include = "cli" }]
readme = "README.adoc"

[tool.poetry.dependencies]
python = "^3.11"
update-all-core = { path = "../core", develop = true }
update-all-plugins = { path = "../plugins", develop = true }
update-all-ui = { path = "../ui", develop = true }
typer = "^0.21"
rich = "^14.0"

[tool.poetry.group.testing.dependencies]
pytest = "^8.3"
coverage = "^7.9"

[tool.poetry.scripts]
update-all = "cli.main:app"

[build-system]
requires = ["poetry-core>=2.0.0,<3.0.0"]
build-backend = "poetry.core.masonry.api"
```

### 16.4 Root Justfile

The root justfile orchestrates operations across all subprojects:

```just
set fallback := true

# Subprojects in dependency order
subprojects := "core plugins ui stats cli"

[private]
_help:
    just --list

# Install all subprojects (poetry install)
install:
    #!/usr/bin/env bash
    set -euo pipefail
    for p in {{ subprojects }}; do
      echo "==> Installing $p"
      (cd "$p" && just install-code)
    done

# Run tests for all subprojects
test:
    #!/usr/bin/env bash
    set -euo pipefail
    for p in {{ subprojects }}; do
      echo "==> Testing $p"
      (cd "$p" && just test)
    done

# Run formatting hooks
format: install
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Running formatting hooks"
    pre-commit run ruff --all-files || true
    pre-commit run ruff-format --all-files || true
    echo "==> Formatting complete"

# Run all pre-commit hooks
validate: format
    #!/usr/bin/env bash
    set -euo pipefail
    echo "==> Running all pre-commit hooks"
    pre-commit run --all-files

# Clean build artifacts and virtualenvs
clean:
    #!/usr/bin/env bash
    set -euo pipefail
    for p in {{ subprojects }}; do
      echo "==> Cleaning $p"
      (cd "$p" && rm -rf .venv .pytest_cache .mypy_cache .ruff_cache dist build .coverage htmlcov)
    done

# Setup development environment
setup: install install-hooks
    @echo "Setup complete."

# Install pre-commit hooks
install-hooks: install
    pre-commit install --install-hooks
```

### 16.5 Shared Subproject Justfile

Each subproject imports a common justfile with shared tasks:

```just
# core/justfile
set fallback := true

import 'justfile-common-subproject.just'

[private]
help:
    just --list

# Run the sample script (if defined in pyproject.toml)
run-hello:
    poetry run core-hello
```

The shared justfile (`justfile-common-subproject.just`) provides:
- `install-poetry` - Install Poetry if missing
- `install-deps` - Install project dependencies
- `install-code` - Install code into the environment
- `test` - Run pytest with coverage
- `upgrade-all-dependencies` - Update all dependencies

### 16.6 Subproject Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Subproject Dependencies                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                              ┌──────────┐                                    │
│                              │   cli    │                                    │
│                              └────┬─────┘                                    │
│                                   │                                          │
│                    ┌──────────────┼──────────────┐                          │
│                    │              │              │                          │
│                    ▼              ▼              ▼                          │
│              ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
│              │ plugins  │  │    ui    │  │  stats   │                       │
│              └────┬─────┘  └────┬─────┘  └────┬─────┘                       │
│                   │             │             │                              │
│                   └─────────────┼─────────────┘                              │
│                                 │                                            │
│                                 ▼                                            │
│                           ┌──────────┐                                       │
│                           │   core   │                                       │
│                           └──────────┘                                       │
│                                                                              │
│  Legend:                                                                     │
│  ───► depends on (via path dependency in pyproject.toml)                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 16.7 Creating New Subprojects

To create a new subproject, use the template as a guide:

1. Create the subproject directory structure
2. Copy and adapt `pyproject.toml` from an existing subproject
3. Create `justfile` that imports `justfile-common-subproject.just`
4. Add the subproject to the root `justfile` subprojects list
5. Run `just install` to install all subprojects

### 16.8 External Dependencies per Subproject

```toml
# pyproject.toml
[tool.poetry.dependencies]
python = "^3.11"
typer = "^0.21"
rich = "^13.0"
pydantic = "^2.12"
pydantic-settings = "^2.0"
structlog = "^25.0"
aiofiles = "^24.0"
psutil = "^6.0"
asyncssh = "^2.18"  # For remote updates

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^0.24"
mypy = "^1.14"
ruff = "^0.8"
```

---

## 17. Testing Strategy

### 17.1 Test Categories

| Category | Coverage Target | Tools |
|----------|-----------------|-------|
| Unit tests | 80% | pytest |
| Integration tests | Key flows | pytest, mock plugins |
| Property tests | Scheduler | hypothesis |
| E2E tests | Happy path | pytest, real plugins |

### 17.2 Mock Plugin for Testing

```python
# tests/fixtures/mock_plugin.py
class MockPlugin:
    """Mock plugin for testing."""

    def __init__(self, name: str, behavior: dict):
        self.name = name
        self.behavior = behavior

    def is_applicable(self) -> bool:
        return self.behavior.get("applicable", True)

    def estimate_update(self) -> dict:
        return self.behavior.get("estimate", {"applicable": True})

    def update(self) -> int:
        if self.behavior.get("fail", False):
            return 1
        time.sleep(self.behavior.get("duration", 0.1))
        return 0
```

### 17.3 Testing Parallel Execution

```python
@pytest.mark.asyncio
async def test_parallel_execution_respects_mutexes():
    plugins = [
        MockPlugin("a", {"mutexes": ["shared"]}),
        MockPlugin("b", {"mutexes": ["shared"]}),
        MockPlugin("c", {"mutexes": ["other"]}),
    ]

    scheduler = Scheduler()
    dag = scheduler.build_execution_dag(plugins)
    waves = scheduler.get_execution_waves(dag)

    # a and b should not be in the same wave
    for wave in waves:
        assert not ("a" in wave and "b" in wave)
```

---

## 18. Implementation Timeline

### 18.1 Revised Timeline (26 weeks)

| Phase | Weeks | Deliverables |
|-------|-------|--------------|
| **Phase 1: MVP** | 1-8 | Core infrastructure, 3 plugins, basic UI |
| **Phase 2: Parallel** | 9-14 | Mutex system, scheduler, resource control |
| **Phase 3: Remote** | 15-20 | SSH updates, systemd timers, notifications |
| **Phase 4: Advanced** | 21-26 | Statistics, plugin signing, repository |

### 18.2 Phase 1 Breakdown (MVP)

| Week | Tasks |
|------|-------|
| 1 | Project setup, Poetry, basic CLI with Typer |
| 2 | Configuration management with Pydantic |
| 3 | Plugin discovery and validation |
| 4 | Plugin executor (subprocess management) |
| 5 | First plugin: apt |
| 6 | Plugins: pipx, flatpak |
| 7 | Rich progress display |
| 8 | Testing, documentation, alpha release |

### 18.3 Success Criteria

**MVP (Week 8):**
- [ ] `update-all run` executes all enabled plugins sequentially
- [ ] `update-all check` shows available updates
- [ ] Progress display shows current plugin and status
- [ ] Configuration via YAML file works
- [ ] Structured logging to file

**Phase 2 (Week 14):**
- [ ] Parallel execution with mutex system
- [ ] Resource limits enforced
- [ ] 7+ plugins available

**Phase 3 (Week 20):**
- [ ] Remote updates via SSH
- [ ] Scheduled updates via systemd
- [ ] Desktop notifications

**Phase 4 (Week 26):**
- [ ] Time estimation with confidence intervals
- [ ] Plugin self-update mechanism
- [ ] Documentation complete

---

## Appendix A: CLI Reference

```bash
# Main commands
update-all run [--dry-run] [--parallel N] [--plugins PLUGIN...]
update-all check [--json]
update-all download [--plugins PLUGIN...]

# Plugin management
update-all plugins list
update-all plugins info PLUGIN
update-all plugins enable PLUGIN
update-all plugins disable PLUGIN
update-all plugins update

# Configuration
update-all config show
update-all config edit
update-all config validate

# Remote updates
update-all remote HOST [--user USER] [--key KEY]

# Scheduling
update-all schedule enable [--interval weekly|monthly]
update-all schedule disable
update-all schedule status

# Sudo setup
update-all sudo-setup [--plugin PLUGIN]

# Statistics
update-all stats [--last N]
update-all history [--plugin PLUGIN]
```

---

## Appendix B: Risk Mitigation Summary

| Risk | Mitigation |
|------|------------|
| Plugin compatibility | Strict interface validation, version pinning |
| Sudo privilege escalation | Minimal sudo scope, sudoers validation |
| Resource exhaustion | Resource controller with limits |
| Plugin timeout/hang | Configurable timeouts, process killing |
| Concurrent update conflicts | Mutex system, dependency resolution |
| Network failures | Retry logic, resume support |
| Partial update state | State persistence, resume capability |
| Breaking system updates | Dry-run mode, staged rollout |

---

*End of Implementation Plan*

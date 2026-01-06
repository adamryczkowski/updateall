# Update-All Architecture Refinement Plan

**Date:** January 6, 2026
**Version:** 1.0
**Status:** Draft

---

## Executive Summary

This document describes architectural refinements to the update-all system to support:

1. **Live streaming output** from plugins to the tabbed UI during update check, download, and execution phases
2. **Download API** for plugins that support separate download and update steps
3. **Verification** that all original requirements remain satisfied

The current architecture executes plugins and captures output only after completion. This refinement introduces an async streaming model where plugins emit output line-by-line, enabling real-time display in the tabbed UI.

---

## Table of Contents

1. [Current Architecture Analysis](#1-current-architecture-analysis)
2. [Problem Statement](#2-problem-statement)
3. [Live Streaming Architecture](#3-live-streaming-architecture)
4. [Download API Design](#4-download-api-design)
5. [Plugin CLI Protocol Changes](#5-plugin-cli-protocol-changes)
6. [UI Integration](#6-ui-integration)
7. [Implementation Plan](#7-implementation-plan)
8. [Requirements Verification](#8-requirements-verification)
9. [Migration Strategy](#9-migration-strategy)

---

## 1. Current Architecture Analysis

### 1.1 Current Execution Flow

The current architecture follows a **batch output model**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Current Execution Flow                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Orchestrator                    Plugin                     UI               │
│      │                             │                         │               │
│      │──── execute() ─────────────►│                         │               │
│      │                             │                         │               │
│      │     (plugin runs,           │                         │               │
│      │      output buffered)       │                         │               │
│      │                             │                         │               │
│      │◄─── ExecutionResult ────────│                         │               │
│      │     (stdout, stderr)        │                         │               │
│      │                             │                         │               │
│      │──────────────────────────── display output ──────────►│               │
│      │                                                       │               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Current Plugin Interface

From [`core/core/interfaces.py`](../core/core/interfaces.py:12):

```python
class UpdatePlugin(ABC):
    async def check_available(self) -> bool: ...
    async def check_updates(self) -> list[dict[str, Any]]: ...
    async def execute(self, dry_run: bool = False) -> ExecutionResult: ...
```

### 1.3 Current BasePlugin Command Execution

From [`plugins/plugins/base.py`](../plugins/plugins/base.py:222):

```python
async def _run_command(self, cmd: list[str], timeout: int, ...) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        process.communicate(),  # Waits for completion
        timeout=timeout,
    )
    return return_code, stdout_str, stderr_str
```

**Problem:** `process.communicate()` waits for the entire command to complete before returning output.

### 1.4 Current Tab System

From [`ui/ui/tabbed_run.py`](../ui/ui/tabbed_run.py:447):

```python
async def _execute_plugin_with_streaming(self, plugin: UpdatePlugin) -> ExecutionResult:
    result = await plugin.execute(dry_run=self.dry_run)

    # Display output AFTER execution completes
    if result.stdout:
        for line in result.stdout.splitlines():
            self.post_message(PluginOutputMessage(plugin_name, line))
```

**Problem:** Output is displayed only after the plugin finishes, not during execution.

---

## 2. Problem Statement

### 2.1 User Experience Issues

1. **No live feedback** — Users see no output until a plugin completes (which can take minutes)
2. **No progress indication** — Cannot tell if a long-running update is progressing or stuck
3. **No download progress** — Cannot see download progress for large updates
4. **Delayed error detection** — Errors only visible after full execution

### 2.2 Missing Download API

The current plugin interface lacks:
- Separate download phase with progress reporting
- Ability to pre-download updates for offline installation
- Download size estimation and progress tracking

### 2.3 Requirements Gap

From the original requirements:

> *"Tabbed output, with one tab per plugin, showing **live updates** of update check, download and execution steps."*

The current implementation does not satisfy this requirement.

---

## 3. Live Streaming Architecture

### 3.1 Design Goals

1. **Real-time output** — Display plugin output as it's generated
2. **Structured progress** — Support JSON progress events alongside raw output
3. **Backward compatibility** — Existing plugins continue to work
4. **Phase awareness** — Track which phase (check, download, execute) is running

### 3.2 Streaming Execution Model

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Streaming Execution Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Orchestrator                    Plugin                     UI               │
│      │                             │                         │               │
│      │──── execute_streaming() ───►│                         │               │
│      │                             │                         │               │
│      │◄─── OutputEvent ────────────│                         │               │
│      │──────────────────────────── display ─────────────────►│               │
│      │                             │                         │               │
│      │◄─── ProgressEvent ──────────│                         │               │
│      │──────────────────────────── update progress ─────────►│               │
│      │                             │                         │               │
│      │◄─── OutputEvent ────────────│                         │               │
│      │──────────────────────────── display ─────────────────►│               │
│      │                             │                         │               │
│      │◄─── CompletionEvent ────────│                         │               │
│      │──────────────────────────── finalize ────────────────►│               │
│      │                             │                         │               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Event Types

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any

class EventType(str, Enum):
    """Types of streaming events from plugins."""
    OUTPUT = "output"           # Raw output line
    PROGRESS = "progress"       # Progress update (percentage, message)
    PHASE_START = "phase_start" # Phase started (check, download, execute)
    PHASE_END = "phase_end"     # Phase completed
    ERROR = "error"             # Error occurred
    COMPLETION = "completion"   # Plugin execution completed

class Phase(str, Enum):
    """Execution phases for plugins."""
    CHECK = "check"             # Checking for updates
    DOWNLOAD = "download"       # Downloading updates
    EXECUTE = "execute"         # Applying updates

@dataclass
class StreamEvent:
    """Base class for streaming events."""
    event_type: EventType
    plugin_name: str
    timestamp: datetime

@dataclass
class OutputEvent(StreamEvent):
    """Raw output line from plugin."""
    line: str
    stream: str = "stdout"  # "stdout" or "stderr"

@dataclass
class ProgressEvent(StreamEvent):
    """Progress update from plugin."""
    phase: Phase
    percent: float | None = None
    message: str | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    items_completed: int | None = None
    items_total: int | None = None

@dataclass
class PhaseEvent(StreamEvent):
    """Phase start/end event."""
    phase: Phase
    success: bool | None = None  # Only for phase_end
    error_message: str | None = None

@dataclass
class CompletionEvent(StreamEvent):
    """Plugin execution completed."""
    success: bool
    exit_code: int
    packages_updated: int = 0
    error_message: str | None = None
```

### 3.4 Streaming Plugin Interface

Add new streaming methods to the plugin interface:

```python
# core/core/interfaces.py

from collections.abc import AsyncIterator

class UpdatePlugin(ABC):
    # ... existing methods ...

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute the update process with streaming output.

        Yields:
            StreamEvent objects as the plugin executes.

        The final event should be a CompletionEvent.
        """
        # Default implementation wraps execute() for backward compatibility
        result = await self.execute(dry_run=dry_run)

        # Emit output lines
        for line in result.stdout.splitlines():
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=line,
                stream="stdout",
            )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=result.status == PluginStatus.SUCCESS,
            exit_code=result.exit_code or 0,
            packages_updated=result.packages_updated,
            error_message=result.error_message,
        )

    async def check_updates_streaming(self) -> AsyncIterator[StreamEvent]:
        """Check for updates with streaming output.

        Default implementation wraps check_updates().
        """
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
        )

        updates = await self.check_updates()

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
            success=True,
        )
```

### 3.5 Streaming Command Execution

Add streaming command execution to BasePlugin:

```python
# plugins/plugins/base.py

class BasePlugin(UpdatePlugin):
    # ... existing methods ...

    async def _run_command_streaming(
        self,
        cmd: list[str],
        timeout: int,
        *,
        sudo: bool = False,
        phase: Phase = Phase.EXECUTE,
    ) -> AsyncIterator[StreamEvent]:
        """Run a command with streaming output.

        Yields:
            StreamEvent objects as output is produced.
        """
        if sudo:
            cmd = ["sudo", *cmd]

        log = logger.bind(plugin=self.name, command=" ".join(cmd))
        log.debug("running_command_streaming")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def read_stream(
            stream: asyncio.StreamReader,
            stream_name: str,
        ) -> AsyncIterator[OutputEvent]:
            """Read lines from a stream and yield events."""
            while True:
                line = await stream.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").rstrip()

                # Check for JSON progress events
                if line_str.startswith('{"type":'):
                    try:
                        data = json.loads(line_str)
                        if data.get("type") == "progress":
                            yield ProgressEvent(
                                event_type=EventType.PROGRESS,
                                plugin_name=self.name,
                                timestamp=datetime.now(tz=UTC),
                                phase=phase,
                                percent=data.get("percent"),
                                message=data.get("message"),
                                bytes_downloaded=data.get("bytes_downloaded"),
                                bytes_total=data.get("bytes_total"),
                            )
                            continue
                    except json.JSONDecodeError:
                        pass

                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line_str,
                    stream=stream_name,
                )

        # Read stdout and stderr concurrently
        async def merge_streams() -> AsyncIterator[StreamEvent]:
            stdout_task = asyncio.create_task(
                self._collect_stream(process.stdout, "stdout")
            )
            stderr_task = asyncio.create_task(
                self._collect_stream(process.stderr, "stderr")
            )

            # Use asyncio.Queue to merge streams
            queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

            async def stream_to_queue(
                stream: asyncio.StreamReader,
                stream_name: str,
            ) -> None:
                async for event in read_stream(stream, stream_name):
                    await queue.put(event)
                await queue.put(None)  # Signal completion

            # Start stream readers
            tasks = [
                asyncio.create_task(stream_to_queue(process.stdout, "stdout")),
                asyncio.create_task(stream_to_queue(process.stderr, "stderr")),
            ]

            completed_streams = 0
            while completed_streams < 2:
                event = await queue.get()
                if event is None:
                    completed_streams += 1
                else:
                    yield event

            await asyncio.gather(*tasks)

        try:
            async with asyncio.timeout(timeout):
                async for event in merge_streams():
                    yield event

                await process.wait()

        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=f"Command timed out after {timeout}s",
            )
            return

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=process.returncode == 0,
            exit_code=process.returncode or 0,
        )
```

---

## 4. Download API Design

### 4.1 Design Goals

1. **Separate download phase** — Allow pre-downloading updates
2. **Progress tracking** — Report download progress in real-time
3. **Resumable downloads** — Support resuming interrupted downloads
4. **Size estimation** — Report expected download size before starting

### 4.2 Download Interface

Add download methods to the plugin interface:

```python
# core/core/interfaces.py

class UpdatePlugin(ABC):
    # ... existing methods ...

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Returns:
            True if download() can be called separately from execute().
        """
        return False

    async def estimate_download(self) -> DownloadEstimate | None:
        """Estimate the download size and time.

        Returns:
            DownloadEstimate with size and time estimates, or None if
            no downloads are needed or estimation is not supported.
        """
        return None

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Download updates without applying them.

        This method should only be called if supports_download is True.

        Yields:
            StreamEvent objects with download progress.
        """
        raise NotImplementedError("Plugin does not support separate download")

    async def execute_after_download(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute updates after download phase.

        This method assumes download() was already called.

        Yields:
            StreamEvent objects as the plugin executes.
        """
        # Default: same as execute_streaming
        async for event in self.execute_streaming(dry_run=dry_run):
            yield event
```

### 4.3 Download Estimate Model

```python
# core/core/models.py

@dataclass
class DownloadEstimate:
    """Estimate for download phase."""

    total_bytes: int | None = None
    """Total bytes to download, or None if unknown."""

    package_count: int | None = None
    """Number of packages to download."""

    estimated_seconds: float | None = None
    """Estimated download time in seconds."""

    packages: list[PackageDownload] = field(default_factory=list)
    """Details for each package to download."""

@dataclass
class PackageDownload:
    """Download information for a single package."""

    name: str
    """Package name."""

    version: str
    """Version to download."""

    size_bytes: int | None = None
    """Download size in bytes."""

    url: str | None = None
    """Download URL (for logging/debugging)."""
```

### 4.4 Download Progress Events

Plugins report download progress via `ProgressEvent`:

```python
# Example progress events during download

# Starting download
yield PhaseEvent(
    event_type=EventType.PHASE_START,
    plugin_name="apt",
    timestamp=now,
    phase=Phase.DOWNLOAD,
)

# Progress update
yield ProgressEvent(
    event_type=EventType.PROGRESS,
    plugin_name="apt",
    timestamp=now,
    phase=Phase.DOWNLOAD,
    percent=45.5,
    message="Downloading python3.12...",
    bytes_downloaded=15_000_000,
    bytes_total=33_000_000,
    items_completed=3,
    items_total=10,
)

# Download complete
yield PhaseEvent(
    event_type=EventType.PHASE_END,
    plugin_name="apt",
    timestamp=now,
    phase=Phase.DOWNLOAD,
    success=True,
)
```

### 4.5 Example Download Implementation

```python
# plugins/plugins/apt.py

class AptPlugin(BasePlugin):
    @property
    def supports_download(self) -> bool:
        return True

    async def estimate_download(self) -> DownloadEstimate | None:
        # Run apt-get --print-uris to get download info
        return_code, stdout, stderr = await self._run_command(
            ["apt-get", "--print-uris", "-qq", "upgrade"],
            timeout=60,
            sudo=True,
        )

        if return_code != 0:
            return None

        packages = []
        total_bytes = 0

        for line in stdout.splitlines():
            # Parse: 'url' filename size md5
            match = re.match(r"'([^']+)'\s+(\S+)\s+(\d+)", line)
            if match:
                url, filename, size = match.groups()
                size_bytes = int(size)
                total_bytes += size_bytes
                packages.append(PackageDownload(
                    name=filename,
                    version="",
                    size_bytes=size_bytes,
                    url=url,
                ))

        return DownloadEstimate(
            total_bytes=total_bytes,
            package_count=len(packages),
            packages=packages,
        )

    async def download(self) -> AsyncIterator[StreamEvent]:
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        async for event in self._run_command_streaming(
            ["apt-get", "-d", "-y", "upgrade"],
            timeout=3600,
            sudo=True,
            phase=Phase.DOWNLOAD,
        ):
            yield event

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            success=True,
        )
```

---

## 5. Plugin CLI Protocol Changes

### 5.1 External Plugin Streaming

For external executable plugins (non-Python), define a streaming protocol:

**stdout:** Regular output lines
**stderr:** Progress events as JSON (one per line)

```json
{"type": "progress", "phase": "download", "percent": 45, "message": "Downloading..."}
{"type": "progress", "phase": "download", "bytes_downloaded": 15000000, "bytes_total": 33000000}
{"type": "phase_end", "phase": "download", "success": true}
```

### 5.2 New CLI Commands

Add to the plugin CLI API:

| Command | Description | Output |
|---------|-------------|--------|
| `can-separate-download` | Check if download is separate | Exit 0=yes, 1=no |
| `estimate-download` | Get download size estimate | JSON to stdout |
| `download` | Download updates only | Streaming output |

### 5.3 estimate-download Output Format

```json
{
  "status": "success",
  "data": {
    "total_bytes": 95000000,
    "package_count": 12,
    "estimated_seconds": 120,
    "packages": [
      {
        "name": "python3.12",
        "version": "3.12.2",
        "size_bytes": 15000000
      }
    ]
  }
}
```

---

## 6. UI Integration

### 6.1 Updated Tab System

Modify [`ui/ui/tabbed_run.py`](../ui/ui/tabbed_run.py) to consume streaming events:

```python
# ui/ui/tabbed_run.py

class TabbedRunApp(App[None]):
    async def _execute_plugin_with_streaming(
        self,
        plugin: UpdatePlugin,
    ) -> ExecutionResult:
        """Execute a plugin and stream its output."""
        plugin_name = plugin.name

        # Run pre-execute hook
        await plugin.pre_execute()

        # Stream execution events
        async for event in plugin.execute_streaming(dry_run=self.dry_run):
            if isinstance(event, OutputEvent):
                self.post_message(PluginOutputMessage(
                    plugin_name,
                    event.line if event.stream == "stdout"
                    else f"[red]{event.line}[/red]",
                ))

            elif isinstance(event, ProgressEvent):
                self._update_progress(plugin_name, event)

            elif isinstance(event, PhaseEvent):
                if event.event_type == EventType.PHASE_START:
                    self.post_message(PluginOutputMessage(
                        plugin_name,
                        f"[bold]Starting {event.phase.value}...[/bold]",
                    ))
                elif event.event_type == EventType.PHASE_END:
                    status = "✓" if event.success else "✗"
                    self.post_message(PluginOutputMessage(
                        plugin_name,
                        f"[bold]{status} {event.phase.value} complete[/bold]",
                    ))

            elif isinstance(event, CompletionEvent):
                # Build ExecutionResult from completion event
                result = ExecutionResult(
                    plugin_name=plugin_name,
                    status=PluginStatus.SUCCESS if event.success else PluginStatus.FAILED,
                    start_time=self.plugin_tabs[plugin_name].start_time,
                    end_time=datetime.now(tz=UTC),
                    exit_code=event.exit_code,
                    packages_updated=event.packages_updated,
                    error_message=event.error_message,
                )

                await plugin.post_execute(result)
                return result

        # Should not reach here
        raise RuntimeError("Plugin did not emit CompletionEvent")

    def _update_progress(self, plugin_name: str, event: ProgressEvent) -> None:
        """Update progress display for a plugin."""
        if plugin_name in self.status_bars:
            bar = self.status_bars[plugin_name]

            if event.percent is not None:
                bar.update_progress(event.percent)

            if event.message:
                bar.update_status(event.message)

            if event.bytes_downloaded and event.bytes_total:
                pct = (event.bytes_downloaded / event.bytes_total) * 100
                size_mb = event.bytes_downloaded / (1024 * 1024)
                total_mb = event.bytes_total / (1024 * 1024)
                bar.update_status(f"{size_mb:.1f}/{total_mb:.1f} MB")
```

### 6.2 Enhanced Progress Display

Add download progress to the status bar:

```python
# ui/ui/tabbed_run.py

class StatusBar(Static):
    state: reactive[PluginState] = reactive(PluginState.PENDING)
    progress: reactive[float] = reactive(0.0)
    status_message: reactive[str] = reactive("")

    def watch_progress(self, progress: float) -> None:
        self._refresh_display()

    def _refresh_display(self) -> None:
        icons = {
            PluginState.PENDING: "⏳",
            PluginState.RUNNING: "🔄",
            PluginState.SUCCESS: "✅",
            PluginState.FAILED: "❌",
            PluginState.SKIPPED: "⊘",
            PluginState.TIMEOUT: "⏱️",
        }
        icon = icons.get(self.state, "")

        if self.state == PluginState.RUNNING and self.progress > 0:
            bar = self._render_progress_bar(self.progress)
            text = f"{icon} {self.plugin_name}: {bar} {self.progress:.0f}%"
            if self.status_message:
                text += f" - {self.status_message}"
        else:
            text = f"{icon} {self.plugin_name}: {self.state.value.upper()}"

        self.update(text)

    def _render_progress_bar(self, percent: float, width: int = 20) -> str:
        filled = int(width * percent / 100)
        empty = width - filled
        return f"[{'█' * filled}{'░' * empty}]"
```

---

## 7. Implementation Plan

> **Note:** This implementation plan incorporates risk mitigation strategies from the
> [Architecture Refinement Risk Analysis](architecture-refinement-risk-analysis.md).
> The timeline has been extended from 8 weeks to 12 weeks based on risk assessment.

### 7.1 Phase 1: Core Streaming Infrastructure (Week 1-3)

**Objective:** Establish the foundational streaming architecture with proper resource management.

#### 7.1.1 Event Types and Streaming Interface

1. **Add event types** to `core/core/streaming.py` (new file)
   - Use `@dataclass(slots=True)` for all event classes to reduce memory overhead (Risk P2)
   - Implement `to_dict()` and `to_json()` methods for serialization

2. **Add streaming interface** to `core/core/interfaces.py`
   - Add `execute_streaming()` with default implementation wrapping `execute()` (Risk I1, B1)
   - Add `check_updates_streaming()` with default implementation
   - Add `supports_streaming` property for capability detection

#### 7.1.2 Streaming Command Execution

3. **Implement streaming execution** in `plugins/plugins/base.py`
   - Use `asyncio.TaskGroup` (Python 3.11+) for stream merging (Risk T2)
   - Use bounded `asyncio.Queue(maxsize=1000)` with backpressure (Risk T3)
   - Implement event dropping with warning logs when queue is full
   - Use `PROGRESS:` prefix for JSON progress lines (Risk T5)

4. **Add streaming helper utilities** to `core/core/streaming.py`
   - Create `safe_consume_stream()` using `contextlib.aclosing()` (Risk T1)
   - Create `timeout_stream()` wrapper using `asyncio.timeout()` (Risk O2)
   - Create `batched_stream()` for UI event batching (Risk P1)

#### 7.1.3 Mutex Manager Improvements

5. **Enhance MutexManager** in `core/core/mutex.py` (Risk T4)
   - Implement ordered mutex acquisition (sort mutex names before acquiring)
   - Add `asyncio.Condition` for efficient waiting instead of polling
   - Add deadlock detection with configurable timeout
   - Add comprehensive mutex state logging

#### 7.1.4 Testing Infrastructure

6. **Add streaming tests** using `pytest-asyncio` (Risk S2)
   - Create mock stream generators for deterministic testing
   - Add property-based tests for event parsing using `hypothesis`
   - Test edge cases: empty streams, rapid events, timeouts

### 7.2 Phase 2: Download API (Week 4-5)

**Objective:** Implement separate download phase with progress tracking.

#### 7.2.1 Download Interface

1. **Add download interface** to `core/core/interfaces.py`
   - Add `supports_download` property (default: `False`)
   - Add `estimate_download()` method returning `DownloadEstimate | None`
   - Add `download()` async generator method
   - Add `execute_after_download()` for post-download execution

2. **Add download models** to `core/core/models.py`
   - Add `DownloadEstimate` dataclass with size, package count, time estimate
   - Add `PackageDownload` dataclass for per-package information

#### 7.2.2 Plugin Implementations

3. **Implement download** in apt plugin as reference
   - Use `apt-get --print-uris` for download estimation
   - Use `apt-get -d -y upgrade` for download-only mode
   - Parse apt progress output for real-time updates

4. **Add download support** to other plugins
   - flatpak: Use `flatpak update --no-deploy` for download-only
   - snap: Investigate snap download capabilities
   - Document plugins that don't support separate download

### 7.3 Phase 3: UI Integration (Week 6-8)

**Objective:** Update the Textual UI to consume streaming events with optimal performance.

#### 7.3.1 Textual Version Management (Risk I2, E2)

1. **Pin Textual version** in `ui/pyproject.toml`
   ```toml
   textual = ">=0.47.0,<0.50.0"
   ```

2. **Abstract Textual-specific code** behind interfaces
   - Create `UIEventHandler` protocol for event processing
   - Allow future replacement of Textual if needed

#### 7.3.2 Streaming UI Components

3. **Update TabbedRunApp** to consume streaming events
   - Implement `BatchedEventHandler` with 50ms batching interval (Risk P1)
   - Rate-limit UI updates to 30 FPS maximum
   - Use virtual scrolling for log output (Textual's `RichLog` supports this)

4. **Add progress bars** to status display
   - Update `StatusBar` widget with progress percentage
   - Add download size display (bytes downloaded / total)
   - Show phase indicators (check → download → execute)

5. **Add download progress** visualization
   - Per-package download progress
   - Overall download progress bar
   - Estimated time remaining based on current speed

#### 7.3.3 Sudo Handling (Risk O1)

6. **Implement sudo pre-authentication**
   - Add `ensure_sudo_authenticated()` helper
   - Use `sudo -v -n` to check if sudo is cached
   - Show clear UI message when waiting for sudo password
   - Prompt for password before streaming starts

### 7.4 Phase 4: External Plugin Support (Week 9-10)

**Objective:** Enable external executable plugins to participate in streaming.

#### 7.4.1 Streaming Protocol Documentation

1. **Document streaming protocol** for external plugins
   - stdout: Regular output lines
   - stderr: Progress events as JSON with `PROGRESS:` prefix (Risk T5)
   - Define all event types and their JSON schemas
   - Provide examples in Bash, Python, and Go

2. **Create validation tool** for plugin authors
   - CLI tool to validate plugin streaming output
   - Test harness for plugin development

#### 7.4.2 Plugin Executor Updates

3. **Add JSON progress parsing** to plugin executor
   - Parse `PROGRESS:` prefixed lines from stderr
   - Graceful fallback for non-streaming plugins (Risk B2)
   - Show "legacy mode" indicator in UI for non-streaming plugins

4. **Update plugin development guide**
   - Add streaming protocol section
   - Include migration guide for existing plugins
   - Document backward compatibility guarantees

#### 7.4.3 Example Plugins

5. **Create example external plugins**
   - Bash example with progress reporting
   - Python example with full streaming support
   - Document best practices for plugin authors

### 7.5 Phase 5: Polish, Testing & Documentation (Week 11-12)

**Objective:** Ensure production readiness with comprehensive testing and documentation.

#### 7.5.1 Integration Testing

1. **End-to-end streaming tests**
   - Test with real plugins (apt, flatpak, snap)
   - Test parallel execution with streaming
   - Test error handling and recovery

2. **Performance testing**
   - Benchmark UI with high-frequency events
   - Memory usage profiling during long updates
   - CPU usage monitoring

3. **Cross-Python version testing** (Risk E1)
   - Test on Python 3.11, 3.12, 3.13
   - Verify asyncio behavior consistency

#### 7.5.2 Feature Flags (Risk I3)

4. **Implement streaming feature flag**
   - Add `streaming_enabled` to `GlobalConfig`
   - Allow fallback to batch mode if issues occur
   - Enable gradual rollout

#### 7.5.3 Documentation

5. **Update all documentation**
   - Architecture documentation
   - Plugin development guide
   - User guide with streaming features
   - Troubleshooting guide

#### 7.5.4 Monitoring Metrics (from Risk Analysis Appendix B)

6. **Add monitoring for production**
   - Memory usage per plugin (target: < 50 MB, alert: > 100 MB)
   - UI update latency (target: < 50 ms, alert: > 200 ms)
   - Event queue depth (target: < 100, alert: > 500)
   - Test coverage (target: > 80%, alert: < 70%)

### 7.6 Implementation Timeline Summary

| Phase | Duration | Weeks | Key Deliverables |
|-------|----------|-------|------------------|
| 1: Core Streaming | 3 weeks | 1-3 | Event types, streaming interface, mutex improvements |
| 2: Download API | 2 weeks | 4-5 | Download interface, apt/flatpak implementation |
| 3: UI Integration | 3 weeks | 6-8 | Streaming UI, progress bars, sudo handling |
| 4: External Plugins | 2 weeks | 9-10 | Protocol docs, validation tools, examples |
| 5: Polish & Testing | 2 weeks | 11-12 | Integration tests, feature flags, documentation |
| **Total** | **12 weeks** | | |

### 7.7 Risk Mitigation Strategy Summary

The following table summarizes the chosen mitigation strategies for each identified risk:

| Risk ID | Risk | Chosen Mitigation Strategy |
|---------|------|---------------------------|
| T1 | AsyncIterator complexity | Use `contextlib.aclosing()` + helper utilities |
| T2 | Race conditions in stream merging | Use `asyncio.TaskGroup` (Python 3.11+) |
| T3 | Memory leaks from unbounded buffering | Bounded queues (maxsize=1000) + event dropping with logging |
| T4 | Deadlocks in mutex acquisition | Ordered acquisition + `asyncio.Condition` + timeout detection |
| T5 | JSON progress parsing failures | Use `PROGRESS:` prefix marker for JSON lines |
| I1 | Breaking changes to UpdatePlugin | Add new methods with default implementations |
| I2 | Textual version incompatibility | Pin version range + abstract Textual-specific code |
| I3 | Orchestrator changes affecting parallel | Streaming as separate layer + feature flags |
| B1 | Existing plugins fail with streaming | Default `execute_streaming()` wraps `execute()` |
| B2 | External plugins incompatible | Graceful degradation + "legacy mode" indicator |
| P1 | UI performance degradation | Event batching (50ms) + rate-limit to 30 FPS |
| P2 | Increased memory from events | Use `@dataclass(slots=True)` for all events |
| O1 | Sudo password prompts blocking | Pre-authenticate with `sudo -v` + clear UI message |
| O2 | Plugin timeout handling | Use `asyncio.timeout()` + proper process termination |
| S1 | 8-week timeline insufficient | Extended to 12 weeks with buffer |
| S2 | Testing complexity underestimated | pytest-asyncio + mock generators + property-based tests |

---

## 8. Requirements Verification

### 8.1 Original Requirements Checklist

| Requirement | Status | Notes |
|-------------|--------|-------|
| Plugin-driven system | ✅ Satisfied | Unchanged |
| Arbitrary executable plugins | ✅ Satisfied | Streaming protocol added |
| Sudo elevation | ✅ Satisfied | Unchanged |
| One command to run | ✅ Satisfied | Unchanged |
| **Tabbed output with live updates** | 🔄 **Fixed** | This refinement addresses this |
| Quick if nothing to update | ✅ Satisfied | Unchanged |
| Remote computer updates | ✅ Satisfied | Unchanged |
| Overall progress display | 🔄 **Enhanced** | Now with streaming progress |
| Live log of current task | 🔄 **Fixed** | This refinement addresses this |
| Estimated time remaining | ✅ Satisfied | Enhanced with download estimates |
| Check-only mode | ✅ Satisfied | Now with streaming output |
| **Download-only mode** | 🔄 **Added** | This refinement adds this |
| Parallel execution with mutexes | ✅ Satisfied | Unchanged |
| Scheduled updates | ✅ Satisfied | Unchanged |
| Plugin self-update | ✅ Satisfied | Unchanged |
| Advanced logging | ✅ Satisfied | Unchanged |
| Statistical modeling | ✅ Satisfied | Unchanged |
| Memory/CPU/Network control | ✅ Satisfied | Unchanged |

### 8.2 Plugin CLI API Verification

| Command | Status | Notes |
|---------|--------|-------|
| `is-applicable` | ✅ Exists | Unchanged |
| `estimate-update` | ✅ Exists | Unchanged |
| `can-separate-download` | 🔄 **Added** | New command |
| `download` | 🔄 **Added** | New command |
| `self-update` | ✅ Exists | Unchanged |
| `self-upgrade` | ✅ Exists | Unchanged |
| `does-require-sudo` | ✅ Exists | Unchanged |
| `sudo-programs-paths` | ✅ Exists | Unchanged |
| `update` | ✅ Exists | Now supports streaming |
| `*-dependency` | ✅ Exists | Unchanged |
| `*-mutexes` | ✅ Exists | Unchanged |

### 8.3 New Capabilities

| Capability | Description |
|------------|-------------|
| Live streaming output | Real-time display of plugin output |
| Progress events | Structured progress reporting |
| Download phase | Separate download from execution |
| Download estimation | Size and time estimates before download |
| Phase tracking | Know which phase is currently running |

---

## 9. Migration Strategy

### 9.1 Backward Compatibility

The streaming interface is **additive** — existing plugins continue to work:

1. `execute()` method remains unchanged
2. `execute_streaming()` has default implementation that wraps `execute()`
3. External plugins can ignore streaming protocol (output shown after completion)

### 9.2 Gradual Migration

1. **Phase 1:** Add streaming infrastructure, existing plugins work unchanged
2. **Phase 2:** Update built-in plugins to use streaming
3. **Phase 3:** Update UI to prefer streaming when available
4. **Phase 4:** Document streaming for external plugin authors

### 9.3 Testing Strategy

1. **Unit tests:** Test event generation and parsing
2. **Integration tests:** Test streaming with real commands
3. **UI tests:** Test display updates with streaming events
4. **Regression tests:** Ensure non-streaming plugins still work

---

## Appendix A: Complete Event Type Definitions

```python
# core/core/streaming.py

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Types of streaming events from plugins."""
    OUTPUT = "output"
    PROGRESS = "progress"
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    ERROR = "error"
    COMPLETION = "completion"


class Phase(str, Enum):
    """Execution phases for plugins."""
    CHECK = "check"
    DOWNLOAD = "download"
    EXECUTE = "execute"


@dataclass
class StreamEvent:
    """Base class for streaming events."""
    event_type: EventType
    plugin_name: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.event_type.value,
            "plugin": self.plugin_name,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class OutputEvent(StreamEvent):
    """Raw output line from plugin."""
    line: str
    stream: str = "stdout"

    def __post_init__(self) -> None:
        self.event_type = EventType.OUTPUT

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "line": self.line,
            "stream": self.stream,
        })
        return d


@dataclass
class ProgressEvent(StreamEvent):
    """Progress update from plugin."""
    phase: Phase
    percent: float | None = None
    message: str | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    items_completed: int | None = None
    items_total: int | None = None

    def __post_init__(self) -> None:
        self.event_type = EventType.PROGRESS

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "phase": self.phase.value,
            "percent": self.percent,
            "message": self.message,
            "bytes_downloaded": self.bytes_downloaded,
            "bytes_total": self.bytes_total,
            "items_completed": self.items_completed,
            "items_total": self.items_total,
        })
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class PhaseEvent(StreamEvent):
    """Phase start/end event."""
    phase: Phase
    success: bool | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "phase": self.phase.value,
        })
        if self.success is not None:
            d["success"] = self.success
        if self.error_message:
            d["error"] = self.error_message
        return d


@dataclass
class CompletionEvent(StreamEvent):
    """Plugin execution completed."""
    success: bool
    exit_code: int
    packages_updated: int = 0
    error_message: str | None = None

    def __post_init__(self) -> None:
        self.event_type = EventType.COMPLETION

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d.update({
            "success": self.success,
            "exit_code": self.exit_code,
            "packages_updated": self.packages_updated,
        })
        if self.error_message:
            d["error"] = self.error_message
        return d


def parse_event(data: dict[str, Any], plugin_name: str) -> StreamEvent | None:
    """Parse a dictionary into a StreamEvent.

    Args:
        data: Dictionary with event data.
        plugin_name: Name of the plugin.

    Returns:
        StreamEvent or None if parsing fails.
    """
    event_type = data.get("type")
    timestamp = datetime.now()

    if event_type == "progress":
        return ProgressEvent(
            event_type=EventType.PROGRESS,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=Phase(data.get("phase", "execute")),
            percent=data.get("percent"),
            message=data.get("message"),
            bytes_downloaded=data.get("bytes_downloaded"),
            bytes_total=data.get("bytes_total"),
            items_completed=data.get("items_completed"),
            items_total=data.get("items_total"),
        )

    elif event_type == "phase_start":
        return PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=Phase(data.get("phase", "execute")),
        )

    elif event_type == "phase_end":
        return PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=plugin_name,
            timestamp=timestamp,
            phase=Phase(data.get("phase", "execute")),
            success=data.get("success"),
            error_message=data.get("error"),
        )

    return None
```

---

## Appendix B: Example Streaming Plugin

```python
# plugins/plugins/example_streaming.py

"""Example plugin demonstrating streaming output."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from core.models import DownloadEstimate, PackageDownload
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    ProgressEvent,
    StreamEvent,
)
from plugins.base import BasePlugin


class ExampleStreamingPlugin(BasePlugin):
    """Example plugin with full streaming support."""

    @property
    def name(self) -> str:
        return "example-streaming"

    @property
    def command(self) -> str:
        return "echo"

    @property
    def supports_download(self) -> bool:
        return True

    async def estimate_download(self) -> DownloadEstimate | None:
        return DownloadEstimate(
            total_bytes=100_000_000,
            package_count=5,
            estimated_seconds=30,
            packages=[
                PackageDownload(name="package-1", version="1.0", size_bytes=20_000_000),
                PackageDownload(name="package-2", version="2.0", size_bytes=30_000_000),
                PackageDownload(name="package-3", version="1.5", size_bytes=50_000_000),
            ],
        )

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Simulate download with progress."""
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        total_bytes = 100_000_000
        for i in range(10):
            await asyncio.sleep(0.5)
            bytes_done = (i + 1) * 10_000_000

            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                percent=(i + 1) * 10,
                message=f"Downloading package {(i // 3) + 1}/3...",
                bytes_downloaded=bytes_done,
                bytes_total=total_bytes,
            )

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            success=True,
        )

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute with streaming output."""
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        for i in range(5):
            await asyncio.sleep(0.3)

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Installing package {i + 1}/5...",
                stream="stdout",
            )

            yield ProgressEvent(
                event_type=EventType.PROGRESS,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.EXECUTE,
                percent=(i + 1) * 20,
                items_completed=i + 1,
                items_total=5,
            )

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=True,
        )

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=True,
            exit_code=0,
            packages_updated=5,
        )
```

---

## References

1. [Update-All Python Implementation Plan](update-all-python-plan.md)
2. [Plugin Development Guide](plugin-development.md)
3. [Python asyncio subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html)
4. [Textual framework documentation](https://textual.textualize.io/)
5. [pre-commit source code](https://github.com/pre-commit/pre-commit) - Studied for plugin execution patterns

# Architecture Refinement Risk Analysis

**Date:** January 6, 2026
**Version:** 1.0
**Status:** Draft
**Related Document:** [update-all-architecture-refinement-plan.md](update-all-architecture-refinement-plan.md)

---

## Executive Summary

This document identifies risks associated with implementing the architecture refinement plan for the update-all system. The plan introduces:

1. **Live streaming output** from plugins to the tabbed UI
2. **Download API** for plugins that support separate download and update steps
3. **Enhanced progress tracking** with real-time updates

Each risk is categorized by severity (Critical, High, Medium, Low) and likelihood (High, Medium, Low), with mitigation strategies provided.

---

## Table of Contents

1. [Risk Matrix Summary](#1-risk-matrix-summary)
2. [Technical Risks](#2-technical-risks)
3. [Integration Risks](#3-integration-risks)
4. [Backward Compatibility Risks](#4-backward-compatibility-risks)
5. [Performance Risks](#5-performance-risks)
6. [Testing Risks](#6-testing-risks)
7. [External Dependency Risks](#7-external-dependency-risks)
8. [Operational Risks](#8-operational-risks)
9. [Schedule Risks](#9-schedule-risks)

---

## 1. Risk Matrix Summary

| ID | Risk | Severity | Likelihood | Priority |
|----|------|----------|------------|----------|
| T1 | AsyncIterator complexity in streaming interface | High | High | Critical |
| T2 | Race conditions in concurrent stream merging | Critical | Medium | Critical |
| T3 | Memory leaks from unbounded output buffering | High | Medium | High |
| T4 | Deadlocks in mutex acquisition during streaming | Critical | Low | High |
| T5 | JSON progress parsing failures from malformed output | Medium | High | High |
| I1 | Breaking changes to UpdatePlugin interface | High | Medium | High |
| I2 | Textual framework version incompatibility | Medium | Medium | Medium |
| I3 | Orchestrator changes affecting parallel execution | High | Medium | High |
| B1 | Existing plugins fail with new streaming interface | High | Low | Medium |
| B2 | External plugins incompatible with streaming protocol | Medium | High | High |
| B3 | Configuration file format changes | Low | Low | Low |
| P1 | UI performance degradation with high-frequency events | High | Medium | High |
| P2 | Increased memory usage from event objects | Medium | Medium | Medium |
| P3 | CPU overhead from continuous stream reading | Medium | Low | Low |
| E1 | asyncio.Queue behavior changes in Python 3.12+ | Medium | Low | Low |
| E2 | Textual API changes in future versions | Medium | Medium | Medium |
| O1 | Sudo password prompts blocking streaming | High | High | Critical |
| O2 | Plugin timeout handling with streaming | Medium | Medium | Medium |
| S1 | 8-week timeline insufficient for full implementation | High | Medium | High |
| S2 | Testing complexity underestimated | Medium | High | High |

---

## 2. Technical Risks

### T1: AsyncIterator Complexity in Streaming Interface

**Description:** The proposed streaming interface uses `AsyncIterator[StreamEvent]` which introduces complexity in error handling, cancellation, and resource cleanup.

**Severity:** High
**Likelihood:** High

**Impact:**
- Difficult-to-debug issues when iterators are not properly consumed
- Resource leaks if async generators are not closed properly
- Complex exception propagation through async generators

**Mitigation Strategies:**
1. Use `contextlib.aclosing()` to ensure proper cleanup of async generators
2. Implement comprehensive try/finally blocks in all streaming methods
3. Add timeout wrappers around async iteration
4. Create helper utilities for common streaming patterns

**Code Example:**
```python
from contextlib import aclosing

async def safe_consume_stream(plugin: UpdatePlugin) -> list[StreamEvent]:
    events = []
    async with aclosing(plugin.execute_streaming()) as stream:
        async for event in stream:
            events.append(event)
    return events
```

---

### T2: Race Conditions in Concurrent Stream Merging

**Description:** The proposed `_run_command_streaming()` method merges stdout and stderr streams concurrently using `asyncio.Queue`. This introduces potential race conditions.

**Severity:** Critical
**Likelihood:** Medium

**Impact:**
- Events may arrive out of order
- Queue operations may deadlock if not properly synchronized
- Completion signals may be missed

**Mitigation Strategies:**
1. Use `asyncio.TaskGroup` (Python 3.11+) for proper task management
2. Implement proper sentinel values for stream completion
3. Add comprehensive logging for debugging stream ordering issues
4. Consider using `aiostream` library for robust stream merging

**Code Example:**
```python
async def merge_streams_safely() -> AsyncIterator[StreamEvent]:
    async with asyncio.TaskGroup() as tg:
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue()

        async def read_stream(stream, name):
            try:
                async for line in stream:
                    await queue.put(OutputEvent(...))
            finally:
                await queue.put(None)  # Sentinel

        tg.create_task(read_stream(process.stdout, "stdout"))
        tg.create_task(read_stream(process.stderr, "stderr"))

        completed = 0
        while completed < 2:
            event = await queue.get()
            if event is None:
                completed += 1
            else:
                yield event
```

---

### T3: Memory Leaks from Unbounded Output Buffering

**Description:** If the UI cannot consume events as fast as they are produced, events may accumulate in memory.

**Severity:** High
**Likelihood:** Medium

**Impact:**
- Memory exhaustion during long-running updates
- System instability
- OOM killer terminating the process

**Mitigation Strategies:**
1. Implement bounded queues with backpressure
2. Add event dropping with logging when queue is full
3. Implement output line rate limiting
4. Add memory monitoring and warnings

**Code Example:**
```python
# Use bounded queue with timeout
queue: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=1000)

try:
    await asyncio.wait_for(queue.put(event), timeout=1.0)
except asyncio.TimeoutError:
    logger.warning("Event queue full, dropping event")
```

---

### T4: Deadlocks in Mutex Acquisition During Streaming

**Description:** The current `MutexManager` uses polling with `asyncio.sleep()` for waiting. Combined with streaming, this could lead to deadlocks.

**Severity:** Critical
**Likelihood:** Low

**Impact:**
- Complete system hang
- Plugins stuck waiting indefinitely
- User must force-kill the application

**Mitigation Strategies:**
1. Implement proper async condition variables for mutex waiting
2. Add deadlock detection with timeout
3. Implement mutex acquisition ordering to prevent circular waits
4. Add comprehensive logging of mutex state

**Code Example:**
```python
class MutexManager:
    def __init__(self):
        self._conditions: dict[str, asyncio.Condition] = {}

    async def acquire(self, plugin: str, mutexes: list[str], timeout: float) -> bool:
        async with asyncio.timeout(timeout):
            for mutex in sorted(mutexes):  # Ordered acquisition
                condition = self._get_or_create_condition(mutex)
                async with condition:
                    while self.is_held(mutex):
                        await condition.wait()
                    self._held[mutex] = MutexInfo(name=mutex, holder=plugin)
        return True
```

---

### T5: JSON Progress Parsing Failures from Malformed Output

**Description:** The streaming protocol expects JSON progress events on stderr. Malformed JSON or non-JSON output will cause parsing failures.

**Severity:** Medium
**Likelihood:** High

**Impact:**
- Progress information lost
- Error messages in logs
- Potential crashes if not handled properly

**Mitigation Strategies:**
1. Implement robust JSON parsing with fallback to raw output
2. Use a prefix marker (e.g., `PROGRESS:`) to identify JSON lines
3. Log parsing failures at debug level only
4. Provide clear documentation for plugin authors

**Code Example:**
```python
PROGRESS_PREFIX = "PROGRESS:"

def parse_line(line: str) -> StreamEvent:
    if line.startswith(PROGRESS_PREFIX):
        try:
            data = json.loads(line[len(PROGRESS_PREFIX):])
            return parse_progress_event(data)
        except json.JSONDecodeError:
            logger.debug("Failed to parse progress JSON", line=line)
    return OutputEvent(line=line, stream="stderr")
```

---

## 3. Integration Risks

### I1: Breaking Changes to UpdatePlugin Interface

**Description:** Adding new abstract methods to `UpdatePlugin` will break existing plugin implementations.

**Severity:** High
**Likelihood:** Medium

**Impact:**
- All existing plugins must be updated
- Third-party plugins will fail
- Increased maintenance burden

**Mitigation Strategies:**
1. Add new methods with default implementations (as proposed in the plan)
2. Use `@abstractmethod` only for truly required methods
3. Provide clear deprecation warnings for old methods
4. Create a migration guide for plugin authors

**Current Interface (safe additions):**
```python
class UpdatePlugin(ABC):
    # Existing abstract methods remain unchanged

    # New methods with defaults - no breaking change
    async def execute_streaming(self, dry_run: bool = False) -> AsyncIterator[StreamEvent]:
        """Default wraps execute() for backward compatibility."""
        result = await self.execute(dry_run=dry_run)
        # ... yield events from result
```

---

### I2: Textual Framework Version Incompatibility

**Description:** The UI uses Textual framework which is actively developed and may have breaking changes.

**Severity:** Medium
**Likelihood:** Medium

**Impact:**
- UI components may break with Textual updates
- Need to pin specific Textual version
- May miss security fixes in newer versions

**Mitigation Strategies:**
1. Pin Textual version in `pyproject.toml` with upper bound
2. Add integration tests for UI components
3. Monitor Textual changelog for breaking changes
4. Abstract Textual-specific code behind interfaces

**Dependency Specification:**
```toml
[tool.poetry.dependencies]
textual = ">=0.47.0,<0.50.0"  # Pin to known-good range
```

---

### I3: Orchestrator Changes Affecting Parallel Execution

**Description:** Modifying the orchestrator to support streaming may affect the existing parallel execution logic.

**Severity:** High
**Likelihood:** Medium

**Impact:**
- Parallel execution may become sequential
- Resource limits may not be respected
- Mutex handling may break

**Mitigation Strategies:**
1. Keep streaming changes isolated from orchestration logic
2. Add comprehensive integration tests for parallel execution
3. Implement streaming as a separate layer on top of existing execution
4. Use feature flags to enable/disable streaming

---

## 4. Backward Compatibility Risks

### B1: Existing Plugins Fail with New Streaming Interface

**Description:** Plugins that override `execute()` may not work correctly with the streaming wrapper.

**Severity:** High
**Likelihood:** Low

**Impact:**
- Plugins appear to hang (no output until completion)
- Error handling may differ between streaming and non-streaming paths
- Inconsistent user experience

**Mitigation Strategies:**
1. Ensure default `execute_streaming()` properly wraps `execute()`
2. Test all built-in plugins with both interfaces
3. Add detection for plugins that don't support streaming
4. Show "legacy mode" indicator in UI for non-streaming plugins

---

### B2: External Plugins Incompatible with Streaming Protocol

**Description:** External executable plugins may not implement the JSON progress protocol.

**Severity:** Medium
**Likelihood:** High

**Impact:**
- No progress information for external plugins
- Users may think external plugins are stuck
- Inconsistent experience across plugins

**Mitigation Strategies:**
1. Make streaming protocol optional (graceful degradation)
2. Show raw output for plugins without progress events
3. Provide example implementations in multiple languages
4. Create a validation tool for plugin authors

---

### B3: Configuration File Format Changes

**Description:** New features may require configuration file changes.

**Severity:** Low
**Likelihood:** Low

**Impact:**
- Existing configurations may not load
- Users need to update configuration files
- Migration scripts needed

**Mitigation Strategies:**
1. Use optional fields with sensible defaults
2. Implement configuration versioning
3. Provide automatic migration on first run
4. Document all configuration changes

---

## 5. Performance Risks

### P1: UI Performance Degradation with High-Frequency Events

**Description:** Plugins producing many output lines per second may overwhelm the Textual UI.

**Severity:** High
**Likelihood:** Medium

**Impact:**
- UI becomes unresponsive
- High CPU usage
- Delayed display of important information

**Mitigation Strategies:**
1. Implement event batching (collect events for 50-100ms before updating UI)
2. Use virtual scrolling for log output
3. Rate-limit UI updates to 30 FPS maximum
4. Add option to disable live output for performance

**Code Example:**
```python
class BatchedEventHandler:
    def __init__(self, update_interval: float = 0.05):
        self._pending: list[StreamEvent] = []
        self._last_update = time.monotonic()
        self._interval = update_interval

    async def handle(self, event: StreamEvent) -> None:
        self._pending.append(event)
        now = time.monotonic()
        if now - self._last_update >= self._interval:
            await self._flush()
            self._last_update = now

    async def _flush(self) -> None:
        events = self._pending
        self._pending = []
        for event in events:
            self.post_message(PluginOutputMessage(...))
```

---

### P2: Increased Memory Usage from Event Objects

**Description:** Creating many `StreamEvent` dataclass instances may increase memory usage.

**Severity:** Medium
**Likelihood:** Medium

**Impact:**
- Higher memory footprint
- More garbage collection pressure
- Slower performance on memory-constrained systems

**Mitigation Strategies:**
1. Use `__slots__` in event dataclasses
2. Reuse event objects where possible
3. Implement event pooling for high-frequency events
4. Consider using named tuples for simple events

**Code Example:**
```python
@dataclass(slots=True)
class OutputEvent(StreamEvent):
    """Raw output line from plugin."""
    line: str
    stream: str = "stdout"
```

---

### P3: CPU Overhead from Continuous Stream Reading

**Description:** Continuously reading from subprocess streams adds CPU overhead.

**Severity:** Medium
**Likelihood:** Low

**Impact:**
- Higher CPU usage during updates
- Reduced battery life on laptops
- May affect system responsiveness

**Mitigation Strategies:**
1. Use efficient async I/O patterns
2. Avoid busy-waiting loops
3. Use appropriate buffer sizes for stream reading
4. Profile and optimize hot paths

---

## 6. Testing Risks

### S2: Testing Complexity Underestimated

**Description:** Testing async streaming code with concurrent operations is significantly more complex than testing synchronous code.

**Severity:** Medium
**Likelihood:** High

**Impact:**
- Insufficient test coverage
- Flaky tests due to timing issues
- Bugs discovered late in development

**Mitigation Strategies:**
1. Use `pytest-asyncio` with proper fixtures
2. Create mock stream generators for testing
3. Implement deterministic test helpers
4. Add integration tests with real subprocesses
5. Use property-based testing for event parsing

**Test Helper Example:**
```python
async def mock_streaming_plugin(events: list[StreamEvent]) -> AsyncIterator[StreamEvent]:
    """Create a mock streaming plugin for testing."""
    for event in events:
        await asyncio.sleep(0.001)  # Simulate async behavior
        yield event

@pytest.fixture
def mock_events():
    return [
        PhaseEvent(event_type=EventType.PHASE_START, ...),
        OutputEvent(line="Installing...", ...),
        ProgressEvent(percent=50, ...),
        CompletionEvent(success=True, ...),
    ]
```

---

## 7. External Dependency Risks

### E1: asyncio.Queue Behavior Changes in Python 3.12+

**Description:** Python's asyncio module continues to evolve, and behavior may change.

**Severity:** Medium
**Likelihood:** Low

**Impact:**
- Code may behave differently on different Python versions
- Need to maintain compatibility across versions
- Potential subtle bugs

**Mitigation Strategies:**
1. Test on all supported Python versions (3.11, 3.12, 3.13)
2. Use well-documented asyncio patterns
3. Avoid relying on implementation details
4. Pin minimum Python version in pyproject.toml

---

### E2: Textual API Changes in Future Versions

**Description:** Textual is a relatively new framework with active development.

**Severity:** Medium
**Likelihood:** Medium

**Impact:**
- UI code may break with updates
- Need to track Textual releases
- May need to rewrite UI components

**Mitigation Strategies:**
1. Abstract Textual-specific code
2. Create UI component tests
3. Monitor Textual release notes
4. Consider contributing to Textual for needed features

---

## 8. Operational Risks

### O1: Sudo Password Prompts Blocking Streaming

**Description:** When a plugin requires sudo and the user hasn't cached credentials, the password prompt may block streaming.

**Severity:** High
**Likelihood:** High

**Impact:**
- Plugin appears to hang
- No output visible to user
- User doesn't know to enter password

**Mitigation Strategies:**
1. Detect sudo requirement before streaming starts
2. Prompt for sudo password in UI before plugin execution
3. Use `sudo -v` to pre-authenticate
4. Show clear message when waiting for sudo
5. Support sudoers configuration for passwordless execution

**Code Example:**
```python
async def ensure_sudo_authenticated(plugin: UpdatePlugin) -> bool:
    """Ensure sudo is authenticated before streaming."""
    if not plugin.requires_sudo:
        return True

    # Try to refresh sudo timestamp
    proc = await asyncio.create_subprocess_exec(
        "sudo", "-v", "-n",  # Non-interactive
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    if proc.returncode != 0:
        # Need to prompt for password
        return await prompt_sudo_password()

    return True
```

---

### O2: Plugin Timeout Handling with Streaming

**Description:** Timeout handling becomes more complex with streaming because we need to cancel the async iterator properly.

**Severity:** Medium
**Likelihood:** Medium

**Impact:**
- Plugins may not be properly terminated on timeout
- Resources may leak
- Zombie processes may remain

**Mitigation Strategies:**
1. Use `asyncio.timeout()` context manager
2. Implement proper process termination on timeout
3. Add cleanup in finally blocks
4. Track and kill child processes

**Code Example:**
```python
async def execute_with_timeout(
    plugin: UpdatePlugin,
    timeout: float,
) -> AsyncIterator[StreamEvent]:
    try:
        async with asyncio.timeout(timeout):
            async for event in plugin.execute_streaming():
                yield event
    except asyncio.TimeoutError:
        yield CompletionEvent(
            success=False,
            exit_code=-1,
            error_message=f"Timeout after {timeout}s",
        )
        # Ensure cleanup
        await plugin.cleanup()
```

---

## 9. Schedule Risks

### S1: 8-Week Timeline Insufficient for Full Implementation

**Description:** The proposed 8-week implementation timeline may be optimistic given the complexity of the changes.

**Severity:** High
**Likelihood:** Medium

**Impact:**
- Features delivered incomplete
- Reduced testing time
- Technical debt accumulation

**Mitigation Strategies:**
1. Prioritize core streaming functionality (Phase 1-2)
2. Defer external plugin support if needed
3. Implement feature flags for incremental rollout
4. Plan for a Phase 5 for polish and bug fixes
5. Consider parallel workstreams if resources allow

**Revised Timeline Recommendation:**
| Phase | Original | Recommended | Notes |
|-------|----------|-------------|-------|
| 1: Core Streaming | 2 weeks | 3 weeks | Add buffer for complexity |
| 2: Download API | 2 weeks | 2 weeks | Keep as planned |
| 3: UI Integration | 2 weeks | 3 weeks | Add performance tuning |
| 4: External Plugins | 2 weeks | 2 weeks | Keep as planned |
| 5: Polish & Testing | - | 2 weeks | New phase |
| **Total** | **8 weeks** | **12 weeks** | 50% buffer |

---

## Appendix A: Risk Response Actions

### Immediate Actions (Before Implementation Starts)

1. **Create proof-of-concept** for streaming with a single plugin
2. **Benchmark Textual** with high-frequency updates
3. **Review asyncio patterns** for stream merging
4. **Set up comprehensive CI** with multiple Python versions

### During Implementation

1. **Weekly risk review** meetings
2. **Continuous integration** with streaming tests
3. **Performance monitoring** in CI
4. **Early user testing** with streaming UI

### Post-Implementation

1. **Monitor production** for memory/CPU issues
2. **Collect user feedback** on streaming experience
3. **Document lessons learned**
4. **Plan follow-up improvements**

---

## Appendix B: Risk Monitoring Metrics

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Memory usage per plugin | < 50 MB | > 100 MB |
| UI update latency | < 50 ms | > 200 ms |
| Event queue depth | < 100 | > 500 |
| Test coverage | > 80% | < 70% |
| Flaky test rate | < 1% | > 5% |

---

## References

1. [Python asyncio documentation](https://docs.python.org/3/library/asyncio.html)
2. [Textual framework documentation](https://textual.textualize.io/)
3. [AsyncIterator best practices](https://peps.python.org/pep-0525/)
4. [update-all-architecture-refinement-plan.md](update-all-architecture-refinement-plan.md)

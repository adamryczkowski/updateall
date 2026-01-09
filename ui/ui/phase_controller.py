"""Phase controller for managing phase transitions with pause points.

This module provides a PhaseController that manages the execution of plugins
through their phases (CHECK, DOWNLOAD, EXECUTE) with optional pause points
between phases.

UI Revision Plan - Phase 1 Core Infrastructure
See docs/UI-revision-plan.md section 3.2
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from textual.message import Message

from core.streaming import Phase

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class PhaseState(str, Enum):
    """State of a phase execution."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseResult:
    """Result of a phase execution."""

    phase: Phase
    state: PhaseState
    start_time: datetime | None = None
    end_time: datetime | None = None
    exit_code: int | None = None
    error_message: str | None = None
    output: str = ""

    @property
    def duration_seconds(self) -> float | None:
        """Get the duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


@dataclass
class PluginPhaseState:
    """Tracks the phase state for a single plugin."""

    plugin_name: str
    current_phase: Phase | None = None
    phase_results: dict[Phase, PhaseResult] = field(default_factory=dict)
    paused_at_phase: Phase | None = None

    def get_next_phase(self) -> Phase | None:
        """Get the next phase to execute.

        Returns:
            The next phase, or None if all phases are complete.
        """
        phase_order = [Phase.CHECK, Phase.DOWNLOAD, Phase.EXECUTE]

        if self.current_phase is None:
            return Phase.CHECK

        try:
            current_idx = phase_order.index(self.current_phase)
            if current_idx < len(phase_order) - 1:
                return phase_order[current_idx + 1]
        except ValueError:
            pass

        return None

    def is_complete(self) -> bool:
        """Check if all phases are complete."""
        return Phase.EXECUTE in self.phase_results and self.phase_results[Phase.EXECUTE].state in (
            PhaseState.COMPLETED,
            PhaseState.FAILED,
            PhaseState.SKIPPED,
        )


class PhaseTransitionRequest(Message):
    """Message requesting a phase transition."""

    def __init__(
        self,
        plugin_name: str,
        from_phase: Phase | None,
        to_phase: Phase,
    ) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            from_phase: The phase transitioning from (None if starting).
            to_phase: The phase transitioning to.
        """
        self.plugin_name = plugin_name
        self.from_phase = from_phase
        self.to_phase = to_phase
        super().__init__()


class PhaseCompleted(Message):
    """Message indicating a phase has completed."""

    def __init__(
        self,
        plugin_name: str,
        phase: Phase,
        result: PhaseResult,
    ) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase that completed.
            result: The result of the phase.
        """
        self.plugin_name = plugin_name
        self.phase = phase
        self.result = result
        super().__init__()


class PhasePaused(Message):
    """Message indicating execution is paused before a phase."""

    def __init__(
        self,
        plugin_name: str,
        next_phase: Phase,
    ) -> None:
        """Initialize the message.

        Args:
            plugin_name: Name of the plugin.
            next_phase: The phase that will run when resumed.
        """
        self.plugin_name = plugin_name
        self.next_phase = next_phase
        super().__init__()


class PhaseController:
    """Controls phase transitions with optional pause points.

    The PhaseController manages the execution of plugins through their
    phases (CHECK, DOWNLOAD, EXECUTE). It supports:

    - Pausing before each phase transition
    - Waiting for user confirmation to proceed
    - Tracking phase state for each plugin
    - Coordinating phase execution across multiple plugins
    - Getting phase-specific commands from plugins

    Attributes:
        pause_between_phases: Whether to pause before each phase.
        plugin_states: State tracking for each plugin.
    """

    def __init__(
        self,
        plugins: list[Any] | None = None,
        pause_between_phases: bool = False,
        on_phase_start: Callable[[str, Phase], Awaitable[None]] | None = None,
        on_phase_complete: Callable[[str, Phase, PhaseResult], Awaitable[None]] | None = None,
        on_phase_paused: Callable[[str, Phase], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize the phase controller.

        Args:
            plugins: List of plugins to manage phases for.
            pause_between_phases: Whether to pause before each phase.
            on_phase_start: Callback when a phase starts.
            on_phase_complete: Callback when a phase completes.
            on_phase_paused: Callback when paused before a phase.
        """
        self.pause_between_phases = pause_between_phases
        self._on_phase_start = on_phase_start
        self._on_phase_complete = on_phase_complete
        self._on_phase_paused = on_phase_paused

        # Plugin state tracking
        self.plugin_states: dict[str, PluginPhaseState] = {}

        # Plugin references for getting phase commands
        self._plugins: dict[str, Any] = {}

        # Resume events for paused plugins
        self._resume_events: dict[str, asyncio.Event] = {}

        # Lock for thread-safe state updates
        self._lock = asyncio.Lock()

        # Register plugins if provided
        if plugins:
            for plugin in plugins:
                self.register_plugin(plugin.name, plugin)

    def register_plugin(self, plugin_name: str, plugin: Any | None = None) -> None:
        """Register a plugin for phase tracking.

        Args:
            plugin_name: Name of the plugin.
            plugin: Optional plugin instance for getting phase commands.
        """
        if plugin_name not in self.plugin_states:
            self.plugin_states[plugin_name] = PluginPhaseState(plugin_name=plugin_name)
            self._resume_events[plugin_name] = asyncio.Event()
        if plugin is not None:
            self._plugins[plugin_name] = plugin

    def toggle_pause(self) -> bool:
        """Toggle the pause_between_phases setting.

        Returns:
            The new value of pause_between_phases.
        """
        self.pause_between_phases = not self.pause_between_phases
        return self.pause_between_phases

    def get_plugin_state(self, plugin_name: str) -> PluginPhaseState | None:
        """Get the phase state for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            The plugin's phase state, or None if not registered.
        """
        return self.plugin_states.get(plugin_name)

    async def request_phase_transition(
        self,
        plugin_name: str,
        next_phase: Phase,
    ) -> bool:
        """Request transition to the next phase.

        If pause_between_phases is enabled, this method will wait for
        user confirmation before returning True.

        Args:
            plugin_name: Name of the plugin.
            next_phase: The phase to transition to.

        Returns:
            True if the transition is approved, False if cancelled.
        """
        async with self._lock:
            state = self.plugin_states.get(plugin_name)
            if not state:
                self.register_plugin(plugin_name)
                state = self.plugin_states[plugin_name]

            # If pause is enabled, wait for confirmation
            if self.pause_between_phases:
                state.paused_at_phase = next_phase

                # Notify that we're paused
                if self._on_phase_paused:
                    await self._on_phase_paused(plugin_name, next_phase)

                # Clear the event before waiting
                self._resume_events[plugin_name].clear()

        # Wait for resume (outside lock to allow other operations)
        if self.pause_between_phases:
            await self._resume_events[plugin_name].wait()

        async with self._lock:
            state = self.plugin_states[plugin_name]
            state.paused_at_phase = None
            state.current_phase = next_phase

        return True

    async def start_phase(
        self,
        plugin_name: str,
        phase: Phase,
    ) -> None:
        """Mark a phase as started.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase that is starting.
        """
        async with self._lock:
            state = self.plugin_states.get(plugin_name)
            if not state:
                self.register_plugin(plugin_name)
                state = self.plugin_states[plugin_name]

            state.current_phase = phase
            state.phase_results[phase] = PhaseResult(
                phase=phase,
                state=PhaseState.RUNNING,
                start_time=datetime.now(tz=UTC),
            )

        if self._on_phase_start:
            await self._on_phase_start(plugin_name, phase)

    async def complete_phase(
        self,
        plugin_name: str,
        phase: Phase,
        success: bool,
        exit_code: int = 0,
        error_message: str | None = None,
        output: str = "",
    ) -> None:
        """Mark a phase as completed.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase that completed.
            success: Whether the phase succeeded.
            exit_code: The exit code of the phase.
            error_message: Error message if the phase failed.
            output: Output from the phase.
        """
        async with self._lock:
            state = self.plugin_states.get(plugin_name)
            if not state:
                return

            result = state.phase_results.get(phase)
            if result:
                result.state = PhaseState.COMPLETED if success else PhaseState.FAILED
                result.end_time = datetime.now(tz=UTC)
                result.exit_code = exit_code
                result.error_message = error_message
                result.output = output

        if self._on_phase_complete and result:
            await self._on_phase_complete(plugin_name, phase, result)

    def resume_plugin(self, plugin_name: str) -> bool:
        """Resume a paused plugin.

        Args:
            plugin_name: Name of the plugin to resume.

        Returns:
            True if the plugin was paused and is now resumed.
        """
        if plugin_name in self._resume_events:
            self._resume_events[plugin_name].set()
            return True
        return False

    def resume_all(self) -> int:
        """Resume all paused plugins.

        Returns:
            Number of plugins resumed.
        """
        count = 0
        for plugin_name, event in self._resume_events.items():
            state = self.plugin_states.get(plugin_name)
            if state and state.paused_at_phase is not None:
                event.set()
                count += 1
        return count

    def is_paused(self, plugin_name: str) -> bool:
        """Check if a plugin is paused.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            True if the plugin is paused.
        """
        state = self.plugin_states.get(plugin_name)
        return state is not None and state.paused_at_phase is not None

    def get_paused_plugins(self) -> list[str]:
        """Get list of paused plugin names.

        Returns:
            List of plugin names that are currently paused.
        """
        return [
            name for name, state in self.plugin_states.items() if state.paused_at_phase is not None
        ]

    def get_all_phase_results(self, plugin_name: str) -> dict[Phase, PhaseResult]:
        """Get all phase results for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Dictionary of phase results.
        """
        state = self.plugin_states.get(plugin_name)
        if state:
            return state.phase_results.copy()
        return {}

    def get_cumulative_metrics(self, plugin_name: str) -> dict[str, Any]:
        """Get cumulative metrics across all phases for a plugin.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            Dictionary with cumulative metrics.
        """
        state = self.plugin_states.get(plugin_name)
        if not state:
            return {}

        total_duration = 0.0
        for result in state.phase_results.values():
            if result.duration_seconds:
                total_duration += result.duration_seconds

        completed_phases = sum(
            1
            for r in state.phase_results.values()
            if r.state in (PhaseState.COMPLETED, PhaseState.SKIPPED)
        )

        failed_phases = sum(1 for r in state.phase_results.values() if r.state == PhaseState.FAILED)

        return {
            "total_duration_seconds": total_duration,
            "completed_phases": completed_phases,
            "failed_phases": failed_phases,
            "current_phase": state.current_phase.value if state.current_phase else None,
            "is_paused": state.paused_at_phase is not None,
            "paused_at_phase": (state.paused_at_phase.value if state.paused_at_phase else None),
        }

    def get_current_phase(self, plugin_name: str) -> Phase | None:
        """Get the current phase for a plugin.

        Returns the next phase to execute. If the plugin has completed
        all phases, returns None.

        Args:
            plugin_name: Name of the plugin.

        Returns:
            The current/next phase to execute, or None if complete.
        """
        state = self.plugin_states.get(plugin_name)
        if not state:
            # Plugin not registered - return first phase
            return Phase.CHECK

        # If no phases have been completed, return CHECK
        if not state.phase_results:
            return Phase.CHECK

        # Check which phases are complete and return the next one
        phase_order = [Phase.CHECK, Phase.DOWNLOAD, Phase.EXECUTE]

        for phase in phase_order:
            result = state.phase_results.get(phase)
            if result is None:
                # This phase hasn't been started yet
                return phase
            if result.state == PhaseState.RUNNING:
                # This phase is currently running
                return phase
            if result.state == PhaseState.FAILED:
                # This phase failed - return it for retry
                return phase
            # Phase is COMPLETED or SKIPPED - continue to next

        # All phases complete
        return None

    def get_phase_command(self, plugin_name: str, phase: Phase) -> list[str] | None:
        """Get the command to execute for a specific phase.

        This method queries the plugin for its phase-specific command.
        Plugins should implement get_phase_commands() to return a dict
        mapping Phase to command lists.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase to get the command for.

        Returns:
            Command as a list of strings, or None if no command defined.
        """
        plugin = self._plugins.get(plugin_name)
        if not plugin:
            return None

        # Check if plugin has get_phase_commands method
        if hasattr(plugin, "get_phase_commands"):
            try:
                phase_commands = plugin.get_phase_commands()
                # Validate that phase_commands is a dict and the command is a list
                if isinstance(phase_commands, dict):
                    command = phase_commands.get(phase)
                    if isinstance(command, list) and all(isinstance(c, str) for c in command):
                        return command
            except Exception:
                pass

        # Fall back to get_interactive_command for CHECK phase
        if phase == Phase.CHECK and hasattr(plugin, "get_interactive_command"):
            try:
                command = plugin.get_interactive_command(dry_run=False)
                if isinstance(command, list) and all(isinstance(c, str) for c in command):
                    return command
            except Exception:
                pass

        return None

    def skip_plugin(self, plugin_name: str, reason: str = "") -> None:
        """Mark a plugin as skipped (all phases).

        This is used when a plugin is not applicable or disabled.

        Args:
            plugin_name: Name of the plugin.
            reason: Reason for skipping.
        """
        if plugin_name not in self.plugin_states:
            self.register_plugin(plugin_name)

        state = self.plugin_states[plugin_name]

        # Mark all phases as skipped
        for phase in [Phase.CHECK, Phase.DOWNLOAD, Phase.EXECUTE]:
            state.phase_results[phase] = PhaseResult(
                phase=phase,
                state=PhaseState.SKIPPED,
                error_message=reason,
            )

    def reset_phase(self, plugin_name: str, phase: Phase) -> None:
        """Reset a phase for retry.

        This clears the phase result so it can be re-executed.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase to reset.
        """
        state = self.plugin_states.get(plugin_name)
        if state and phase in state.phase_results:
            # Remove the phase result so it can be re-run
            del state.phase_results[phase]

    def start_phase_sync(self, plugin_name: str, phase: Phase) -> None:
        """Mark a phase as started (synchronous version).

        This is a synchronous version of start_phase() for use in contexts
        where async is not available.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase that is starting.
        """
        state = self.plugin_states.get(plugin_name)
        if not state:
            self.register_plugin(plugin_name)
            state = self.plugin_states[plugin_name]

        state.current_phase = phase
        state.phase_results[phase] = PhaseResult(
            phase=phase,
            state=PhaseState.RUNNING,
            start_time=datetime.now(tz=UTC),
        )

    def complete_phase_sync(
        self,
        plugin_name: str,
        phase: Phase,
        success: bool,
        exit_code: int = 0,
        error: str | None = None,
        output: str = "",
    ) -> None:
        """Mark a phase as completed (synchronous version).

        This is a synchronous version of complete_phase() for use in contexts
        where async is not available.

        Args:
            plugin_name: Name of the plugin.
            phase: The phase that completed.
            success: Whether the phase succeeded.
            exit_code: The exit code of the phase.
            error: Error message if the phase failed.
            output: Output from the phase.
        """
        state = self.plugin_states.get(plugin_name)
        if not state:
            return

        result = state.phase_results.get(phase)
        if result:
            result.state = PhaseState.COMPLETED if success else PhaseState.FAILED
            result.end_time = datetime.now(tz=UTC)
            result.exit_code = exit_code
            result.error_message = error
            result.output = output

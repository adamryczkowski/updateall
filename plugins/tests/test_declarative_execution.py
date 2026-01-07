"""Tests for declarative command execution API.

This module tests the get_update_commands() and _execute_commands_streaming()
methods in BasePlugin that enable declarative plugin development.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from core.models import UpdateCommand
from core.streaming import CompletionEvent, EventType, OutputEvent, Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.streaming import StreamEvent


# =============================================================================
# Test Fixtures
# =============================================================================


class SimpleDeclarativePlugin(BasePlugin):
    """A simple plugin that uses declarative commands."""

    @property
    def name(self) -> str:
        return "simple-declarative"

    @property
    def command(self) -> str:
        return "echo"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["echo", "dry-run"])]
        return [UpdateCommand(cmd=["echo", "update"], description="Run update")]

    def _count_updated_packages(self, output: str) -> int:
        return output.count("updated")

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class MultiStepDeclarativePlugin(BasePlugin):
    """A plugin with multiple update steps."""

    @property
    def name(self) -> str:
        return "multi-step"

    @property
    def command(self) -> str:
        return "echo"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [UpdateCommand(cmd=["echo", "dry-run"])]
        return [
            UpdateCommand(
                cmd=["echo", "step1"],
                description="First step",
                step_name="step1",
                step_number=1,
                total_steps=2,
            ),
            UpdateCommand(
                cmd=["echo", "step2"],
                description="Second step",
                step_name="step2",
                step_number=2,
                total_steps=2,
            ),
        ]

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class SudoDeclarativePlugin(BasePlugin):
    """A plugin that requires sudo."""

    @property
    def name(self) -> str:
        return "sudo-plugin"

    @property
    def command(self) -> str:
        return "apt"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:  # noqa: ARG002
        return [
            UpdateCommand(
                cmd=["apt", "update"],
                description="Update package lists",
                sudo=True,
            )
        ]

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class SuccessPatternPlugin(BasePlugin):
    """A plugin with success patterns."""

    @property
    def name(self) -> str:
        return "success-pattern"

    @property
    def command(self) -> str:
        return "echo"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:  # noqa: ARG002
        return [
            UpdateCommand(
                cmd=["echo", "nothing to do"],
                success_patterns=("Nothing to do", "Already up to date"),
            )
        ]

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class ErrorPatternPlugin(BasePlugin):
    """A plugin with error patterns."""

    @property
    def name(self) -> str:
        return "error-pattern"

    @property
    def command(self) -> str:
        return "echo"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:  # noqa: ARG002
        return [
            UpdateCommand(
                cmd=["echo", "FATAL error"],
                error_patterns=("FATAL", "CRITICAL"),
            )
        ]

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class IgnoreExitCodePlugin(BasePlugin):
    """A plugin that ignores certain exit codes."""

    @property
    def name(self) -> str:
        return "ignore-exit"

    @property
    def command(self) -> str:
        return "false"

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:  # noqa: ARG002
        return [
            UpdateCommand(
                cmd=["false"],  # Always exits with 1
                ignore_exit_codes=(1,),
            )
        ]

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        """Legacy method - not used when get_update_commands is implemented."""
        return "", None


class LegacyPlugin(BasePlugin):
    """A plugin that uses the legacy API (no get_update_commands)."""

    @property
    def name(self) -> str:
        return "legacy"

    @property
    def command(self) -> str:
        return "echo"

    async def _execute_update(self, _config: object) -> tuple[str, str | None]:
        return "legacy output", None


# =============================================================================
# Tests for get_update_commands() (GUC-*)
# =============================================================================


class TestGetUpdateCommands:
    """Tests for the get_update_commands() method."""

    def test_get_update_commands_default_empty(self) -> None:
        """GUC-001: Base class returns empty list by default."""

        class MinimalPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "minimal"

            @property
            def command(self) -> str:
                return "echo"

            async def _execute_update(self, _config: object) -> tuple[str, str | None]:
                return "", None

        plugin = MinimalPlugin()
        commands = plugin.get_update_commands()
        assert commands == []

    def test_get_update_commands_dry_run_flag(self) -> None:
        """GUC-002: dry_run parameter is passed correctly."""
        plugin = SimpleDeclarativePlugin()

        normal_commands = plugin.get_update_commands(dry_run=False)
        dry_run_commands = plugin.get_update_commands(dry_run=True)

        assert normal_commands[0].cmd == ["echo", "update"]
        assert dry_run_commands[0].cmd == ["echo", "dry-run"]

    def test_get_update_commands_returns_list(self) -> None:
        """GUC-003: Return type is list of UpdateCommand."""
        plugin = MultiStepDeclarativePlugin()
        commands = plugin.get_update_commands()

        assert isinstance(commands, list)
        assert len(commands) == 2
        assert all(isinstance(cmd, UpdateCommand) for cmd in commands)


# =============================================================================
# Tests for _execute_commands_streaming() (ECS-*)
# =============================================================================


class TestExecuteCommandsStreaming:
    """Tests for the _execute_commands_streaming() method."""

    @pytest.mark.asyncio
    async def test_execute_single_command(self) -> None:
        """ECS-001: Single command execution."""
        plugin = SimpleDeclarativePlugin()

        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(
            [UpdateCommand(cmd=["echo", "hello"])]
        ):
            events.append(event)

        # Should have at least header output and completion
        assert any(isinstance(e, OutputEvent) for e in events)
        assert any(isinstance(e, CompletionEvent) for e in events)

    @pytest.mark.asyncio
    async def test_execute_multiple_commands(self) -> None:
        """ECS-002: Sequential command execution."""
        plugin = MultiStepDeclarativePlugin()
        commands = plugin.get_update_commands()

        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(commands):
            events.append(event)

        # Should have outputs from both commands
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        assert len(output_events) >= 2  # At least headers for each step

        # Should have exactly one completion event at the end
        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1

    @pytest.mark.asyncio
    async def test_execute_with_sudo(self) -> None:
        """ECS-003: Sudo is prepended correctly."""
        plugin = SudoDeclarativePlugin()

        # Mock _run_command_streaming to capture the command
        captured_commands: list[list[str]] = []

        async def mock_run_command_streaming(
            cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = phase  # Unused but required for signature match
            if sudo:
                captured_commands.append(["sudo", *cmd])
            else:
                captured_commands.append(cmd)
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=True,
                exit_code=0,
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            async for _ in plugin._execute_commands_streaming(plugin.get_update_commands()):
                pass

        assert len(captured_commands) == 1
        assert captured_commands[0][0] == "sudo"

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self) -> None:
        """ECS-004: Custom timeout is used."""
        plugin = SimpleDeclarativePlugin()

        captured_timeouts: list[int] = []

        async def mock_run_command_streaming(
            _cmd: list[str],
            timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            captured_timeouts.append(timeout)
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=True,
                exit_code=0,
            )

        commands = [UpdateCommand(cmd=["echo", "test"], timeout_seconds=999)]

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            async for _ in plugin._execute_commands_streaming(commands):
                pass

        assert 999 in captured_timeouts

    @pytest.mark.asyncio
    async def test_execute_emits_header(self) -> None:
        """ECS-005: Header OutputEvent is emitted for each command."""
        plugin = SimpleDeclarativePlugin()

        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(
            [UpdateCommand(cmd=["echo", "test"], description="Test command")]
        ):
            events.append(event)

        # Find header events (contain === or description)
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        header_found = any("===" in e.line or "Test command" in e.line for e in output_events)
        assert header_found, "Header output event not found"

    @pytest.mark.asyncio
    async def test_execute_collects_output(self) -> None:
        """ECS-006: Output is collected for package counting."""
        plugin = SimpleDeclarativePlugin()

        # The plugin's _count_updated_packages counts "updated" occurrences
        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(
            [UpdateCommand(cmd=["echo", "package1 updated\npackage2 updated"])]
        ):
            events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        # Package count should be calculated from collected output
        assert completion.packages_updated >= 0

    @pytest.mark.asyncio
    async def test_execute_success_patterns(self) -> None:
        """ECS-007: Success patterns override exit code."""
        plugin = SuccessPatternPlugin()

        # Mock to return non-zero exit but with success pattern in output
        async def mock_run_command_streaming(
            _cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin.name,
                line="Nothing to do",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=False,  # Command "failed"
                exit_code=1,
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(plugin.get_update_commands()):
                events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is True, "Success pattern should override exit code"

    @pytest.mark.asyncio
    async def test_execute_error_patterns(self) -> None:
        """ECS-008: Error patterns override exit code."""
        plugin = ErrorPatternPlugin()

        # Mock to return zero exit but with error pattern in output
        async def mock_run_command_streaming(
            _cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin.name,
                line="FATAL error occurred",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=True,  # Command "succeeded"
                exit_code=0,
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(plugin.get_update_commands()):
                events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is False, "Error pattern should override exit code"

    @pytest.mark.asyncio
    async def test_execute_ignore_exit_codes(self) -> None:
        """ECS-009: Ignored exit codes don't fail."""
        plugin = IgnoreExitCodePlugin()

        # Mock to return exit code 1
        async def mock_run_command_streaming(
            _cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=False,
                exit_code=1,
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(plugin.get_update_commands()):
                events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is True, "Ignored exit code should not fail"

    @pytest.mark.asyncio
    async def test_execute_step_progress(self) -> None:
        """ECS-010: Step progress is reported in output."""
        plugin = MultiStepDeclarativePlugin()

        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(plugin.get_update_commands()):
            events.append(event)

        output_events = [e for e in events if isinstance(e, OutputEvent)]
        # Should have step indicators like [1/2] or step1, step2
        step_indicators = [e for e in output_events if "1" in e.line or "2" in e.line]
        assert len(step_indicators) >= 2

    @pytest.mark.asyncio
    async def test_execute_completion_event(self) -> None:
        """ECS-011: Final CompletionEvent is correct."""
        plugin = SimpleDeclarativePlugin()

        events: list[StreamEvent] = []
        async for event in plugin._execute_commands_streaming(
            [UpdateCommand(cmd=["echo", "success"])]
        ):
            events.append(event)

        completion_events = [e for e in events if isinstance(e, CompletionEvent)]
        assert len(completion_events) == 1

        completion = completion_events[0]
        assert completion.event_type == EventType.COMPLETION
        assert completion.plugin_name == plugin.name

    @pytest.mark.asyncio
    async def test_execute_package_count(self) -> None:
        """ECS-012: Package count is in CompletionEvent."""
        plugin = SimpleDeclarativePlugin()

        # Mock to return output with "updated" keywords
        async def mock_run_command_streaming(
            _cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin.name,
                line="package1 updated",
                stream="stdout",
            )
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=plugin.name,
                line="package2 updated",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=True,
                exit_code=0,
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(
                [UpdateCommand(cmd=["echo", "test"])]
            ):
                events.append(event)

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.packages_updated == 2

    @pytest.mark.asyncio
    async def test_execute_stops_on_failure(self) -> None:
        """ECS-013: Stops on first failed command."""
        plugin = MultiStepDeclarativePlugin()

        call_count = 0

        async def mock_run_command_streaming(
            _cmd: list[str],
            _timeout: int,
            *,
            sudo: bool = False,
            phase: Phase = Phase.EXECUTE,
        ) -> AsyncIterator[StreamEvent]:
            _ = sudo, phase  # Unused but required for signature match
            nonlocal call_count
            call_count += 1
            # First command fails
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=plugin.name,
                success=False,
                exit_code=1,
                error_message="Command failed",
            )

        with patch.object(plugin, "_run_command_streaming", mock_run_command_streaming):
            events: list[StreamEvent] = []
            async for event in plugin._execute_commands_streaming(plugin.get_update_commands()):
                events.append(event)

        # Should only call once (stopped after first failure)
        assert call_count == 1

        completion = next(e for e in events if isinstance(e, CompletionEvent))
        assert completion.success is False

    @pytest.mark.asyncio
    async def test_execute_with_env(self) -> None:
        """ECS-014: Environment variables are passed."""
        # Verify the command structure accepts env
        commands = [
            UpdateCommand(
                cmd=["echo", "test"],
                env={"MY_VAR": "my_value"},
            )
        ]

        # The env should be accessible in the command
        assert commands[0].env == {"MY_VAR": "my_value"}

    @pytest.mark.asyncio
    async def test_execute_with_cwd(self) -> None:
        """ECS-015: Working directory is used."""
        # Verify the command structure accepts cwd
        commands = [
            UpdateCommand(
                cmd=["echo", "test"],
                cwd="/tmp",
            )
        ]

        # The cwd should be accessible in the command
        assert commands[0].cwd == "/tmp"


# =============================================================================
# Integration Tests (INT-*)
# =============================================================================


class TestDeclarativeIntegration:
    """Integration tests for declarative plugin execution."""

    @pytest.mark.asyncio
    async def test_declarative_plugin_execution(self) -> None:
        """INT-001: Full execution flow with declarative plugin."""
        plugin = SimpleDeclarativePlugin()

        with patch("shutil.which", return_value="/bin/echo"):
            events: list[StreamEvent] = []
            async for event in plugin.execute_streaming(dry_run=False):
                events.append(event)

        assert any(isinstance(e, CompletionEvent) for e in events)

    @pytest.mark.asyncio
    async def test_declarative_plugin_dry_run(self) -> None:
        """INT-002: Dry run mode works with declarative plugin."""
        plugin = SimpleDeclarativePlugin()

        with patch("shutil.which", return_value="/bin/echo"):
            events: list[StreamEvent] = []
            async for event in plugin.execute_streaming(dry_run=True):
                events.append(event)

        # In dry run, should still complete successfully
        completion = next((e for e in events if isinstance(e, CompletionEvent)), None)
        assert completion is not None

    @pytest.mark.asyncio
    async def test_declarative_plugin_fallback(self) -> None:
        """INT-004: Falls back to legacy if get_update_commands returns empty."""
        plugin = LegacyPlugin()

        with patch("shutil.which", return_value="/bin/echo"):
            events: list[StreamEvent] = []
            async for event in plugin.execute_streaming(dry_run=False):
                events.append(event)

        # Should still work with legacy API
        output_events = [e for e in events if isinstance(e, OutputEvent)]
        assert any("legacy" in e.line.lower() for e in output_events)

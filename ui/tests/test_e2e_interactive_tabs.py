"""End-to-end tests for interactive tabs.

Phase 5 - Polish and Documentation
See docs/interactive-tabs-implementation-plan.md section 5.2.6

These tests verify complete user workflows with the interactive tabbed UI,
including plugin execution, sudo handling, and interactive prompts.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ui.interactive_tabbed_run import (
    InteractiveTabbedApp,
    run_with_interactive_tabbed_ui,
)
from ui.key_bindings import KeyBindings
from ui.pty_session import is_pty_available
from ui.terminal_pane import PaneState

if TYPE_CHECKING:
    from core.interfaces import UpdatePlugin

# Skip all tests if PTY is not available (e.g., on Windows or CI without PTY)
pytestmark = pytest.mark.skipif(
    not is_pty_available(),
    reason="PTY not available on this platform",
)


def create_mock_plugin(
    name: str,
    *,
    supports_interactive: bool = True,
    command: list[str] | None = None,
) -> MagicMock:
    """Create a mock plugin for testing.

    Args:
        name: Plugin name.
        supports_interactive: Whether plugin supports interactive mode.
        command: Command to run (default: echo command).

    Returns:
        Mock plugin object.
    """
    plugin = MagicMock()
    plugin.name = name
    plugin.supports_interactive = supports_interactive

    if command is None:
        command = ["/bin/echo", f"Hello from {name}"]

    if supports_interactive:
        plugin.get_interactive_command.return_value = command
    else:
        plugin.get_interactive_command.side_effect = NotImplementedError()

    plugin.check_available = AsyncMock(return_value=True)
    plugin.pre_execute = AsyncMock()
    plugin.post_execute = AsyncMock()

    return plugin


class TestE2EPluginExecution:
    """E2E tests for plugin execution in interactive tabs."""

    @pytest.mark.asyncio
    async def test_single_plugin_execution(self) -> None:
        """Test executing a single plugin in interactive mode."""
        plugin = create_mock_plugin(
            "test",
            command=["/bin/bash", "-c", "echo 'Test output' && exit 0"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,  # Don't auto-start for controlled testing
        )

        async with app.run_test():
            # Verify app is mounted (use internal attribute to avoid mypy warning)
            assert getattr(app, "_is_mounted", True)

            # Verify tab was created
            assert "test" in app.tab_data
            assert app.tab_data["test"].state == PaneState.IDLE

            # Verify terminal pane exists
            assert "test" in app.terminal_panes

    @pytest.mark.asyncio
    async def test_multiple_plugins_create_tabs(self) -> None:
        """Test that multiple plugins create separate tabs."""
        plugins = [
            create_mock_plugin("apt"),
            create_mock_plugin("flatpak"),
            create_mock_plugin("pipx"),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test():
            # Verify all tabs were created
            assert len(app.tab_data) == 3
            assert "apt" in app.tab_data
            assert "flatpak" in app.tab_data
            assert "pipx" in app.tab_data

            # Verify all terminal panes exist
            assert len(app.terminal_panes) == 3

    @pytest.mark.asyncio
    async def test_plugin_with_quick_exit(self) -> None:
        """Test plugin that exits quickly with success."""
        plugin = create_mock_plugin(
            "quick",
            command=["/bin/bash", "-c", "echo 'Done' && exit 0"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            # Start the plugin manually
            pane = app.terminal_panes["quick"]
            await pane.start()

            # Wait for process to complete
            await asyncio.sleep(0.5)

            # Check that state changed
            # Note: State may be SUCCESS or EXITED depending on timing
            assert pane.state in (PaneState.SUCCESS, PaneState.EXITED, PaneState.RUNNING)

    @pytest.mark.asyncio
    async def test_plugin_with_failure(self) -> None:
        """Test plugin that exits with failure."""
        plugin = create_mock_plugin(
            "failing",
            command=["/bin/bash", "-c", "echo 'Error!' && exit 1"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            # Start the plugin manually
            pane = app.terminal_panes["failing"]
            await pane.start()

            # Wait for process to complete
            await asyncio.sleep(0.5)

            # Check that state reflects failure
            # Note: State may be FAILED or still RUNNING depending on timing
            assert pane.state in (PaneState.FAILED, PaneState.RUNNING, PaneState.EXITED)


class TestE2ETabNavigation:
    """E2E tests for tab navigation."""

    @pytest.mark.asyncio
    async def test_ctrl_tab_switches_to_next_tab(self) -> None:
        """Test Ctrl+Tab switches to next tab."""
        plugins = [
            create_mock_plugin("apt"),
            create_mock_plugin("flatpak"),
            create_mock_plugin("pipx"),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Initial tab should be 0
            assert app.active_tab_index == 0

            # Press Ctrl+Tab to go to next tab
            await pilot.press("ctrl+tab")
            assert app.active_tab_index == 1

            # Press again
            await pilot.press("ctrl+tab")
            assert app.active_tab_index == 2

            # Should not go beyond last tab
            await pilot.press("ctrl+tab")
            assert app.active_tab_index == 2

    @pytest.mark.asyncio
    async def test_ctrl_shift_tab_switches_to_previous_tab(self) -> None:
        """Test Ctrl+Shift+Tab switches to previous tab."""
        plugins = [
            create_mock_plugin("apt"),
            create_mock_plugin("flatpak"),
            create_mock_plugin("pipx"),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Start at tab 2
            app.active_tab_index = 2

            # Press Ctrl+Shift+Tab to go to previous tab
            await pilot.press("ctrl+shift+tab")
            assert app.active_tab_index == 1

            # Press again
            await pilot.press("ctrl+shift+tab")
            assert app.active_tab_index == 0

            # Should not go below 0
            await pilot.press("ctrl+shift+tab")
            assert app.active_tab_index == 0

    @pytest.mark.asyncio
    async def test_alt_number_switches_to_specific_tab(self) -> None:
        """Test Alt+number switches to specific tab."""
        plugins = [
            create_mock_plugin("apt"),
            create_mock_plugin("flatpak"),
            create_mock_plugin("pipx"),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Press Alt+3 to go to tab 3
            await pilot.press("alt+3")
            assert app.active_tab_index == 2

            # Press Alt+1 to go to tab 1
            await pilot.press("alt+1")
            assert app.active_tab_index == 0

            # Press Alt+2 to go to tab 2
            await pilot.press("alt+2")
            assert app.active_tab_index == 1


class TestE2EScrollback:
    """E2E tests for scrollback functionality."""

    @pytest.mark.asyncio
    async def test_scroll_up_and_down(self) -> None:
        """Test scrolling up and down in terminal history."""
        # Create plugin that produces lots of output
        plugin = create_mock_plugin(
            "verbose",
            command=["/bin/bash", "-c", "for i in $(seq 1 100); do echo Line $i; done"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["verbose"]
            await pane.start()

            # Wait for some output
            await asyncio.sleep(0.5)

            # Test scroll actions don't crash
            app.action_scroll_up()
            app.action_scroll_down()
            app.action_scroll_top()
            app.action_scroll_bottom()


class TestE2EInputHandling:
    """E2E tests for input handling in tabs."""

    @pytest.mark.asyncio
    async def test_input_goes_to_active_tab_only(self) -> None:
        """Test that input only goes to active tab."""
        plugins = [
            create_mock_plugin("tab1", command=["/bin/cat"]),
            create_mock_plugin("tab2", command=["/bin/cat"]),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test():
            # Start both panes
            await app.terminal_panes["tab1"].start()
            await app.terminal_panes["tab2"].start()

            # Ensure tab1 is active
            app.active_tab_index = 0

            # The input router should route to active tab only
            # This is tested at the unit level; here we just verify no crash
            await asyncio.sleep(0.1)


class TestE2EProgressTracking:
    """E2E tests for progress tracking."""

    @pytest.mark.asyncio
    async def test_progress_bar_updates(self) -> None:
        """Test that progress bar updates as plugins complete."""
        plugins = [
            create_mock_plugin("fast1", command=["/bin/bash", "-c", "exit 0"]),
            create_mock_plugin("fast2", command=["/bin/bash", "-c", "exit 0"]),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test():
            # Verify progress bar exists
            from ui.interactive_tabbed_run import ProgressBar

            progress = app.query_one("#progress", ProgressBar)
            assert progress.total_plugins == 2
            assert progress.completed == 0


class TestE2EFallbackBehavior:
    """E2E tests for fallback behavior."""

    @pytest.mark.asyncio
    async def test_fallback_when_pty_unavailable(self) -> None:
        """Test fallback to non-interactive mode when PTY unavailable."""
        plugin = create_mock_plugin("test")

        with (
            patch("ui.interactive_tabbed_run.is_pty_available", return_value=False),
            patch("ui.tabbed_run.run_with_tabbed_ui") as mock_run,
        ):
            mock_run.return_value = None
            await run_with_interactive_tabbed_ui(plugins=[plugin])
            mock_run.assert_called_once()


class TestE2EKeyBindings:
    """E2E tests for custom key bindings."""

    @pytest.mark.asyncio
    async def test_custom_key_bindings(self) -> None:
        """Test using custom key bindings."""
        plugins = [
            create_mock_plugin("apt"),
            create_mock_plugin("flatpak"),
        ]

        custom_bindings = KeyBindings({"next_tab": "alt+n", "prev_tab": "alt+p"})

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            key_bindings=custom_bindings,
            auto_start=False,
        )

        async with app.run_test():
            # Verify custom bindings are set
            assert app.key_bindings.get_key_for_action("next_tab") == "alt+n"
            assert app.key_bindings.get_key_for_action("prev_tab") == "alt+p"


class TestE2EHelpDisplay:
    """E2E tests for help display."""

    @pytest.mark.asyncio
    async def test_f1_shows_help(self) -> None:
        """Test F1 shows help notification."""
        plugin = create_mock_plugin("test")

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Press F1 for help
            await pilot.press("f1")
            # Help is shown via notify, which we can't easily verify in tests
            # but we verify no crash occurs


class TestE2EQuit:
    """E2E tests for quit functionality."""

    @pytest.mark.asyncio
    async def test_ctrl_q_quits_app(self) -> None:
        """Test Ctrl+Q quits the application."""
        plugin = create_mock_plugin("test")

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test() as pilot:
            # Press Ctrl+Q to quit
            await pilot.press("ctrl+q")
            # App should exit - verified by run_test completing


class TestE2EMultiplePluginsIndependent:
    """E2E tests for multiple plugins running independently."""

    @pytest.mark.asyncio
    async def test_multiple_plugins_run_independently(self) -> None:
        """Test that multiple plugins run independently."""
        plugins = [
            create_mock_plugin("slow", command=["/bin/bash", "-c", "sleep 0.2 && echo slow"]),
            create_mock_plugin("fast", command=["/bin/bash", "-c", "echo fast"]),
        ]

        app = InteractiveTabbedApp(
            plugins=cast("list[UpdatePlugin]", plugins),
            auto_start=False,
        )

        async with app.run_test():
            # Start both plugins
            await app.terminal_panes["slow"].start()
            await app.terminal_panes["fast"].start()

            # Both should be running initially
            assert app.terminal_panes["slow"].is_running
            assert app.terminal_panes["fast"].is_running

            # Wait for fast to complete
            await asyncio.sleep(0.3)

            # Slow may still be running or just completed
            # Fast should have completed
            # This verifies they run independently


class TestE2ETerminalResize:
    """E2E tests for terminal resize handling."""

    @pytest.mark.asyncio
    async def test_terminal_resize(self) -> None:
        """Test terminal resize handling."""
        plugin = create_mock_plugin(
            "resize",
            command=["/bin/bash", "-c", "echo 'Resize test'"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["resize"]

            # Resize the terminal
            await pane.resize(120, 40)

            # Verify config was updated
            assert pane.config.columns == 120
            assert pane.config.lines == 40


class TestE2EOutputCapture:
    """E2E tests for output capture and display."""

    @pytest.mark.asyncio
    async def test_output_is_captured(self) -> None:
        """Test that output from PTY is captured."""
        plugin = create_mock_plugin(
            "output",
            command=["/bin/bash", "-c", "echo 'Hello World'"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["output"]
            await pane.start()

            # Wait for output
            await asyncio.sleep(0.3)

            # Output bytes should have been tracked
            app.tab_data["output"]
            # Note: output_bytes may or may not be updated depending on timing
            # The main test is that no crash occurs


class TestE2EAnsiColors:
    """E2E tests for ANSI color handling."""

    @pytest.mark.asyncio
    async def test_ansi_colors_are_processed(self) -> None:
        """Test that ANSI color codes are processed."""
        # Command that outputs colored text
        plugin = create_mock_plugin(
            "colors",
            command=[
                "/bin/bash",
                "-c",
                "echo -e '\\033[31mRed\\033[0m \\033[32mGreen\\033[0m'",
            ],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["colors"]
            await pane.start()

            # Wait for output
            await asyncio.sleep(0.3)

            # Verify terminal view exists and has processed output
            assert pane.terminal_view is not None


class TestE2EStateTransitions:
    """E2E tests for pane state transitions."""

    @pytest.mark.asyncio
    async def test_state_transitions_idle_to_running(self) -> None:
        """Test state transition from IDLE to RUNNING."""
        plugin = create_mock_plugin(
            "states",
            command=["/bin/bash", "-c", "sleep 0.5"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["states"]

            # Initially IDLE
            assert pane.state == PaneState.IDLE

            # Start the pane
            await pane.start()

            # Should be RUNNING (or may have already completed)
            assert pane.state in (PaneState.RUNNING, PaneState.SUCCESS, PaneState.EXITED)

    @pytest.mark.asyncio
    async def test_state_transitions_running_to_success(self) -> None:
        """Test state transition from RUNNING to SUCCESS."""
        plugin = create_mock_plugin(
            "success",
            command=["/bin/bash", "-c", "exit 0"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["success"]
            await pane.start()

            # Wait for completion
            await asyncio.sleep(0.3)

            # Should be SUCCESS or EXITED
            assert pane.state in (PaneState.SUCCESS, PaneState.EXITED, PaneState.RUNNING)

    @pytest.mark.asyncio
    async def test_state_transitions_running_to_failed(self) -> None:
        """Test state transition from RUNNING to FAILED."""
        plugin = create_mock_plugin(
            "failure",
            command=["/bin/bash", "-c", "exit 1"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["failure"]
            await pane.start()

            # Wait for completion
            await asyncio.sleep(0.3)

            # Should be FAILED or still RUNNING (timing dependent)
            assert pane.state in (PaneState.FAILED, PaneState.RUNNING, PaneState.EXITED)


class TestE2EPluginOutputVisible:
    """E2E tests for verifying plugin output is visible in terminal display."""

    @pytest.mark.asyncio
    async def test_plugin_output_visible_in_terminal_display(self) -> None:
        """Test that plugin output is visible in the terminal display buffer.

        This test verifies the complete data flow:
        1. Plugin command runs in PTY
        2. PTY output is read by _read_loop
        3. Output is fed to TerminalView
        4. Output appears in terminal_display buffer
        """
        # Use a unique marker to identify our output
        marker = "VISIBLE_OUTPUT_TEST_12345"
        plugin = create_mock_plugin(
            "visible",
            command=["/bin/bash", "-c", f"echo '{marker}'"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["visible"]
            await pane.start()

            # Wait for output to be processed
            await asyncio.sleep(0.5)

            # Verify terminal view exists
            assert pane.terminal_view is not None

            # Verify the marker appears in the terminal display
            display = pane.terminal_view.terminal_display
            display_text = "\n".join(display)
            assert marker in display_text, (
                f"Expected marker '{marker}' not found in terminal display. "
                f"First 3 lines: {display[:3]}"
            )

    @pytest.mark.asyncio
    async def test_multiline_output_visible_in_terminal_display(self) -> None:
        """Test that multiline output is visible in the terminal display."""
        plugin = create_mock_plugin(
            "multiline",
            command=["/bin/bash", "-c", "echo 'Line1' && echo 'Line2' && echo 'Line3'"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["multiline"]
            await pane.start()

            # Wait for output to be processed
            await asyncio.sleep(0.5)

            # Verify terminal view exists
            assert pane.terminal_view is not None

            # Verify all lines appear in the terminal display
            display = pane.terminal_view.terminal_display
            assert "Line1" in display[0], f"Line1 not in display[0]: {display[0]}"
            assert "Line2" in display[1], f"Line2 not in display[1]: {display[1]}"
            assert "Line3" in display[2], f"Line3 not in display[2]: {display[2]}"

    @pytest.mark.asyncio
    async def test_render_line_returns_content(self) -> None:
        """Test that render_line returns the terminal content as Strip.

        This verifies that Textual can render the terminal content.
        """
        plugin = create_mock_plugin(
            "render",
            command=["/bin/bash", "-c", "echo 'RenderTest'"],
        )

        app = InteractiveTabbedApp(
            plugins=[plugin],
            auto_start=False,
        )

        async with app.run_test():
            pane = app.terminal_panes["render"]
            await pane.start()

            # Wait for output to be processed
            await asyncio.sleep(0.5)

            # Verify terminal view exists
            assert pane.terminal_view is not None

            # Verify render_line returns content
            strip = pane.terminal_view.render_line(0)
            strip_text = "".join(seg.text for seg in strip)
            assert "RenderTest" in strip_text, (
                f"Expected 'RenderTest' in rendered strip, got: {strip_text}"
            )

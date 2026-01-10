"""Data models for the UI module.

This module contains data classes used across the UI module,
extracted for better separation of concerns and maintainability.

Milestone 4 - UI Module Architecture Refactoring
See docs/cleanup-and-refactoring-plan.md section 4.3.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ui.phase_tab import DisplayPhase, TabStatus
from ui.terminal_pane import PaneConfig, PaneState

if TYPE_CHECKING:
    from datetime import datetime

    from core.interfaces import UpdatePlugin


@dataclass
class InteractiveTabData:
    """Data for an interactive tab.

    This dataclass holds all the state and configuration for a single
    interactive terminal tab in the InteractiveTabbedApp.

    Attributes:
        plugin_name: Name of the plugin this tab represents.
        plugin: The UpdatePlugin instance.
        command: Command to execute in the PTY session.
        state: Current state of the terminal pane.
        start_time: When the plugin execution started.
        end_time: When the plugin execution ended.
        exit_code: Exit code from the plugin execution.
        error_message: Error message if execution failed.
        output_bytes: Number of bytes of output produced.
        config: Configuration for the terminal pane.
        current_phase: Current display phase (Update, Download, Upgrade).
        tab_status: Visual status of the tab.
    """

    plugin_name: str
    plugin: UpdatePlugin
    command: list[str]
    state: PaneState = PaneState.IDLE
    start_time: datetime | None = None
    end_time: datetime | None = None
    exit_code: int | None = None
    error_message: str | None = None
    output_bytes: int = 0
    config: PaneConfig = field(default_factory=PaneConfig)
    # Phase 2: Visual enhancement fields
    current_phase: DisplayPhase = DisplayPhase.PENDING
    tab_status: TabStatus = TabStatus.PENDING

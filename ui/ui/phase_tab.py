"""Phase-aware tab widget with visual status indicators.

This module provides enhanced tab components with phase labels and color-coded
status indicators for the interactive tabbed UI.

Phase 2 - Visual Enhancements
See docs/UI-revision-plan.md section 3.1 and 3.3
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.streaming import Phase


class DisplayPhase(str, Enum):
    """User-facing phase names.

    These are the display labels shown to users, which map to the internal
    Phase enum values from core.streaming.
    """

    UPDATE = "Update"  # Maps to Phase.CHECK
    DOWNLOAD = "Download"  # Maps to Phase.DOWNLOAD
    UPGRADE = "Upgrade"  # Maps to Phase.EXECUTE
    PENDING = "Pending"  # Not yet started
    COMPLETE = "Complete"  # All phases done


def get_display_phase(phase: Phase | None) -> DisplayPhase:
    """Map internal Phase enum to user-facing DisplayPhase.

    Args:
        phase: Internal phase from core.streaming, or None if not started.

    Returns:
        User-facing display phase.
    """
    # Import here to avoid circular imports
    from core.streaming import Phase as CorePhase

    if phase is None:
        return DisplayPhase.PENDING

    mapping = {
        CorePhase.CHECK: DisplayPhase.UPDATE,
        CorePhase.DOWNLOAD: DisplayPhase.DOWNLOAD,
        CorePhase.EXECUTE: DisplayPhase.UPGRADE,
    }
    return mapping.get(phase, DisplayPhase.PENDING)


class TabStatus(str, Enum):
    """Visual status of a tab.

    Each status corresponds to a specific color and icon for visual feedback.
    """

    COMPLETED = "completed"
    RUNNING = "running"
    ERROR = "error"
    PENDING = "pending"
    LOCKED = "locked"


# Color scheme for tab statuses
# These map to CSS color values or Textual color names
TAB_STATUS_COLORS: dict[TabStatus, str] = {
    TabStatus.COMPLETED: "green",
    TabStatus.RUNNING: "yellow",
    TabStatus.ERROR: "red",
    TabStatus.PENDING: "grey",
    TabStatus.LOCKED: "dim grey",
}

# Icon indicators for tab statuses
TAB_STATUS_ICONS: dict[TabStatus, str] = {
    TabStatus.COMPLETED: "🟢",
    TabStatus.RUNNING: "🟡",
    TabStatus.ERROR: "🔴",
    TabStatus.PENDING: "⬜",
    TabStatus.LOCKED: "🔒",
}

# CSS class names for tab statuses
TAB_STATUS_CSS_CLASSES: dict[TabStatus, str] = {
    TabStatus.COMPLETED: "tab-completed",
    TabStatus.RUNNING: "tab-running",
    TabStatus.ERROR: "tab-error",
    TabStatus.PENDING: "tab-pending",
    TabStatus.LOCKED: "tab-locked",
}


def get_tab_label(
    plugin_name: str,
    status: TabStatus,
    phase: DisplayPhase | None = None,
) -> str:
    """Generate a formatted tab label with status icon and phase.

    Format: [status_icon] plugin_name (phase_name)
    Example: 🟢 apt (Upgrade) or 🟡 flatpak (Download)

    Args:
        plugin_name: Name of the plugin.
        status: Current tab status.
        phase: Current display phase, or None to omit phase from label.

    Returns:
        Formatted tab label string.
    """
    icon = TAB_STATUS_ICONS.get(status, "")
    if phase is not None:
        return f"{icon} {plugin_name} ({phase.value})"
    return f"{icon} {plugin_name}"


def get_tab_css_class(status: TabStatus) -> str:
    """Get the CSS class name for a tab status.

    Args:
        status: Tab status.

    Returns:
        CSS class name for styling.
    """
    return TAB_STATUS_CSS_CLASSES.get(status, "tab-pending")


# CSS styles for phase tabs
# These should be included in the main app's CSS
PHASE_TAB_CSS = """
/* Phase Tab Status Colors */
/* See docs/UI-revision-plan.md section 3.3 */

.tab-completed {
    background: $success;
    color: $text;
}

.tab-completed:focus {
    background: $success-darken-1;
}

.tab-running {
    background: $warning;
    color: $text;
}

.tab-running:focus {
    background: $warning-darken-1;
}

.tab-error {
    background: $error;
    color: $text;
}

.tab-error:focus {
    background: $error-darken-1;
}

.tab-pending {
    background: $surface-darken-1;
    color: $text-muted;
}

.tab-pending:focus {
    background: $surface;
}

.tab-locked {
    background: $surface-darken-2;
    color: $text-disabled;
}

.tab-locked:focus {
    background: $surface-darken-1;
}

/* Phase indicator in tab label */
/* Note: font-size and opacity are not supported in Textual CSS */
.phase-indicator {
    color: $text-muted;
}
"""


def determine_tab_status_from_pane_state(pane_state: str) -> TabStatus:
    """Determine tab status from PaneState value.

    This is a simplified version that maps PaneState to TabStatus
    without requiring PhaseController or dependency information.

    Args:
        pane_state: PaneState value as string (e.g., "success", "running").

    Returns:
        Corresponding TabStatus.
    """
    # Import here to avoid circular imports at module level
    from ui.terminal_pane import PaneState

    state_mapping = {
        PaneState.SUCCESS.value: TabStatus.COMPLETED,
        PaneState.RUNNING.value: TabStatus.RUNNING,
        PaneState.FAILED.value: TabStatus.ERROR,
        PaneState.EXITED.value: TabStatus.ERROR,
        PaneState.IDLE.value: TabStatus.PENDING,
    }
    return state_mapping.get(pane_state, TabStatus.PENDING)


def determine_tab_status(
    pane_state: str,
    has_unmet_dependencies: bool = False,
    is_mutex_blocked: bool = False,
) -> TabStatus:
    """Determine the visual status of a tab.

    This function considers:
    1. The current pane state (running, completed, failed, etc.)
    2. Whether dependencies are unmet (locked status)
    3. Whether blocked by mutex (locked status)

    Args:
        pane_state: Current PaneState value as string.
        has_unmet_dependencies: True if plugin has unmet dependencies.
        is_mutex_blocked: True if plugin is blocked by a mutex.

    Returns:
        The appropriate TabStatus for visual display.
    """
    # Import here to avoid circular imports
    from ui.terminal_pane import PaneState

    # First check completion states
    if pane_state == PaneState.SUCCESS.value:
        return TabStatus.COMPLETED
    if pane_state in (PaneState.FAILED.value, PaneState.EXITED.value):
        return TabStatus.ERROR
    if pane_state == PaneState.RUNNING.value:
        return TabStatus.RUNNING

    # Check if locked due to dependencies or mutex
    if has_unmet_dependencies or is_mutex_blocked:
        return TabStatus.LOCKED

    return TabStatus.PENDING

"""Update-All UI package.

Rich terminal UI components for the update-all system.

Phase 3 - UI Integration adds:
- Streaming event handling with batched updates
- Progress bar visualization
- Sudo pre-authentication utilities

Phase 1 - Interactive Tabs adds:
- PTY session management for interactive terminal tabs
- See docs/interactive-tabs-implementation-plan.md

Phase 2 - Terminal Emulation adds:
- TerminalScreen: pyte-based terminal emulation with scrollback
- TerminalView: Textual widget for rendering terminal content
- See docs/interactive-tabs-implementation-plan.md

Phase 3 - Input Handling adds:
- KeyBindings: Configurable key binding system
- InputRouter: Keyboard input routing between app and PTY
- See docs/interactive-tabs-implementation-plan.md

Phase 4 - Integration adds:
- TerminalPane: Container widget combining TerminalView with PTY management
- InteractiveTabbedApp: Main application with PTY-based terminal tabs
- See docs/interactive-tabs-implementation-plan.md

UI Revision Plan - Phase 2 Visual Enhancements adds:
- DisplayPhase: User-facing phase names (Update, Download, Upgrade)
- TabStatus: Visual status indicators (completed, running, error, pending, locked)
- Phase-aware tab labels with color-coded status icons
- See docs/UI-revision-plan.md

UI Revision Plan - Phase 3 Status Bar adds:
- PhaseStatusBar: Per-tab status bar with metrics display
- PhaseMetrics: Dataclass for runtime metrics
- MetricsCollector: Process metrics collection using psutil
- See docs/UI-revision-plan.md section 3.4

Milestone 3 - Textual Library Usage Review and Fixes adds:
- MetricsStore: Persistent storage for metrics across phase transitions
- PhaseSnapshot: Immutable snapshot of phase metrics at completion
- AccumulatedMetrics: Accumulated metrics across all phases
- See docs/cleanup-and-refactoring-plan.md section 3.3.1

Milestone 4 - UI Module Architecture Refactoring adds:
- Extracted InteractiveTabData to ui/ui/models.py
- Extracted AllPluginsCompleted to ui/ui/messages.py
- Extracted ProgressBar to ui/ui/progress.py
- Moved MetricsCollector, PhaseMetrics, etc. to ui/ui/metrics.py
- See docs/cleanup-and-refactoring-plan.md section 4

UI Revision Plan - Phase 5 Integration and Polish adds:
- End-to-end integration tests for phase control features
- Performance optimization and benchmarks
- Documentation updates with migration guide
- See docs/UI-revision-plan.md section 4 Phase 5

Task 3 - Statistics Viewer adds:
- StatisticsViewerApp: Interactive TUI for viewing historical update statistics
- run_statistics_viewer: Entry point for the statistics viewer
- Available via: `update-all statistics`
"""

from ui.event_handler import (
    BatchedEvent,
    BatchedEventHandler,
    CallbackEventHandler,
    StreamEventAdapter,
    UIEventHandler,
)
from ui.input_router import InputRouter, RouteTarget
from ui.interactive_tabbed_run import (
    InteractiveTabbedApp,
    run_with_interactive_tabbed_ui,
)
from ui.key_bindings import InvalidKeyError, KeyBindings, normalize_key
from ui.messages import AllPluginsCompleted
from ui.metrics import (
    AccumulatedMetrics,
    MetricsCollector,
    MetricsSnapshot,
    MetricsStore,
    PhaseMetrics,
    PhaseSnapshot,
    PhaseStats,
    RunningProgress,
    create_metrics_collector_for_pid,
)
from ui.models import InteractiveTabData
from ui.panels import SummaryPanel
from ui.phase_status_bar import (
    PHASE_STATUS_BAR_CSS,
    PhaseStatusBar,
)
from ui.phase_tab import (
    PHASE_TAB_CSS,
    TAB_STATUS_COLORS,
    TAB_STATUS_CSS_CLASSES,
    TAB_STATUS_ICONS,
    DisplayPhase,
    TabStatus,
    determine_tab_status,
    determine_tab_status_from_pane_state,
    get_display_phase,
    get_tab_css_class,
    get_tab_label,
)
from ui.progress import ProgressBar, ProgressDisplay
from ui.pty_manager import PTYSessionManager, SessionNotFoundError
from ui.pty_session import (
    PTYAlreadyStartedError,
    PTYError,
    PTYNotStartedError,
    PTYReadTimeoutError,
    PTYSession,
    is_pty_available,
)
from ui.statistics_viewer import StatisticsViewerApp, run_statistics_viewer
from ui.sudo import (
    SudoCheckResult,
    SudoKeepAlive,
    SudoStatus,
    check_sudo_status,
    ensure_sudo_authenticated,
    refresh_sudo_timestamp,
)
from ui.tabbed_run import (
    PluginProgressMessage,
    PluginState,
    TabbedRunApp,
    TextualBatchedEventHandler,
    TextualUIEventHandler,
    run_with_tabbed_ui,
)
from ui.tables import ResultsTable
from ui.terminal_pane import (
    PaneConfig,
    PaneOutputMessage,
    PaneState,
    PaneStateChanged,
    TerminalPane,
)
from ui.terminal_screen import StyledChar, TerminalScreen
from ui.terminal_view import TerminalView, ansi_color_to_rich_color

__all__ = [
    "PHASE_STATUS_BAR_CSS",
    "PHASE_TAB_CSS",
    "TAB_STATUS_COLORS",
    "TAB_STATUS_CSS_CLASSES",
    "TAB_STATUS_ICONS",
    "AccumulatedMetrics",
    "AllPluginsCompleted",
    "BatchedEvent",
    "BatchedEventHandler",
    "CallbackEventHandler",
    "DisplayPhase",
    "InputRouter",
    "InteractiveTabData",
    "InteractiveTabbedApp",
    "InvalidKeyError",
    "KeyBindings",
    "MetricsCollector",
    "MetricsSnapshot",
    "MetricsStore",
    "PTYAlreadyStartedError",
    "PTYError",
    "PTYNotStartedError",
    "PTYReadTimeoutError",
    "PTYSession",
    "PTYSessionManager",
    "PaneConfig",
    "PaneOutputMessage",
    "PaneState",
    "PaneStateChanged",
    "PhaseMetrics",
    "PhaseSnapshot",
    "PhaseStats",
    "PhaseStatusBar",
    "PluginProgressMessage",
    "PluginState",
    "ProgressBar",
    "ProgressDisplay",
    "ResultsTable",
    "RouteTarget",
    "RunningProgress",
    "SessionNotFoundError",
    "StatisticsViewerApp",
    "StreamEventAdapter",
    "StyledChar",
    "SudoCheckResult",
    "SudoKeepAlive",
    "SudoStatus",
    "SummaryPanel",
    "TabStatus",
    "TabbedRunApp",
    "TerminalPane",
    "TerminalScreen",
    "TerminalView",
    "TextualBatchedEventHandler",
    "TextualUIEventHandler",
    "UIEventHandler",
    "ansi_color_to_rich_color",
    "check_sudo_status",
    "create_metrics_collector_for_pid",
    "determine_tab_status",
    "determine_tab_status_from_pane_state",
    "ensure_sudo_authenticated",
    "get_display_phase",
    "get_tab_css_class",
    "get_tab_label",
    "is_pty_available",
    "normalize_key",
    "refresh_sudo_timestamp",
    "run_statistics_viewer",
    "run_with_interactive_tabbed_ui",
    "run_with_tabbed_ui",
]

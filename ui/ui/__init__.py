"""Update-All UI package.

Rich terminal UI components for the update-all system.

Phase 3 - UI Integration adds:
- Streaming event handling with batched updates
- Progress bar visualization
- Sudo pre-authentication utilities

Phase 1 - Interactive Tabs adds:
- PTY session management for interactive terminal tabs
- See docs/interactive-tabs-implementation-plan.md
"""

from ui.event_handler import (
    BatchedEvent,
    BatchedEventHandler,
    CallbackEventHandler,
    StreamEventAdapter,
    UIEventHandler,
)
from ui.panels import SummaryPanel
from ui.progress import ProgressDisplay
from ui.pty_manager import PTYSessionManager, SessionNotFoundError
from ui.pty_session import (
    PTYAlreadyStartedError,
    PTYError,
    PTYNotStartedError,
    PTYReadTimeoutError,
    PTYSession,
    is_pty_available,
)
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

__all__ = [
    "BatchedEvent",
    "BatchedEventHandler",
    "CallbackEventHandler",
    "PTYAlreadyStartedError",
    "PTYError",
    "PTYNotStartedError",
    "PTYReadTimeoutError",
    "PTYSession",
    "PTYSessionManager",
    "PluginProgressMessage",
    "PluginState",
    "ProgressDisplay",
    "ResultsTable",
    "SessionNotFoundError",
    "StreamEventAdapter",
    "SudoCheckResult",
    "SudoKeepAlive",
    "SudoStatus",
    "SummaryPanel",
    "TabbedRunApp",
    "TextualBatchedEventHandler",
    "TextualUIEventHandler",
    "UIEventHandler",
    "check_sudo_status",
    "ensure_sudo_authenticated",
    "is_pty_available",
    "refresh_sudo_timestamp",
    "run_with_tabbed_ui",
]

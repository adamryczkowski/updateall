#!/usr/bin/env python3
"""Script to add debug logging to trace phase stats preservation.

This script adds logging statements to key points in the code to trace:
1. When MetricsCollector is created vs reused
2. When phase stats are updated
3. When stop() is called and whether collector is preserved
4. What values are in phase_stats at each point

Run this script, then run the app with:
    poetry run update-all run -i -P -p mock-alpha

The debug output will show in the terminal.
"""

import sys
from pathlib import Path

# Add the ui directory to the path
ui_dir = Path(__file__).parent.parent / "ui"
sys.path.insert(0, str(ui_dir))

# Now we can import and patch the modules
import ui.terminal_pane as terminal_pane  # noqa: E402
import ui.phase_status_bar as phase_status_bar  # noqa: E402

# Store original methods
original_start = terminal_pane.TerminalPane.start
original_stop = terminal_pane.TerminalPane.stop
original_update_pid = phase_status_bar.MetricsCollector.update_pid
original_start_phase = phase_status_bar.MetricsCollector.start_phase
original_complete_phase = phase_status_bar.MetricsCollector.complete_phase
original_refresh_display = phase_status_bar.PhaseStatusBar._refresh_display


def debug_log(msg: str) -> None:
    """Print debug message with timestamp."""
    from datetime import datetime

    print(f"[DEBUG {datetime.now().strftime('%H:%M:%S.%f')}] {msg}", file=sys.stderr)


async def patched_start(self) -> None:
    """Patched start() with debug logging."""
    debug_log(f"TerminalPane.start() called for pane_id={self.pane_id}")
    debug_log(f"  _metrics_collector is None: {self._metrics_collector is None}")
    if self._metrics_collector:
        debug_log(f"  Existing phase_stats: {self._metrics_collector._phase_stats}")

    await original_start(self)

    debug_log(f"TerminalPane.start() completed for pane_id={self.pane_id}")
    debug_log(f"  _metrics_collector is None: {self._metrics_collector is None}")
    if self._metrics_collector:
        debug_log(f"  phase_stats after start: {self._metrics_collector._phase_stats}")


async def patched_stop(self) -> None:
    """Patched stop() with debug logging."""
    debug_log(f"TerminalPane.stop() called for pane_id={self.pane_id}")
    debug_log(f"  _metrics_collector is None: {self._metrics_collector is None}")
    if self._metrics_collector:
        debug_log(f"  phase_stats before stop: {self._metrics_collector._phase_stats}")

    await original_stop(self)

    debug_log(f"TerminalPane.stop() completed for pane_id={self.pane_id}")
    debug_log(f"  _metrics_collector is None: {self._metrics_collector is None}")
    if self._metrics_collector:
        debug_log(f"  phase_stats after stop: {self._metrics_collector._phase_stats}")


def patched_update_pid(self, pid) -> None:
    """Patched update_pid() with debug logging."""
    debug_log(f"MetricsCollector.update_pid() called with pid={pid}")
    debug_log(f"  phase_stats before: {self._phase_stats}")

    original_update_pid(self, pid)

    debug_log("MetricsCollector.update_pid() completed")
    debug_log(f"  phase_stats after: {self._phase_stats}")


def patched_start_phase(self, phase_name: str) -> None:
    """Patched start_phase() with debug logging."""
    debug_log(f"MetricsCollector.start_phase() called with phase_name={phase_name}")
    debug_log(f"  phase_stats before: {self._phase_stats}")

    original_start_phase(self, phase_name)

    debug_log("MetricsCollector.start_phase() completed")
    debug_log(f"  phase_stats after: {self._phase_stats}")


def patched_complete_phase(self, phase_name: str) -> None:
    """Patched complete_phase() with debug logging."""
    debug_log(f"MetricsCollector.complete_phase() called with phase_name={phase_name}")
    debug_log(f"  phase_stats before: {self._phase_stats}")

    original_complete_phase(self, phase_name)

    debug_log("MetricsCollector.complete_phase() completed")
    debug_log(f"  phase_stats after: {self._phase_stats}")


def patched_refresh_display(self) -> None:
    """Patched _refresh_display() with debug logging."""
    if self._metrics_collector:
        debug_log("PhaseStatusBar._refresh_display() called")
        debug_log(f"  phase_stats: {self._metrics_collector._phase_stats}")

    original_refresh_display(self)


# Apply patches
terminal_pane.TerminalPane.start = patched_start
terminal_pane.TerminalPane.stop = patched_stop
phase_status_bar.MetricsCollector.update_pid = patched_update_pid
phase_status_bar.MetricsCollector.start_phase = patched_start_phase
phase_status_bar.MetricsCollector.complete_phase = patched_complete_phase
phase_status_bar.PhaseStatusBar._refresh_display = patched_refresh_display

print("Debug logging patches applied!", file=sys.stderr)
print("Now run: poetry run update-all run -i -P -p mock-alpha", file=sys.stderr)


if __name__ == "__main__":
    # Import and run the CLI
    from cli.main import app

    app()

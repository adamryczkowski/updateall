#!/usr/bin/env python3
"""Trace phase stats during multi-phase execution.

This script patches the MetricsCollector to add tracing, then runs
the interactive tabbed app with mock plugins to observe phase stats.
"""

import sys
import os

# Add the project packages to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ui"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cli"))

from datetime import datetime

# Open trace log file
TRACE_LOG = open("/tmp/phase_stats_trace.log", "w", buffering=1)


def trace(msg):
    """Write trace message to log file."""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    TRACE_LOG.write(f"[{timestamp}] {msg}\n")
    TRACE_LOG.flush()


def patch_metrics_collector():
    """Patch MetricsCollector to add tracing."""
    from ui.phase_status_bar import MetricsCollector

    original_init = MetricsCollector.__init__
    original_start = MetricsCollector.start
    original_stop = MetricsCollector.stop
    original_update_pid = MetricsCollector.update_pid
    original_start_phase = MetricsCollector.start_phase
    original_complete_phase = MetricsCollector.complete_phase
    original_update_phase_stats = MetricsCollector.update_phase_stats
    original_collect = MetricsCollector.collect

    def traced_init(self, *args, **kwargs):
        result = original_init(self, *args, **kwargs)
        trace(f"MetricsCollector.__init__ called, id={id(self)}, pid={self.pid}")
        return result

    def traced_start(self):
        trace(f"MetricsCollector.start called, id={id(self)}, _running={self._running}")
        result = original_start(self)
        trace(f"MetricsCollector.start done, _running={self._running}")
        return result

    def traced_stop(self):
        trace(f"MetricsCollector.stop called, id={id(self)}, _running={self._running}")
        result = original_stop(self)
        trace(f"MetricsCollector.stop done, _running={self._running}")
        return result

    def traced_update_pid(self, pid):
        trace(
            f"MetricsCollector.update_pid called, id={id(self)}, old_pid={self.pid}, new_pid={pid}"
        )
        phase_stats_before = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats before: {phase_stats_before}")
        result = original_update_pid(self, pid)
        phase_stats_after = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats after: {phase_stats_after}")
        return result

    def traced_start_phase(self, phase_name):
        trace(f"MetricsCollector.start_phase called, id={id(self)}, phase={phase_name}")
        phase_stats_before = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats before: {phase_stats_before}")
        result = original_start_phase(self, phase_name)
        phase_stats_after = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats after: {phase_stats_after}")
        return result

    def traced_complete_phase(self, phase_name):
        trace(
            f"MetricsCollector.complete_phase called, id={id(self)}, phase={phase_name}"
        )
        phase_stats_before = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats before: {phase_stats_before}")
        result = original_complete_phase(self, phase_name)
        phase_stats_after = {
            k: (v.wall_time_seconds, v.cpu_time_seconds, v.data_bytes, v.is_complete)
            for k, v in self._phase_stats.items()
        }
        trace(f"  _phase_stats after: {phase_stats_after}")
        return result

    def traced_update_phase_stats(self, phase_name, **kwargs):
        # Only trace if there are actual updates
        if any(v is not None for v in kwargs.values()):
            stats = self._phase_stats.get(phase_name)
            if stats and stats.is_complete:
                trace(
                    f"MetricsCollector.update_phase_stats BLOCKED (phase complete), phase={phase_name}, kwargs={kwargs}"
                )
        result = original_update_phase_stats(self, phase_name, **kwargs)
        return result

    def traced_collect(self):
        result = original_collect(self)
        # Print phase stats summary periodically
        if hasattr(self, "_trace_counter"):
            self._trace_counter += 1
        else:
            self._trace_counter = 0

        if self._trace_counter % 10 == 0:  # Every 10 collects
            trace(f"collect() phase_stats summary (collect #{self._trace_counter}):")
            for name, stats in self._phase_stats.items():
                trace(
                    f"  {name}: wall={stats.wall_time_seconds:.1f}s, cpu={stats.cpu_time_seconds:.1f}s, data={stats.data_bytes}B, complete={stats.is_complete}, running={stats.is_running}"
                )
        return result

    MetricsCollector.__init__ = traced_init
    MetricsCollector.start = traced_start
    MetricsCollector.stop = traced_stop
    MetricsCollector.update_pid = traced_update_pid
    MetricsCollector.start_phase = traced_start_phase
    MetricsCollector.complete_phase = traced_complete_phase
    MetricsCollector.update_phase_stats = traced_update_phase_stats
    MetricsCollector.collect = traced_collect

    trace("MetricsCollector patched with tracing")


def patch_terminal_pane():
    """Patch TerminalPane to add tracing."""
    from ui.terminal_pane import TerminalPane

    original_start = TerminalPane.start
    original_stop = TerminalPane.stop

    async def traced_start(self):
        trace(f"TerminalPane.start called, pane_id={self.pane_id}")
        trace(
            f"  _metrics_collector before: {self._metrics_collector is not None}, id={id(self._metrics_collector) if self._metrics_collector else None}"
        )
        result = await original_start(self)
        trace(
            f"  _metrics_collector after: {self._metrics_collector is not None}, id={id(self._metrics_collector) if self._metrics_collector else None}"
        )
        return result

    async def traced_stop(self):
        trace(f"TerminalPane.stop called, pane_id={self.pane_id}")
        trace(
            f"  _metrics_collector before: {self._metrics_collector is not None}, id={id(self._metrics_collector) if self._metrics_collector else None}"
        )
        result = await original_stop(self)
        trace(
            f"  _metrics_collector after: {self._metrics_collector is not None}, id={id(self._metrics_collector) if self._metrics_collector else None}"
        )
        return result

    TerminalPane.start = traced_start
    TerminalPane.stop = traced_stop

    trace("TerminalPane patched with tracing")


if __name__ == "__main__":
    trace("=" * 60)
    trace("Starting phase stats trace")
    trace("=" * 60)

    # Apply patches before importing the app
    patch_metrics_collector()
    patch_terminal_pane()

    # Now run the app
    import asyncio
    from plugins.mock_alpha import MockAlphaPlugin
    from plugins.mock_beta import MockBetaPlugin
    from ui.interactive_tabbed_run import InteractiveTabbedApp

    async def main():
        plugins = [MockAlphaPlugin(), MockBetaPlugin()]
        app = InteractiveTabbedApp(
            plugins=plugins,
            pause_phases=False,
        )
        await app.run_async()

    try:
        asyncio.run(main())
    finally:
        trace("=" * 60)
        trace("Trace complete")
        trace("=" * 60)
        TRACE_LOG.close()

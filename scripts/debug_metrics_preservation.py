#!/usr/bin/env python3
"""Debug script to trace MetricsCollector preservation across phases.

This script adds logging to understand why phase statistics are being reset
in the actual running application despite the fix being applied.

Run from the ui directory:
    poetry run python ../scripts/debug_metrics_preservation.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the ui package to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger("debug_metrics")


def patch_terminal_pane():
    """Patch TerminalPane to add debug logging."""
    from ui.terminal_pane import TerminalPane

    original_start = TerminalPane.start

    async def patched_start(self):
        logger.info(f"[{self.pane_id}] TerminalPane.start() called")
        logger.info(
            f"[{self.pane_id}] _metrics_collector is None: {self._metrics_collector is None}"
        )
        logger.info(
            f"[{self.pane_id}] _phase_status_bar is None: {self._phase_status_bar is None}"
        )
        logger.info(
            f"[{self.pane_id}] config.show_phase_status_bar: {self.config.show_phase_status_bar}"
        )

        if self._metrics_collector is not None:
            logger.info(f"[{self.pane_id}] Existing MetricsCollector found!")
            logger.info(
                f"[{self.pane_id}] _phase_stats: {self._metrics_collector._phase_stats}"
            )
            for phase_name, stats in self._metrics_collector._phase_stats.items():
                logger.info(
                    f"[{self.pane_id}] Phase {phase_name}: "
                    f"cpu_time={stats.cpu_time_seconds:.2f}s, "
                    f"data={stats.data_bytes} bytes, "
                    f"is_complete={stats.is_complete}"
                )

        result = await original_start(self)

        logger.info(f"[{self.pane_id}] After start():")
        logger.info(
            f"[{self.pane_id}] _metrics_collector is None: {self._metrics_collector is None}"
        )
        if self._metrics_collector is not None:
            for phase_name, stats in self._metrics_collector._phase_stats.items():
                logger.info(
                    f"[{self.pane_id}] Phase {phase_name}: "
                    f"cpu_time={stats.cpu_time_seconds:.2f}s, "
                    f"data={stats.data_bytes} bytes, "
                    f"is_complete={stats.is_complete}"
                )

        return result

    TerminalPane.start = patched_start
    logger.info("Patched TerminalPane.start()")


def patch_metrics_collector():
    """Patch MetricsCollector to add debug logging."""
    from ui.phase_status_bar import MetricsCollector

    original_init = MetricsCollector.__init__
    original_update_pid = MetricsCollector.update_pid
    original_start_phase = MetricsCollector.start_phase
    original_complete_phase = MetricsCollector.complete_phase

    def patched_init(self, pid=None, update_interval=1.0):
        logger.info(f"MetricsCollector.__init__(pid={pid})")
        import traceback

        logger.debug("".join(traceback.format_stack()[-5:-1]))
        return original_init(self, pid, update_interval)

    def patched_update_pid(self, pid):
        logger.info(f"MetricsCollector.update_pid(pid={pid})")
        logger.info("Before update_pid, _phase_stats:")
        for phase_name, stats in self._phase_stats.items():
            logger.info(
                f"  Phase {phase_name}: "
                f"cpu_time={stats.cpu_time_seconds:.2f}s, "
                f"data={stats.data_bytes} bytes, "
                f"is_complete={stats.is_complete}"
            )
        result = original_update_pid(self, pid)
        logger.info("After update_pid, _phase_stats:")
        for phase_name, stats in self._phase_stats.items():
            logger.info(
                f"  Phase {phase_name}: "
                f"cpu_time={stats.cpu_time_seconds:.2f}s, "
                f"data={stats.data_bytes} bytes, "
                f"is_complete={stats.is_complete}"
            )
        return result

    def patched_start_phase(self, phase_name):
        logger.info(f"MetricsCollector.start_phase(phase_name={phase_name})")
        return original_start_phase(self, phase_name)

    def patched_complete_phase(self, phase_name):
        logger.info(f"MetricsCollector.complete_phase(phase_name={phase_name})")
        logger.info(f"Before complete_phase, _phase_stats[{phase_name}]:")
        stats = self._phase_stats.get(phase_name)
        if stats:
            logger.info(
                f"  cpu_time={stats.cpu_time_seconds:.2f}s, "
                f"data={stats.data_bytes} bytes, "
                f"is_complete={stats.is_complete}"
            )
        result = original_complete_phase(self, phase_name)
        logger.info(f"After complete_phase, _phase_stats[{phase_name}]:")
        stats = self._phase_stats.get(phase_name)
        if stats:
            logger.info(
                f"  cpu_time={stats.cpu_time_seconds:.2f}s, "
                f"data={stats.data_bytes} bytes, "
                f"is_complete={stats.is_complete}"
            )
        return result

    MetricsCollector.__init__ = patched_init
    MetricsCollector.update_pid = patched_update_pid
    MetricsCollector.start_phase = patched_start_phase
    MetricsCollector.complete_phase = patched_complete_phase
    logger.info("Patched MetricsCollector")


async def main():
    """Run the interactive app with debug patches."""
    # Apply patches before importing the app
    patch_metrics_collector()
    patch_terminal_pane()

    # Now import and run the app
    from plugins.mock_alpha import MockAlphaPlugin
    from plugins.mock_beta import MockBetaPlugin
    from ui.interactive_tabbed_run import InteractiveTabbedApp

    plugins = [MockAlphaPlugin(), MockBetaPlugin()]

    app = InteractiveTabbedApp(
        plugins=plugins,
        pause_phases=True,  # Enable pause to see phase transitions
        auto_start=True,
    )

    await app.run_async()


if __name__ == "__main__":
    asyncio.run(main())

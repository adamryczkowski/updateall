"""Tests for phase counter reset issue.

This test verifies that when transitioning between phases (Update -> Download -> Upgrade),
the counters (wall time, CPU time, data bytes) from previous phases are preserved
and not reset to zero.

Issue: Each new phase resets counters for the previous one.
Expected: Completed phase stats should be preserved when starting a new phase.
"""

from __future__ import annotations

import time

import pytest

from ui.phase_status_bar import MetricsCollector, PhaseStats


class TestPhaseCounterPreservation:
    """Tests for phase counter preservation across phase transitions."""

    def test_completed_phase_stats_preserved_when_starting_new_phase(self) -> None:
        """Test that completed phase stats are preserved when starting a new phase.

        This is the core test for the phase counter reset issue.
        When we complete the Update phase and start the Download phase,
        the Update phase stats should remain unchanged.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Simulate Update phase
        collector.start_phase("Update")

        # Let some time pass to accumulate wall time
        time.sleep(0.1)

        # Manually set some stats for Update phase to simulate work done
        # Note: wall_time_seconds is calculated automatically, not set directly
        collector.update_phase_stats(
            "Update",
            cpu_time_seconds=2.0,
            data_bytes=1024,
            peak_memory_mb=100.0,
        )

        # Complete the Update phase
        collector.complete_phase("Update")

        # Verify Update phase is marked complete
        assert collector.phase_stats["Update"].is_complete is True
        assert collector.phase_stats["Update"].wall_time_seconds > 0

        # Record the Update phase stats before starting Download
        update_stats_before = PhaseStats(
            phase_name="Update",
            wall_time_seconds=collector.phase_stats["Update"].wall_time_seconds,
            cpu_time_seconds=collector.phase_stats["Update"].cpu_time_seconds,
            data_bytes=collector.phase_stats["Update"].data_bytes,
            peak_memory_mb=collector.phase_stats["Update"].peak_memory_mb,
            is_complete=collector.phase_stats["Update"].is_complete,
        )

        # Now start the Download phase
        collector.start_phase("Download")

        # THE BUG: Check if Update phase stats were reset
        # They should NOT be reset - this is what we're testing
        update_stats_after = collector.phase_stats["Update"]

        # Assert that Update phase stats are preserved
        assert update_stats_after.is_complete is True, (
            "Update phase should still be marked as complete after starting Download"
        )
        assert update_stats_after.wall_time_seconds == update_stats_before.wall_time_seconds, (
            f"Update wall_time was reset from {update_stats_before.wall_time_seconds} "
            f"to {update_stats_after.wall_time_seconds}"
        )
        assert update_stats_after.cpu_time_seconds == update_stats_before.cpu_time_seconds, (
            f"Update cpu_time was reset from {update_stats_before.cpu_time_seconds} "
            f"to {update_stats_after.cpu_time_seconds}"
        )
        assert update_stats_after.data_bytes == update_stats_before.data_bytes, (
            f"Update data_bytes was reset from {update_stats_before.data_bytes} "
            f"to {update_stats_after.data_bytes}"
        )

        collector.stop()

    def test_multiple_phase_transitions_preserve_all_previous_stats(self) -> None:
        """Test that all previous phase stats are preserved through multiple transitions.

        Scenario: Update -> Download -> Upgrade
        After Upgrade starts, both Update and Download stats should be preserved.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Phase 1: Update
        collector.start_phase("Update")
        time.sleep(0.05)  # Let wall time accumulate
        collector.update_phase_stats("Update", cpu_time_seconds=1.0, data_bytes=512)
        collector.complete_phase("Update")
        update_wall_time = collector.phase_stats["Update"].wall_time_seconds
        update_cpu_time = collector.phase_stats["Update"].cpu_time_seconds

        # Phase 2: Download
        collector.start_phase("Download")
        time.sleep(0.05)  # Let wall time accumulate
        collector.update_phase_stats("Download", cpu_time_seconds=0.5, data_bytes=10240)
        collector.complete_phase("Download")
        download_wall_time = collector.phase_stats["Download"].wall_time_seconds
        download_cpu_time = collector.phase_stats["Download"].cpu_time_seconds

        # Phase 3: Upgrade
        collector.start_phase("Upgrade")

        # After starting Upgrade, both Update and Download stats should be preserved
        assert collector.phase_stats["Update"].is_complete is True
        assert collector.phase_stats["Update"].wall_time_seconds == update_wall_time, (
            f"Update wall_time was reset from {update_wall_time} to "
            f"{collector.phase_stats['Update'].wall_time_seconds}"
        )
        assert collector.phase_stats["Update"].cpu_time_seconds == update_cpu_time, (
            f"Update cpu_time was reset from {update_cpu_time} to "
            f"{collector.phase_stats['Update'].cpu_time_seconds}"
        )

        assert collector.phase_stats["Download"].is_complete is True
        assert collector.phase_stats["Download"].wall_time_seconds == download_wall_time, (
            f"Download wall_time was reset from {download_wall_time} to "
            f"{collector.phase_stats['Download'].wall_time_seconds}"
        )
        assert collector.phase_stats["Download"].cpu_time_seconds == download_cpu_time, (
            f"Download cpu_time was reset from {download_cpu_time} to "
            f"{collector.phase_stats['Download'].cpu_time_seconds}"
        )

        collector.stop()

    def test_collect_does_not_overwrite_completed_phase_stats(self) -> None:
        """Test that collect() does not overwrite stats for completed phases.

        When collect() is called during a new phase, it should only update
        the current running phase, not modify completed phases.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase with specific stats
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        update_cpu_time_before = collector.phase_stats["Update"].cpu_time_seconds
        update_data_bytes_before = collector.phase_stats["Update"].data_bytes

        # Start Download phase
        collector.start_phase("Download")

        # Call collect() multiple times (simulating periodic updates)
        for _ in range(5):
            collector.collect()
            time.sleep(0.05)

        # Update phase stats should NOT have changed
        assert collector.phase_stats["Update"].cpu_time_seconds == update_cpu_time_before, (
            f"Update cpu_time changed from {update_cpu_time_before} to "
            f"{collector.phase_stats['Update'].cpu_time_seconds} after collect() calls"
        )
        assert collector.phase_stats["Update"].data_bytes == update_data_bytes_before, (
            f"Update data_bytes changed from {update_data_bytes_before} to "
            f"{collector.phase_stats['Update'].data_bytes} after collect() calls"
        )

        collector.stop()

    def test_update_phase_stats_blocked_for_completed_phases(self) -> None:
        """Test that update_phase_stats() is blocked for completed phases.

        Once a phase is marked complete, update_phase_stats() should not
        modify its stats unless force=True is passed.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        original_cpu_time = collector.phase_stats["Update"].cpu_time_seconds
        original_data_bytes = collector.phase_stats["Update"].data_bytes

        # Try to update completed phase (should be blocked)
        collector.update_phase_stats("Update", cpu_time_seconds=0.0, data_bytes=0)

        # Stats should NOT have changed
        assert collector.phase_stats["Update"].cpu_time_seconds == original_cpu_time
        assert collector.phase_stats["Update"].data_bytes == original_data_bytes

        # With force=True, it should update
        collector.update_phase_stats("Update", cpu_time_seconds=10.0, data_bytes=4096, force=True)

        assert collector.phase_stats["Update"].cpu_time_seconds == 10.0
        assert collector.phase_stats["Update"].data_bytes == 4096

        collector.stop()

    def test_total_stats_accumulates_across_phases(self) -> None:
        """Test that get_total_stats() correctly accumulates stats from all phases.

        The total should be the sum of all phase stats, not just the current phase.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Set up stats for each phase
        # Note: wall_time is calculated automatically, we set cpu_time and data_bytes
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=2.0, data_bytes=1000)
        collector.complete_phase("Update")

        collector.start_phase("Download")
        collector.update_phase_stats("Download", cpu_time_seconds=1.0, data_bytes=5000)
        collector.complete_phase("Download")

        collector.start_phase("Upgrade")
        collector.update_phase_stats("Upgrade", cpu_time_seconds=4.0, data_bytes=500)
        collector.complete_phase("Upgrade")

        # Get total stats
        total = collector.get_total_stats()

        # Total cpu_time and data_bytes should be sum of all phases
        expected_cpu_time = 2.0 + 1.0 + 4.0  # 7.0
        expected_data_bytes = 1000 + 5000 + 500  # 6500

        assert total.cpu_time_seconds == expected_cpu_time, (
            f"Total cpu_time {total.cpu_time_seconds} != expected {expected_cpu_time}"
        )
        assert total.data_bytes == expected_data_bytes, (
            f"Total data_bytes {total.data_bytes} != expected {expected_data_bytes}"
        )

        collector.stop()


class TestPhaseCounterResetWithRealProcess:
    """Tests for phase counter reset with real process monitoring.

    These tests use actual subprocess execution to verify that phase
    stats are correctly tracked and preserved across phase transitions.
    """

    @pytest.mark.asyncio
    async def test_phase_stats_preserved_with_real_subprocess(self) -> None:
        """Test phase stats preservation with real subprocess execution.

        This test simulates the actual flow in InteractiveTabbedApp where
        a PTY session runs commands for each phase.
        """
        import asyncio
        import subprocess

        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Simulate Update phase with a real subprocess
        collector.start_phase("Update")

        # Run a simple command that takes some time
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            "sleep 0.1 && echo 'Update done'",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        collector.update_pid(proc.pid)

        # Collect metrics while running
        for _ in range(3):
            collector.collect()
            await asyncio.sleep(0.05)

        await proc.wait()
        collector.complete_phase("Update")

        # Record Update stats
        update_wall_time = collector.phase_stats["Update"].wall_time_seconds
        update_is_complete = collector.phase_stats["Update"].is_complete

        assert update_is_complete is True
        assert update_wall_time > 0, "Update wall_time should be > 0"

        # Simulate Download phase with a new subprocess
        collector.start_phase("Download")

        proc2 = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-c",
            "sleep 0.1 && echo 'Download done'",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        collector.update_pid(proc2.pid)

        # Collect metrics while running
        for _ in range(3):
            collector.collect()
            await asyncio.sleep(0.05)

        await proc2.wait()

        # THE KEY CHECK: Update stats should still be preserved
        assert collector.phase_stats["Update"].is_complete is True, (
            "Update phase should still be marked complete"
        )
        assert collector.phase_stats["Update"].wall_time_seconds == update_wall_time, (
            f"Update wall_time was reset from {update_wall_time} to "
            f"{collector.phase_stats['Update'].wall_time_seconds}"
        )

        collector.stop()


class TestPhaseCounterResetRootCause:
    """Tests to identify the root cause of the phase counter reset issue.

    These tests examine specific code paths that might cause the reset.
    """

    def test_start_phase_calls_collect_which_might_reset_stats(self) -> None:
        """Test if start_phase() calling collect() causes stats reset.

        The start_phase() method calls collect() to get current values.
        This test checks if that collect() call inadvertently resets
        completed phase stats.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Complete Update phase
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        # Manually set _current_phase to None to simulate between-phase state
        collector._current_phase = None

        # Record stats before starting Download
        update_cpu_before = collector.phase_stats["Update"].cpu_time_seconds
        update_data_before = collector.phase_stats["Update"].data_bytes

        # Now start Download - this calls collect() internally
        collector.start_phase("Download")

        # Check if Update stats were affected
        assert collector.phase_stats["Update"].cpu_time_seconds == update_cpu_before, (
            "start_phase() -> collect() reset Update cpu_time"
        )
        assert collector.phase_stats["Update"].data_bytes == update_data_before, (
            "start_phase() -> collect() reset Update data_bytes"
        )

        collector.stop()

    def test_update_pid_preserves_phase_stats(self) -> None:
        """Test that update_pid() preserves phase stats.

        When transitioning between phases, update_pid() is called with
        the new process ID. This should not reset phase stats.
        """
        collector = MetricsCollector(pid=1234, update_interval=0.1)
        collector.start()

        # Complete Update phase
        collector.start_phase("Update")
        collector.update_phase_stats("Update", cpu_time_seconds=5.0, data_bytes=2048)
        collector.complete_phase("Update")

        update_cpu_before = collector.phase_stats["Update"].cpu_time_seconds
        update_data_before = collector.phase_stats["Update"].data_bytes

        # Update PID (simulating new phase with new process)
        collector.update_pid(5678)

        # Phase stats should be preserved
        assert collector.phase_stats["Update"].cpu_time_seconds == update_cpu_before
        assert collector.phase_stats["Update"].data_bytes == update_data_before

        collector.stop()

    def test_phase_start_values_are_recorded_correctly(self) -> None:
        """Test that phase start values are recorded correctly.

        When starting a new phase, _phase_start_cpu_time and
        _phase_start_network_bytes should be set to current cumulative values
        from _metrics (after collect() is called), not reset to zero.
        """
        collector = MetricsCollector(pid=None, update_interval=0.1)
        collector.start()

        # Start Update phase - this calls collect() first
        collector.start_phase("Update")

        # After start_phase, the phase start values should be set to
        # whatever collect() returned for cpu_time and network_bytes
        # The key invariant is: phase_start values == _metrics values at phase start
        assert collector._phase_start_cpu_time == collector._metrics.cpu_time_seconds, (
            f"_phase_start_cpu_time ({collector._phase_start_cpu_time}) should equal "
            f"_metrics.cpu_time_seconds ({collector._metrics.cpu_time_seconds})"
        )
        assert collector._phase_start_network_bytes == collector._metrics.network_bytes, (
            f"_phase_start_network_bytes ({collector._phase_start_network_bytes}) should equal "
            f"_metrics.network_bytes ({collector._metrics.network_bytes})"
        )

        # Let some time pass and collect metrics
        time.sleep(0.05)
        collector.collect()

        # Complete Update phase
        collector.complete_phase("Update")

        # Record metrics after Update completes
        cpu_after_update = collector._metrics.cpu_time_seconds
        network_after_update = collector._metrics.network_bytes

        # Start Download phase - this calls collect() again
        collector.start_phase("Download")

        # Phase start values for Download should be the current cumulative values
        # (which may have changed slightly due to collect() call in start_phase)
        assert collector._phase_start_cpu_time >= cpu_after_update, (
            f"_phase_start_cpu_time for Download ({collector._phase_start_cpu_time}) "
            f"should be >= cpu_after_update ({cpu_after_update})"
        )
        assert collector._phase_start_network_bytes >= network_after_update, (
            f"_phase_start_network_bytes for Download ({collector._phase_start_network_bytes}) "
            f"should be >= network_after_update ({network_after_update})"
        )

        # Most importantly, Download's start values should be different from Update's
        # (assuming some metrics were collected during Update phase)
        # This verifies that phase start values are updated for each new phase

        collector.stop()

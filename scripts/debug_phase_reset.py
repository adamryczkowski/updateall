#!/usr/bin/env python3
"""Debug script to investigate phase counter reset issue.

This script simulates the phase transition flow that happens in
InteractiveTabbedApp to identify where phase counters get reset.
"""

import sys
import os
import time

# Add the project packages to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "ui"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

from ui.phase_status_bar import MetricsCollector


def print_phase_stats(collector: MetricsCollector, label: str) -> None:
    """Print current phase stats for debugging."""
    print(f"\n=== {label} ===")
    for name, stats in collector.phase_stats.items():
        print(
            f"  {name}: wall={stats.wall_time_seconds:.2f}s, "
            f"cpu={stats.cpu_time_seconds:.2f}s, "
            f"data={stats.data_bytes}B, "
            f"complete={stats.is_complete}, "
            f"running={stats.is_running}"
        )
    print(f"  _current_phase: {collector._current_phase}")
    print(f"  _phase_start_cpu_time: {collector._phase_start_cpu_time:.2f}")
    print(f"  _phase_start_network_bytes: {collector._phase_start_network_bytes}")


def simulate_phase_transitions():
    """Simulate the phase transition flow from InteractiveTabbedApp."""
    print("Creating MetricsCollector...")
    collector = MetricsCollector(pid=None, update_interval=0.1)
    collector.start()

    print_phase_stats(collector, "Initial state")

    # Phase 1: Update
    print("\n>>> Starting Update phase...")
    collector.start_phase("Update")
    print_phase_stats(collector, "After start_phase('Update')")

    # Simulate some work
    time.sleep(0.1)
    collector.collect()
    collector.update_phase_stats("Update", cpu_time_seconds=2.0, data_bytes=1024)
    print_phase_stats(collector, "After Update work")

    # Complete Update
    print("\n>>> Completing Update phase...")
    collector.complete_phase("Update")
    print_phase_stats(collector, "After complete_phase('Update')")

    # Record Update stats for comparison
    update_wall = collector.phase_stats["Update"].wall_time_seconds
    update_cpu = collector.phase_stats["Update"].cpu_time_seconds
    update_data = collector.phase_stats["Update"].data_bytes
    print(
        f"\nRecorded Update stats: wall={update_wall:.2f}, cpu={update_cpu:.2f}, data={update_data}"
    )

    # Phase 2: Download
    print("\n>>> Starting Download phase...")
    # This is where the bug might occur - set a breakpoint here
    # To debug, uncomment the following lines:
    # import pdb
    # pdb.set_trace()  # BREAKPOINT
    collector.start_phase("Download")
    print_phase_stats(collector, "After start_phase('Download')")

    # Check if Update stats were preserved
    if collector.phase_stats["Update"].wall_time_seconds != update_wall:
        print(
            f"\n!!! BUG: Update wall_time changed from {update_wall:.2f} to "
            f"{collector.phase_stats['Update'].wall_time_seconds:.2f}"
        )
    if collector.phase_stats["Update"].cpu_time_seconds != update_cpu:
        print(
            f"\n!!! BUG: Update cpu_time changed from {update_cpu:.2f} to "
            f"{collector.phase_stats['Update'].cpu_time_seconds:.2f}"
        )
    if collector.phase_stats["Update"].data_bytes != update_data:
        print(
            f"\n!!! BUG: Update data_bytes changed from {update_data} to "
            f"{collector.phase_stats['Update'].data_bytes}"
        )

    # Simulate Download work
    time.sleep(0.1)
    collector.collect()
    collector.update_phase_stats("Download", cpu_time_seconds=1.0, data_bytes=5000)
    print_phase_stats(collector, "After Download work")

    # Complete Download
    print("\n>>> Completing Download phase...")
    collector.complete_phase("Download")
    print_phase_stats(collector, "After complete_phase('Download')")

    # Record Download stats
    download_wall = collector.phase_stats["Download"].wall_time_seconds
    download_cpu = collector.phase_stats["Download"].cpu_time_seconds
    download_data = collector.phase_stats["Download"].data_bytes

    # Phase 3: Upgrade
    print("\n>>> Starting Upgrade phase...")
    collector.start_phase("Upgrade")
    print_phase_stats(collector, "After start_phase('Upgrade')")

    # Final check - all previous phase stats should be preserved
    print("\n=== FINAL VERIFICATION ===")
    errors = []

    if collector.phase_stats["Update"].wall_time_seconds != update_wall:
        errors.append(
            f"Update wall_time: {update_wall:.2f} -> {collector.phase_stats['Update'].wall_time_seconds:.2f}"
        )
    if collector.phase_stats["Update"].cpu_time_seconds != update_cpu:
        errors.append(
            f"Update cpu_time: {update_cpu:.2f} -> {collector.phase_stats['Update'].cpu_time_seconds:.2f}"
        )
    if collector.phase_stats["Update"].data_bytes != update_data:
        errors.append(
            f"Update data_bytes: {update_data} -> {collector.phase_stats['Update'].data_bytes}"
        )

    if collector.phase_stats["Download"].wall_time_seconds != download_wall:
        errors.append(
            f"Download wall_time: {download_wall:.2f} -> {collector.phase_stats['Download'].wall_time_seconds:.2f}"
        )
    if collector.phase_stats["Download"].cpu_time_seconds != download_cpu:
        errors.append(
            f"Download cpu_time: {download_cpu:.2f} -> {collector.phase_stats['Download'].cpu_time_seconds:.2f}"
        )
    if collector.phase_stats["Download"].data_bytes != download_data:
        errors.append(
            f"Download data_bytes: {download_data} -> {collector.phase_stats['Download'].data_bytes}"
        )

    if errors:
        print("!!! BUGS FOUND:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("All phase stats preserved correctly!")

    # Get totals
    total = collector.get_total_stats()
    print(
        f"\nTotal stats: wall={total.wall_time_seconds:.2f}s, "
        f"cpu={total.cpu_time_seconds:.2f}s, data={total.data_bytes}B"
    )

    collector.stop()


if __name__ == "__main__":
    simulate_phase_transitions()

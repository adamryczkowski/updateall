"""Statistics calculator for update history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stats.history import HistoryStore


@dataclass
class UpdateStats:
    """Aggregate statistics for update runs."""

    total_runs: int
    successful_runs: int
    failed_runs: int
    timeout_runs: int
    skipped_runs: int
    total_packages_updated: int
    total_duration_seconds: float
    avg_duration_seconds: float
    success_rate: float
    period_days: int

    @property
    def avg_packages_per_run(self) -> float:
        """Average packages updated per run."""
        if self.total_runs == 0:
            return 0.0
        return self.total_packages_updated / self.total_runs


@dataclass
class PluginStats:
    """Statistics for a specific plugin."""

    plugin_name: str
    total_runs: int
    successful_runs: int
    failed_runs: int
    total_packages_updated: int
    avg_duration_seconds: float
    success_rate: float


class StatsCalculator:
    """Calculate statistics from update history.

    Provides aggregate statistics over configurable time periods.
    """

    def __init__(self, history_store: HistoryStore) -> None:
        """Initialize the calculator.

        Args:
            history_store: History store to read from.
        """
        self.history_store = history_store

    def calculate_stats(self, days: int = 30) -> UpdateStats:
        """Calculate aggregate statistics for a time period.

        Args:
            days: Number of days to include in statistics.

        Returns:
            UpdateStats with aggregate statistics.
        """
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=days)
        runs = self.history_store.get_runs_in_range(start, end)

        total_runs = len(runs)
        successful_runs = 0
        failed_runs = 0
        timeout_runs = 0
        skipped_runs = 0
        total_packages = 0
        total_duration = 0.0

        for run in runs:
            for plugin in run.get("plugins", []):
                status = plugin.get("status", "")
                if status == "success":
                    successful_runs += 1
                elif status == "failed":
                    failed_runs += 1
                elif status == "timeout":
                    timeout_runs += 1
                elif status == "skipped":
                    skipped_runs += 1

                total_packages += plugin.get("packages_updated", 0)

                # Calculate duration
                start_str = plugin.get("start_time")
                end_str = plugin.get("end_time")
                if start_str and end_str:
                    try:
                        start_time = datetime.fromisoformat(start_str)
                        end_time = datetime.fromisoformat(end_str)
                        total_duration += (end_time - start_time).total_seconds()
                    except ValueError:
                        pass

        plugin_count = successful_runs + failed_runs + timeout_runs + skipped_runs
        avg_duration = total_duration / plugin_count if plugin_count > 0 else 0.0
        success_rate = successful_runs / plugin_count if plugin_count > 0 else 0.0

        return UpdateStats(
            total_runs=total_runs,
            successful_runs=successful_runs,
            failed_runs=failed_runs,
            timeout_runs=timeout_runs,
            skipped_runs=skipped_runs,
            total_packages_updated=total_packages,
            total_duration_seconds=total_duration,
            avg_duration_seconds=avg_duration,
            success_rate=success_rate,
            period_days=days,
        )

    def calculate_plugin_stats(self, plugin_name: str, days: int = 30) -> PluginStats:
        """Calculate statistics for a specific plugin.

        Args:
            plugin_name: Name of the plugin.
            days: Number of days to include.

        Returns:
            PluginStats for the plugin.
        """
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=days)
        runs = self.history_store.get_runs_in_range(start, end)

        total_runs = 0
        successful_runs = 0
        failed_runs = 0
        total_packages = 0
        total_duration = 0.0

        for run in runs:
            for plugin in run.get("plugins", []):
                if plugin.get("name") != plugin_name:
                    continue

                total_runs += 1
                status = plugin.get("status", "")
                if status == "success":
                    successful_runs += 1
                elif status == "failed":
                    failed_runs += 1

                total_packages += plugin.get("packages_updated", 0)

                # Calculate duration
                start_str = plugin.get("start_time")
                end_str = plugin.get("end_time")
                if start_str and end_str:
                    try:
                        start_time = datetime.fromisoformat(start_str)
                        end_time = datetime.fromisoformat(end_str)
                        total_duration += (end_time - start_time).total_seconds()
                    except ValueError:
                        pass

        avg_duration = total_duration / total_runs if total_runs > 0 else 0.0
        success_rate = successful_runs / total_runs if total_runs > 0 else 0.0

        return PluginStats(
            plugin_name=plugin_name,
            total_runs=total_runs,
            successful_runs=successful_runs,
            failed_runs=failed_runs,
            total_packages_updated=total_packages,
            avg_duration_seconds=avg_duration,
            success_rate=success_rate,
        )

    def get_all_plugin_stats(self, days: int = 30) -> list[PluginStats]:
        """Get statistics for all plugins.

        Args:
            days: Number of days to include.

        Returns:
            List of PluginStats for each plugin.
        """
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=days)
        runs = self.history_store.get_runs_in_range(start, end)

        # Collect unique plugin names
        plugin_names: set[str] = set()
        for run in runs:
            for plugin in run.get("plugins", []):
                name = plugin.get("name")
                if name:
                    plugin_names.add(name)

        return [self.calculate_plugin_stats(name, days) for name in sorted(plugin_names)]

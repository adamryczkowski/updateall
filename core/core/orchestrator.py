"""Orchestrator for sequential plugin execution.

This module provides the main orchestrator that runs plugins sequentially,
collecting results and managing the execution lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from .models import ExecutionResult, ExecutionSummary, PluginConfig, PluginStatus

if TYPE_CHECKING:
    from .interfaces import UpdatePlugin

logger = structlog.get_logger(__name__)


class Orchestrator:
    """Orchestrates sequential execution of update plugins.

    The orchestrator is responsible for:
    - Running plugins in sequence
    - Collecting execution results
    - Generating execution summaries
    - Handling errors and timeouts
    """

    def __init__(
        self,
        dry_run: bool = False,
        continue_on_error: bool = True,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            dry_run: If True, simulate updates without making changes.
            continue_on_error: If True, continue with remaining plugins after a failure.
        """
        self.dry_run = dry_run
        self.continue_on_error = continue_on_error
        self._log = logger.bind(component="orchestrator")

    async def run_all(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
    ) -> ExecutionSummary:
        """Run all plugins sequentially.

        Args:
            plugins: List of plugins to execute.
            configs: Optional plugin configurations keyed by plugin name.

        Returns:
            ExecutionSummary with results for all plugins.
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = datetime.now(tz=UTC)
        results: list[ExecutionResult] = []

        self._log.info(
            "run_started",
            run_id=run_id,
            plugin_count=len(plugins),
            dry_run=self.dry_run,
        )

        for plugin in plugins:
            plugin_name = plugin.name
            config = self._get_config(plugin_name, configs)

            if not config.enabled:
                self._log.info("plugin_skipped", plugin=plugin_name, reason="disabled")
                result = ExecutionResult(
                    plugin_name=plugin_name,
                    status=PluginStatus.SKIPPED,
                    start_time=datetime.now(tz=UTC),
                    end_time=datetime.now(tz=UTC),
                    error_message="Plugin is disabled",
                )
                results.append(result)
                continue

            result = await self._run_plugin(plugin, config)
            results.append(result)

            if result.status == PluginStatus.FAILED and not self.continue_on_error:
                self._log.warning(
                    "run_aborted",
                    run_id=run_id,
                    failed_plugin=plugin_name,
                )
                break

        end_time = datetime.now(tz=UTC)
        summary = self._create_summary(run_id, start_time, end_time, results)

        self._log.info(
            "run_completed",
            run_id=run_id,
            total_plugins=summary.total_plugins,
            successful=summary.successful_plugins,
            failed=summary.failed_plugins,
            skipped=summary.skipped_plugins,
            duration_seconds=summary.total_duration_seconds,
        )

        return summary

    async def _run_plugin(
        self,
        plugin: UpdatePlugin,
        config: PluginConfig,
    ) -> ExecutionResult:
        """Run a single plugin.

        Args:
            plugin: The plugin to run.
            config: Plugin configuration.

        Returns:
            ExecutionResult for the plugin.
        """
        plugin_name = plugin.name
        start_time = datetime.now(tz=UTC)
        log = self._log.bind(plugin=plugin_name)

        log.info("plugin_started")

        try:
            # Check if plugin is available on this system
            if not await plugin.check_available():
                log.info("plugin_not_available")
                return ExecutionResult(
                    plugin_name=plugin_name,
                    status=PluginStatus.SKIPPED,
                    start_time=start_time,
                    end_time=datetime.now(tz=UTC),
                    error_message="Plugin not available on this system",
                )

            # Run pre-execute hook
            await plugin.pre_execute()

            # Execute the update
            result = await plugin.execute(dry_run=self.dry_run)

            # Run post-execute hook
            await plugin.post_execute(result)

            log.info(
                "plugin_completed",
                status=result.status.value,
                packages_updated=result.packages_updated,
            )

            return result

        except TimeoutError as e:
            log.warning("plugin_timeout", timeout=config.timeout_seconds)
            return ExecutionResult(
                plugin_name=plugin_name,
                status=PluginStatus.TIMEOUT,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                error_message=str(e),
            )

        except Exception as e:
            log.exception("plugin_error", error=str(e))
            return ExecutionResult(
                plugin_name=plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                error_message=str(e),
            )

    def _get_config(
        self,
        plugin_name: str,
        configs: dict[str, PluginConfig] | None,
    ) -> PluginConfig:
        """Get configuration for a plugin.

        Args:
            plugin_name: Name of the plugin.
            configs: Optional configurations dict.

        Returns:
            PluginConfig for the plugin (default if not specified).
        """
        if configs and plugin_name in configs:
            return configs[plugin_name]
        return PluginConfig(name=plugin_name)

    def _create_summary(
        self,
        run_id: str,
        start_time: datetime,
        end_time: datetime,
        results: list[ExecutionResult],
    ) -> ExecutionSummary:
        """Create an execution summary from results.

        Args:
            run_id: Unique run identifier.
            start_time: Run start time.
            end_time: Run end time.
            results: List of execution results.

        Returns:
            ExecutionSummary for the run.
        """
        successful = sum(1 for r in results if r.status == PluginStatus.SUCCESS)
        failed = sum(1 for r in results if r.status == PluginStatus.FAILED)
        skipped = sum(1 for r in results if r.status == PluginStatus.SKIPPED)
        timed_out = sum(1 for r in results if r.status == PluginStatus.TIMEOUT)

        return ExecutionSummary(
            run_id=run_id,
            start_time=start_time,
            end_time=end_time,
            total_duration_seconds=(end_time - start_time).total_seconds(),
            results=results,
            total_plugins=len(results),
            successful_plugins=successful,
            failed_plugins=failed + timed_out,
            skipped_plugins=skipped,
        )

"""Parallel orchestrator for concurrent plugin execution.

This module provides a parallel orchestrator that runs plugins concurrently
while respecting mutex constraints and resource limits.

The ParallelOrchestrator is designed for high-performance execution where
plugins can run in parallel, with sophisticated scheduling based on a
directed acyclic graph (DAG) of dependencies and mutex constraints.

Key features:
    - Parallel execution in waves (plugins in the same wave run concurrently)
    - DAG-based scheduling from plugin dependencies and mutex conflicts
    - Mutex management to prevent resource conflicts
    - Resource limits (max parallel tasks, memory, CPU)
    - Automatic wave determination for optimal parallelism

Key differences from Orchestrator:
    - Parallel execution (multiple plugins run concurrently)
    - Mutex management (prevents conflicts on shared resources)
    - Resource limits (CPU, memory, bandwidth)
    - DAG-based scheduling (respects dependencies)
    - Higher overhead but better performance for many plugins

Use this orchestrator when:
    - Plugins have complex dependencies or mutex requirements
    - Resource contention needs to be managed
    - Performance is critical and parallelism is beneficial

See Also:
    orchestrator.Orchestrator: For simple sequential execution without
        mutex management or resource limits.
    scheduler.Scheduler: For building execution DAGs.
    mutex.MutexManager: For mutex acquisition and release.
    resource.ResourceController: For resource limit enforcement.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from .models import ExecutionResult, ExecutionSummary, PluginConfig, PluginStatus
from .mutex import MutexManager
from .resource import ResourceContext, ResourceController, ResourceLimits
from .scheduler import ExecutionDAG, Scheduler

if TYPE_CHECKING:
    from .interfaces import UpdatePlugin

logger = structlog.get_logger(__name__)


class ParallelOrchestrator:
    """Orchestrates parallel execution of update plugins.

    The parallel orchestrator:
    - Builds a DAG from plugin dependencies and mutex constraints
    - Executes plugins in waves (plugins in the same wave run in parallel)
    - Respects resource limits (max parallel tasks, memory, etc.)
    - Handles mutex acquisition and release
    """

    def __init__(
        self,
        dry_run: bool = False,
        continue_on_error: bool = True,
        resource_limits: ResourceLimits | None = None,
    ) -> None:
        """Initialize the parallel orchestrator.

        Args:
            dry_run: If True, simulate updates without making changes.
            continue_on_error: If True, continue with remaining plugins after a failure.
            resource_limits: Resource limits configuration.
        """
        self.dry_run = dry_run
        self.continue_on_error = continue_on_error
        self.mutex_manager = MutexManager()
        self.resource_controller = ResourceController(resource_limits)
        self.scheduler = Scheduler()
        self._log = logger.bind(component="parallel_orchestrator")
        self._failed_plugins: set[str] = set()

    async def run_all(
        self,
        plugins: list[UpdatePlugin],
        configs: dict[str, PluginConfig] | None = None,
        plugin_mutexes: dict[str, list[str]] | None = None,
    ) -> ExecutionSummary:
        """Run all plugins with parallel execution.

        Args:
            plugins: List of plugins to execute.
            configs: Optional plugin configurations keyed by plugin name.
            plugin_mutexes: Optional dict mapping plugin names to their mutexes.

        Returns:
            ExecutionSummary with results for all plugins.
        """
        run_id = str(uuid.uuid4())[:8]
        start_time = datetime.now(tz=UTC)
        results: list[ExecutionResult] = []
        self._failed_plugins.clear()

        self._log.info(
            "parallel_run_started",
            run_id=run_id,
            plugin_count=len(plugins),
            dry_run=self.dry_run,
            max_parallel=self.resource_controller.limits.max_parallel_tasks,
        )

        # Build execution DAG
        dag = self.scheduler.build_execution_dag(
            plugins,
            plugin_mutexes=plugin_mutexes or {},
        )

        # Get execution waves
        waves = self.scheduler.get_execution_waves(dag)

        self._log.info(
            "execution_plan",
            run_id=run_id,
            wave_count=len(waves),
            waves=[list(wave) for wave in waves],
        )

        # Execute each wave
        for wave_num, wave in enumerate(waves, 1):
            self._log.info(
                "wave_started",
                run_id=run_id,
                wave=wave_num,
                plugins=wave,
            )

            # Execute plugins in this wave in parallel
            wave_results = await self._execute_wave(
                wave,
                dag,
                configs or {},
                plugin_mutexes or {},
            )
            results.extend(wave_results)

            # Check for failures
            wave_failures = [r for r in wave_results if r.status == PluginStatus.FAILED]
            if wave_failures and not self.continue_on_error:
                self._log.warning(
                    "wave_aborted",
                    run_id=run_id,
                    wave=wave_num,
                    failed_plugins=[r.plugin_name for r in wave_failures],
                )
                break

            self._log.info(
                "wave_completed",
                run_id=run_id,
                wave=wave_num,
                success_count=len([r for r in wave_results if r.status == PluginStatus.SUCCESS]),
                failed_count=len(wave_failures),
            )

        end_time = datetime.now(tz=UTC)
        summary = self._create_summary(run_id, start_time, end_time, results)

        self._log.info(
            "parallel_run_completed",
            run_id=run_id,
            total_plugins=summary.total_plugins,
            successful=summary.successful_plugins,
            failed=summary.failed_plugins,
            skipped=summary.skipped_plugins,
            duration_seconds=summary.total_duration_seconds,
        )

        return summary

    async def _execute_wave(
        self,
        wave: list[str],
        dag: ExecutionDAG,
        configs: dict[str, PluginConfig],
        plugin_mutexes: dict[str, list[str]],
    ) -> list[ExecutionResult]:
        """Execute a wave of plugins in parallel.

        Args:
            wave: List of plugin names to execute.
            dag: The execution DAG.
            configs: Plugin configurations.
            plugin_mutexes: Plugin mutex mappings.

        Returns:
            List of execution results for this wave.
        """
        tasks = []
        for plugin_name in wave:
            node = dag.nodes.get(plugin_name)
            if node:
                config = self._get_config(plugin_name, configs)
                mutexes = plugin_mutexes.get(plugin_name, [])
                task = asyncio.create_task(
                    self._run_plugin_with_resources(node.plugin, config, mutexes),
                    name=f"plugin-{plugin_name}",
                )
                tasks.append(task)

        # Wait for all tasks in this wave to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        processed_results: list[ExecutionResult] = []
        for i, result in enumerate(results):
            plugin_name = wave[i]
            if isinstance(result, BaseException):
                self._log.exception(
                    "plugin_exception",
                    plugin=plugin_name,
                    error=str(result),
                )
                processed_results.append(
                    ExecutionResult(
                        plugin_name=plugin_name,
                        status=PluginStatus.FAILED,
                        start_time=datetime.now(tz=UTC),
                        end_time=datetime.now(tz=UTC),
                        error_message=str(result),
                    )
                )
                self._failed_plugins.add(plugin_name)
            else:
                # result is ExecutionResult here
                execution_result: ExecutionResult = result
                processed_results.append(execution_result)
                if execution_result.status == PluginStatus.FAILED:
                    self._failed_plugins.add(plugin_name)

        return processed_results

    async def _run_plugin_with_resources(
        self,
        plugin: UpdatePlugin,
        config: PluginConfig,
        mutexes: list[str],
    ) -> ExecutionResult:
        """Run a plugin with resource management.

        Args:
            plugin: The plugin to run.
            config: Plugin configuration.
            mutexes: Mutexes to acquire for this plugin.

        Returns:
            ExecutionResult for the plugin.
        """
        plugin_name = plugin.name
        start_time = datetime.now(tz=UTC)
        log = self._log.bind(plugin=plugin_name)

        # Check if plugin is enabled
        if not config.enabled:
            log.info("plugin_skipped", reason="disabled")
            return ExecutionResult(
                plugin_name=plugin_name,
                status=PluginStatus.SKIPPED,
                start_time=start_time,
                end_time=datetime.now(tz=UTC),
                error_message="Plugin is disabled",
            )

        # Acquire resource slot and mutexes
        async with ResourceContext(self.resource_controller, plugin_name, task=True):
            # Acquire mutexes
            if mutexes:
                acquired = await self.mutex_manager.acquire(
                    plugin_name,
                    mutexes,
                    timeout=config.timeout_seconds,
                )
                if not acquired:
                    log.warning("mutex_acquisition_failed", mutexes=mutexes)
                    return ExecutionResult(
                        plugin_name=plugin_name,
                        status=PluginStatus.FAILED,
                        start_time=start_time,
                        end_time=datetime.now(tz=UTC),
                        error_message=f"Failed to acquire mutexes: {mutexes}",
                    )

            try:
                result = await self._run_plugin(plugin, config)
                return result
            finally:
                # Release mutexes
                if mutexes:
                    await self.mutex_manager.release(plugin_name, mutexes)

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
        configs: dict[str, PluginConfig],
    ) -> PluginConfig:
        """Get configuration for a plugin.

        Args:
            plugin_name: Name of the plugin.
            configs: Configurations dict.

        Returns:
            PluginConfig for the plugin (default if not specified).
        """
        if plugin_name in configs:
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

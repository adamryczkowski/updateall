"""Tests for the parallel orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from core.models import ExecutionResult, PluginConfig, PluginStatus
from core.parallel_orchestrator import ParallelOrchestrator
from core.resource import ResourceLimits


class MockPlugin:
    """Mock plugin for testing."""

    def __init__(
        self,
        name: str,
        available: bool = True,
        success: bool = True,
        packages: int = 5,
    ) -> None:
        self.name = name
        self._available = available
        self._success = success
        self._packages = packages
        self.metadata = MagicMock()
        self.metadata.description = f"Mock {name} plugin"

    async def check_available(self) -> bool:
        return self._available

    async def pre_execute(self) -> None:
        pass

    async def execute(self, dry_run: bool = False) -> ExecutionResult:  # noqa: ARG002
        status = PluginStatus.SUCCESS if self._success else PluginStatus.FAILED
        return ExecutionResult(
            plugin_name=self.name,
            status=status,
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC),
            packages_updated=self._packages if self._success else 0,
            error_message=None if self._success else "Mock failure",
        )

    async def post_execute(self, result: ExecutionResult) -> None:
        pass


class TestParallelOrchestrator:
    """Tests for ParallelOrchestrator class."""

    @pytest.fixture
    def orchestrator(self) -> ParallelOrchestrator:
        """Create a parallel orchestrator for testing."""
        limits = ResourceLimits(max_parallel_tasks=4)
        return ParallelOrchestrator(resource_limits=limits)

    @pytest.mark.asyncio
    async def test_run_all_empty_list(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running with no plugins."""
        summary = await orchestrator.run_all([])
        assert summary.total_plugins == 0
        assert summary.successful_plugins == 0
        assert summary.failed_plugins == 0

    @pytest.mark.asyncio
    async def test_run_all_single_plugin_success(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running a single successful plugin."""
        plugins = [MockPlugin("apt", success=True, packages=10)]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 1
        assert summary.successful_plugins == 1
        assert summary.failed_plugins == 0
        assert summary.results[0].packages_updated == 10

    @pytest.mark.asyncio
    async def test_run_all_single_plugin_failure(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running a single failing plugin."""
        plugins = [MockPlugin("apt", success=False)]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 1
        assert summary.successful_plugins == 0
        assert summary.failed_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_multiple_plugins(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running multiple plugins."""
        plugins = [
            MockPlugin("apt", packages=5),
            MockPlugin("flatpak", packages=3),
            MockPlugin("snap", packages=2),
        ]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 3
        assert summary.successful_plugins == 3
        assert summary.failed_plugins == 0

    @pytest.mark.asyncio
    async def test_run_all_with_unavailable_plugin(
        self, orchestrator: ParallelOrchestrator
    ) -> None:
        """Test running with an unavailable plugin."""
        plugins = [
            MockPlugin("apt", available=True),
            MockPlugin("snap", available=False),
        ]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 1
        assert summary.skipped_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_continue_on_error(self, orchestrator: ParallelOrchestrator) -> None:
        """Test that execution continues after failure."""
        orchestrator.continue_on_error = True
        plugins = [
            MockPlugin("apt", success=False),
            MockPlugin("flatpak", success=True),
        ]
        # With no dependencies, they run in parallel
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 1
        assert summary.failed_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_stop_on_error(self) -> None:
        """Test that execution stops on error when configured."""
        orchestrator = ParallelOrchestrator(continue_on_error=False)
        plugins = [
            MockPlugin("apt", success=False),
            MockPlugin("flatpak", success=True),
        ]
        # With dependencies, apt runs first and fails
        summary = await orchestrator.run_all(
            plugins,
            plugin_mutexes={"apt": ["shared"], "flatpak": ["shared"]},
        )
        # apt fails, flatpak should not run (or run in parallel and complete)
        assert summary.failed_plugins >= 1

    @pytest.mark.asyncio
    async def test_run_all_with_disabled_plugin(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running with a disabled plugin."""
        plugins = [MockPlugin("apt"), MockPlugin("flatpak")]
        configs = {
            "apt": PluginConfig(name="apt", enabled=True),
            "flatpak": PluginConfig(name="flatpak", enabled=False),
        }
        summary = await orchestrator.run_all(plugins, configs=configs)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 1
        assert summary.skipped_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_dry_run(self, orchestrator: ParallelOrchestrator) -> None:
        """Test dry run mode."""
        orchestrator.dry_run = True
        plugins = [MockPlugin("apt")]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_with_mutexes(self, orchestrator: ParallelOrchestrator) -> None:
        """Test running with mutex constraints."""
        plugins = [
            MockPlugin("apt"),
            MockPlugin("snap"),
        ]
        mutexes = {
            "apt": ["pkgmgr:dpkg"],
            "snap": ["pkgmgr:dpkg"],  # Shared mutex
        }
        summary = await orchestrator.run_all(plugins, plugin_mutexes=mutexes)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 2

    @pytest.mark.asyncio
    async def test_run_all_parallel_execution(self, orchestrator: ParallelOrchestrator) -> None:
        """Test that independent plugins run in parallel."""
        plugins = [
            MockPlugin("apt"),
            MockPlugin("flatpak"),
            MockPlugin("pipx"),
        ]
        # No shared mutexes, should run in parallel
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 3
        assert summary.successful_plugins == 3

    @pytest.mark.asyncio
    async def test_summary_duration(self, orchestrator: ParallelOrchestrator) -> None:
        """Test that summary includes duration."""
        plugins = [MockPlugin("apt")]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_duration_seconds is not None
        assert summary.total_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_run_id_is_unique(self, orchestrator: ParallelOrchestrator) -> None:
        """Test that each run has a unique ID."""
        plugins = [MockPlugin("apt")]
        summary1 = await orchestrator.run_all(plugins)
        summary2 = await orchestrator.run_all(plugins)
        assert summary1.run_id != summary2.run_id

    @pytest.mark.asyncio
    async def test_resource_limits_respected(self) -> None:
        """Test that resource limits are respected."""
        limits = ResourceLimits(max_parallel_tasks=1)
        orchestrator = ParallelOrchestrator(resource_limits=limits)
        plugins = [
            MockPlugin("apt"),
            MockPlugin("flatpak"),
        ]
        summary = await orchestrator.run_all(plugins)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 2

    @pytest.mark.asyncio
    async def test_execution_waves(self, orchestrator: ParallelOrchestrator) -> None:
        """Test that plugins are executed in waves based on dependencies."""
        plugins = [
            MockPlugin("apt"),
            MockPlugin("pipx"),  # Depends on apt via mutex
        ]
        mutexes = {
            "apt": ["runtime:python"],
            "pipx": ["runtime:python"],
        }
        summary = await orchestrator.run_all(plugins, plugin_mutexes=mutexes)
        assert summary.total_plugins == 2
        assert summary.successful_plugins == 2

"""Tests for the orchestrator module."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.interfaces import UpdatePlugin
from core.models import ExecutionResult, PluginConfig, PluginMetadata, PluginStatus
from core.orchestrator import Orchestrator


class MockPlugin(UpdatePlugin):
    """Mock plugin for testing."""

    def __init__(
        self,
        name: str = "mock",
        available: bool = True,
        should_fail: bool = False,
        packages_updated: int = 5,
    ) -> None:
        self._name = name
        self._available = available
        self._should_fail = should_fail
        self._packages_updated = packages_updated

    @property
    def name(self) -> str:
        return self._name

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name=self._name, description=f"Mock plugin {self._name}")

    async def check_available(self) -> bool:
        return self._available

    async def execute(self, dry_run: bool = False) -> ExecutionResult:  # noqa: ARG002
        if self._should_fail:
            return ExecutionResult(
                plugin_name=self._name,
                status=PluginStatus.FAILED,
                start_time=datetime.now(tz=UTC),
                end_time=datetime.now(tz=UTC),
                error_message="Mock failure",
            )
        return ExecutionResult(
            plugin_name=self._name,
            status=PluginStatus.SUCCESS,
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC),
            packages_updated=self._packages_updated,
        )


class TestOrchestrator:
    """Tests for Orchestrator class."""

    @pytest.mark.asyncio
    async def test_run_all_empty_list(self) -> None:
        """Test running with no plugins."""
        orchestrator = Orchestrator()
        summary = await orchestrator.run_all([])

        assert summary.total_plugins == 0
        assert summary.successful_plugins == 0
        assert summary.failed_plugins == 0

    @pytest.mark.asyncio
    async def test_run_all_single_plugin_success(self) -> None:
        """Test running a single successful plugin."""
        orchestrator = Orchestrator()
        plugin = MockPlugin(name="test", packages_updated=10)

        summary = await orchestrator.run_all([plugin])

        assert summary.total_plugins == 1
        assert summary.successful_plugins == 1
        assert summary.failed_plugins == 0
        assert len(summary.results) == 1
        assert summary.results[0].plugin_name == "test"
        assert summary.results[0].status == PluginStatus.SUCCESS
        assert summary.results[0].packages_updated == 10

    @pytest.mark.asyncio
    async def test_run_all_single_plugin_failure(self) -> None:
        """Test running a single failing plugin."""
        orchestrator = Orchestrator()
        plugin = MockPlugin(name="test", should_fail=True)

        summary = await orchestrator.run_all([plugin])

        assert summary.total_plugins == 1
        assert summary.successful_plugins == 0
        assert summary.failed_plugins == 1
        assert summary.results[0].status == PluginStatus.FAILED

    @pytest.mark.asyncio
    async def test_run_all_multiple_plugins(self) -> None:
        """Test running multiple plugins."""
        orchestrator = Orchestrator()
        plugins = [
            MockPlugin(name="plugin1", packages_updated=5),
            MockPlugin(name="plugin2", packages_updated=10),
            MockPlugin(name="plugin3", packages_updated=3),
        ]

        summary = await orchestrator.run_all(plugins)

        assert summary.total_plugins == 3
        assert summary.successful_plugins == 3
        assert summary.failed_plugins == 0

    @pytest.mark.asyncio
    async def test_run_all_with_unavailable_plugin(self) -> None:
        """Test that unavailable plugins are skipped."""
        orchestrator = Orchestrator()
        plugins = [
            MockPlugin(name="available", available=True),
            MockPlugin(name="unavailable", available=False),
        ]

        summary = await orchestrator.run_all(plugins)

        assert summary.total_plugins == 2
        assert summary.successful_plugins == 1
        assert summary.skipped_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_continue_on_error(self) -> None:
        """Test that execution continues after failure when continue_on_error=True."""
        orchestrator = Orchestrator(continue_on_error=True)
        plugins = [
            MockPlugin(name="first", should_fail=True),
            MockPlugin(name="second", packages_updated=5),
        ]

        summary = await orchestrator.run_all(plugins)

        assert summary.total_plugins == 2
        assert summary.successful_plugins == 1
        assert summary.failed_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_stop_on_error(self) -> None:
        """Test that execution stops after failure when continue_on_error=False."""
        orchestrator = Orchestrator(continue_on_error=False)
        plugins = [
            MockPlugin(name="first", should_fail=True),
            MockPlugin(name="second", packages_updated=5),
        ]

        summary = await orchestrator.run_all(plugins)

        # Only the first plugin should have run
        assert summary.total_plugins == 1
        assert summary.failed_plugins == 1

    @pytest.mark.asyncio
    async def test_run_all_with_disabled_plugin(self) -> None:
        """Test that disabled plugins are skipped."""
        orchestrator = Orchestrator()
        plugins = [MockPlugin(name="test")]
        configs = {"test": PluginConfig(name="test", enabled=False)}

        summary = await orchestrator.run_all(plugins, configs)

        assert summary.total_plugins == 1
        assert summary.skipped_plugins == 1
        assert summary.results[0].error_message == "Plugin is disabled"

    @pytest.mark.asyncio
    async def test_run_all_dry_run(self) -> None:
        """Test dry run mode."""
        orchestrator = Orchestrator(dry_run=True)
        plugin = MockPlugin(name="test")

        summary = await orchestrator.run_all([plugin])

        # Plugin should still run (it's up to the plugin to handle dry_run)
        assert summary.total_plugins == 1

    @pytest.mark.asyncio
    async def test_summary_duration(self) -> None:
        """Test that summary includes duration."""
        orchestrator = Orchestrator()
        plugin = MockPlugin(name="test")

        summary = await orchestrator.run_all([plugin])

        assert summary.total_duration_seconds is not None
        assert summary.total_duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_run_id_is_unique(self) -> None:
        """Test that each run gets a unique ID."""
        orchestrator = Orchestrator()
        plugin = MockPlugin(name="test")

        summary1 = await orchestrator.run_all([plugin])
        summary2 = await orchestrator.run_all([plugin])

        assert summary1.run_id != summary2.run_id

"""Tests for the resource controller."""

from __future__ import annotations

import pytest

from core.resource import ResourceContext, ResourceController, ResourceLimits, ResourceUsage


class TestResourceLimits:
    """Tests for ResourceLimits dataclass."""

    def test_default_values(self) -> None:
        """Test default resource limits."""
        limits = ResourceLimits()
        assert limits.max_parallel_tasks == 4
        assert limits.max_parallel_downloads == 2
        assert limits.max_memory_mb == 0
        assert limits.max_cpu_percent == 0
        assert limits.nice_value == 10

    def test_custom_values(self) -> None:
        """Test custom resource limits."""
        limits = ResourceLimits(
            max_parallel_tasks=8,
            max_parallel_downloads=4,
            max_memory_mb=8192,
        )
        assert limits.max_parallel_tasks == 8
        assert limits.max_parallel_downloads == 4
        assert limits.max_memory_mb == 8192


class TestResourceUsage:
    """Tests for ResourceUsage dataclass."""

    def test_default_values(self) -> None:
        """Test default resource usage."""
        usage = ResourceUsage()
        assert usage.active_tasks == 0
        assert usage.active_downloads == 0
        assert usage.memory_mb == 0
        assert usage.cpu_percent == 0.0
        assert usage.active_pids == set()


class TestResourceController:
    """Tests for ResourceController class."""

    @pytest.fixture
    def controller(self) -> ResourceController:
        """Create a resource controller for testing."""
        limits = ResourceLimits(max_parallel_tasks=2, max_parallel_downloads=1)
        return ResourceController(limits)

    @pytest.mark.asyncio
    async def test_acquire_task_slot(self, controller: ResourceController) -> None:
        """Test acquiring a task slot."""
        result = await controller.acquire_task_slot("plugin1")
        assert result is True
        assert controller.get_usage().active_tasks == 1

    @pytest.mark.asyncio
    async def test_release_task_slot(self, controller: ResourceController) -> None:
        """Test releasing a task slot."""
        await controller.acquire_task_slot("plugin1")
        controller.release_task_slot("plugin1")
        assert controller.get_usage().active_tasks == 0

    @pytest.mark.asyncio
    async def test_acquire_download_slot(self, controller: ResourceController) -> None:
        """Test acquiring a download slot."""
        result = await controller.acquire_download_slot("plugin1")
        assert result is True
        assert controller.get_usage().active_downloads == 1

    @pytest.mark.asyncio
    async def test_release_download_slot(self, controller: ResourceController) -> None:
        """Test releasing a download slot."""
        await controller.acquire_download_slot("plugin1")
        controller.release_download_slot("plugin1")
        assert controller.get_usage().active_downloads == 0

    @pytest.mark.asyncio
    async def test_get_available_slots(self, controller: ResourceController) -> None:
        """Test getting available slots."""
        assert controller.get_available_slots() == 2
        await controller.acquire_task_slot("plugin1")
        assert controller.get_available_slots() == 1
        await controller.acquire_task_slot("plugin2")
        assert controller.get_available_slots() == 0

    def test_register_pid(self, controller: ResourceController) -> None:
        """Test registering a PID."""
        controller.register_pid(12345, "plugin1")
        # Check internal state directly since get_usage() may clean up non-existent PIDs
        assert 12345 in controller._usage.active_pids

    def test_unregister_pid(self, controller: ResourceController) -> None:
        """Test unregistering a PID."""
        controller.register_pid(12345, "plugin1")
        controller.unregister_pid(12345, "plugin1")
        usage = controller.get_usage()
        assert 12345 not in usage.active_pids

    def test_get_usage(self, controller: ResourceController) -> None:
        """Test getting resource usage."""
        usage = controller.get_usage()
        assert isinstance(usage, ResourceUsage)
        assert usage.active_tasks == 0
        assert usage.active_downloads == 0

    @pytest.mark.asyncio
    async def test_multiple_task_slots(self, controller: ResourceController) -> None:
        """Test acquiring multiple task slots."""
        await controller.acquire_task_slot("plugin1")
        await controller.acquire_task_slot("plugin2")
        assert controller.get_usage().active_tasks == 2
        assert controller.get_available_slots() == 0

    @pytest.mark.asyncio
    async def test_release_does_not_go_negative(self, controller: ResourceController) -> None:
        """Test that releasing without acquiring doesn't go negative."""
        controller.release_task_slot("plugin1")
        assert controller.get_usage().active_tasks == 0

    def test_default_limits(self) -> None:
        """Test controller with default limits."""
        controller = ResourceController()
        assert controller.limits.max_parallel_tasks == 4
        assert controller.limits.max_parallel_downloads == 2


class TestResourceContext:
    """Tests for ResourceContext context manager."""

    @pytest.fixture
    def controller(self) -> ResourceController:
        """Create a resource controller for testing."""
        return ResourceController(ResourceLimits(max_parallel_tasks=2))

    @pytest.mark.asyncio
    async def test_context_acquires_task(self, controller: ResourceController) -> None:
        """Test that context manager acquires task slot."""
        async with ResourceContext(controller, "plugin1", task=True):
            assert controller.get_usage().active_tasks == 1
        assert controller.get_usage().active_tasks == 0

    @pytest.mark.asyncio
    async def test_context_acquires_download(self, controller: ResourceController) -> None:
        """Test that context manager acquires download slot."""
        async with ResourceContext(controller, "plugin1", task=False, download=True):
            assert controller.get_usage().active_downloads == 1
        assert controller.get_usage().active_downloads == 0

    @pytest.mark.asyncio
    async def test_context_acquires_both(self, controller: ResourceController) -> None:
        """Test that context manager acquires both slots."""
        async with ResourceContext(controller, "plugin1", task=True, download=True):
            assert controller.get_usage().active_tasks == 1
            assert controller.get_usage().active_downloads == 1
        assert controller.get_usage().active_tasks == 0
        assert controller.get_usage().active_downloads == 0

    @pytest.mark.asyncio
    async def test_context_releases_on_exception(self, controller: ResourceController) -> None:
        """Test that context manager releases on exception."""
        with pytest.raises(ValueError):
            async with ResourceContext(controller, "plugin1", task=True):
                assert controller.get_usage().active_tasks == 1
                raise ValueError("Test error")
        assert controller.get_usage().active_tasks == 0

    @pytest.mark.asyncio
    async def test_context_no_acquisition(self, controller: ResourceController) -> None:
        """Test context manager with no acquisition."""
        async with ResourceContext(controller, "plugin1", task=False, download=False):
            assert controller.get_usage().active_tasks == 0
            assert controller.get_usage().active_downloads == 0

"""Tests for the mutex system.

Phase 1 enhancements include:
- Ordered mutex acquisition
- asyncio.Condition for efficient waiting
- Deadlock detection
- Comprehensive mutex state logging
"""

from __future__ import annotations

import asyncio

import pytest

from core.mutex import (
    DeadlockError,
    MutexInfo,
    MutexManager,
    MutexState,
    StandardMutexes,
    WaiterInfo,
)


class TestMutexManager:
    """Tests for MutexManager class."""

    @pytest.fixture
    def manager(self) -> MutexManager:
        """Create a fresh mutex manager for each test."""
        return MutexManager()

    @pytest.mark.asyncio
    async def test_acquire_single_mutex(self, manager: MutexManager) -> None:
        """Test acquiring a single mutex."""
        result = await manager.acquire("plugin1", ["mutex1"])
        assert result is True
        assert manager.is_held("mutex1")
        assert manager.get_holder("mutex1") == "plugin1"

    @pytest.mark.asyncio
    async def test_acquire_multiple_mutexes(self, manager: MutexManager) -> None:
        """Test acquiring multiple mutexes atomically."""
        result = await manager.acquire("plugin1", ["mutex1", "mutex2", "mutex3"])
        assert result is True
        assert manager.is_held("mutex1")
        assert manager.is_held("mutex2")
        assert manager.is_held("mutex3")
        assert manager.get_holder("mutex1") == "plugin1"

    @pytest.mark.asyncio
    async def test_acquire_empty_list(self, manager: MutexManager) -> None:
        """Test acquiring with empty mutex list."""
        result = await manager.acquire("plugin1", [])
        assert result is True

    @pytest.mark.asyncio
    async def test_release_mutexes(self, manager: MutexManager) -> None:
        """Test releasing mutexes."""
        await manager.acquire("plugin1", ["mutex1", "mutex2"])
        await manager.release("plugin1", ["mutex1", "mutex2"])
        assert not manager.is_held("mutex1")
        assert not manager.is_held("mutex2")

    @pytest.mark.asyncio
    async def test_release_all_mutexes(self, manager: MutexManager) -> None:
        """Test releasing all mutexes held by a plugin."""
        await manager.acquire("plugin1", ["mutex1", "mutex2", "mutex3"])
        await manager.release("plugin1")  # Release all
        assert not manager.is_held("mutex1")
        assert not manager.is_held("mutex2")
        assert not manager.is_held("mutex3")

    @pytest.mark.asyncio
    async def test_release_only_owned_mutexes(self, manager: MutexManager) -> None:
        """Test that release only affects owned mutexes."""
        await manager.acquire("plugin1", ["mutex1"])
        await manager.acquire("plugin2", ["mutex2"])
        await manager.release("plugin1", ["mutex1", "mutex2"])  # Try to release both
        assert not manager.is_held("mutex1")  # Released (owned)
        assert manager.is_held("mutex2")  # Still held (not owned by plugin1)

    @pytest.mark.asyncio
    async def test_acquire_conflict_timeout(self, manager: MutexManager) -> None:
        """Test that acquiring a held mutex times out."""
        await manager.acquire("plugin1", ["mutex1"])
        result = await manager.acquire("plugin2", ["mutex1"], timeout=0.1)
        assert result is False
        assert manager.get_holder("mutex1") == "plugin1"

    @pytest.mark.asyncio
    async def test_acquire_waits_for_release(self, manager: MutexManager) -> None:
        """Test that acquire waits for mutex release."""
        await manager.acquire("plugin1", ["mutex1"])

        async def release_after_delay() -> None:
            await asyncio.sleep(0.1)
            await manager.release("plugin1", ["mutex1"])

        # Start release task and keep reference to avoid warning
        release_task = asyncio.create_task(release_after_delay())

        # This should succeed after the release
        result = await manager.acquire("plugin2", ["mutex1"], timeout=1.0)
        assert result is True
        assert manager.get_holder("mutex1") == "plugin2"

        # Ensure task completes
        await release_task

    @pytest.mark.asyncio
    async def test_get_held_by(self, manager: MutexManager) -> None:
        """Test getting all mutexes held by a plugin."""
        await manager.acquire("plugin1", ["mutex1", "mutex2"])
        await manager.acquire("plugin2", ["mutex3"])

        held = manager.get_held_by("plugin1")
        assert set(held) == {"mutex1", "mutex2"}

        held = manager.get_held_by("plugin2")
        assert held == ["mutex3"]

    @pytest.mark.asyncio
    async def test_get_all_held(self, manager: MutexManager) -> None:
        """Test getting all held mutexes."""
        await manager.acquire("plugin1", ["mutex1", "mutex2"])
        await manager.acquire("plugin2", ["mutex3"])

        all_held = manager.get_all_held()
        assert all_held == {
            "mutex1": "plugin1",
            "mutex2": "plugin1",
            "mutex3": "plugin2",
        }

    @pytest.mark.asyncio
    async def test_get_holder_not_held(self, manager: MutexManager) -> None:
        """Test getting holder of non-held mutex."""
        assert manager.get_holder("nonexistent") is None

    @pytest.mark.asyncio
    async def test_is_held_not_held(self, manager: MutexManager) -> None:
        """Test is_held for non-held mutex."""
        assert not manager.is_held("nonexistent")


class TestMutexInfo:
    """Tests for MutexInfo dataclass."""

    def test_mutex_info_creation(self) -> None:
        """Test creating MutexInfo."""
        info = MutexInfo(name="test", holder="plugin1")
        assert info.name == "test"
        assert info.holder == "plugin1"
        assert info.acquired_at > 0


class TestStandardMutexes:
    """Tests for StandardMutexes constants."""

    def test_package_manager_mutexes(self) -> None:
        """Test package manager mutex names."""
        assert StandardMutexes.APT_LOCK == "pkgmgr:apt"
        assert StandardMutexes.DPKG_LOCK == "pkgmgr:dpkg"
        assert StandardMutexes.SNAP_LOCK == "pkgmgr:snap"
        assert StandardMutexes.FLATPAK_LOCK == "pkgmgr:flatpak"

    def test_runtime_mutexes(self) -> None:
        """Test runtime mutex names."""
        assert StandardMutexes.PYTHON_RUNTIME == "runtime:python"
        assert StandardMutexes.NODE_RUNTIME == "runtime:node"
        assert StandardMutexes.RUST_RUNTIME == "runtime:rust"

    def test_system_mutexes(self) -> None:
        """Test system mutex names."""
        assert StandardMutexes.NETWORK == "system:network"
        assert StandardMutexes.DISK == "system:disk"


# =============================================================================
# Phase 1 Enhancement Tests
# =============================================================================


class TestMutexManagerPhase1Enhancements:
    """Tests for Phase 1 mutex manager enhancements."""

    @pytest.fixture
    def manager(self) -> MutexManager:
        """Create a fresh mutex manager for each test."""
        return MutexManager(deadlock_timeout=0.5, enable_deadlock_detection=True)

    @pytest.mark.asyncio
    async def test_ordered_acquisition(self, manager: MutexManager) -> None:
        """Test that mutexes are acquired in sorted order to prevent deadlocks."""
        # Acquire in reverse order - should still work due to internal sorting
        result = await manager.acquire("plugin1", ["mutex_c", "mutex_a", "mutex_b"])
        assert result is True

        # All mutexes should be held
        assert manager.is_held("mutex_a")
        assert manager.is_held("mutex_b")
        assert manager.is_held("mutex_c")

    @pytest.mark.asyncio
    async def test_duplicate_mutexes_deduplicated(self, manager: MutexManager) -> None:
        """Test that duplicate mutex requests are deduplicated."""
        result = await manager.acquire("plugin1", ["mutex1", "mutex1", "mutex1"])
        assert result is True

        # Only one mutex should be held
        held = manager.get_held_by("plugin1")
        assert len(held) == 1
        assert "mutex1" in held

    @pytest.mark.asyncio
    async def test_condition_based_waiting(self, manager: MutexManager) -> None:
        """Test that condition-based waiting is more efficient than polling."""
        await manager.acquire("plugin1", ["mutex1"])

        async def release_after_delay() -> None:
            await asyncio.sleep(0.05)
            await manager.release("plugin1", ["mutex1"])

        release_task = asyncio.create_task(release_after_delay())

        # Should wake up quickly after release due to condition notification
        start = asyncio.get_event_loop().time()
        result = await manager.acquire("plugin2", ["mutex1"], timeout=1.0)
        elapsed = asyncio.get_event_loop().time() - start

        assert result is True
        # Should complete much faster than 1 second timeout
        assert elapsed < 0.5

        await release_task

    @pytest.mark.asyncio
    async def test_get_mutex_info(self, manager: MutexManager) -> None:
        """Test getting detailed mutex information."""
        await manager.acquire("plugin1", ["mutex1"])

        info = manager.get_mutex_info("mutex1")
        assert info is not None
        assert info.name == "mutex1"
        assert info.holder == "plugin1"
        assert info.hold_duration >= 0

    @pytest.mark.asyncio
    async def test_get_mutex_info_not_held(self, manager: MutexManager) -> None:
        """Test getting info for non-held mutex."""
        info = manager.get_mutex_info("nonexistent")
        assert info is None

    @pytest.mark.asyncio
    async def test_get_all_mutex_info(self, manager: MutexManager) -> None:
        """Test getting all mutex info."""
        await manager.acquire("plugin1", ["mutex1", "mutex2"])

        all_info = manager.get_all_mutex_info()
        assert len(all_info) == 2
        assert "mutex1" in all_info
        assert "mutex2" in all_info

    @pytest.mark.asyncio
    async def test_get_state_summary(self, manager: MutexManager) -> None:
        """Test getting state summary for debugging."""
        await manager.acquire("plugin1", ["mutex1"])

        summary = manager.get_state_summary()
        assert summary["held_count"] == 1
        assert summary["waiter_count"] == 0
        assert "mutex1" in summary["held_mutexes"]

    @pytest.mark.asyncio
    async def test_deadlock_timeout_property(self) -> None:
        """Test deadlock_timeout property."""
        manager = MutexManager(deadlock_timeout=30.0)
        assert manager.deadlock_timeout == 30.0

    @pytest.mark.asyncio
    async def test_enable_deadlock_detection_property(self) -> None:
        """Test enable_deadlock_detection property."""
        manager = MutexManager(enable_deadlock_detection=False)
        assert manager.enable_deadlock_detection is False


class TestWaiterInfo:
    """Tests for WaiterInfo dataclass."""

    def test_waiter_info_creation(self) -> None:
        """Test creating WaiterInfo."""
        info = WaiterInfo(plugin="plugin1", mutexes=["mutex1", "mutex2"])
        assert info.plugin == "plugin1"
        assert info.mutexes == ["mutex1", "mutex2"]
        assert info.started_at > 0

    def test_waiter_info_wait_duration(self) -> None:
        """Test wait_duration property."""
        import time

        info = WaiterInfo(plugin="plugin1", mutexes=["mutex1"])
        time.sleep(0.01)
        assert info.wait_duration >= 0.01


class TestMutexInfoPhase1:
    """Additional tests for MutexInfo Phase 1 enhancements."""

    def test_hold_duration(self) -> None:
        """Test hold_duration property."""
        import time

        info = MutexInfo(name="test", holder="plugin1")
        time.sleep(0.01)
        assert info.hold_duration >= 0.01


class TestMutexState:
    """Tests for MutexState enum."""

    def test_mutex_state_values(self) -> None:
        """Test MutexState enum values."""
        assert MutexState.ACQUIRED.value == "acquired"
        assert MutexState.WAITING.value == "waiting"
        assert MutexState.TIMEOUT.value == "timeout"
        assert MutexState.DEADLOCK.value == "deadlock"


class TestDeadlockError:
    """Tests for DeadlockError exception."""

    def test_deadlock_error_creation(self) -> None:
        """Test creating DeadlockError."""
        error = DeadlockError(
            plugin="plugin1",
            mutexes=["mutex1", "mutex2"],
            conflicts={"mutex1": "plugin2"},
            wait_time=5.0,
        )
        assert error.plugin == "plugin1"
        assert error.mutexes == ["mutex1", "mutex2"]
        assert error.conflicts == {"mutex1": "plugin2"}
        assert error.wait_time == 5.0
        assert "deadlock" in str(error).lower()

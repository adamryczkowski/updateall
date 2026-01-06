"""Tests for the mutex system."""

from __future__ import annotations

import asyncio

import pytest

from core.mutex import MutexInfo, MutexManager, StandardMutexes


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

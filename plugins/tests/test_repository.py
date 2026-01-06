"""Tests for plugin repository system."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from plugins.repository import (
    InstalledPlugin,
    PluginInfo,
    PluginNotFoundError,
    PluginRepository,
    PluginSource,
    RepositoryConfig,
    RepositoryIndex,
)
from plugins.signing import TrustLevel


class TestPluginInfo:
    """Tests for PluginInfo dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        info = PluginInfo(
            name="apt",
            version="1.0.0",
            description="APT package manager plugin",
            author="Test Author",
            requires_sudo=True,
        )

        data = info.to_dict()

        assert data["name"] == "apt"
        assert data["version"] == "1.0.0"
        assert data["description"] == "APT package manager plugin"
        assert data["requires_sudo"] is True

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "name": "flatpak",
            "version": "2.0.0",
            "description": "Flatpak plugin",
            "author": "Author",
            "homepage": "https://example.com",
            "license": "MIT",
            "requires_sudo": False,
            "supported_platforms": ["linux"],
            "dependencies": [],
            "download_url": "file:///path/to/plugin",
            "checksum_sha256": "abc123",
        }

        info = PluginInfo.from_dict(data)

        assert info.name == "flatpak"
        assert info.version == "2.0.0"
        assert info.homepage == "https://example.com"

    def test_roundtrip(self) -> None:
        """Test serialization roundtrip."""
        original = PluginInfo(
            name="test",
            version="1.0.0",
            description="Test plugin",
            published_at=datetime(2025, 1, 1, tzinfo=UTC),
        )

        data = original.to_dict()
        restored = PluginInfo.from_dict(data)

        assert restored.name == original.name
        assert restored.version == original.version
        assert restored.published_at == original.published_at


class TestInstalledPlugin:
    """Tests for InstalledPlugin dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        installed = InstalledPlugin(
            name="apt",
            version="1.0.0",
            source=PluginSource.REPOSITORY,
            install_path=Path("/path/to/plugin"),
            installed_at=datetime(2025, 1, 1, tzinfo=UTC),
            trust_level=TrustLevel.CHECKSUM_VALID,
        )

        data = installed.to_dict()

        assert data["name"] == "apt"
        assert data["source"] == "repository"
        assert data["trust_level"] == "checksum_valid"

    def test_from_dict(self) -> None:
        """Test deserialization from dictionary."""
        data = {
            "name": "flatpak",
            "version": "2.0.0",
            "source": "local",
            "install_path": "/path/to/plugin",
            "installed_at": "2025-01-01T00:00:00+00:00",
            "trust_level": "signed",
        }

        installed = InstalledPlugin.from_dict(data)

        assert installed.name == "flatpak"
        assert installed.source == PluginSource.LOCAL
        assert installed.trust_level == TrustLevel.SIGNED


class TestRepositoryConfig:
    """Tests for RepositoryConfig dataclass."""

    def test_to_dict(self) -> None:
        """Test serialization."""
        config = RepositoryConfig(
            name="official",
            url="https://plugins.example.com",
            priority=50,
        )

        data = config.to_dict()

        assert data["name"] == "official"
        assert data["url"] == "https://plugins.example.com"
        assert data["priority"] == 50

    def test_from_dict(self) -> None:
        """Test deserialization."""
        data = {
            "name": "community",
            "url": "https://community.example.com",
            "enabled": False,
            "priority": 200,
        }

        config = RepositoryConfig.from_dict(data)

        assert config.name == "community"
        assert config.enabled is False
        assert config.priority == 200


class TestRepositoryIndex:
    """Tests for RepositoryIndex class."""

    def test_refresh_local_repository(self) -> None:
        """Test refreshing from local file:// URL."""
        with TemporaryDirectory() as tmpdir:
            # Create index file
            index_path = Path(tmpdir) / "index.json"
            index_data = {
                "plugins": [
                    {"name": "apt", "version": "1.0.0", "description": "APT plugin"},
                    {"name": "flatpak", "version": "2.0.0", "description": "Flatpak plugin"},
                ]
            }
            index_path.write_text(json.dumps(index_data))

            config = RepositoryConfig(
                name="test",
                url=f"file://{tmpdir}/",
            )
            index = RepositoryIndex(config)

            count = index.refresh()

            assert count == 2
            assert "apt" in index.plugins
            assert "flatpak" in index.plugins

    def test_search(self) -> None:
        """Test searching plugins."""
        config = RepositoryConfig(name="test", url="file:///tmp/")
        index = RepositoryIndex(config)
        index.plugins = {
            "apt": PluginInfo(name="apt", version="1.0.0", description="APT package manager"),
            "flatpak": PluginInfo(name="flatpak", version="1.0.0", description="Flatpak apps"),
            "snap": PluginInfo(name="snap", version="1.0.0", description="Snap packages"),
        }

        results = index.search("package")

        assert len(results) == 2
        names = [r.name for r in results]
        assert "apt" in names
        assert "snap" in names

    def test_search_case_insensitive(self) -> None:
        """Test that search is case insensitive."""
        config = RepositoryConfig(name="test", url="file:///tmp/")
        index = RepositoryIndex(config)
        index.plugins = {
            "APT": PluginInfo(name="APT", version="1.0.0", description="APT plugin"),
        }

        results = index.search("apt")

        assert len(results) == 1

    def test_get_plugin(self) -> None:
        """Test getting plugin by name."""
        config = RepositoryConfig(name="test", url="file:///tmp/")
        index = RepositoryIndex(config)
        index.plugins = {
            "apt": PluginInfo(name="apt", version="1.0.0"),
        }

        result = index.get_plugin("apt")

        assert result is not None
        assert result.name == "apt"

    def test_get_plugin_not_found(self) -> None:
        """Test getting non-existent plugin."""
        config = RepositoryConfig(name="test", url="file:///tmp/")
        index = RepositoryIndex(config)

        result = index.get_plugin("nonexistent")

        assert result is None


class TestPluginRepository:
    """Tests for PluginRepository class."""

    def test_init_creates_directory(self) -> None:
        """Test that initialization creates plugins directory."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"

            _repo = PluginRepository(plugins_dir=plugins_dir)

            assert plugins_dir.exists()

    def test_add_repository(self) -> None:
        """Test adding a repository."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            config = RepositoryConfig(name="test", url="file:///tmp/")
            repo.add_repository(config)

            assert "test" in repo.repositories

    def test_remove_repository(self) -> None:
        """Test removing a repository."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")
            config = RepositoryConfig(name="test", url="file:///tmp/")
            repo.add_repository(config)

            result = repo.remove_repository("test")

            assert result is True
            assert "test" not in repo.repositories

    def test_remove_nonexistent_repository(self) -> None:
        """Test removing non-existent repository."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            result = repo.remove_repository("nonexistent")

            assert result is False

    def test_search_across_repositories(self) -> None:
        """Test searching across multiple repositories."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            # Add two repositories
            config1 = RepositoryConfig(name="repo1", url="file:///tmp/", priority=100)
            config2 = RepositoryConfig(name="repo2", url="file:///tmp/", priority=50)
            repo.add_repository(config1)
            repo.add_repository(config2)

            # Add plugins to indexes
            repo.repositories["repo1"].plugins = {
                "apt": PluginInfo(name="apt", version="1.0.0"),
            }
            repo.repositories["repo2"].plugins = {
                "flatpak": PluginInfo(name="flatpak", version="1.0.0"),
            }

            results = repo.search("a")

            assert len(results) == 2

    def test_get_plugin_info_priority(self) -> None:
        """Test that plugin info respects repository priority."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            # Add two repositories with same plugin
            config1 = RepositoryConfig(name="low", url="file:///tmp/", priority=100)
            config2 = RepositoryConfig(name="high", url="file:///tmp/", priority=50)
            repo.add_repository(config1)
            repo.add_repository(config2)

            repo.repositories["low"].plugins = {
                "apt": PluginInfo(name="apt", version="1.0.0"),
            }
            repo.repositories["high"].plugins = {
                "apt": PluginInfo(name="apt", version="2.0.0"),
            }

            result = repo.get_plugin_info("apt")

            assert result is not None
            repo_name, info = result
            assert repo_name == "high"  # Lower priority number = higher priority
            assert info.version == "2.0.0"

    def test_install_plugin_not_found(self) -> None:
        """Test installing non-existent plugin."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            with pytest.raises(PluginNotFoundError):
                repo.install("nonexistent")

    def test_install_already_installed(self) -> None:
        """Test installing already installed plugin."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"
            repo = PluginRepository(plugins_dir=plugins_dir)

            # Manually add installed plugin
            repo.installed["apt"] = InstalledPlugin(
                name="apt",
                version="1.0.0",
                source=PluginSource.REPOSITORY,
                install_path=plugins_dir / "apt",
                installed_at=datetime.now(tz=UTC),
            )

            # Should return existing installation
            result = repo.install("apt")

            assert result.version == "1.0.0"

    def test_uninstall_plugin(self) -> None:
        """Test uninstalling a plugin."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"
            repo = PluginRepository(plugins_dir=plugins_dir)

            # Create installed plugin
            plugin_path = plugins_dir / "test"
            plugin_path.mkdir(parents=True)
            (plugin_path / "plugin.py").write_text("# Plugin")

            repo.installed["test"] = InstalledPlugin(
                name="test",
                version="1.0.0",
                source=PluginSource.REPOSITORY,
                install_path=plugin_path,
                installed_at=datetime.now(tz=UTC),
            )

            result = repo.uninstall("test")

            assert result is True
            assert "test" not in repo.installed
            assert not plugin_path.exists()

    def test_uninstall_builtin_fails(self) -> None:
        """Test that builtin plugins cannot be uninstalled."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"
            repo = PluginRepository(plugins_dir=plugins_dir)

            repo.installed["apt"] = InstalledPlugin(
                name="apt",
                version="1.0.0",
                source=PluginSource.BUILTIN,
                install_path=plugins_dir / "apt",
                installed_at=datetime.now(tz=UTC),
            )

            result = repo.uninstall("apt")

            assert result is False
            assert "apt" in repo.installed

    def test_list_installed(self) -> None:
        """Test listing installed plugins."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            repo.installed["apt"] = InstalledPlugin(
                name="apt",
                version="1.0.0",
                source=PluginSource.BUILTIN,
                install_path=Path("/path"),
                installed_at=datetime.now(tz=UTC),
            )
            repo.installed["flatpak"] = InstalledPlugin(
                name="flatpak",
                version="2.0.0",
                source=PluginSource.REPOSITORY,
                install_path=Path("/path"),
                installed_at=datetime.now(tz=UTC),
            )

            installed = repo.list_installed()

            assert len(installed) == 2

    def test_check_updates(self) -> None:
        """Test checking for updates."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"
            repo = PluginRepository(plugins_dir=plugins_dir)

            # Add repository with newer version
            config = RepositoryConfig(name="test", url="file:///tmp/")
            repo.add_repository(config)
            repo.repositories["test"].plugins = {
                "apt": PluginInfo(name="apt", version="2.0.0"),
            }

            # Add installed plugin with older version
            repo.installed["apt"] = InstalledPlugin(
                name="apt",
                version="1.0.0",
                source=PluginSource.REPOSITORY,
                install_path=plugins_dir / "apt",
                installed_at=datetime.now(tz=UTC),
            )

            updates = repo.check_updates()

            assert len(updates) == 1
            installed, available = updates[0]
            assert installed.version == "1.0.0"
            assert available.version == "2.0.0"

    def test_version_comparison(self) -> None:
        """Test version comparison."""
        with TemporaryDirectory() as tmpdir:
            repo = PluginRepository(plugins_dir=Path(tmpdir) / "plugins")

            assert repo._version_greater("2.0.0", "1.0.0") is True
            assert repo._version_greater("1.0.0", "2.0.0") is False
            assert repo._version_greater("1.0.0", "1.0.0") is False
            assert repo._version_greater("1.10.0", "1.9.0") is True
            assert repo._version_greater("1.0.1", "1.0.0") is True

    def test_state_persistence(self) -> None:
        """Test that state is persisted and loaded."""
        with TemporaryDirectory() as tmpdir:
            plugins_dir = Path(tmpdir) / "plugins"

            # Create repo and add data
            repo1 = PluginRepository(plugins_dir=plugins_dir)
            repo1.add_repository(RepositoryConfig(name="test", url="file:///tmp/"))
            repo1.installed["apt"] = InstalledPlugin(
                name="apt",
                version="1.0.0",
                source=PluginSource.REPOSITORY,
                install_path=plugins_dir / "apt",
                installed_at=datetime.now(tz=UTC),
            )
            repo1._save_state()

            # Create new repo and verify state is loaded
            repo2 = PluginRepository(plugins_dir=plugins_dir)

            assert "test" in repo2.repositories
            assert "apt" in repo2.installed

"""Plugin repository system for Phase 4.

This module provides a plugin repository system for discovering, downloading,
and managing plugins from remote sources. It supports:

1. Repository index management
2. Plugin discovery and search
3. Plugin download and installation
4. Version management and updates
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import structlog

from plugins.signing import PluginSignature, PluginVerifier, TrustLevel, VerificationStatus

logger = structlog.get_logger(__name__)


class RepositoryError(Exception):
    """Base exception for repository operations."""


class PluginNotFoundError(RepositoryError):
    """Plugin not found in repository."""


class PluginDownloadError(RepositoryError):
    """Failed to download plugin from repository."""


class InstallationError(RepositoryError):
    """Failed to install plugin."""


class PluginSource(str, Enum):
    """Source of a plugin."""

    BUILTIN = "builtin"  # Shipped with update-all
    LOCAL = "local"  # Installed locally
    REPOSITORY = "repository"  # From remote repository


@dataclass
class PluginInfo:
    """Information about a plugin in the repository."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    homepage: str = ""
    license: str = ""
    requires_sudo: bool = False
    supported_platforms: list[str] = field(default_factory=lambda: ["linux"])
    dependencies: list[str] = field(default_factory=list)
    download_url: str = ""
    signature_url: str = ""
    checksum_sha256: str = ""
    download_size: int = 0
    published_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "homepage": self.homepage,
            "license": self.license,
            "requires_sudo": self.requires_sudo,
            "supported_platforms": self.supported_platforms,
            "dependencies": self.dependencies,
            "download_url": self.download_url,
            "signature_url": self.signature_url,
            "checksum_sha256": self.checksum_sha256,
            "download_size": self.download_size,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginInfo:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", ""),
            homepage=data.get("homepage", ""),
            license=data.get("license", ""),
            requires_sudo=data.get("requires_sudo", False),
            supported_platforms=data.get("supported_platforms", ["linux"]),
            dependencies=data.get("dependencies", []),
            download_url=data.get("download_url", ""),
            signature_url=data.get("signature_url", ""),
            checksum_sha256=data.get("checksum_sha256", ""),
            download_size=data.get("download_size", 0),
            published_at=(
                datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None
            ),
        )


@dataclass
class InstalledPlugin:
    """Information about an installed plugin."""

    name: str
    version: str
    source: PluginSource
    install_path: Path
    installed_at: datetime
    signature: PluginSignature | None = None
    trust_level: TrustLevel = TrustLevel.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source.value,
            "install_path": str(self.install_path),
            "installed_at": self.installed_at.isoformat(),
            "signature": self.signature.to_dict() if self.signature else None,
            "trust_level": self.trust_level.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstalledPlugin:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            version=data["version"],
            source=PluginSource(data["source"]),
            install_path=Path(data["install_path"]),
            installed_at=datetime.fromisoformat(data["installed_at"]),
            signature=(
                PluginSignature.from_dict(data["signature"]) if data.get("signature") else None
            ),
            trust_level=TrustLevel(data.get("trust_level", "unknown")),
        )


@dataclass
class RepositoryConfig:
    """Configuration for a plugin repository."""

    name: str
    url: str
    enabled: bool = True
    priority: int = 100  # Lower number = higher priority
    trusted_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "url": self.url,
            "enabled": self.enabled,
            "priority": self.priority,
            "trusted_keys": self.trusted_keys,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepositoryConfig:
        """Create from dictionary."""
        return cls(
            name=data["name"],
            url=data["url"],
            enabled=data.get("enabled", True),
            priority=data.get("priority", 100),
            trusted_keys=data.get("trusted_keys", []),
        )


class RepositoryIndex:
    """Index of plugins available in a repository."""

    def __init__(self, config: RepositoryConfig) -> None:
        """Initialize the repository index.

        Args:
            config: Repository configuration.
        """
        self.config = config
        self.plugins: dict[str, PluginInfo] = {}
        self.last_updated: datetime | None = None

    def refresh(self) -> int:
        """Refresh the repository index.

        Downloads and parses the repository index file.

        Returns:
            Number of plugins in the index.

        Raises:
            RepositoryError: If refresh fails.
        """
        log = logger.bind(repository=self.config.name)
        log.info("refreshing_repository_index", url=self.config.url)

        try:
            index_url = urljoin(self.config.url, "index.json")
            index_data = self._download_index(index_url)

            self.plugins = {}
            for plugin_data in index_data.get("plugins", []):
                info = PluginInfo.from_dict(plugin_data)
                self.plugins[info.name] = info

            self.last_updated = datetime.now(tz=UTC)
            log.info("repository_index_refreshed", plugin_count=len(self.plugins))
            return len(self.plugins)

        except Exception as e:
            log.error("repository_refresh_failed", error=str(e))
            raise RepositoryError(f"Failed to refresh repository: {e}") from e

    def _download_index(self, url: str) -> dict[str, Any]:
        """Download and parse repository index.

        Args:
            url: URL of the index file.

        Returns:
            Parsed index data.
        """
        # For now, support file:// URLs for local testing
        if url.startswith("file://"):
            path = Path(url[7:])
            with path.open() as f:
                return json.load(f)  # type: ignore[no-any-return]

        # HTTP support would require httpx or similar
        # For Phase 4 MVP, we'll raise an error for HTTP URLs
        raise RepositoryError(f"HTTP repositories not yet supported: {url}")

    def search(self, query: str) -> list[PluginInfo]:
        """Search for plugins matching a query.

        Args:
            query: Search query (matches name or description).

        Returns:
            List of matching plugins.
        """
        query_lower = query.lower()
        return [
            info
            for info in self.plugins.values()
            if query_lower in info.name.lower() or query_lower in info.description.lower()
        ]

    def get_plugin(self, name: str) -> PluginInfo | None:
        """Get plugin info by name.

        Args:
            name: Plugin name.

        Returns:
            PluginInfo or None if not found.
        """
        return self.plugins.get(name)


class PluginRepository:
    """Manages plugin repositories and installations.

    Provides functionality to:
    - Manage multiple repositories
    - Search and discover plugins
    - Download and install plugins
    - Track installed plugins
    """

    def __init__(
        self,
        plugins_dir: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        """Initialize the plugin repository manager.

        Args:
            plugins_dir: Directory for installed plugins.
            state_file: Path to state file for tracking installations.
        """
        self.plugins_dir = plugins_dir or self._get_default_plugins_dir()
        self.state_file = state_file or self.plugins_dir / "state.json"
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        self.repositories: dict[str, RepositoryIndex] = {}
        self.installed: dict[str, InstalledPlugin] = {}
        self.verifier = PluginVerifier()

        self._load_state()

    def _get_default_plugins_dir(self) -> Path:
        """Get the default plugins directory."""
        import os

        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
        return base / "update-all" / "plugins"

    def _load_state(self) -> None:
        """Load state from file."""
        if not self.state_file.exists():
            return

        try:
            with self.state_file.open() as f:
                data = json.load(f)

            for plugin_data in data.get("installed", []):
                plugin = InstalledPlugin.from_dict(plugin_data)
                self.installed[plugin.name] = plugin

            for repo_data in data.get("repositories", []):
                config = RepositoryConfig.from_dict(repo_data)
                self.repositories[config.name] = RepositoryIndex(config)

        except Exception as e:
            logger.warning("failed_to_load_state", error=str(e))

    def _save_state(self) -> None:
        """Save state to file."""
        data = {
            "installed": [p.to_dict() for p in self.installed.values()],
            "repositories": [r.config.to_dict() for r in self.repositories.values()],
        }

        with self.state_file.open("w") as f:
            json.dump(data, f, indent=2)

    def add_repository(self, config: RepositoryConfig) -> None:
        """Add a repository.

        Args:
            config: Repository configuration.
        """
        self.repositories[config.name] = RepositoryIndex(config)
        self._save_state()
        logger.info("repository_added", name=config.name, url=config.url)

    def remove_repository(self, name: str) -> bool:
        """Remove a repository.

        Args:
            name: Repository name.

        Returns:
            True if removed, False if not found.
        """
        if name in self.repositories:
            del self.repositories[name]
            self._save_state()
            logger.info("repository_removed", name=name)
            return True
        return False

    def refresh_all(self) -> dict[str, int]:
        """Refresh all repository indexes.

        Returns:
            Dict mapping repository name to plugin count.
        """
        results = {}
        for name, repo in self.repositories.items():
            if repo.config.enabled:
                try:
                    count = repo.refresh()
                    results[name] = count
                except RepositoryError as e:
                    logger.warning("repository_refresh_failed", name=name, error=str(e))
                    results[name] = -1
        return results

    def search(self, query: str) -> list[tuple[str, PluginInfo]]:
        """Search all repositories for plugins.

        Args:
            query: Search query.

        Returns:
            List of (repository_name, PluginInfo) tuples.
        """
        results = []
        for name, repo in sorted(
            self.repositories.items(),
            key=lambda x: x[1].config.priority,
        ):
            if repo.config.enabled:
                for info in repo.search(query):
                    results.append((name, info))
        return results

    def get_plugin_info(self, name: str) -> tuple[str, PluginInfo] | None:
        """Get plugin info from any repository.

        Args:
            name: Plugin name.

        Returns:
            Tuple of (repository_name, PluginInfo) or None.
        """
        for repo_name, repo in sorted(
            self.repositories.items(),
            key=lambda x: x[1].config.priority,
        ):
            if repo.config.enabled:
                info = repo.get_plugin(name)
                if info:
                    return repo_name, info
        return None

    def install(
        self,
        plugin_name: str,
        *,
        verify: bool = True,
        force: bool = False,
    ) -> InstalledPlugin:
        """Install a plugin from repository.

        Args:
            plugin_name: Name of the plugin to install.
            verify: Whether to verify plugin signature.
            force: Whether to force reinstall if already installed.

        Returns:
            InstalledPlugin with installation details.

        Raises:
            PluginNotFoundError: If plugin not found.
            PluginDownloadError: If download fails.
            InstallationError: If installation fails.
        """
        log = logger.bind(plugin=plugin_name)

        # Check if already installed
        if plugin_name in self.installed and not force:
            log.info("plugin_already_installed", version=self.installed[plugin_name].version)
            return self.installed[plugin_name]

        # Find plugin in repositories
        result = self.get_plugin_info(plugin_name)
        if not result:
            raise PluginNotFoundError(f"Plugin '{plugin_name}' not found in any repository")

        repo_name, info = result
        log.info("installing_plugin", version=info.version, repository=repo_name)

        try:
            # Download plugin
            plugin_path = self._download_plugin(info)

            # Verify if requested
            trust_level = TrustLevel.UNKNOWN
            signature = None

            if verify and info.checksum_sha256:
                signature = PluginSignature(
                    plugin_name=info.name,
                    version=info.version,
                    checksum_sha256=info.checksum_sha256,
                )
                verification = self.verifier.verify_plugin(plugin_path, signature)

                if verification.status != VerificationStatus.VERIFIED:
                    raise InstallationError(f"Plugin verification failed: {verification.message}")

                trust_level = verification.trust_level

            # Install to plugins directory
            install_path = self.plugins_dir / plugin_name
            if install_path.exists():
                shutil.rmtree(install_path)

            if plugin_path.is_dir():
                shutil.copytree(plugin_path, install_path)
            else:
                install_path.mkdir(parents=True, exist_ok=True)
                shutil.copy2(plugin_path, install_path / plugin_path.name)

            # Record installation
            installed = InstalledPlugin(
                name=plugin_name,
                version=info.version,
                source=PluginSource.REPOSITORY,
                install_path=install_path,
                installed_at=datetime.now(tz=UTC),
                signature=signature,
                trust_level=trust_level,
            )

            self.installed[plugin_name] = installed
            self._save_state()

            log.info("plugin_installed", version=info.version, trust_level=trust_level.value)
            return installed

        except (PluginNotFoundError, InstallationError):
            raise
        except Exception as e:
            log.error("installation_failed", error=str(e))
            raise InstallationError(f"Failed to install plugin: {e}") from e

    def _download_plugin(self, info: PluginInfo) -> Path:
        """Download a plugin.

        Args:
            info: Plugin information.

        Returns:
            Path to downloaded plugin.
        """
        if not info.download_url:
            raise PluginDownloadError(f"No download URL for plugin '{info.name}'")

        # For file:// URLs (local testing)
        if info.download_url.startswith("file://"):
            path = Path(info.download_url[7:])
            if not path.exists():
                raise PluginDownloadError(f"Plugin file not found: {path}")
            return path

        # HTTP support would require httpx
        raise PluginDownloadError(f"HTTP downloads not yet supported: {info.download_url}")

    def uninstall(self, plugin_name: str) -> bool:
        """Uninstall a plugin.

        Args:
            plugin_name: Name of the plugin to uninstall.

        Returns:
            True if uninstalled, False if not found.
        """
        if plugin_name not in self.installed:
            return False

        installed = self.installed[plugin_name]

        # Don't uninstall builtin plugins
        if installed.source == PluginSource.BUILTIN:
            logger.warning("cannot_uninstall_builtin", plugin=plugin_name)
            return False

        # Remove files
        if installed.install_path.exists():
            shutil.rmtree(installed.install_path)

        del self.installed[plugin_name]
        self._save_state()

        logger.info("plugin_uninstalled", plugin=plugin_name)
        return True

    def list_installed(self) -> list[InstalledPlugin]:
        """List all installed plugins.

        Returns:
            List of installed plugins.
        """
        return list(self.installed.values())

    def check_updates(self) -> list[tuple[InstalledPlugin, PluginInfo]]:
        """Check for plugin updates.

        Returns:
            List of (installed, available) tuples for plugins with updates.
        """
        updates = []

        for installed in self.installed.values():
            if installed.source != PluginSource.REPOSITORY:
                continue

            result = self.get_plugin_info(installed.name)
            if result:
                _, info = result
                if self._version_greater(info.version, installed.version):
                    updates.append((installed, info))

        return updates

    def _version_greater(self, v1: str, v2: str) -> bool:
        """Check if v1 is greater than v2.

        Simple version comparison. For production, use packaging.version.

        Args:
            v1: First version.
            v2: Second version.

        Returns:
            True if v1 > v2.
        """
        try:
            parts1 = [int(x) for x in v1.split(".")]
            parts2 = [int(x) for x in v2.split(".")]

            # Pad to same length
            max_len = max(len(parts1), len(parts2))
            parts1.extend([0] * (max_len - len(parts1)))
            parts2.extend([0] * (max_len - len(parts2)))

            return parts1 > parts2
        except ValueError:
            # Fall back to string comparison
            return v1 > v2

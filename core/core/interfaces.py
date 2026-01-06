"""Core interfaces for update-all system.

This module defines abstract base classes for plugins and executors.
"""

from abc import ABC, abstractmethod
from typing import Any

from .models import ExecutionResult, PluginMetadata


class UpdatePlugin(ABC):
    """Abstract base class for update plugins.

    All plugins must inherit from this class and implement the required methods.
    Plugins can be instantiated without configuration for metadata access.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the plugin name.

        Returns:
            Unique plugin identifier
        """
        ...

    @property
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata.

        Default implementation returns basic metadata from name property.
        Override for more detailed metadata.

        Returns:
            Plugin metadata including name, version, description, etc.
        """
        return PluginMetadata(name=self.name)

    @abstractmethod
    async def check_available(self) -> bool:
        """Check if the plugin's package manager is available.

        Returns:
            True if the package manager is available, False otherwise
        """
        ...

    async def check_updates(self) -> list[dict[str, Any]]:
        """Check for available updates.

        Default implementation returns empty list.
        Override to implement update checking.

        Returns:
            List of available updates with package information
        """
        return []

    async def execute(self, dry_run: bool = False) -> ExecutionResult:
        """Execute the update process.

        Default implementation raises NotImplementedError.
        Override to implement the update logic.

        Args:
            dry_run: If True, simulate the update without making changes

        Returns:
            Execution result with status and details
        """
        raise NotImplementedError("Subclasses must implement execute()")

    async def pre_execute(self) -> None:  # noqa: B027
        """Hook called before execute().

        Override this method to perform setup tasks.
        """
        pass

    async def post_execute(self, result: ExecutionResult) -> None:  # noqa: B027
        """Hook called after execute().

        Override this method to perform cleanup tasks.

        Args:
            result: The execution result
        """
        pass


class PluginExecutor(ABC):
    """Abstract base class for plugin executors.

    Executors are responsible for running plugins and managing their lifecycle.
    """

    @abstractmethod
    async def execute_plugin(self, plugin: UpdatePlugin, dry_run: bool = False) -> ExecutionResult:
        """Execute a single plugin.

        Args:
            plugin: The plugin to execute
            dry_run: If True, simulate the update

        Returns:
            Execution result
        """
        ...

    @abstractmethod
    async def execute_all(
        self, plugins: list[UpdatePlugin], dry_run: bool = False
    ) -> list[ExecutionResult]:
        """Execute all plugins.

        Args:
            plugins: List of plugins to execute
            dry_run: If True, simulate the updates

        Returns:
            List of execution results
        """
        ...


class ConfigLoader(ABC):
    """Abstract base class for configuration loaders."""

    @abstractmethod
    def load(self, path: str) -> dict[str, Any]:
        """Load configuration from a file.

        Args:
            path: Path to the configuration file

        Returns:
            Configuration dictionary
        """
        ...

    @abstractmethod
    def save(self, config: dict[str, Any], path: str) -> None:
        """Save configuration to a file.

        Args:
            config: Configuration dictionary
            path: Path to save the configuration
        """
        ...

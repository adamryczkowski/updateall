"""Core interfaces for update-all system.

This module defines abstract base classes for plugins and executors.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .models import DownloadEstimate, ExecutionResult, PluginMetadata, PluginStatus

if TYPE_CHECKING:
    from .models import UpdateEstimate, VersionInfo
from .streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    PhaseEvent,
    StreamEvent,
)


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

    # =========================================================================
    # Streaming Interface (Phase 1 - Core Streaming Infrastructure)
    # =========================================================================

    @property
    def supports_streaming(self) -> bool:
        """Check if this plugin supports streaming output.

        Plugins that override execute_streaming() should return True.
        This allows the UI to choose between streaming and batch modes.

        Returns:
            True if streaming is supported, False otherwise.
        """
        return False

    async def execute_streaming(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute the update process with streaming output.

        This method provides real-time output during plugin execution.
        The default implementation wraps execute() for backward compatibility.

        Override this method to provide native streaming support.

        Args:
            dry_run: If True, simulate the update without making changes.

        Yields:
            StreamEvent objects as the plugin executes.
            The final event should be a CompletionEvent.
        """
        # Default implementation wraps execute() for backward compatibility
        result = await self.execute(dry_run=dry_run)

        # Emit output lines
        if result.stdout:
            for line in result.stdout.splitlines():
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line,
                    stream="stdout",
                )

        if result.stderr:
            for line in result.stderr.splitlines():
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=line,
                    stream="stderr",
                )

        # Emit completion
        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=result.status == PluginStatus.SUCCESS,
            exit_code=result.exit_code or 0,
            packages_updated=result.packages_updated,
            error_message=result.error_message,
        )

    async def check_updates_streaming(self) -> AsyncIterator[StreamEvent]:
        """Check for updates with streaming output.

        This method provides real-time output during update checking.
        The default implementation wraps check_updates().

        Override this method to provide native streaming support.

        Yields:
            StreamEvent objects during the check process.
        """
        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
        )

        try:
            updates = await self.check_updates()

            # Emit phase end with success
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.CHECK,
                success=True,
            )

            # Emit output with update count
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Found {len(updates)} updates available",
                stream="stdout",
            )

        except Exception as e:
            # Emit phase end with failure
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.CHECK,
                success=False,
                error_message=str(e),
            )

    # =========================================================================
    # Download API (Phase 2 - Download API)
    # =========================================================================

    @property
    def supports_download(self) -> bool:
        """Check if this plugin supports separate download phase.

        Plugins that can download updates separately from applying them
        should override this property to return True. This enables:
        - Pre-downloading updates for offline installation
        - Download progress tracking
        - Separate download and execute phases in the UI

        Returns:
            True if download() can be called separately from execute().
        """
        return False

    async def estimate_download(self) -> DownloadEstimate | None:
        """Estimate the download size and time.

        This method provides information about expected downloads before
        they begin. Override this method to provide accurate estimates.

        Returns:
            DownloadEstimate with size and time estimates, or None if
            no downloads are needed or estimation is not supported.
        """
        return None

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Download updates without applying them.

        This method downloads updates but does not install them. It should
        only be called if supports_download is True.

        Override this method to implement download-only functionality.
        The default implementation raises NotImplementedError.

        Yields:
            StreamEvent objects with download progress.
            Should emit PhaseEvent for PHASE_START and PHASE_END.
            Should emit ProgressEvent for download progress.
            Final event should be CompletionEvent.

        Raises:
            NotImplementedError: If the plugin does not support separate download.
        """
        raise NotImplementedError("Plugin does not support separate download")
        # Make this a generator (required for AsyncIterator return type)
        yield  # type: ignore[misc]  # pragma: no cover

    async def download_streaming(self) -> AsyncIterator[StreamEvent]:
        """Download updates with streaming progress output.

        This is the streaming version of download() that provides
        real-time progress updates during the download phase.

        Default implementation wraps download() for backward compatibility.

        Yields:
            StreamEvent objects with download progress.
        """
        # Emit phase start
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        try:
            async for event in self.download():
                yield event

            # Emit phase end with success
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=True,
            )

        except NotImplementedError:
            # Plugin doesn't support download
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Download not supported - skipping download phase",
                stream="stderr",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message="Plugin does not support separate download",
            )

        except Exception as e:
            # Emit phase end with failure
            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.DOWNLOAD,
                success=False,
                error_message=str(e),
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=-1,
                error_message=str(e),
            )

    async def execute_after_download(
        self,
        dry_run: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Execute updates after download phase.

        This method applies updates that were previously downloaded.
        It assumes download() was already called successfully.

        Override this method to implement post-download execution.
        The default implementation delegates to execute_streaming().

        Args:
            dry_run: If True, simulate the update without making changes.

        Yields:
            StreamEvent objects as the plugin executes.
        """
        # Default: same as execute_streaming
        async for event in self.execute_streaming(dry_run=dry_run):
            yield event

    # =========================================================================
    # Interactive Mode Interface (Phase 4 - Interactive Tabs Integration)
    # =========================================================================

    @property
    def supports_interactive(self) -> bool:
        """Check if this plugin supports interactive mode with PTY.

        Plugins that can run in an interactive PTY session should override
        this property to return True. This enables:
        - Full terminal emulation with ANSI escape sequences
        - Interactive prompts (sudo, confirmations, etc.)
        - Live progress display with cursor movement

        Returns:
            True if the plugin supports interactive PTY mode, False otherwise.
        """
        return False

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the command to run in interactive mode.

        This method returns the command and arguments to execute in a PTY
        session. Override this method to provide the appropriate command
        for your plugin.

        Args:
            dry_run: If True, return a command that simulates the update.

        Returns:
            Command and arguments as a list of strings.

        Raises:
            NotImplementedError: If the plugin does not support interactive mode.
        """
        raise NotImplementedError(f"Plugin '{self.name}' does not support interactive mode")

    # =========================================================================
    # Version Checking Protocol (Proposal 3)
    # =========================================================================

    async def get_installed_version(self) -> str | None:
        """Get the currently installed version.

        Override this method to provide version information for the
        managed software. The default implementation returns None.

        Returns:
            Version string (e.g., "1.2.3") or None if:
            - Software is not installed
            - Version cannot be determined
            - Version checking is not supported
        """
        return None

    async def get_available_version(self) -> str | None:
        """Get the latest available version.

        Override this method to check for the latest version from
        the upstream source (e.g., GitHub releases, package registry).

        Returns:
            Version string (e.g., "1.3.0") or None if:
            - Version cannot be determined
            - Network is unavailable
            - Version checking is not supported
        """
        return None

    async def needs_update(self) -> bool | None:
        """Check if an update is needed.

        Compares installed version with available version to determine
        if an update should be performed.

        The default implementation compares versions from
        get_installed_version() and get_available_version().
        Override for custom comparison logic.

        Returns:
            - True: Update is available
            - False: Already up-to-date
            - None: Cannot determine (version check not supported or failed)
        """
        installed = await self.get_installed_version()
        available = await self.get_available_version()

        if installed is None or available is None:
            return None  # Cannot determine

        # Import here to avoid circular imports
        from .version import needs_update as version_needs_update

        return version_needs_update(installed, available)

    async def get_update_estimate(self) -> "UpdateEstimate | None":
        """Get estimated download size and package count for the update.

        Override this method to provide download size estimates. This is
        particularly useful for package managers like apt, flatpak, and snap
        that can report download sizes before performing updates.

        Returns:
            UpdateEstimate with download_bytes, package_count, etc., or None
            if estimation is not supported or no update is needed.
        """
        return None

    async def get_version_info(self) -> "VersionInfo":
        """Get complete version information.

        This method aggregates version checking results into a
        single VersionInfo object for easy consumption. If the plugin
        supports update estimation and an update is needed, it will
        also include download size and package count information.

        Returns:
            VersionInfo with installed, available, needs_update, and
            optionally estimate fields.
        """
        from .models import UpdateEstimate, VersionInfo

        try:
            installed = await self.get_installed_version()
            available = await self.get_available_version()
            update_needed = await self.needs_update()

            # Get update estimate if supported and update is needed
            estimate: UpdateEstimate | None = None
            if update_needed and self.supports_update_estimate:
                estimate = await self.get_update_estimate()

            return VersionInfo(
                installed=installed,
                available=available,
                needs_update=update_needed,
                check_time=datetime.now(tz=UTC),
                estimate=estimate,
            )
        except Exception as e:
            return VersionInfo(
                check_time=datetime.now(tz=UTC),
                error_message=str(e),
            )

    @property
    def supports_version_check(self) -> bool:
        """Check if this plugin supports version checking.

        Returns True if the plugin has implemented version checking
        by overriding get_installed_version() or get_available_version().

        Returns:
            True if version checking is supported, False otherwise.
        """
        # Check if methods are overridden from UpdatePlugin
        return (
            type(self).get_installed_version is not UpdatePlugin.get_installed_version
            or type(self).get_available_version is not UpdatePlugin.get_available_version
        )

    @property
    def supports_update_estimate(self) -> bool:
        """Check if this plugin supports update estimation.

        Returns True if the plugin has implemented get_update_estimate().

        Returns:
            True if update estimation is supported, False otherwise.
        """
        return type(self).get_update_estimate is not UpdatePlugin.get_update_estimate


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

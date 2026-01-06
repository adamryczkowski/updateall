"""Remote update execution via SSH.

This module provides SSH-based remote execution for running update-all
on remote hosts. It uses asyncssh for asynchronous SSH connections.

Sources consulted:
- AsyncSSH ReadTheDocs: https://asyncssh.readthedocs.io/en/latest/
- PyPI: https://pypi.org/project/asyncssh/
- GitHub: https://github.com/ronf/asyncssh
- GitHub Examples: https://github.com/ronf/asyncssh/tree/develop/examples
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

if TYPE_CHECKING:
    import asyncssh

logger = structlog.get_logger(__name__)


class RemoteUpdateError(Exception):
    """Error during remote update execution."""


class ConnectionError(RemoteUpdateError):
    """Error connecting to remote host."""


class ProgressEventType(str, Enum):
    """Types of progress events from remote execution."""

    STARTED = "started"
    PROGRESS = "progress"
    PLUGIN_STARTED = "plugin_started"
    PLUGIN_COMPLETED = "plugin_completed"
    LOG = "log"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ProgressEvent:
    """Progress event from remote update execution."""

    type: ProgressEventType
    message: str = ""
    plugin_name: str | None = None
    percent: float | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProgressEvent:
        """Create a ProgressEvent from a dictionary."""
        event_type = data.get("type", "log")
        try:
            event_type = ProgressEventType(event_type)
        except ValueError:
            event_type = ProgressEventType.LOG

        return cls(
            type=event_type,
            message=data.get("message", ""),
            plugin_name=data.get("plugin_name"),
            percent=data.get("percent"),
            data=data.get("data", {}),
        )


@dataclass
class HostConfig:
    """Configuration for a remote host."""

    name: str
    hostname: str
    user: str
    port: int = 22
    key_file: Path | None = None
    password: str | None = None
    update_all_path: str = "/usr/local/bin/update-all"
    sudo_password_env: str | None = None
    known_hosts: Path | None = None
    connect_timeout: float = 30.0

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> HostConfig:
        """Create a HostConfig from a dictionary."""
        key_file = data.get("key_file")
        if key_file:
            key_file = Path(key_file).expanduser()

        known_hosts = data.get("known_hosts")
        if known_hosts:
            known_hosts = Path(known_hosts).expanduser()

        return cls(
            name=name,
            hostname=data["hostname"],
            user=data["user"],
            port=data.get("port", 22),
            key_file=key_file,
            password=data.get("password"),
            update_all_path=data.get("update_all_path", "/usr/local/bin/update-all"),
            sudo_password_env=data.get("sudo_password_env"),
            known_hosts=known_hosts,
            connect_timeout=data.get("connect_timeout", 30.0),
        )


@dataclass
class RemoteUpdateResult:
    """Result of a remote update execution."""

    host_name: str
    success: bool
    start_time: datetime
    end_time: datetime | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error_message: str | None = None
    events: list[ProgressEvent] = field(default_factory=list)


class RemoteExecutor:
    """Executes update-all on remote hosts via SSH.

    This class provides methods to connect to remote hosts and execute
    update-all commands, streaming progress events back to the caller.
    """

    def __init__(self, host_config: HostConfig) -> None:
        """Initialize the remote executor.

        Args:
            host_config: Configuration for the remote host.
        """
        self.config = host_config
        self._connection: asyncssh.SSHClientConnection | None = None

    async def connect(self) -> None:
        """Connect to the remote host.

        Raises:
            ConnectionError: If connection fails.
        """
        try:
            import asyncssh
        except ImportError as e:
            raise RemoteUpdateError(
                "asyncssh is required for remote updates. Install it with: pip install asyncssh"
            ) from e

        try:
            connect_kwargs: dict[str, Any] = {
                "host": self.config.hostname,
                "port": self.config.port,
                "username": self.config.user,
            }

            if self.config.key_file:
                connect_kwargs["client_keys"] = [str(self.config.key_file)]

            if self.config.password:
                connect_kwargs["password"] = self.config.password

            if self.config.known_hosts:
                connect_kwargs["known_hosts"] = str(self.config.known_hosts)
            else:
                # Accept any host key (less secure, but convenient for initial setup)
                connect_kwargs["known_hosts"] = None

            logger.info(
                "connecting_to_remote",
                host=self.config.hostname,
                port=self.config.port,
                user=self.config.user,
            )

            self._connection = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=self.config.connect_timeout,
            )

            logger.info("connected_to_remote", host=self.config.hostname)

        except TimeoutError as e:
            raise ConnectionError(
                f"Connection to {self.config.hostname} timed out "
                f"after {self.config.connect_timeout} seconds"
            ) from e
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.config.hostname}: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the remote host."""
        if self._connection:
            self._connection.close()
            await self._connection.wait_closed()
            self._connection = None
            logger.info("disconnected_from_remote", host=self.config.hostname)

    async def run_update(
        self,
        plugins: list[str] | None = None,
        dry_run: bool = False,
        check_only: bool = False,
    ) -> AsyncIterator[ProgressEvent]:
        """Run update-all on the remote host, streaming progress.

        Args:
            plugins: Optional list of specific plugins to run.
            dry_run: If True, simulate updates without making changes.
            check_only: If True, only check for updates without applying.

        Yields:
            ProgressEvent objects as updates occur.

        Raises:
            RemoteUpdateError: If the update fails.
        """
        if not self._connection:
            raise RemoteUpdateError("Not connected to remote host")

        # Build command
        cmd = self.config.update_all_path

        if check_only:
            cmd += " check"
        else:
            cmd += " run --json"

        if plugins:
            for plugin in plugins:
                cmd += f" --plugin {plugin}"

        if dry_run:
            cmd += " --dry-run"

        logger.info("running_remote_update", host=self.config.hostname, command=cmd)

        yield ProgressEvent(
            type=ProgressEventType.STARTED,
            message=f"Starting update on {self.config.hostname}",
        )

        try:
            async with self._connection.create_process(cmd) as process:
                # Read stdout line by line
                async for line in process.stdout:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event_data = json.loads(line)
                        yield ProgressEvent.from_dict(event_data)
                    except json.JSONDecodeError:
                        # Not JSON, treat as log message
                        yield ProgressEvent(
                            type=ProgressEventType.LOG,
                            message=line,
                        )

                await process.wait()

                if process.returncode != 0:
                    stderr = await process.stderr.read()
                    yield ProgressEvent(
                        type=ProgressEventType.ERROR,
                        message=f"Remote update failed with exit code {process.returncode}",
                        data={"exit_code": process.returncode, "stderr": stderr},
                    )
                else:
                    yield ProgressEvent(
                        type=ProgressEventType.COMPLETED,
                        message=f"Update completed on {self.config.hostname}",
                    )

        except Exception as e:
            logger.error("remote_update_failed", host=self.config.hostname, error=str(e))
            yield ProgressEvent(
                type=ProgressEventType.ERROR,
                message=f"Remote update failed: {e}",
            )
            raise RemoteUpdateError(f"Remote update failed: {e}") from e

    async def check_connection(self) -> bool:
        """Check if we can connect to the remote host.

        Returns:
            True if connection is successful, False otherwise.
        """
        try:
            await self.connect()
            # Run a simple command to verify
            if self._connection:
                result = await self._connection.run("echo ok", check=True)
                return result.stdout.strip() == "ok"
            return False
        except Exception as e:
            logger.warning("connection_check_failed", host=self.config.hostname, error=str(e))
            return False
        finally:
            await self.disconnect()


class ResilientRemoteExecutor(RemoteExecutor):
    """Remote executor with automatic reconnection and retry logic."""

    def __init__(
        self,
        host_config: HostConfig,
        max_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        """Initialize the resilient remote executor.

        Args:
            host_config: Configuration for the remote host.
            max_retries: Maximum number of connection retries.
            retry_delay: Base delay between retries (exponential backoff).
        """
        super().__init__(host_config)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def run_update_with_recovery(
        self,
        plugins: list[str] | None = None,
        dry_run: bool = False,
        check_only: bool = False,
    ) -> AsyncIterator[ProgressEvent]:
        """Run update with automatic retry on connection failure.

        Args:
            plugins: Optional list of specific plugins to run.
            dry_run: If True, simulate updates without making changes.
            check_only: If True, only check for updates without applying.

        Yields:
            ProgressEvent objects as updates occur.

        Raises:
            ConnectionError: If all retry attempts fail.
        """
        retries = 0
        last_error: Exception | None = None

        while retries < self.max_retries:
            try:
                await self.connect()
                async for event in self.run_update(
                    plugins=plugins,
                    dry_run=dry_run,
                    check_only=check_only,
                ):
                    yield event
                return
            except (ConnectionError, OSError) as e:
                last_error = e
                retries += 1
                if retries >= self.max_retries:
                    break

                delay = self.retry_delay * (2 ** (retries - 1))
                logger.warning(
                    "connection_retry",
                    host=self.config.hostname,
                    attempt=retries,
                    max_retries=self.max_retries,
                    delay=delay,
                )
                yield ProgressEvent(
                    type=ProgressEventType.LOG,
                    message=f"Connection failed, retrying in {delay:.1f}s (attempt {retries}/{self.max_retries})",
                )
                await asyncio.sleep(delay)
            finally:
                await self.disconnect()

        raise ConnectionError(
            f"Failed to connect to {self.config.hostname} after {retries} attempts: {last_error}"
        )


class RemoteUpdateManager:
    """Manages updates across multiple remote hosts."""

    def __init__(self, hosts: list[HostConfig]) -> None:
        """Initialize the remote update manager.

        Args:
            hosts: List of host configurations.
        """
        self.hosts = {host.name: host for host in hosts}

    @classmethod
    def from_config_file(cls, config_path: Path) -> RemoteUpdateManager:
        """Create a RemoteUpdateManager from a YAML configuration file.

        Args:
            config_path: Path to the hosts configuration file.

        Returns:
            Configured RemoteUpdateManager.
        """
        import yaml

        if not config_path.exists():
            return cls([])

        content = config_path.read_text()
        data = yaml.safe_load(content) or {}

        hosts_data = data.get("hosts", {})
        hosts = [HostConfig.from_dict(name, host_data) for name, host_data in hosts_data.items()]

        return cls(hosts)

    def get_host(self, name: str) -> HostConfig | None:
        """Get a host configuration by name.

        Args:
            name: Host name.

        Returns:
            HostConfig if found, None otherwise.
        """
        return self.hosts.get(name)

    def get_all_hosts(self) -> list[HostConfig]:
        """Get all host configurations.

        Returns:
            List of all host configurations.
        """
        return list(self.hosts.values())

    async def run_update_single(
        self,
        host_name: str,
        plugins: list[str] | None = None,
        dry_run: bool = False,
    ) -> RemoteUpdateResult:
        """Run update on a single host.

        Args:
            host_name: Name of the host to update.
            plugins: Optional list of specific plugins to run.
            dry_run: If True, simulate updates without making changes.

        Returns:
            RemoteUpdateResult with the outcome.
        """
        host = self.get_host(host_name)
        if not host:
            return RemoteUpdateResult(
                host_name=host_name,
                success=False,
                start_time=datetime.now(),
                end_time=datetime.now(),
                error_message=f"Host '{host_name}' not found in configuration",
            )

        start_time = datetime.now()
        events: list[ProgressEvent] = []
        executor = ResilientRemoteExecutor(host)

        try:
            async for event in executor.run_update_with_recovery(
                plugins=plugins,
                dry_run=dry_run,
            ):
                events.append(event)

            success = not any(e.type == ProgressEventType.ERROR for e in events)
            return RemoteUpdateResult(
                host_name=host_name,
                success=success,
                start_time=start_time,
                end_time=datetime.now(),
                events=events,
            )
        except Exception as e:
            return RemoteUpdateResult(
                host_name=host_name,
                success=False,
                start_time=start_time,
                end_time=datetime.now(),
                error_message=str(e),
                events=events,
            )

    async def run_update_parallel(
        self,
        host_names: list[str],
        plugins: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[RemoteUpdateResult]:
        """Run updates on multiple hosts in parallel.

        Args:
            host_names: Names of hosts to update.
            plugins: Optional list of specific plugins to run.
            dry_run: If True, simulate updates without making changes.

        Returns:
            List of RemoteUpdateResult for each host.
        """
        tasks = [self.run_update_single(host_name, plugins, dry_run) for host_name in host_names]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed results
        final_results: list[RemoteUpdateResult] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                final_results.append(
                    RemoteUpdateResult(
                        host_name=host_names[i],
                        success=False,
                        start_time=datetime.now(),
                        end_time=datetime.now(),
                        error_message=str(result),
                    )
                )
            elif isinstance(result, RemoteUpdateResult):
                final_results.append(result)

        return final_results

    async def run_update_sequential(
        self,
        host_names: list[str],
        plugins: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[RemoteUpdateResult]:
        """Run updates on multiple hosts sequentially.

        Args:
            host_names: Names of hosts to update.
            plugins: Optional list of specific plugins to run.
            dry_run: If True, simulate updates without making changes.

        Returns:
            List of RemoteUpdateResult for each host.
        """
        results: list[RemoteUpdateResult] = []
        for host_name in host_names:
            result = await self.run_update_single(host_name, plugins, dry_run)
            results.append(result)
        return results

"""Tests for remote update functionality."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from core.remote import (
    HostConfig,
    ProgressEvent,
    ProgressEventType,
    RemoteExecutor,
    RemoteUpdateError,
    RemoteUpdateManager,
    RemoteUpdateResult,
    ResilientRemoteExecutor,
)


class TestHostConfig:
    """Tests for HostConfig."""

    def test_from_dict_minimal(self) -> None:
        """Test creating HostConfig from minimal dict."""
        data = {
            "hostname": "server.example.com",
            "user": "admin",
        }
        config = HostConfig.from_dict("server1", data)

        assert config.name == "server1"
        assert config.hostname == "server.example.com"
        assert config.user == "admin"
        assert config.port == 22
        assert config.key_file is None
        assert config.password is None

    def test_from_dict_full(self) -> None:
        """Test creating HostConfig from full dict."""
        data = {
            "hostname": "192.168.1.100",
            "user": "pi",
            "port": 2222,
            "key_file": "~/.ssh/id_rsa",
            "password": "secret",
            "update_all_path": "/usr/bin/update-all",
            "sudo_password_env": "PI_SUDO_PASS",
            "connect_timeout": 60.0,
        }
        config = HostConfig.from_dict("raspberry-pi", data)

        assert config.name == "raspberry-pi"
        assert config.hostname == "192.168.1.100"
        assert config.user == "pi"
        assert config.port == 2222
        assert config.key_file == Path.home() / ".ssh" / "id_rsa"
        assert config.password == "secret"
        assert config.update_all_path == "/usr/bin/update-all"
        assert config.sudo_password_env == "PI_SUDO_PASS"
        assert config.connect_timeout == 60.0


class TestProgressEvent:
    """Tests for ProgressEvent."""

    def test_from_dict_basic(self) -> None:
        """Test creating ProgressEvent from dict."""
        data = {
            "type": "progress",
            "message": "Updating packages...",
            "percent": 45.0,
        }
        event = ProgressEvent.from_dict(data)

        assert event.type == ProgressEventType.PROGRESS
        assert event.message == "Updating packages..."
        assert event.percent == 45.0

    def test_from_dict_unknown_type(self) -> None:
        """Test creating ProgressEvent with unknown type."""
        data = {
            "type": "unknown_type",
            "message": "Some message",
        }
        event = ProgressEvent.from_dict(data)

        assert event.type == ProgressEventType.LOG
        assert event.message == "Some message"

    def test_from_dict_with_plugin_name(self) -> None:
        """Test creating ProgressEvent with plugin name."""
        data = {
            "type": "plugin_started",
            "plugin_name": "apt",
            "message": "Starting apt update",
        }
        event = ProgressEvent.from_dict(data)

        assert event.type == ProgressEventType.PLUGIN_STARTED
        assert event.plugin_name == "apt"


class TestRemoteUpdateResult:
    """Tests for RemoteUpdateResult."""

    def test_success_result(self) -> None:
        """Test creating a successful result."""
        result = RemoteUpdateResult(
            host_name="server1",
            success=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

        assert result.success is True
        assert result.host_name == "server1"
        assert result.error_message is None

    def test_failed_result(self) -> None:
        """Test creating a failed result."""
        result = RemoteUpdateResult(
            host_name="server1",
            success=False,
            start_time=datetime.now(),
            error_message="Connection refused",
        )

        assert result.success is False
        assert result.error_message == "Connection refused"


class TestRemoteExecutor:
    """Tests for RemoteExecutor."""

    def test_init(self) -> None:
        """Test RemoteExecutor initialization."""
        config = HostConfig(
            name="test",
            hostname="localhost",
            user="testuser",
        )
        executor = RemoteExecutor(config)

        assert executor.config == config
        assert executor._connection is None

    @pytest.mark.asyncio
    async def test_connect_without_asyncssh(self) -> None:
        """Test connect raises error when asyncssh is not installed."""
        config = HostConfig(
            name="test",
            hostname="localhost",
            user="testuser",
        )
        executor = RemoteExecutor(config)

        # Mock asyncssh import to fail
        with (
            patch.dict("sys.modules", {"asyncssh": None}),
            pytest.raises(RemoteUpdateError, match="asyncssh is required"),
        ):
            await executor.connect()

    @pytest.mark.asyncio
    async def test_run_update_not_connected(self) -> None:
        """Test run_update raises error when not connected."""
        config = HostConfig(
            name="test",
            hostname="localhost",
            user="testuser",
        )
        executor = RemoteExecutor(config)

        with pytest.raises(RemoteUpdateError, match="Not connected"):
            async for _ in executor.run_update():
                pass


class TestResilientRemoteExecutor:
    """Tests for ResilientRemoteExecutor."""

    def test_init_with_retry_settings(self) -> None:
        """Test ResilientRemoteExecutor initialization with retry settings."""
        config = HostConfig(
            name="test",
            hostname="localhost",
            user="testuser",
        )
        executor = ResilientRemoteExecutor(
            config,
            max_retries=5,
            retry_delay=3.0,
        )

        assert executor.max_retries == 5
        assert executor.retry_delay == 3.0


class TestRemoteUpdateManager:
    """Tests for RemoteUpdateManager."""

    def test_init_with_hosts(self) -> None:
        """Test RemoteUpdateManager initialization with hosts."""
        hosts = [
            HostConfig(name="server1", hostname="s1.example.com", user="admin"),
            HostConfig(name="server2", hostname="s2.example.com", user="admin"),
        ]
        manager = RemoteUpdateManager(hosts)

        assert len(manager.hosts) == 2
        assert "server1" in manager.hosts
        assert "server2" in manager.hosts

    def test_get_host(self) -> None:
        """Test getting a host by name."""
        hosts = [
            HostConfig(name="server1", hostname="s1.example.com", user="admin"),
        ]
        manager = RemoteUpdateManager(hosts)

        host = manager.get_host("server1")
        assert host is not None
        assert host.hostname == "s1.example.com"

        assert manager.get_host("nonexistent") is None

    def test_get_all_hosts(self) -> None:
        """Test getting all hosts."""
        hosts = [
            HostConfig(name="server1", hostname="s1.example.com", user="admin"),
            HostConfig(name="server2", hostname="s2.example.com", user="admin"),
        ]
        manager = RemoteUpdateManager(hosts)

        all_hosts = manager.get_all_hosts()
        assert len(all_hosts) == 2

    def test_from_config_file_nonexistent(self, tmp_path: Path) -> None:
        """Test loading from nonexistent config file."""
        config_path = tmp_path / "hosts.yaml"
        manager = RemoteUpdateManager.from_config_file(config_path)

        assert len(manager.hosts) == 0

    def test_from_config_file(self, tmp_path: Path) -> None:
        """Test loading from config file."""
        config_path = tmp_path / "hosts.yaml"
        config_path.write_text("""
hosts:
  server1:
    hostname: s1.example.com
    user: admin
    port: 22
  server2:
    hostname: s2.example.com
    user: root
    port: 2222
""")
        manager = RemoteUpdateManager.from_config_file(config_path)

        assert len(manager.hosts) == 2
        assert manager.hosts["server1"].hostname == "s1.example.com"
        assert manager.hosts["server2"].port == 2222

    @pytest.mark.asyncio
    async def test_run_update_single_host_not_found(self) -> None:
        """Test running update on nonexistent host."""
        manager = RemoteUpdateManager([])
        result = await manager.run_update_single("nonexistent")

        assert result.success is False
        assert "not found" in result.error_message.lower()

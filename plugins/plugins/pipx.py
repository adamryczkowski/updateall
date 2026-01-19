"""Pipx package manager plugin with three-step upgrade support.

This plugin updates Python applications installed via pipx.

Official documentation:
- pipx: https://pypa.github.io/pipx/
- pipx upgrade-all: https://pypa.github.io/pipx/docs/#pipx-upgrade-all

Three-phase update mechanism:
- CHECK: Identify outdated main packages using pipx_metadata.json + pip list --outdated
- DOWNLOAD: Download main packages to cache using pip download (includes dependencies)
- EXECUTE: Install from cache using pip install --no-index --find-links

Note: pipx installs each application in its own isolated virtual environment.
Only the main package and injected packages are tracked for updates, not transitive
dependencies. pip handles dependency resolution during download and install.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from core.streaming import Phase
from plugins.base import BasePlugin

if TYPE_CHECKING:
    from core.models import PluginConfig

logger = structlog.get_logger(__name__)


# Default pipx venvs location on Linux
DEFAULT_PIPX_VENVS = Path.home() / ".local" / "share" / "pipx" / "venvs"
# Download cache location
DEFAULT_DOWNLOAD_CACHE = Path.home() / ".cache" / "updateall" / "pipx"


@dataclass
class OutdatedPackage:
    """Information about an outdated main/injected package in a pipx venv."""

    venv_name: str
    package_name: str
    current_version: str
    latest_version: str
    is_main_package: bool = True  # True if main package, False if injected
    download_size_bytes: int | None = None


@dataclass
class VenvMetadata:
    """Metadata about a pipx venv from pipx_metadata.json."""

    venv_name: str
    main_package: str
    main_package_version: str
    injected_packages: dict[str, str] = field(default_factory=dict)  # name -> version


class PipxPlugin(BasePlugin):
    """Plugin for pipx Python application manager with three-step upgrade.

    Three-phase execution:
    1. CHECK: Identify outdated packages in each pipx venv
    2. DOWNLOAD: Download updates to cache directory
    3. EXECUTE: Install from cache using offline mode

    The plugin iterates through all pipx-managed venvs and updates each
    application independently.
    """

    def __init__(
        self,
        venvs_dir: Path | None = None,
        download_cache: Path | None = None,
    ) -> None:
        """Initialize the pipx plugin.

        Args:
            venvs_dir: Path to pipx venvs directory. Defaults to ~/.local/share/pipx/venvs
            download_cache: Path to download cache. Defaults to ~/.cache/updateall/pipx
        """
        self._venvs_dir = venvs_dir or DEFAULT_PIPX_VENVS
        self._download_cache = download_cache or DEFAULT_DOWNLOAD_CACHE
        self._outdated_packages: list[OutdatedPackage] = []
        self._check_performed = False  # Track if check_for_updates() has been called

    @property
    def name(self) -> str:
        return "pipx"

    @property
    def command(self) -> str:
        return "pipx"

    @property
    def description(self) -> str:
        return "Python application installer (pipx)"

    @property
    def supports_download(self) -> bool:
        return True

    @property
    def supports_phases(self) -> bool:
        return True

    def get_interactive_command(self, dry_run: bool = False) -> list[str]:
        """Get the shell command to run for interactive mode."""
        if dry_run:
            return ["pipx", "list"]
        return ["pipx", "upgrade-all"]

    def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
        """Get commands for each execution phase.

        For pipx, we use custom logic in execute_streaming() rather than
        simple commands, because we need to iterate through each venv.
        This method returns placeholder commands for phase support detection.
        """
        if dry_run:
            return {
                Phase.CHECK: ["pipx", "list", "--json"],
            }
        return {
            Phase.CHECK: ["pipx", "list", "--json"],
            Phase.DOWNLOAD: ["echo", "Downloading pipx package updates..."],
            Phase.EXECUTE: ["echo", "Installing pipx package updates..."],
        }

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute pipx upgrade-all (legacy API)."""
        return_code, stdout, stderr = await self._run_command(
            ["pipx", "upgrade-all"],
            timeout=config.timeout_seconds,
            sudo=False,
        )

        output = f"=== pipx upgrade-all ===\n{stdout}"

        if return_code != 0:
            if "No packages to upgrade" in stderr or "already at latest" in stdout:
                return output, None
            return output, f"pipx upgrade-all failed: {stderr}"

        return output, None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from pipx output."""
        upgraded_count = len(re.findall(r"upgraded\s+\S+\s+from", output, re.IGNORECASE))
        if upgraded_count == 0:
            upgraded_count = len(re.findall(r"Package\s+'\S+'\s+upgraded", output, re.IGNORECASE))
        return upgraded_count

    # =========================================================================
    # Three-Step Upgrade Implementation
    # =========================================================================

    def _get_venv_dirs(self) -> list[Path]:
        """Get list of pipx venv directories."""
        if not self._venvs_dir.is_dir():
            return []
        return [d for d in self._venvs_dir.iterdir() if d.is_dir()]

    def _get_venv_python(self, venv_dir: Path) -> Path:
        """Get the Python executable path for a venv."""
        return venv_dir / "bin" / "python"

    def _get_venv_download_dir(self, venv_name: str) -> Path:
        """Get the download cache directory for a specific venv."""
        return self._download_cache / venv_name

    def _read_venv_metadata(self, venv_dir: Path) -> VenvMetadata | None:
        """Read pipx_metadata.json to get main package and injected packages.

        Returns:
            VenvMetadata with main package and injected packages, or None if not found.
        """
        metadata_path = venv_dir / "pipx_metadata.json"
        if not metadata_path.exists():
            return None

        try:
            with metadata_path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        main_pkg = data.get("main_package", {})
        main_name = main_pkg.get("package", "")
        main_version = main_pkg.get("package_version", "")

        if not main_name:
            return None

        # Get injected packages
        injected: dict[str, str] = {}
        for pkg_name, pkg_data in data.get("injected_packages", {}).items():
            pkg_version = pkg_data.get("package_version", "")
            if pkg_version:
                injected[pkg_name] = pkg_version

        return VenvMetadata(
            venv_name=venv_dir.name,
            main_package=main_name,
            main_package_version=main_version,
            injected_packages=injected,
        )

    async def check_for_updates(self) -> list[OutdatedPackage]:
        """Check for outdated main/injected packages in all pipx venvs.

        Only checks the main package and injected packages, not transitive dependencies.
        This matches pipx upgrade-all behavior.

        Returns:
            List of OutdatedPackage objects for main/injected packages only.
        """
        log = logger.bind(plugin=self.name)
        outdated: list[OutdatedPackage] = []

        venv_dirs = self._get_venv_dirs()
        if not venv_dirs:
            log.info("no_pipx_venvs_found", venvs_dir=str(self._venvs_dir))
            return []

        log.info("checking_pipx_venvs", count=len(venv_dirs))

        for venv_dir in venv_dirs:
            venv_name = venv_dir.name
            python_path = self._get_venv_python(venv_dir)

            if not python_path.exists():
                log.warning("venv_python_not_found", venv=venv_name)
                continue

            # Read pipx metadata to get main package and injected packages
            metadata = self._read_venv_metadata(venv_dir)
            if not metadata:
                log.warning("venv_metadata_not_found", venv=venv_name)
                continue

            # Build set of packages we care about (main + injected)
            tracked_packages: dict[str, tuple[str, bool]] = {
                metadata.main_package.lower(): (metadata.main_package_version, True)
            }
            for pkg_name, pkg_version in metadata.injected_packages.items():
                tracked_packages[pkg_name.lower()] = (pkg_version, False)

            # Run pip list --outdated --format=json
            return_code, stdout, _stderr = await self._run_command(
                [str(python_path), "-m", "pip", "list", "--outdated", "--format=json"],
                timeout=60,
            )

            if return_code != 0:
                log.debug("pip_list_failed", venv=venv_name)
                continue

            try:
                all_outdated = json.loads(stdout) if stdout.strip() else []
            except json.JSONDecodeError:
                continue

            # Filter to only main package and injected packages
            for pkg in all_outdated:
                pkg_name_lower = pkg.get("name", "").lower()
                if pkg_name_lower in tracked_packages:
                    current_version, is_main = tracked_packages[pkg_name_lower]
                    outdated.append(
                        OutdatedPackage(
                            venv_name=venv_name,
                            package_name=pkg.get("name", ""),
                            current_version=current_version,
                            latest_version=pkg.get("latest_version", ""),
                            is_main_package=is_main,
                        )
                    )

        self._outdated_packages = outdated
        self._check_performed = True
        log.info("check_complete", outdated_count=len(outdated))
        return outdated

    async def download_updates(self) -> tuple[bool, str]:
        """Download updates for main/injected packages only.

        pip download automatically includes dependencies, so we only need to
        download the main package and any injected packages.

        Returns:
            Tuple of (success, message).
        """
        log = logger.bind(plugin=self.name)

        if not self._outdated_packages:
            return True, "No packages to download"

        # Group packages by venv
        venv_packages: dict[str, list[OutdatedPackage]] = {}
        for pkg in self._outdated_packages:
            if pkg.venv_name not in venv_packages:
                venv_packages[pkg.venv_name] = []
            venv_packages[pkg.venv_name].append(pkg)

        log.info("downloading_updates", venv_count=len(venv_packages))

        errors: list[str] = []

        for venv_name, packages in venv_packages.items():
            venv_dir = self._venvs_dir / venv_name
            python_path = self._get_venv_python(venv_dir)
            download_dir = self._get_venv_download_dir(venv_name)

            # Clean up existing downloads for this venv
            if download_dir.exists():
                shutil.rmtree(download_dir)
            download_dir.mkdir(parents=True, exist_ok=True)

            # Download each main/injected package (pip includes dependencies automatically)
            for pkg in packages:
                pkg_type = "main" if pkg.is_main_package else "injected"
                log.debug(
                    "downloading_package",
                    venv=venv_name,
                    package=pkg.package_name,
                    version=pkg.latest_version,
                    type=pkg_type,
                )

                return_code, _stdout, stderr = await self._run_command(
                    [
                        str(python_path),
                        "-m",
                        "pip",
                        "download",
                        "-d",
                        str(download_dir),
                        f"{pkg.package_name}=={pkg.latest_version}",
                    ],
                    timeout=300,
                )

                if return_code != 0:
                    error_msg = f"Failed to download {pkg.package_name}: {stderr}"
                    log.warning("download_failed", package=pkg.package_name, error=stderr)
                    errors.append(error_msg)

        if errors:
            return False, "; ".join(errors)

        log.info("download_complete")
        return True, "All packages downloaded successfully"

    async def install_updates(self) -> tuple[bool, str]:
        """Install updates from downloaded cache.

        Installs main/injected packages from cache. pip handles dependency
        resolution using the downloaded wheels.

        Returns:
            Tuple of (success, message).
        """
        log = logger.bind(plugin=self.name)

        if not self._outdated_packages:
            return True, "No packages to install"

        # Group packages by venv
        venv_packages: dict[str, list[OutdatedPackage]] = {}
        for pkg in self._outdated_packages:
            if pkg.venv_name not in venv_packages:
                venv_packages[pkg.venv_name] = []
            venv_packages[pkg.venv_name].append(pkg)

        log.info("installing_updates", venv_count=len(venv_packages))

        errors: list[str] = []
        installed_count = 0

        for venv_name, packages in venv_packages.items():
            venv_dir = self._venvs_dir / venv_name
            python_path = self._get_venv_python(venv_dir)
            download_dir = self._get_venv_download_dir(venv_name)

            if not download_dir.exists():
                log.warning("download_dir_missing", venv=venv_name)
                errors.append(f"Download directory missing for {venv_name}")
                continue

            # Install each main/injected package from cache
            for pkg in packages:
                pkg_type = "main" if pkg.is_main_package else "injected"
                log.debug(
                    "installing_package",
                    venv=venv_name,
                    package=pkg.package_name,
                    version=pkg.latest_version,
                    type=pkg_type,
                )

                return_code, _stdout, stderr = await self._run_command(
                    [
                        str(python_path),
                        "-m",
                        "pip",
                        "install",
                        "--no-index",
                        f"--find-links={download_dir}",
                        "--upgrade",
                        pkg.package_name,
                    ],
                    timeout=300,
                )

                if return_code != 0:
                    error_msg = f"Failed to install {pkg.package_name}: {stderr}"
                    log.warning("install_failed", package=pkg.package_name, error=stderr)
                    errors.append(error_msg)
                else:
                    installed_count += 1

            # Cleanup download cache for this venv after successful install
            if venv_name not in [e.split(":")[0] for e in errors if ":" in e]:
                self._cleanup_venv_cache(venv_name)

        if errors:
            return False, f"Installed {installed_count} packages with errors: {'; '.join(errors)}"

        log.info("install_complete", installed_count=installed_count)
        return True, f"Successfully installed {installed_count} packages"

    def _cleanup_venv_cache(self, venv_name: str) -> None:
        """Remove downloaded artifacts for a venv after installation."""
        download_dir = self._get_venv_download_dir(venv_name)
        if download_dir.exists():
            shutil.rmtree(download_dir)
            logger.debug("cleaned_download_cache", venv=venv_name)

    def cleanup_all_cache(self) -> None:
        """Remove all downloaded artifacts."""
        if self._download_cache.exists():
            shutil.rmtree(self._download_cache)
            logger.info("cleaned_all_download_cache")

    async def download(self):
        """Download updates without applying them.

        This method implements the download phase for the three-step upgrade.
        It first checks for outdated packages, then downloads them to cache.
        """
        from datetime import UTC, datetime

        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
        )

        log = logger.bind(plugin=self.name)

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== Checking for outdated packages ===",
            stream="stdout",
        )

        # First check for updates if not already done
        if not self._outdated_packages:
            await self.check_for_updates()

        if not self._outdated_packages:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="All pipx packages are up to date - nothing to download",
                stream="stdout",
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )
            return

        # Report what we're downloading
        for pkg in self._outdated_packages:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"  {pkg.venv_name}/{pkg.package_name}: {pkg.current_version} -> {pkg.latest_version}",
                stream="stdout",
            )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Downloading {len(self._outdated_packages)} package(s)...",
            stream="stdout",
        )

        log.info("downloading_packages", count=len(self._outdated_packages))

        success, message = await self.download_updates()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=message,
            stream="stdout" if success else "stderr",
        )

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=success,
            exit_code=0 if success else 1,
            error_message=None if success else message,
        )

    # =========================================================================
    # Streaming Execution with Three Phases
    # =========================================================================

    async def _execute_update_streaming(self):
        """Execute the three-step update with streaming output."""
        from datetime import UTC, datetime

        from core.streaming import (
            CompletionEvent,
            EventType,
            OutputEvent,
            PhaseEvent,
        )

        log = logger.bind(plugin=self.name)

        # Phase 1: CHECK
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [1/3] Checking for outdated packages ===",
            stream="stdout",
        )

        # Reuse cached results if check already performed (e.g., from download phase)
        if self._check_performed:
            outdated = self._outdated_packages
            log.debug("reusing_cached_check_results", count=len(outdated))
        else:
            outdated = await self.check_for_updates()

        if not outdated:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="All pipx packages are up to date",
                stream="stdout",
            )

            yield PhaseEvent(
                event_type=EventType.PHASE_END,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                phase=Phase.CHECK,
                success=True,
            )

            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
                packages_updated=0,
            )
            return

        # Report outdated packages
        for pkg in outdated:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"  {pkg.venv_name}/{pkg.package_name}: {pkg.current_version} -> {pkg.latest_version}",
                stream="stdout",
            )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Found {len(outdated)} outdated package(s)",
            stream="stdout",
        )

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.CHECK,
            success=True,
        )

        # Phase 2: DOWNLOAD
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [2/3] Downloading package updates ===",
            stream="stdout",
        )

        download_success, download_msg = await self.download_updates()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=download_msg,
            stream="stdout" if download_success else "stderr",
        )

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.DOWNLOAD,
            success=download_success,
            error_message=None if download_success else download_msg,
        )

        if not download_success:
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=download_msg,
            )
            return

        # Phase 3: EXECUTE (Install)
        yield PhaseEvent(
            event_type=EventType.PHASE_START,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
        )

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [3/3] Installing package updates ===",
            stream="stdout",
        )

        install_success, install_msg = await self.install_updates()

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=install_msg,
            stream="stdout" if install_success else "stderr",
        )

        yield PhaseEvent(
            event_type=EventType.PHASE_END,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            phase=Phase.EXECUTE,
            success=install_success,
            error_message=None if install_success else install_msg,
        )

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=install_success,
            exit_code=0 if install_success else 1,
            packages_updated=len(outdated) if install_success else 0,
            error_message=None if install_success else install_msg,
        )

        log.info(
            "three_step_upgrade_complete",
            success=install_success,
            packages=len(outdated),
        )

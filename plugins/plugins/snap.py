"""Snap package manager plugin with three-step upgrade support.

This plugin updates Snap packages on Ubuntu and other distributions
that support the Snap package format.

Three-step upgrade process:
1. CHECK: Query Snap Store API for refresh candidates with download info
2. DOWNLOAD: Pre-download snap files to /var/lib/snapd/cache/<sha3-384>
3. INSTALL: Run `snap refresh` which uses cached files if available

This approach allows downloading during cheap internet windows even if
electricity for updates may be expensive later. Since snapd verifies
SHA3-384 hashes of cached files, if we download wrong content, snapd
will reject it and re-download, making this approach safe.

Official documentation:
- Snapcraft: https://snapcraft.io/
- snap command: https://snapcraft.io/docs/getting-started
- Managing updates: https://snapcraft.io/docs/keeping-snaps-up-to-date

Note: Requires sudo privileges for refresh and remove operations.
Download phase also requires root to write to /var/lib/snapd/cache.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from core.models import DownloadEstimate, PackageDownload, UpdateCommand
from core.mutex import StandardMutexes
from core.streaming import (
    CompletionEvent,
    EventType,
    OutputEvent,
    Phase,
    ProgressEvent,
    StreamEvent,
)
from plugins.base import BasePlugin
from plugins.snap_store import (
    SnapDownloadInfo,
    cleanup_corrupted_cache_entries,
    download_snap_to_cache,
    get_refresh_candidates,
    is_cache_complete,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from core.models import PluginConfig

logger = structlog.get_logger(__name__)


class SnapPlugin(BasePlugin):
    """Plugin for Snap package manager with three-step upgrade support.

    Supports:
    1. Three-step upgrade: check → download → install
    2. Legacy single-step: sudo snap refresh
    3. Cleanup of old disabled snap revisions
    """

    def __init__(self) -> None:
        super().__init__()
        self._candidates: list[SnapDownloadInfo] = []

    @property
    def name(self) -> str:
        return "snap"

    @property
    def command(self) -> str:
        return "snap"

    @property
    def description(self) -> str:
        return "Canonical Snap package manager"

    @property
    def sudo_commands(self) -> list[str]:
        return ["/usr/bin/snap"]

    @property
    def mutexes(self) -> dict[Phase, list[str]]:
        return {
            Phase.EXECUTE: [StandardMutexes.SNAP_LOCK],
        }

    @property
    def supports_download(self) -> bool:
        return True

    async def check_updates(self) -> list[dict[str, Any]]:
        """Check for available snap updates via Snap Store API.

        Uses the Snap Store API to get refresh candidates, bypassing the
        `snap refresh --list` command which doesn't work when automatic
        updates are blocked via /etc/hosts.
        """
        log = logger.bind(plugin=self.name)

        try:
            candidates = await get_refresh_candidates()
            self._candidates = candidates

            if not candidates:
                log.info("no_snap_updates_available")
                return []

            log.info("snap_updates_available", count=len(candidates))

            return [
                {
                    "name": c.name,
                    "version": c.version or f"rev{c.revision}",
                    "revision": c.revision,
                    "current_revision": c.current_revision,
                    "size_bytes": c.size,
                }
                for c in candidates
            ]

        except Exception as e:
            log.warning("check_updates_failed", error=str(e))
            return []

    def get_update_commands(self, dry_run: bool = False) -> list[UpdateCommand]:
        if dry_run:
            return [
                UpdateCommand(
                    cmd=["snap", "refresh", "--list"],
                    description="List available snap updates (dry run)",
                    sudo=False,
                )
            ]
        # Return empty list to use _execute_update_streaming() for full control
        return []

    async def estimate_download(self) -> DownloadEstimate | None:
        """Estimate download size by querying Snap Store API."""
        log = logger.bind(plugin=self.name)

        try:
            candidates = await get_refresh_candidates()
            self._candidates = candidates

            if not candidates:
                return None

            total_bytes = sum(c.size for c in candidates)
            packages = [
                PackageDownload(
                    name=c.name,
                    version=c.version or f"rev{c.revision}",
                    size_bytes=c.size,
                    url=c.download_url,
                )
                for c in candidates
            ]

            log.info(
                "download_estimate",
                package_count=len(candidates),
                total_bytes=total_bytes,
            )

            return DownloadEstimate(
                total_bytes=total_bytes,
                package_count=len(candidates),
                packages=packages,
            )

        except Exception as e:
            log.warning("estimate_download_failed", error=str(e))
            return None

    async def download(self) -> AsyncIterator[StreamEvent]:
        """Pre-download snaps to cache for later installation."""
        log = logger.bind(plugin=self.name)

        # Check if we have candidates from estimate_download
        if not self._candidates:
            self._candidates = await get_refresh_candidates()

        candidates = self._candidates

        if not candidates:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="No snap updates available to download.",
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

        # Check root access
        if os.geteuid() != 0:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="Error: Root access required to write to snap cache.",
                stream="stderr",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message="Root access required to write to snap cache",
            )
            return

        total_size = sum(c.size for c in candidates)
        total_downloaded = 0
        downloaded_count = 0
        failed: list[tuple[str, str]] = []

        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line=f"Downloading {len(candidates)} snap(s) to cache...",
            stream="stdout",
        )

        for i, candidate in enumerate(candidates, 1):
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"[{i}/{len(candidates)}] {candidate.name} ({candidate.format_size()})",
                stream="stdout",
            )

            snap_bytes_downloaded = 0

            def progress_callback(bytes_downloaded: int, _total_bytes: int) -> None:
                nonlocal snap_bytes_downloaded
                snap_bytes_downloaded = bytes_downloaded

            try:
                await download_snap_to_cache(candidate, progress_callback)
                downloaded_count += 1
                total_downloaded += candidate.size

                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"  ✓ Downloaded {candidate.name}",
                    stream="stdout",
                )

                # Emit progress event
                percent = (total_downloaded / total_size * 100) if total_size > 0 else 100
                yield ProgressEvent(
                    event_type=EventType.PROGRESS,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    phase=Phase.DOWNLOAD,
                    percent=percent,
                    bytes_downloaded=total_downloaded,
                    bytes_total=total_size,
                    items_completed=downloaded_count,
                    items_total=len(candidates),
                )

            except Exception as e:
                log.warning("snap_download_failed", snap=candidate.name, error=str(e))
                failed.append((candidate.name, str(e)))

                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"  ✗ Failed to download {candidate.name}: {e}",
                    stream="stderr",
                )

        # Summary
        if failed:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Downloaded {downloaded_count}/{len(candidates)} snap(s). {len(failed)} failed.",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=f"Failed to download: {', '.join(name for name, _ in failed)}",
            )
        else:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Successfully downloaded {downloaded_count} snap(s) to cache.",
                stream="stdout",
            )
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=True,
                exit_code=0,
            )

    async def _get_disabled_snap_revisions(self) -> list[tuple[str, str]]:
        """Get list of disabled snap revisions.

        Parses output of 'snap list --all' to find disabled revisions.
        Uses LANG=en_US.UTF-8 to ensure consistent "disabled" label.
        """
        log = logger.bind(plugin=self.name)

        env = os.environ.copy()
        env["LANG"] = "en_US.UTF-8"

        return_code, stdout, stderr = await self._run_command(
            ["snap", "list", "--all"],
            timeout=60,
            sudo=False,
            env=env,
        )

        if return_code != 0:
            log.warning("snap_list_failed", stderr=stderr)
            return []

        disabled_snaps: list[tuple[str, str]] = []

        for line in stdout.splitlines():
            if line.startswith("Name") or not line.strip():
                continue

            if "disabled" in line.lower():
                parts = line.split()
                if len(parts) >= 3:
                    snap_name = parts[0]
                    revision = parts[2]
                    disabled_snaps.append((snap_name, revision))
                    log.debug("found_disabled_snap", name=snap_name, revision=revision)

        return disabled_snaps

    async def _execute_update_streaming(self) -> AsyncIterator[StreamEvent]:
        """Execute snap refresh and cleanup old revisions with streaming."""
        log = logger.bind(plugin=self.name)
        collected_output: list[str] = []
        final_success = True
        final_error: str | None = None
        packages_updated = 0

        # Clean up any corrupted cache entries before refresh
        if self._candidates:
            removed = cleanup_corrupted_cache_entries(self._candidates)
            if removed:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Removed {len(removed)} corrupted cache entry(ies): {', '.join(removed)}",
                    stream="stdout",
                )

        # Check if downloads are cached
        if self._candidates:
            all_cached, missing = is_cache_complete(self._candidates)
            if all_cached:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"All {len(self._candidates)} snap(s) are pre-cached. Installation will be fast.",
                    stream="stdout",
                )
            elif missing:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Note: {len(missing)} snap(s) not cached, will download during refresh.",
                    stream="stdout",
                )

        # Step 1: Refresh all snaps
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [1/2] Refresh all snaps ===",
            stream="stdout",
        )

        log.debug("executing_snap_refresh")

        refresh_success = True
        async for event in self._run_command_streaming(
            ["snap", "refresh"],
            timeout=300,
            sudo=True,
        ):
            if isinstance(event, OutputEvent):
                collected_output.append(event.line)
                yield event
            elif isinstance(event, CompletionEvent):
                if not event.success:
                    full_output = "\n".join(collected_output)
                    if "All snaps up to date" not in full_output:
                        refresh_success = False
                        final_error = event.error_message
            else:
                yield event

        if not refresh_success:
            log.warning("snap_refresh_failed", error=final_error)
            yield CompletionEvent(
                event_type=EventType.COMPLETION,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                success=False,
                exit_code=1,
                error_message=final_error,
            )
            return

        full_output = "\n".join(collected_output)
        packages_updated = self._count_updated_packages(full_output)

        # Step 2: Remove old disabled revisions
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="",
            stream="stdout",
        )
        yield OutputEvent(
            event_type=EventType.OUTPUT,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            line="=== [2/2] Remove old snap revisions ===",
            stream="stdout",
        )

        disabled_snaps = await self._get_disabled_snap_revisions()

        if not disabled_snaps:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line="No old snap revisions to remove.",
                stream="stdout",
            )
        else:
            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Found {len(disabled_snaps)} old revision(s) to remove.",
                stream="stdout",
            )

            removed_count = 0
            for snap_name, revision in disabled_snaps:
                yield OutputEvent(
                    event_type=EventType.OUTPUT,
                    plugin_name=self.name,
                    timestamp=datetime.now(tz=UTC),
                    line=f"Removing {snap_name} revision {revision}...",
                    stream="stdout",
                )

                log.debug("removing_snap_revision", name=snap_name, revision=revision)

                return_code, _stdout, stderr = await self._run_command(
                    ["snap", "remove", snap_name, f"--revision={revision}"],
                    timeout=120,
                    sudo=True,
                )

                if return_code == 0:
                    removed_count += 1
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=f"  ✓ Removed {snap_name} revision {revision}",
                        stream="stdout",
                    )
                else:
                    log.warning(
                        "snap_remove_revision_failed",
                        name=snap_name,
                        revision=revision,
                        stderr=stderr,
                    )
                    yield OutputEvent(
                        event_type=EventType.OUTPUT,
                        plugin_name=self.name,
                        timestamp=datetime.now(tz=UTC),
                        line=f"  ✗ Failed to remove {snap_name} revision {revision}: {stderr.strip()}",
                        stream="stderr",
                    )

            yield OutputEvent(
                event_type=EventType.OUTPUT,
                plugin_name=self.name,
                timestamp=datetime.now(tz=UTC),
                line=f"Removed {removed_count}/{len(disabled_snaps)} old revision(s).",
                stream="stdout",
            )

        # Clear candidates after successful refresh
        self._candidates = []

        yield CompletionEvent(
            event_type=EventType.COMPLETION,
            plugin_name=self.name,
            timestamp=datetime.now(tz=UTC),
            success=final_success,
            exit_code=0 if final_success else 1,
            packages_updated=packages_updated,
            error_message=final_error,
        )

    async def _execute_update(self, config: PluginConfig) -> tuple[str, str | None]:
        """Execute snap refresh and cleanup (legacy API)."""
        output_parts: list[str] = []

        # Step 1: Refresh snaps
        return_code, stdout, stderr = await self._run_command(
            ["snap", "refresh"],
            timeout=config.timeout_seconds,
            sudo=True,
        )

        output_parts.append("=== snap refresh ===")
        output_parts.append(stdout)

        if (
            return_code != 0
            and "All snaps up to date" not in stdout
            and "All snaps up to date" not in stderr
        ):
            return "\n".join(output_parts), f"snap refresh failed: {stderr}"

        # Step 2: Remove old disabled revisions
        output_parts.append("")
        output_parts.append("=== Remove old snap revisions ===")

        disabled_snaps = await self._get_disabled_snap_revisions()

        if not disabled_snaps:
            output_parts.append("No old snap revisions to remove.")
        else:
            output_parts.append(f"Found {len(disabled_snaps)} old revision(s) to remove.")
            removed_count = 0

            for snap_name, revision in disabled_snaps:
                return_code, stdout, stderr = await self._run_command(
                    ["snap", "remove", snap_name, f"--revision={revision}"],
                    timeout=120,
                    sudo=True,
                )

                if return_code == 0:
                    removed_count += 1
                    output_parts.append(f"  ✓ Removed {snap_name} revision {revision}")
                else:
                    output_parts.append(
                        f"  ✗ Failed to remove {snap_name} revision {revision}: {stderr.strip()}"
                    )

            output_parts.append(f"Removed {removed_count}/{len(disabled_snaps)} old revision(s).")

        return "\n".join(output_parts), None

    def _count_updated_packages(self, output: str) -> int:
        """Count updated packages from snap output."""
        refreshed_count = len(re.findall(r"\S+\s+\S+\s+refreshed", output, re.IGNORECASE))

        if refreshed_count == 0:
            refreshed_count = len(re.findall(r"→|->", output))

        return refreshed_count

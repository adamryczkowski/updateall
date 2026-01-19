# Research: Splitting pipx Updater into Three Steps

**Date:** January 2026
**Research Status:** Complete
**Sources Consulted:** 5+ (pip documentation v25.3, PyPI JSON API docs, DeepWiki pipx docs, sqlpey.com offline installation guide, pipx source code)

## Executive Summary

This document outlines how to split the pipx package updater into three distinct phases:
1. **Check Phase** - Update lists of eligible packages with download size information
2. **Download Phase** - Download packages and dependencies without installing
3. **Install Phase** - Install previously downloaded packages

## Key Findings

### 1. Check Phase: Getting Upgradable Packages with Download Sizes

#### Approach A: Using pip's `--dry-run --report` (Recommended)

pip v25.3 provides the `--report` option that produces a detailed JSON report:

```bash
pip install --upgrade --dry-run --report - <package>
```

The JSON report includes:
- `install`: Array of `InstallationReportItem` objects for packages to be installed
- `download_info`: Information about artifacts to be downloaded (URL, hashes)
- `metadata`: Package metadata including name, version, requires_dist

**Limitation:** The `--report` output doesn't directly include file sizes. To get sizes, you need to query the PyPI JSON API.

#### Approach B: Using PyPI JSON API for Download Sizes

Query the PyPI JSON API to get package size information:

```
GET https://pypi.org/pypi/<package>/json
```

Response includes for each release file:
```json
{
  "releases": {
    "1.2.0": [
      {
        "filename": "package-1.2.0-py3-none-any.whl",
        "size": 3795,
        "url": "https://files.pythonhosted.org/...",
        "packagetype": "bdist_wheel"
      }
    ]
  }
}
```

#### Implementation Strategy for Check Phase

1. Use `pip list --outdated --format=json` to get list of outdated packages in each pipx venv
2. For each outdated package, query PyPI JSON API to get the size of the latest version
3. Sum up sizes for the main package and its dependencies
4. Return structured data with package names, current versions, new versions, and download sizes

### 2. Download Phase: Download Without Installing

#### Using `pip download`

pip provides a dedicated `download` command that downloads packages without installing:

```bash
pip download -d /path/to/download/dir <package>
```

Key options:
- `-d, --dest <dir>`: Download packages into specified directory
- `-r, --requirement <file>`: Install from requirements file
- `--no-deps`: Don't download package dependencies
- `--platform <platform>`: Download for specific platform
- `--python-version <version>`: Download for specific Python version
- `--only-binary :all:`: Only download binary wheels

#### For pipx Virtual Environments

Each pipx-managed package has its own virtual environment. To download updates:

```bash
# Get the venv's pip
~/.local/share/pipx/venvs/<package>/bin/pip download \
    -d ~/.cache/pipx/downloads/<package>/ \
    --upgrade <package>
```

### 3. Install Phase: Install from Downloaded Packages

#### Using `pip install --no-index --find-links`

Install packages from a local directory without accessing PyPI:

```bash
pip install --no-index --find-links=/path/to/download/dir <package>
```

Key options:
- `--no-index`: Ignore package index (only look at `--find-links` URLs)
- `--find-links <dir>`: Look for packages in the specified directory
- `--upgrade`: Upgrade packages to newest available version

#### For pipx Virtual Environments

```bash
~/.local/share/pipx/venvs/<package>/bin/pip install \
    --no-index \
    --find-links=~/.cache/pipx/downloads/<package>/ \
    --upgrade <package>
```

## Implementation Details for pipx Plugin

### Current pipx Architecture

Based on analysis of pipx source code (ref/pipx/):

1. **Venv class** (`src/pipx/venv.py`):
   - `upgrade_package()` method calls `pip install --upgrade`
   - Uses `_run_pip()` to execute pip commands

2. **Upgrade command** (`src/pipx/commands/upgrade.py`):
   - `upgrade_all()` iterates through all venvs
   - `_upgrade_venv()` handles individual venv upgrades
   - `_upgrade_package()` performs the actual upgrade

### Proposed Three-Step Implementation

#### Step 1: Check for Updates

```python
def check_for_updates(self) -> List[UpgradablePackage]:
    """
    Check for available updates and return download sizes.

    Returns list of UpgradablePackage with:
    - package_name: str
    - current_version: str
    - new_version: str
    - download_size_bytes: int
    """
    # 1. Get list of installed pipx packages
    venv_container = VenvContainer(paths.ctx.venvs)

    upgradable = []
    for venv_dir in venv_container.iter_venv_dirs():
        venv = Venv(venv_dir)

        # 2. Run pip list --outdated in the venv
        result = run_subprocess([
            str(venv.python_path), "-m", "pip",
            "list", "--outdated", "--format=json"
        ])
        outdated = json.loads(result.stdout)

        # 3. Query PyPI for download sizes
        for pkg in outdated:
            size = get_pypi_package_size(pkg['name'], pkg['latest_version'])
            upgradable.append(UpgradablePackage(
                package_name=pkg['name'],
                current_version=pkg['version'],
                new_version=pkg['latest_version'],
                download_size_bytes=size
            ))

    return upgradable
```

#### Step 2: Download Updates

```python
def download_updates(self, packages: List[str], download_dir: Path) -> None:
    """
    Download package updates without installing.
    """
    venv_container = VenvContainer(paths.ctx.venvs)

    for package in packages:
        venv_dir = venv_container.get_venv_dir(package)
        venv = Venv(venv_dir)

        pkg_download_dir = download_dir / package
        pkg_download_dir.mkdir(parents=True, exist_ok=True)

        # Download package and dependencies
        run_subprocess([
            str(venv.python_path), "-m", "pip",
            "download",
            "-d", str(pkg_download_dir),
            "--upgrade",
            package
        ])
```

#### Step 3: Install Updates

```python
def install_updates(self, packages: List[str], download_dir: Path) -> None:
    """
    Install previously downloaded updates.
    """
    venv_container = VenvContainer(paths.ctx.venvs)

    for package in packages:
        venv_dir = venv_container.get_venv_dir(package)
        venv = Venv(venv_dir)

        pkg_download_dir = download_dir / package

        # Install from local directory
        run_subprocess([
            str(venv.python_path), "-m", "pip",
            "install",
            "--no-index",
            f"--find-links={pkg_download_dir}",
            "--upgrade",
            package
        ])

        # Update pipx metadata
        venv.update_package_metadata(...)
```

## Helper Function: Get Package Size from PyPI

```python
import httpx

def get_pypi_package_size(package_name: str, version: str) -> int:
    """
    Query PyPI JSON API to get the download size for a specific package version.
    Returns size in bytes.
    """
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    response = httpx.get(url)
    data = response.json()

    # Find the wheel file (preferred) or source distribution
    urls = data.get('urls', [])

    # Prefer wheel over source
    for file_info in urls:
        if file_info['packagetype'] == 'bdist_wheel':
            return file_info['size']

    # Fall back to source distribution
    for file_info in urls:
        if file_info['packagetype'] == 'sdist':
            return file_info['size']

    return 0
```

## Sources Used

1. **pip documentation v25.3** - Installation Report
   - URL: https://pip.pypa.io/en/stable/reference/installation-report
   - Key info: `--report` option produces JSON with package details

2. **pip documentation v25.3** - pip download
   - URL: https://pip.pypa.io/en/stable/cli/pip_download
   - Key info: `-d, --dest` option for download directory

3. **PyPI JSON API Documentation**
   - URL: https://docs.pypi.org/api/json
   - Key info: `size` field in release file objects

4. **DeepWiki - pipx Upgrade Commands**
   - URL: https://deepwiki.com/pypa/pipx/3.4-upgrade-and-reinstall-commands
   - Key info: pipx upgrade command options

5. **sqlpey.com - Offline Python Package Installation**
   - URL: https://sqlpey.com/python/offline-python-package-installation
   - Key info: `pip install --no-index --find-links` pattern

6. **pipx Source Code** (cloned to ref/pipx/)
   - Key files: `src/pipx/venv.py`, `src/pipx/commands/upgrade.py`
   - Key info: `upgrade_package()` uses `pip install --upgrade`

## Step 4: Cleanup - Managing Downloaded Artifacts

After installation, downloaded artifacts should be cleaned up to avoid disk space waste. Additionally, stale downloads (packages that were downloaded but never installed because newer versions became available) should be automatically removed.

### 4.1 Post-Installation Cleanup

After successfully installing a package, remove its downloaded artifacts:

```python
import shutil
from pathlib import Path

def cleanup_after_install(package: str, download_dir: Path) -> None:
    """
    Remove downloaded artifacts after successful installation.

    Args:
        package: Name of the package that was installed
        download_dir: Base directory where downloads are stored
    """
    pkg_download_dir = download_dir / package

    if pkg_download_dir.exists():
        shutil.rmtree(pkg_download_dir)
        logger.info(f"Cleaned up download cache for {package}")
```

#### Updated Install Function with Cleanup

```python
def install_updates(
    self,
    packages: List[str],
    download_dir: Path,
    cleanup_after: bool = True
) -> None:
    """
    Install previously downloaded updates with optional cleanup.

    Args:
        packages: List of package names to install
        download_dir: Directory containing downloaded packages
        cleanup_after: If True, remove downloaded files after successful install
    """
    venv_container = VenvContainer(paths.ctx.venvs)

    for package in packages:
        venv_dir = venv_container.get_venv_dir(package)
        venv = Venv(venv_dir)

        pkg_download_dir = download_dir / package

        # Install from local directory
        result = run_subprocess([
            str(venv.python_path), "-m", "pip",
            "install",
            "--no-index",
            f"--find-links={pkg_download_dir}",
            "--upgrade",
            package
        ])

        if result.returncode == 0:
            # Update pipx metadata
            venv.update_package_metadata(...)

            # Cleanup downloaded artifacts
            if cleanup_after:
                cleanup_after_install(package, download_dir)
        else:
            logger.error(f"Failed to install {package}, keeping downloads for retry")
```

### 4.2 Stale Download Detection and Removal

Downloaded packages may become stale if:
1. A newer version was downloaded (superseding the old download)
2. The download was never installed and the package is no longer needed
3. The download was never installed and a newer version is now available on PyPI

#### Download Manifest Tracking

Maintain a manifest file to track downloaded packages:

```python
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, Optional

@dataclass
class DownloadRecord:
    package_name: str
    version: str
    download_time: str  # ISO 8601 format
    files: List[str]    # List of downloaded file paths
    installed: bool = False
    install_time: Optional[str] = None

class DownloadManifest:
    """Track downloaded packages and their status."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.records: Dict[str, DownloadRecord] = {}
        self._load()

    def _load(self) -> None:
        if self.manifest_path.exists():
            data = json.loads(self.manifest_path.read_text())
            for pkg_name, record_data in data.items():
                self.records[pkg_name] = DownloadRecord(**record_data)

    def _save(self) -> None:
        data = {name: asdict(record) for name, record in self.records.items()}
        self.manifest_path.write_text(json.dumps(data, indent=2))

    def record_download(self, package: str, version: str, files: List[str]) -> None:
        """Record a new download."""
        self.records[package] = DownloadRecord(
            package_name=package,
            version=version,
            download_time=datetime.now().isoformat(),
            files=files,
            installed=False
        )
        self._save()

    def mark_installed(self, package: str) -> None:
        """Mark a package as installed."""
        if package in self.records:
            self.records[package].installed = True
            self.records[package].install_time = datetime.now().isoformat()
            self._save()

    def remove_record(self, package: str) -> None:
        """Remove a package record after cleanup."""
        if package in self.records:
            del self.records[package]
            self._save()

    def get_stale_downloads(self, max_age_hours: int = 24) -> List[str]:
        """
        Get list of packages with stale downloads.

        A download is considered stale if:
        - It's older than max_age_hours and not installed
        """
        stale = []
        now = datetime.now()

        for package, record in self.records.items():
            if record.installed:
                continue

            download_time = datetime.fromisoformat(record.download_time)
            age_hours = (now - download_time).total_seconds() / 3600

            if age_hours > max_age_hours:
                stale.append(package)

        return stale
```

#### Automatic Stale Download Cleanup

```python
from datetime import datetime, timedelta

def cleanup_stale_downloads(
    download_dir: Path,
    manifest: DownloadManifest,
    max_age_hours: int = 24,
    check_for_newer: bool = True
) -> List[str]:
    """
    Remove stale downloaded packages.

    Args:
        download_dir: Base directory where downloads are stored
        manifest: Download manifest tracking downloads
        max_age_hours: Maximum age in hours before a download is considered stale
        check_for_newer: If True, also remove downloads if newer version available on PyPI

    Returns:
        List of package names that were cleaned up
    """
    cleaned = []

    # Get packages with old, uninstalled downloads
    stale_packages = manifest.get_stale_downloads(max_age_hours)

    for package in stale_packages:
        record = manifest.records[package]

        should_remove = True

        if check_for_newer:
            # Check if a newer version is available on PyPI
            try:
                latest_version = get_latest_pypi_version(package)
                if latest_version != record.version:
                    logger.info(
                        f"Removing stale download of {package} {record.version} "
                        f"(newer version {latest_version} available)"
                    )
                else:
                    # Same version still latest, might still be useful
                    should_remove = False
            except Exception:
                # If we can't check PyPI, remove anyway if too old
                pass

        if should_remove:
            pkg_download_dir = download_dir / package
            if pkg_download_dir.exists():
                shutil.rmtree(pkg_download_dir)
                manifest.remove_record(package)
                cleaned.append(package)
                logger.info(f"Removed stale download for {package}")

    return cleaned


def get_latest_pypi_version(package_name: str) -> str:
    """Get the latest version of a package from PyPI."""
    import httpx

    url = f"https://pypi.org/pypi/{package_name}/json"
    response = httpx.get(url)
    data = response.json()
    return data['info']['version']
```

### 4.3 Pre-Download Cleanup

Before downloading new packages, clean up any existing downloads for the same package (which would be outdated):

```python
def prepare_download_dir(package: str, download_dir: Path, manifest: DownloadManifest) -> Path:
    """
    Prepare download directory for a package, cleaning up any existing downloads.

    Args:
        package: Package name
        download_dir: Base download directory
        manifest: Download manifest

    Returns:
        Path to the package's download directory
    """
    pkg_download_dir = download_dir / package

    # Remove existing downloads for this package
    if pkg_download_dir.exists():
        shutil.rmtree(pkg_download_dir)
        logger.info(f"Removed existing download for {package}")

    # Remove from manifest if present
    if package in manifest.records:
        manifest.remove_record(package)

    # Create fresh directory
    pkg_download_dir.mkdir(parents=True, exist_ok=True)

    return pkg_download_dir
```

### 4.4 Scheduled Cleanup Task

Run periodic cleanup to remove stale downloads:

```python
def run_scheduled_cleanup(
    download_dir: Path,
    manifest_path: Path,
    max_age_hours: int = 24
) -> Dict[str, int]:
    """
    Run scheduled cleanup of download cache.

    This should be called periodically (e.g., daily) or before each download phase.

    Args:
        download_dir: Base download directory
        manifest_path: Path to manifest file
        max_age_hours: Maximum age for uninstalled downloads

    Returns:
        Statistics about cleanup: {'removed_packages': N, 'freed_bytes': M}
    """
    manifest = DownloadManifest(manifest_path)

    # Calculate size before cleanup
    size_before = sum(
        f.stat().st_size
        for f in download_dir.rglob('*')
        if f.is_file()
    ) if download_dir.exists() else 0

    # Perform cleanup
    cleaned = cleanup_stale_downloads(
        download_dir,
        manifest,
        max_age_hours=max_age_hours,
        check_for_newer=True
    )

    # Calculate size after cleanup
    size_after = sum(
        f.stat().st_size
        for f in download_dir.rglob('*')
        if f.is_file()
    ) if download_dir.exists() else 0

    return {
        'removed_packages': len(cleaned),
        'freed_bytes': size_before - size_after
    }
```

### 4.5 Complete Workflow with Cleanup

```python
class PipxThreeStepUpdater:
    """Complete three-step updater with cleanup."""

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir
        self.manifest_path = download_dir / "manifest.json"
        self.manifest = DownloadManifest(self.manifest_path)

    def check(self) -> List[UpgradablePackage]:
        """Step 1: Check for updates."""
        # Run stale cleanup before checking
        run_scheduled_cleanup(self.download_dir, self.manifest_path)
        return check_for_updates()

    def download(self, packages: List[str]) -> None:
        """Step 2: Download updates."""
        for package in packages:
            # Clean up any existing downloads for this package
            pkg_dir = prepare_download_dir(package, self.download_dir, self.manifest)

            # Download
            files = download_package(package, pkg_dir)

            # Record in manifest
            version = get_downloaded_version(pkg_dir, package)
            self.manifest.record_download(package, version, files)

    def install(self, packages: List[str]) -> None:
        """Step 3: Install updates with cleanup."""
        for package in packages:
            success = install_from_cache(package, self.download_dir)

            if success:
                # Mark as installed and cleanup
                self.manifest.mark_installed(package)
                cleanup_after_install(package, self.download_dir)
                self.manifest.remove_record(package)
```

## Conclusion

Splitting the pipx updater into three steps is fully achievable using pip's existing capabilities:

1. **Check**: Use `pip list --outdated` + PyPI JSON API for sizes
2. **Download**: Use `pip download -d <dir>`
3. **Install**: Use `pip install --no-index --find-links=<dir>`
4. **Cleanup**: Remove artifacts after install + periodic stale download removal

The implementation includes:
- **Post-installation cleanup**: Remove downloaded files immediately after successful installation
- **Stale download detection**: Track downloads via manifest and identify old, uninstalled packages
- **Pre-download cleanup**: Remove existing downloads before downloading newer versions
- **Scheduled cleanup**: Periodic task to remove downloads that were never installed
- **Version checking**: Remove downloads if newer versions are available on PyPI

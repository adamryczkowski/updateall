# APT Three-Step Update Process Research

**Date:** 2026-01-18
**Status:** Research Complete

## Overview

This document describes how to split the APT package manager update process into three distinct steps:
1. **CHECK**: Update package lists and determine download size
2. **DOWNLOAD**: Download packages without installing
3. **EXECUTE**: Install previously downloaded packages

## Research Sources

1. **Ask Ubuntu** - "How to get the size (Megabytes) of all packages of an update"
   - URL: https://askubuntu.com/questions/1350864/how-to-get-the-size-megabytes-of-all-packages-of-an-update
   - Key insight: Use `apt-show-versions -u` with `apt-cache show` to get package sizes

2. **Ask Ubuntu** - "Can I download updates, but not install them with apt"
   - URL: https://askubuntu.com/questions/861071/can-i-download-updates-but-not-install-them-with-apt
   - Key insight: `--download-only` downloads packages, then `--no-download --ignore-missing` installs only cached packages

3. **Debian Man Pages** - apt-get(8) Official Documentation
   - URL: https://manpages.debian.org/bookworm/apt/apt-get.8.en.html
   - Key options documented:
     - `-d, --download-only`: Download only; package files are only retrieved, not unpacked or installed
     - `--no-download`: Disables downloading of packages. Best used with `--ignore-missing` to force APT to use only the .debs it has already downloaded

4. **ditig.com** - APT Cheat Sheet (Updated 2025-05-14)
   - URL: https://www.ditig.com/apt-cheat-sheet
   - Commands reference for apt update, upgrade, and download operations

5. **Ask Ubuntu** - "How to determine the size of a package while using apt prior to downloading"
   - URL: https://askubuntu.com/questions/35956/how-to-determine-the-size-of-a-package-while-using-apt-prior-to-downloading
   - Key insight: Use `apt-cache show $package | grep '^Size: '` to get download size in bytes

## Three-Step Implementation

### Step 1: CHECK Phase - Update Package Lists

**Command:** `sudo apt update`

**Purpose:** Refresh package lists from repositories and determine what packages are upgradable.

**Getting Download Size:**
There are multiple approaches to get the download size:

#### Approach A: Using apt upgrade --dry-run (Recommended)
```bash
sudo apt update
sudo apt upgrade --dry-run
```
The dry-run output includes a line like:
```
Need to get 45.3 MB of archives.
```

#### Approach B: Using apt-cache show with apt list
```bash
# Get list of upgradable packages
apt list --upgradable 2>/dev/null | grep -v "Listing..." | cut -d'/' -f1

# For each package, get size from apt-cache
apt-cache show <package-name> | grep '^Size:'
```

#### Approach C: Using apt-show-versions (requires installation)
```bash
sudo apt-get install apt-show-versions -y
apt-show-versions -u  # Lists upgradable packages with versions
```

**Parsing the Output:**
- The `apt update` command outputs the number of upgradable packages
- Pattern to match: `(\d+) packages can be upgraded`
- The `apt upgrade --dry-run` provides download size in human-readable format

### Step 2: DOWNLOAD Phase - Download Without Installing

**Command:** `sudo apt upgrade --download-only -y`

**Purpose:** Download all package files to `/var/cache/apt/archives/` without unpacking or installing them.

**Key Points:**
- Packages are stored in `/var/cache/apt/archives/`
- Partial downloads go to `/var/cache/apt/archives/partial/`
- The `-y` flag auto-confirms the download
- This step can be run at any time (e.g., during off-peak hours)
- Configuration Item: `APT::Get::Download-Only`

### Step 3: EXECUTE Phase - Install Downloaded Packages

**Command:** `sudo apt upgrade --no-download --ignore-missing -y`

**Purpose:** Install packages using only the already-downloaded .deb files.

**Key Points:**
- `--no-download`: Disables downloading of packages
- `--ignore-missing`: If packages cannot be retrieved, hold them back and continue
- Together, these options force APT to use only cached .deb files
- Configuration Item: `APT::Get::Download`

**Alternative Command:**
```bash
sudo apt upgrade -y
```
If run after `--download-only`, APT will automatically use the cached packages (unless `apt update` was run in between and versions changed).

## Important Considerations

### Cache Invalidation
- If `apt update` is run between the DOWNLOAD and EXECUTE phases, package versions may change
- Downloaded packages may become stale if repository versions are updated
- The `--ignore-missing` flag handles this gracefully by skipping packages that don't match

### Lock Files
- APT uses lock files: `/var/lib/apt/lists/lock` and `/var/lib/dpkg/lock`
- Both CHECK and EXECUTE phases require exclusive access to these locks
- The current plugin implementation correctly uses `StandardMutexes.APT_LOCK` and `StandardMutexes.DPKG_LOCK`

### Parsing Download Size from apt upgrade --dry-run

The output of `apt upgrade --dry-run` contains:
```
Reading package lists... Done
Building dependency tree... Done
Reading state information... Done
Calculating upgrade... Done
The following packages will be upgraded:
  package1 package2 package3
X upgraded, Y newly installed, Z to remove and W not upgraded.
Need to get 45.3 MB of archives.
After this operation, 12.5 MB of additional disk space will be used.
```

**Regex patterns to extract:**
- Number of upgradable packages: `(\d+) upgraded`
- Download size: `Need to get ([\d.]+\s*[KMGT]?B) of archives`
- Disk space change: `([\d.]+\s*[KMGT]?B) of additional disk space`

## Current Implementation Status

The existing [`apt.py`](../plugins/plugins/apt.py) plugin already has a three-phase structure in [`get_phase_commands()`](../plugins/plugins/apt.py:99):

```python
def get_phase_commands(self, dry_run: bool = False) -> dict[Phase, list[str]]:
    if dry_run:
        return {
            Phase.CHECK: ["sudo", "apt", "update"],
            Phase.EXECUTE: ["sudo", "apt", "upgrade", "--dry-run"],
        }

    return {
        Phase.CHECK: ["sudo", "apt", "update"],
        Phase.DOWNLOAD: ["sudo", "apt", "upgrade", "--download-only", "-y"],
        Phase.EXECUTE: ["sudo", "apt", "upgrade", "-y"],
    }
```

**Recommended Enhancement for EXECUTE phase:**
Change the EXECUTE phase command to use `--no-download --ignore-missing` to ensure it only uses cached packages:

```python
Phase.EXECUTE: ["sudo", "apt", "upgrade", "--no-download", "--ignore-missing", "-y"],
```

## Extracting Download Size

To get the download size during the CHECK phase, we need to:

1. Run `apt update` first
2. Run `apt upgrade --dry-run` to get the summary
3. Parse the output for "Need to get X MB of archives"

**Implementation suggestion:**
Add a method to parse the dry-run output and extract:
- Number of packages to upgrade
- Total download size in bytes
- Disk space change

```python
import re

def parse_upgrade_info(output: str) -> dict:
    """Parse apt upgrade --dry-run output for upgrade information."""
    info = {
        "packages_to_upgrade": 0,
        "download_size_bytes": 0,
        "disk_space_change_bytes": 0,
    }

    # Match "X upgraded"
    match = re.search(r"(\d+) upgraded", output)
    if match:
        info["packages_to_upgrade"] = int(match.group(1))

    # Match "Need to get X MB of archives"
    match = re.search(r"Need to get ([\d.]+)\s*([KMGT]?B)", output)
    if match:
        size = float(match.group(1))
        unit = match.group(2)
        multipliers = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        # Handle "kB" as KB
        unit = unit.upper().replace("KB", "KB")
        info["download_size_bytes"] = int(size * multipliers.get(unit, 1))

    return info
```

## Summary

| Phase | Command | Purpose |
|-------|---------|---------|
| CHECK | `sudo apt update` | Refresh package lists |
| CHECK (info) | `sudo apt upgrade --dry-run` | Get upgrade count and download size |
| DOWNLOAD | `sudo apt upgrade --download-only -y` | Download packages to cache |
| EXECUTE | `sudo apt upgrade --no-download --ignore-missing -y` | Install cached packages |

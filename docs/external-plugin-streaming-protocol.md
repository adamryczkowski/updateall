# External Plugin Streaming Protocol

**Version:** 1.0
**Date:** January 2026
**Status:** Stable

---

## Overview

This document defines the streaming protocol for external executable plugins in Update-All. External plugins are standalone executables (scripts or binaries) that communicate with Update-All through stdout/stderr streams.

The streaming protocol enables:
- **Real-time output** — Display plugin output as it's generated
- **Progress tracking** — Report download and execution progress
- **Phase awareness** — Track which phase (check, download, execute) is running
- **Backward compatibility** — Non-streaming plugins continue to work

## Quick Start

### Minimal Streaming Plugin (Bash)

```bash
#!/bin/bash
# my-plugin update

echo "Starting update..."

# Report progress (optional)
echo 'PROGRESS:{"phase":"execute","percent":50,"message":"Installing packages..."}' >&2

echo "Update complete!"
exit 0
```

### Minimal Streaming Plugin (Python)

```python
#!/usr/bin/env python3
import json
import sys

def progress(phase: str, percent: float, message: str) -> None:
    """Emit a progress event to stderr."""
    event = {"phase": phase, "percent": percent, "message": message}
    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr)

print("Starting update...")
progress("execute", 50, "Installing packages...")
print("Update complete!")
sys.exit(0)
```

---

## Protocol Specification

### Stream Usage

| Stream | Purpose | Format |
|--------|---------|--------|
| **stdout** | Regular output lines | Plain text, one line at a time |
| **stderr** | Progress events | `PROGRESS:` prefix + JSON (one per line) |
| **stderr** | Error messages | Plain text (lines without `PROGRESS:` prefix) |

### Progress Event Format

Progress events are JSON objects prefixed with `PROGRESS:` and written to stderr:

```
PROGRESS:{"type":"progress","phase":"download","percent":45,"message":"Downloading..."}
```

**Important:** Each progress event must be on a single line (no newlines within the JSON).

### Event Types

#### Progress Event

Reports progress during execution.

```json
{
  "type": "progress",
  "phase": "download|execute|check",
  "percent": 45.5,
  "message": "Downloading package-name...",
  "bytes_downloaded": 15000000,
  "bytes_total": 33000000,
  "items_completed": 3,
  "items_total": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | No | Always `"progress"` (can be omitted) |
| `phase` | string | Yes | Current phase: `"check"`, `"download"`, or `"execute"` |
| `percent` | number | No | Progress percentage (0-100) |
| `message` | string | No | Human-readable status message |
| `bytes_downloaded` | integer | No | Bytes downloaded so far |
| `bytes_total` | integer | No | Total bytes to download |
| `items_completed` | integer | No | Items (packages) completed |
| `items_total` | integer | No | Total items to process |

#### Phase Start Event

Signals the start of a phase.

```json
{
  "type": "phase_start",
  "phase": "download"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"phase_start"` |
| `phase` | string | Yes | Phase starting: `"check"`, `"download"`, or `"execute"` |

#### Phase End Event

Signals the end of a phase.

```json
{
  "type": "phase_end",
  "phase": "download",
  "success": true,
  "error": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | Yes | Must be `"phase_end"` |
| `phase` | string | Yes | Phase ending: `"check"`, `"download"`, or `"execute"` |
| `success` | boolean | Yes | Whether the phase succeeded |
| `error` | string | No | Error message if `success` is `false` |

---

## CLI Commands

External plugins must support the following CLI commands:

### Required Commands

| Command | Description | Exit Code |
|---------|-------------|-----------|
| `is-applicable` | Check if plugin can run on this system | 0=yes, 1=no |
| `update` | Execute the update process | 0=success, non-zero=failure |

### Optional Commands

| Command | Description | Exit Code |
|---------|-------------|-----------|
| `estimate-update` | Estimate update time/size | 0=success, outputs JSON |
| `can-separate-download` | Check if download is separate | 0=yes, 1=no |
| `download` | Download updates only | 0=success, non-zero=failure |
| `does-require-sudo` | Check if sudo is needed | 0=yes, 1=no |
| `sudo-programs-paths` | List programs needing sudo | 0=success, outputs paths |
| `self-update` | Update the plugin itself | 0=success, non-zero=failure |
| `self-upgrade` | Major version upgrade | 0=success, non-zero=failure |
| `get-dependency` | Get plugin dependencies | 0=success, outputs JSON |
| `get-mutexes` | Get mutex requirements | 0=success, outputs JSON |

### Command Output Formats

#### estimate-update

```json
{
  "status": "success",
  "data": {
    "total_bytes": 95000000,
    "package_count": 12,
    "estimated_seconds": 120,
    "packages": [
      {
        "name": "python3.12",
        "version": "3.12.2",
        "size_bytes": 15000000
      }
    ]
  }
}
```

#### get-dependency

```json
{
  "dependencies": ["apt"],
  "conflicts": ["snap"]
}
```

#### get-mutexes

```json
{
  "mutexes": ["dpkg", "apt-lists"]
}
```

---

## Examples

### Complete Bash Plugin

```bash
#!/bin/bash
# example-plugin - A complete streaming plugin example
#
# Usage: example-plugin <command>
# Commands:
#   is-applicable       Check if this plugin can run
#   update              Run the update process
#   can-separate-download  Check if download is separate
#   download            Download updates only
#   does-require-sudo   Check if sudo is needed
#   estimate-update     Estimate update size/time

set -euo pipefail

# Helper function to emit progress events
progress() {
    local phase="$1"
    local percent="$2"
    local message="$3"
    echo "PROGRESS:{\"phase\":\"$phase\",\"percent\":$percent,\"message\":\"$message\"}" >&2
}

# Helper function to emit phase events
phase_start() {
    echo "PROGRESS:{\"type\":\"phase_start\",\"phase\":\"$1\"}" >&2
}

phase_end() {
    local phase="$1"
    local success="$2"
    echo "PROGRESS:{\"type\":\"phase_end\",\"phase\":\"$phase\",\"success\":$success}" >&2
}

# Check if the plugin is applicable
cmd_is_applicable() {
    # Check if our package manager exists
    if command -v example-pkg &> /dev/null; then
        exit 0
    else
        exit 1
    fi
}

# Check if we need sudo
cmd_does_require_sudo() {
    # This plugin requires sudo
    exit 0
}

# Check if download can be separate
cmd_can_separate_download() {
    # We support separate download
    exit 0
}

# Estimate update size
cmd_estimate_update() {
    cat << 'EOF'
{
  "status": "success",
  "data": {
    "total_bytes": 50000000,
    "package_count": 5,
    "estimated_seconds": 60
  }
}
EOF
    exit 0
}

# Download updates only
cmd_download() {
    phase_start "download"

    echo "Fetching package lists..."
    progress "download" 10 "Fetching package lists..."
    sleep 1

    echo "Downloading package 1/3..."
    progress "download" 40 "Downloading package 1/3..."
    sleep 1

    echo "Downloading package 2/3..."
    progress "download" 70 "Downloading package 2/3..."
    sleep 1

    echo "Downloading package 3/3..."
    progress "download" 100 "Download complete"
    sleep 0.5

    phase_end "download" "true"
    exit 0
}

# Run the update
cmd_update() {
    phase_start "execute"

    echo "Starting example-plugin update..."
    progress "execute" 0 "Starting update..."

    # Simulate update steps
    for i in 1 2 3 4 5; do
        percent=$((i * 20))
        echo "Installing package $i/5..."
        progress "execute" "$percent" "Installing package $i/5..."
        sleep 1
    done

    echo "Update complete!"
    phase_end "execute" "true"
    exit 0
}

# Main command dispatcher
case "${1:-}" in
    is-applicable)
        cmd_is_applicable
        ;;
    does-require-sudo)
        cmd_does_require_sudo
        ;;
    can-separate-download)
        cmd_can_separate_download
        ;;
    estimate-update)
        cmd_estimate_update
        ;;
    download)
        cmd_download
        ;;
    update)
        cmd_update
        ;;
    *)
        echo "Usage: $0 <command>" >&2
        echo "Commands: is-applicable, update, download, estimate-update" >&2
        exit 1
        ;;
esac
```

### Complete Python Plugin

```python
#!/usr/bin/env python3
"""Example streaming plugin in Python.

Usage: example-plugin.py <command>
Commands:
    is-applicable       Check if this plugin can run
    update              Run the update process
    can-separate-download  Check if download is separate
    download            Download updates only
    does-require-sudo   Check if sudo is needed
    estimate-update     Estimate update size/time
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from typing import Any


def emit_progress(
    phase: str,
    percent: float | None = None,
    message: str | None = None,
    bytes_downloaded: int | None = None,
    bytes_total: int | None = None,
    items_completed: int | None = None,
    items_total: int | None = None,
) -> None:
    """Emit a progress event to stderr."""
    event: dict[str, Any] = {"phase": phase}

    if percent is not None:
        event["percent"] = percent
    if message is not None:
        event["message"] = message
    if bytes_downloaded is not None:
        event["bytes_downloaded"] = bytes_downloaded
    if bytes_total is not None:
        event["bytes_total"] = bytes_total
    if items_completed is not None:
        event["items_completed"] = items_completed
    if items_total is not None:
        event["items_total"] = items_total

    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def emit_phase_start(phase: str) -> None:
    """Emit a phase start event."""
    event = {"type": "phase_start", "phase": phase}
    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def emit_phase_end(phase: str, success: bool, error: str | None = None) -> None:
    """Emit a phase end event."""
    event: dict[str, Any] = {
        "type": "phase_end",
        "phase": phase,
        "success": success,
    }
    if error:
        event["error"] = error
    print(f"PROGRESS:{json.dumps(event)}", file=sys.stderr, flush=True)


def cmd_is_applicable() -> int:
    """Check if the plugin is applicable."""
    # Check if our package manager exists
    if shutil.which("example-pkg"):
        return 0
    return 1


def cmd_does_require_sudo() -> int:
    """Check if sudo is required."""
    # This plugin requires sudo
    return 0


def cmd_can_separate_download() -> int:
    """Check if download can be separate from install."""
    return 0  # Yes, we support separate download


def cmd_estimate_update() -> int:
    """Estimate update size and time."""
    estimate = {
        "status": "success",
        "data": {
            "total_bytes": 50_000_000,
            "package_count": 5,
            "estimated_seconds": 60,
            "packages": [
                {"name": "package-a", "version": "1.2.3", "size_bytes": 10_000_000},
                {"name": "package-b", "version": "2.0.0", "size_bytes": 15_000_000},
                {"name": "package-c", "version": "3.1.4", "size_bytes": 25_000_000},
            ],
        },
    }
    print(json.dumps(estimate))
    return 0


def cmd_download() -> int:
    """Download updates without installing."""
    emit_phase_start("download")

    total_bytes = 50_000_000
    packages = ["package-a", "package-b", "package-c"]

    for i, pkg in enumerate(packages):
        bytes_done = (i + 1) * (total_bytes // len(packages))
        percent = ((i + 1) / len(packages)) * 100

        print(f"Downloading {pkg}...")
        emit_progress(
            phase="download",
            percent=percent,
            message=f"Downloading {pkg}...",
            bytes_downloaded=bytes_done,
            bytes_total=total_bytes,
            items_completed=i + 1,
            items_total=len(packages),
        )
        time.sleep(1)  # Simulate download time

    print("Download complete!")
    emit_phase_end("download", success=True)
    return 0


def cmd_update() -> int:
    """Run the update process."""
    emit_phase_start("execute")

    print("Starting update...")
    emit_progress("execute", percent=0, message="Starting update...")

    packages = ["package-a", "package-b", "package-c", "package-d", "package-e"]

    for i, pkg in enumerate(packages):
        percent = ((i + 1) / len(packages)) * 100

        print(f"Installing {pkg}...")
        emit_progress(
            phase="execute",
            percent=percent,
            message=f"Installing {pkg}...",
            items_completed=i + 1,
            items_total=len(packages),
        )
        time.sleep(0.5)  # Simulate install time

    print("Update complete!")
    emit_phase_end("execute", success=True)
    return 0


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: example-plugin.py <command>", file=sys.stderr)
        print("Commands: is-applicable, update, download, estimate-update", file=sys.stderr)
        return 1

    command = sys.argv[1]

    commands = {
        "is-applicable": cmd_is_applicable,
        "does-require-sudo": cmd_does_require_sudo,
        "can-separate-download": cmd_can_separate_download,
        "estimate-update": cmd_estimate_update,
        "download": cmd_download,
        "update": cmd_update,
    }

    if command not in commands:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1

    return commands[command]()


if __name__ == "__main__":
    sys.exit(main())
```

---

## Validation

Use the `update-all plugins validate` command to validate your plugin:

```bash
# Validate a plugin
update-all plugins validate /path/to/my-plugin

# Validate with verbose output
update-all plugins validate /path/to/my-plugin --verbose

# Test streaming output
update-all plugins validate /path/to/my-plugin --test-streaming
```

The validator checks:
1. Plugin is executable
2. Required commands work (`is-applicable`, `update`)
3. Progress events are valid JSON
4. Exit codes are correct
5. Streaming output is properly formatted

---

## Best Practices

### 1. Always Flush Output

Ensure output is flushed immediately for real-time display:

**Bash:**
```bash
# Output is line-buffered by default, which is fine
echo "Progress message"
```

**Python:**
```python
# Use flush=True or run with PYTHONUNBUFFERED=1
print("Progress message", flush=True)
```

### 2. Use Meaningful Progress Percentages

Report progress that reflects actual work done:

```python
# Good: Progress reflects actual packages
for i, pkg in enumerate(packages):
    percent = ((i + 1) / len(packages)) * 100
    emit_progress("execute", percent, f"Installing {pkg}...")

# Bad: Arbitrary progress values
emit_progress("execute", 50, "Doing stuff...")
```

### 3. Handle Errors Gracefully

Report errors through phase end events:

```python
try:
    # Do work
    emit_phase_end("execute", success=True)
except Exception as e:
    emit_phase_end("execute", success=False, error=str(e))
    return 1
```

### 4. Support Dry Run Mode

Check for `--dry-run` flag in the update command:

```bash
cmd_update() {
    if [[ "${2:-}" == "--dry-run" ]]; then
        echo "Dry run - would update 5 packages"
        exit 0
    fi
    # Actual update logic
}
```

### 5. Provide Accurate Estimates

The `estimate-update` command helps users plan:

```python
def cmd_estimate_update():
    # Query the actual package manager for accurate info
    packages = get_pending_updates()
    total_size = sum(p.size for p in packages)

    return {
        "total_bytes": total_size,
        "package_count": len(packages),
        "estimated_seconds": total_size / DOWNLOAD_SPEED,
    }
```

---

## Backward Compatibility

Plugins that don't emit progress events continue to work:
- Output is displayed after command completion
- UI shows "legacy mode" indicator
- No progress bar is displayed

To enable streaming, simply add `PROGRESS:` prefixed lines to stderr.

---

## Troubleshooting

### Progress Events Not Showing

1. Ensure events go to **stderr**, not stdout
2. Check JSON is valid (use a JSON validator)
3. Ensure each event is on a single line
4. Verify the `PROGRESS:` prefix is present

### Output Buffering Issues

1. Disable output buffering in your language
2. Flush after each print statement
3. Use line-buffered mode for stderr

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | General failure |
| 2 | Invalid arguments |
| 3 | Not applicable (for `is-applicable`) |
| 124 | Timeout (if using `timeout` command) |

---

## See Also

- [Plugin Development Guide](plugin-development.md) — Complete plugin development documentation
- [Architecture Refinement Plan](update-all-architecture-refinement-plan.md) — Streaming architecture details
- [Core Streaming Module](../core/core/streaming.py) — Python streaming implementation

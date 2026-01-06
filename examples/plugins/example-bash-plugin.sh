#!/bin/bash
# example-bash-plugin.sh - Example streaming plugin in Bash
#
# This is a complete example of an external Update-All plugin that
# demonstrates the streaming protocol for real-time output.
#
# Usage: example-bash-plugin.sh <command>
#
# Commands:
#   is-applicable         Check if this plugin can run on this system
#   does-require-sudo     Check if sudo is required
#   can-separate-download Check if download is separate from install
#   estimate-update       Estimate update size and time
#   download              Download updates only
#   update [--dry-run]    Run the update process
#
# Streaming Protocol:
#   - stdout: Regular output lines (displayed to user)
#   - stderr: Progress events as JSON with PROGRESS: prefix
#
# For more information, see docs/external-plugin-streaming-protocol.md

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

PLUGIN_NAME="example-bash"
PLUGIN_VERSION="1.0.0"

# Simulated packages for demonstration
PACKAGES=("package-alpha" "package-beta" "package-gamma" "package-delta" "package-epsilon")
PACKAGE_SIZES=(10000000 15000000 25000000 8000000 12000000)  # bytes

# =============================================================================
# Helper Functions
# =============================================================================

# Emit a progress event to stderr
# Usage: progress <phase> <percent> <message> [bytes_downloaded] [bytes_total]
progress() {
    local phase="$1"
    local percent="$2"
    local message="$3"
    local bytes_downloaded="${4:-}"
    local bytes_total="${5:-}"

    local json="{\"phase\":\"$phase\",\"percent\":$percent,\"message\":\"$message\""

    if [[ -n "$bytes_downloaded" ]]; then
        json="$json,\"bytes_downloaded\":$bytes_downloaded"
    fi
    if [[ -n "$bytes_total" ]]; then
        json="$json,\"bytes_total\":$bytes_total"
    fi

    json="$json}"
    echo "PROGRESS:$json" >&2
}

# Emit a phase start event
phase_start() {
    local phase="$1"
    echo "PROGRESS:{\"type\":\"phase_start\",\"phase\":\"$phase\"}" >&2
}

# Emit a phase end event
phase_end() {
    local phase="$1"
    local success="$2"
    local error="${3:-}"

    local json="{\"type\":\"phase_end\",\"phase\":\"$phase\",\"success\":$success"
    if [[ -n "$error" ]]; then
        json="$json,\"error\":\"$error\""
    fi
    json="$json}"
    echo "PROGRESS:$json" >&2
}

# Calculate total size of all packages
get_total_size() {
    local total=0
    for size in "${PACKAGE_SIZES[@]}"; do
        total=$((total + size))
    done
    echo "$total"
}

# =============================================================================
# Commands
# =============================================================================

# Check if the plugin is applicable on this system
cmd_is_applicable() {
    # For this example, we're always applicable
    # In a real plugin, you would check if the package manager exists:
    # if command -v my-package-manager &> /dev/null; then
    #     exit 0
    # else
    #     exit 1
    # fi
    exit 0
}

# Check if sudo is required
cmd_does_require_sudo() {
    # This example plugin doesn't require sudo
    exit 1  # Exit 1 = no sudo required
}

# Check if download can be separate from install
cmd_can_separate_download() {
    # We support separate download
    exit 0  # Exit 0 = yes, download can be separate
}

# Estimate update size and time
cmd_estimate_update() {
    local total_size
    total_size=$(get_total_size)
    local package_count=${#PACKAGES[@]}

    # Build packages JSON array
    local packages_json="["
    for i in "${!PACKAGES[@]}"; do
        if [[ $i -gt 0 ]]; then
            packages_json="$packages_json,"
        fi
        packages_json="$packages_json{\"name\":\"${PACKAGES[$i]}\",\"version\":\"1.0.$i\",\"size_bytes\":${PACKAGE_SIZES[$i]}}"
    done
    packages_json="$packages_json]"

    cat << EOF
{
  "status": "success",
  "data": {
    "total_bytes": $total_size,
    "package_count": $package_count,
    "estimated_seconds": 30,
    "packages": $packages_json
  }
}
EOF
    exit 0
}

# Download updates only (without installing)
cmd_download() {
    phase_start "download"

    local total_size
    total_size=$(get_total_size)
    local bytes_downloaded=0
    local package_count=${#PACKAGES[@]}

    echo "Starting download of $package_count packages..."

    for i in "${!PACKAGES[@]}"; do
        local pkg="${PACKAGES[$i]}"
        local size="${PACKAGE_SIZES[$i]}"

        echo "Downloading $pkg..."

        # Simulate download progress
        for step in 25 50 75 100; do
            local step_bytes=$((size * step / 100))
            local current_total=$((bytes_downloaded + step_bytes))
            local percent=$((current_total * 100 / total_size))

            progress "download" "$percent" "Downloading $pkg... ($step%)" "$current_total" "$total_size"
            sleep 0.2
        done

        bytes_downloaded=$((bytes_downloaded + size))
        echo "  Downloaded $pkg ($(numfmt --to=iec-i --suffix=B $size 2>/dev/null || echo "${size} bytes"))"
    done

    echo "Download complete!"
    phase_end "download" "true"
    exit 0
}

# Run the update process
cmd_update() {
    local dry_run=false

    # Check for --dry-run flag
    if [[ "${1:-}" == "--dry-run" ]]; then
        dry_run=true
    fi

    if [[ "$dry_run" == "true" ]]; then
        echo "Dry run mode - no changes will be made"
        echo ""
        echo "Would update the following packages:"
        for pkg in "${PACKAGES[@]}"; do
            echo "  - $pkg"
        done
        echo ""
        echo "Total: ${#PACKAGES[@]} packages"
        exit 0
    fi

    phase_start "execute"

    local package_count=${#PACKAGES[@]}
    echo "Starting update of $package_count packages..."
    echo ""

    for i in "${!PACKAGES[@]}"; do
        local pkg="${PACKAGES[$i]}"
        local pkg_num=$((i + 1))
        local percent=$((pkg_num * 100 / package_count))

        echo "[$pkg_num/$package_count] Installing $pkg..."
        progress "execute" "$percent" "Installing $pkg..." "" "" "$pkg_num" "$package_count"

        # Simulate installation time
        sleep 0.5

        echo "  ✓ $pkg installed successfully"
    done

    echo ""
    echo "Update complete! $package_count packages updated."

    phase_end "execute" "true"
    exit 0
}

# Show help
cmd_help() {
    cat << EOF
$PLUGIN_NAME v$PLUGIN_VERSION - Example Update-All Plugin

Usage: $0 <command> [options]

Commands:
  is-applicable         Check if this plugin can run on this system
  does-require-sudo     Check if sudo is required (exit 0=yes, 1=no)
  can-separate-download Check if download is separate (exit 0=yes, 1=no)
  estimate-update       Estimate update size and time (JSON output)
  download              Download updates only
  update [--dry-run]    Run the update process

Options:
  --dry-run             Simulate update without making changes

Examples:
  $0 is-applicable
  $0 update --dry-run
  $0 download
  $0 update

For more information, see docs/external-plugin-streaming-protocol.md
EOF
    exit 0
}

# =============================================================================
# Main Entry Point
# =============================================================================

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
        shift
        cmd_update "$@"
        ;;
    help|--help|-h)
        cmd_help
        ;;
    *)
        echo "Error: Unknown command '${1:-}'" >&2
        echo "Run '$0 help' for usage information." >&2
        exit 1
        ;;
esac

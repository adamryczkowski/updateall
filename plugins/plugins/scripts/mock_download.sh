#!/bin/bash
# Mock plugin DOWNLOAD phase - simulates downloading packages
# Uses real network downloads to test update-all's resource estimation

set -e

PLUGIN_NAME="${1:-mock}"
DRY_RUN="${2:-false}"

echo "*** ${PLUGIN_NAME^^} - DOWNLOAD PHASE ***"
echo ""
echo "[${PLUGIN_NAME}] Downloading packages..."
echo ""

# Determine parameters based on dry_run
if [ "$DRY_RUN" = "true" ]; then
    ITERATIONS=2
    DOWNLOAD_SIZE=500000  # 500KB per package
else
    ITERATIONS=5
    DOWNLOAD_SIZE=2000000  # 2MB per package
fi

TOTAL_DOWNLOADED=0

# Spawn multiple download processes
for i in $(seq 1 $ITERATIONS); do
    echo "[${PLUGIN_NAME}] Downloading package $i of $ITERATIONS..."

    # Create a temp file for this download
    TMPFILE=$(mktemp)

    # Real network download with progress
    curl -s -o "$TMPFILE" "https://httpbin.org/bytes/${DOWNLOAD_SIZE}" &
    CURL_PID=$!

    # Spawn additional child process for parallel download simulation
    curl -s -o /dev/null "https://httpbin.org/bytes/$((DOWNLOAD_SIZE / 4))" &
    CURL_PID2=$!

    # Light CPU work during download (checksum verification simulation)
    openssl dgst -sha256 /dev/null >/dev/null 2>&1 &

    # Wait for downloads
    wait $CURL_PID 2>/dev/null || true
    wait $CURL_PID2 2>/dev/null || true

    # Get actual file size
    if [ -f "$TMPFILE" ]; then
        FILE_SIZE=$(stat -c%s "$TMPFILE" 2>/dev/null || echo "$DOWNLOAD_SIZE")
        TOTAL_DOWNLOADED=$((TOTAL_DOWNLOADED + FILE_SIZE))
        rm -f "$TMPFILE"
    fi

    echo "[${PLUGIN_NAME}] Package $i downloaded ($(($FILE_SIZE / 1024)) KB)"
done

echo ""
echo "[${PLUGIN_NAME}] DOWNLOAD PHASE COMPLETE"
echo "Downloaded: $((TOTAL_DOWNLOADED / 1024)) KB"
echo "Packages ready for installation: $ITERATIONS"
echo ""

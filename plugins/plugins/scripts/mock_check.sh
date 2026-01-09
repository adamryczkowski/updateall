#!/bin/bash
# Mock plugin CHECK phase - simulates checking for updates
# Uses real CPU and network to test update-all's resource estimation

set -e

PLUGIN_NAME="${1:-mock}"
DRY_RUN="${2:-false}"

echo "*** ${PLUGIN_NAME^^} - CHECK PHASE (Update) ***"
echo ""
echo "[${PLUGIN_NAME}] Scanning for available updates..."
echo ""

# Determine iteration count based on dry_run
if [ "$DRY_RUN" = "true" ]; then
    ITERATIONS=2
    DOWNLOAD_SIZE=10000  # 10KB
else
    ITERATIONS=4
    DOWNLOAD_SIZE=100000  # 100KB
fi

# Spawn child processes for realistic process tree
for i in $(seq 1 $ITERATIONS); do
    echo "[${PLUGIN_NAME}] Checking repository $i of $ITERATIONS..."

    # Real network download (small, just metadata simulation)
    curl -s -o /dev/null "https://httpbin.org/bytes/${DOWNLOAD_SIZE}" &
    CURL_PID=$!

    # Real CPU work using openssl (spawn as child process, suppress all output)
    openssl speed -seconds 1 sha256 >/dev/null 2>&1 &
    OPENSSL_PID=$!

    # Wait for both
    wait $CURL_PID 2>/dev/null || true
    wait $OPENSSL_PID 2>/dev/null || true

    echo "[${PLUGIN_NAME}] Repository $i checked."
done

echo ""
echo "[${PLUGIN_NAME}] CHECK PHASE COMPLETE"
echo "Found 12 packages to update"
echo ""
echo "ESTIMATED RESOURCES FOR REMAINING PHASES:"
echo "  DOWNLOAD phase: ~50 MB download, ~5% CPU"
echo "  UPGRADE phase:  ~2 MB download, ~80% CPU for 30s"
echo ""
echo "Total estimated: 52 MB download, 35s CPU time"
echo ""

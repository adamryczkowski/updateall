#!/bin/bash
# Mock plugin EXECUTE phase - simulates installing/upgrading packages
# Uses real CPU load to test update-all's resource estimation

set -e

PLUGIN_NAME="${1:-mock}"
DRY_RUN="${2:-false}"

echo "*** ${PLUGIN_NAME^^} - EXECUTE PHASE (Upgrade) ***"
echo ""
echo "[${PLUGIN_NAME}] Installing packages..."
echo ""

# Determine parameters based on dry_run
if [ "$DRY_RUN" = "true" ]; then
    ITERATIONS=2
    CPU_SECONDS=1
else
    ITERATIONS=6
    CPU_SECONDS=3
fi

# Function to generate CPU load with child processes
generate_cpu_load() {
    local seconds=$1
    local name=$2

    # Spawn multiple openssl processes for CPU load (suppress all output)
    for j in $(seq 1 3); do
        openssl speed -seconds "$seconds" aes-256-cbc >/dev/null 2>&1 &
    done

    # Also spawn a sha256 process
    openssl speed -seconds "$seconds" sha256 >/dev/null 2>&1 &

    # Wait for all background jobs
    wait
}

# Function to allocate memory (using Python for portability)
allocate_memory() {
    local mb=$1
    python3 -c "
import time
# Allocate ${mb}MB of memory
data = bytearray($mb * 1024 * 1024)
# Touch the memory to ensure it's allocated
for i in range(0, len(data), 4096):
    data[i] = 1
time.sleep(1)
" &
}

for i in $(seq 1 $ITERATIONS); do
    echo "[${PLUGIN_NAME}] Installing package $i of $ITERATIONS..."

    # Allocate some memory (simulating package extraction)
    allocate_memory 50 &
    MEM_PID=$!

    # Heavy CPU work (simulating compilation/installation)
    echo "[${PLUGIN_NAME}] Compiling package $i..."
    generate_cpu_load $CPU_SECONDS "pkg$i"

    # Small network request (config file download)
    curl -s -o /dev/null "https://httpbin.org/bytes/10000" &

    # Wait for memory process
    wait $MEM_PID 2>/dev/null || true

    echo "[${PLUGIN_NAME}] Package $i installed."
done

echo ""
echo "*** ${PLUGIN_NAME^^} COMPLETED! ***"
echo ""
echo "FINAL STATISTICS:"
echo "  Packages updated: $ITERATIONS"
echo "  Total download: ~52 MB"
echo "  CPU time: ~$((ITERATIONS * CPU_SECONDS * 4)) seconds"
echo ""
echo "[${PLUGIN_NAME}] Finished successfully!"

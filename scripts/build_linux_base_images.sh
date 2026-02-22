#!/usr/bin/env bash
# Build ccb-linux-base Docker images for the 5 Linux fault-localization tasks.
#
# Each image contains gcc:13, python3, standard tools, and the Linux kernel
# source at a specific tag placed at /workspace.
#
# Usage:
#   ./scripts/build_linux_base_images.sh              # build all 5
#   ./scripts/build_linux_base_images.sh v5.6.7       # build one
#   ./scripts/build_linux_base_images.sh --list        # show required tags
#
# Time: ~5-10 minutes per image (shallow clone of Linux kernel).
# Disk: ~1-2 GB per image.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# The 5 kernel version tags required by the ccb_debug linux tasks.
# Tag → commit mapping (for reference, mirrors on sg-benchmarks):
#   v5.6.7    → 55b2af1c  (linux-acpi-backlight-fault-001)
#   v3.7.6    → 07c4ee00  (linux-hda-intel-suspend-fault-001)
#   v5.6-rc2  → 11a48a5a  (linux-iwlwifi-subdevice-fault-001)
#   v4.1.15   → 07cc49f6  (linux-nfs-inode-revalidate-fault-001)
#   v4.14.114 → fa5941f4  (linux-ssd-trim-timeout-fault-001)
ALL_TAGS=(v5.6.7 v3.7.6 v5.6-rc2 v4.1.15 v4.14.114)

if [[ "${1:-}" == "--list" ]]; then
    echo "Required ccb-linux-base tags:"
    for tag in "${ALL_TAGS[@]}"; do
        exists=$(docker images -q "ccb-linux-base:$tag" 2>/dev/null)
        if [ -n "$exists" ]; then
            echo "  ccb-linux-base:$tag  [EXISTS]"
        else
            echo "  ccb-linux-base:$tag  [MISSING]"
        fi
    done
    exit 0
fi

# Determine which tags to build
if [ $# -gt 0 ]; then
    TAGS=("$@")
else
    TAGS=("${ALL_TAGS[@]}")
fi

# Create a temporary Dockerfile
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

cat > "$TMPDIR/Dockerfile" <<'DOCKERFILE'
FROM gcc:13

ARG KERNEL_TAG

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    git \
    curl \
    ca-certificates \
    gawk \
    bc \
    bison \
    flex \
    libssl-dev \
    libelf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Shallow clone at the specific kernel tag — much faster than full clone.
# The --no-tags flag avoids pulling all 1000+ kernel tags.
RUN git clone --depth 1 --branch "$KERNEL_TAG" --no-tags \
    https://github.com/torvalds/linux.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

ENTRYPOINT []
DOCKERFILE

echo "============================================"
echo "Building ccb-linux-base images"
echo "Tags to build: ${TAGS[*]}"
echo "============================================"
echo ""

FAILED=()
for tag in "${TAGS[@]}"; do
    echo "---------- Building ccb-linux-base:$tag ----------"

    # Check if already exists
    exists=$(docker images -q "ccb-linux-base:$tag" 2>/dev/null)
    if [ -n "$exists" ]; then
        echo "  Image already exists ($(docker images --format '{{.Size}}' ccb-linux-base:$tag)). Skipping."
        echo "  Use 'docker rmi ccb-linux-base:$tag' to force rebuild."
        echo ""
        continue
    fi

    if docker build \
        --build-arg "KERNEL_TAG=$tag" \
        -t "ccb-linux-base:$tag" \
        -f "$TMPDIR/Dockerfile" \
        "$TMPDIR" ; then
        echo "  OK: ccb-linux-base:$tag built successfully"
        echo "  Size: $(docker images --format '{{.Size}}' ccb-linux-base:$tag)"
    else
        echo "  FAILED: ccb-linux-base:$tag"
        FAILED+=("$tag")
    fi
    echo ""
done

echo "============================================"
echo "Summary:"
echo "  Requested: ${#TAGS[@]}"
echo "  Failed:    ${#FAILED[@]}"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "  Failed tags: ${FAILED[*]}"
    exit 1
fi
echo "============================================"

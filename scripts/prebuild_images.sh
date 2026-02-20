#!/bin/bash
# Pre-build all Docker images for SDLC benchmark suites.
# Run this before a benchmark batch to warm the Docker layer cache.
# Harbor's docker compose build then exits near-instantly (cache hit).
#
# Usage:
#   ./scripts/prebuild_images.sh [SUITE...] [OPTIONS]
#   ./scripts/prebuild_images.sh ccb_build ccb_fix
#   ./scripts/prebuild_images.sh                     # all 8 suites
#   PREBUILD_JOBS=12 ./scripts/prebuild_images.sh
#
# Options:
#   --baseline-only   Skip SG_only images
#   --sgonly-only     Skip baseline images
#   --dry-run         Print what would be built without building
#   --force           Rebuild even if image exists

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
BENCHMARK_DIR="$REPO_ROOT/benchmarks"

export DOCKER_BUILDKIT=1

PREBUILD_JOBS="${PREBUILD_JOBS:-8}"
DRY_RUN=false
FORCE=false
SKIP_BASELINE=false
SKIP_SGONLY=false
SUITES=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only) SKIP_SGONLY=true; shift ;;
        --sgonly-only)   SKIP_BASELINE=true; shift ;;
        --dry-run)       DRY_RUN=true; shift ;;
        --force)         FORCE=true; shift ;;
        --jobs)          PREBUILD_JOBS="$2"; shift 2 ;;
        ccb_*)           SUITES+=("$1"); shift ;;
        *)               echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ ${#SUITES[@]} -eq 0 ]; then
    SUITES=(ccb_build ccb_debug ccb_design ccb_document ccb_fix ccb_secure ccb_test ccb_understand)
fi

# ============================================
# Step 0: Lightweight pre-build cleanup
# ============================================
# Remove stopped containers and orphan volumes from previous runs.
# Does NOT prune images (we need the layer cache for fast builds).
if [ "$DRY_RUN" = false ]; then
    echo "=== Pre-build cleanup ==="
    docker container prune -f 2>/dev/null | tail -1 || true
    docker volume prune -f 2>/dev/null | tail -1 || true
    echo ""
fi

# ============================================
# Step 1: Ensure base images are built
# ============================================
BASE_BUILD="$REPO_ROOT/base_images/build.sh"
if [ -x "$BASE_BUILD" ] && [ "$DRY_RUN" = false ]; then
    echo "=== Ensuring base images ==="
    bash "$BASE_BUILD" --parallel
    echo ""
fi

# ============================================
# Step 2: Collect build jobs
# ============================================
# Each job: "image_tag|context_dir|cleanup_dir"
# cleanup_dir is empty for baseline (no temp dir to remove)
declare -a JOBS=()

for suite in "${SUITES[@]}"; do
    suite_dir="${BENCHMARK_DIR}/${suite}"
    if [ ! -d "$suite_dir" ]; then
        echo "WARN: Suite directory not found: $suite_dir"
        continue
    fi

    for task_dir in "$suite_dir"/*/; do
        [ -d "$task_dir" ] || continue
        task_id=$(basename "$task_dir")
        env_dir="${task_dir}environment"

        # Baseline image
        if [ "$SKIP_BASELINE" = false ] && [ -f "${env_dir}/Dockerfile" ]; then
            image_tag="hb__${task_id}"
            JOBS+=("${image_tag}|${env_dir}|")
        fi

        # SG_only image
        if [ "$SKIP_SGONLY" = false ] && [ -f "${env_dir}/Dockerfile.sg_only" ]; then
            image_tag="hb__sgonly_${task_id}"
            # Will create temp dir at build time
            JOBS+=("${image_tag}|${env_dir}|sgonly")
        fi
    done
done

echo "=== Pre-building Docker images ==="
echo "Suites: ${SUITES[*]}"
echo "Jobs: ${#JOBS[@]} images (parallel: $PREBUILD_JOBS)"
echo ""

if [ ${#JOBS[@]} -eq 0 ]; then
    echo "No images to build."
    exit 0
fi

# ============================================
# Step 3: Build function
# ============================================
OK_COUNT=0
ERR_COUNT=0
SKIP_COUNT=0
LOG_DIR="/tmp/prebuild_logs"
mkdir -p "$LOG_DIR"

build_one() {
    local image_tag=$1
    local env_dir=$2
    local mode=$3  # empty=baseline, "sgonly"=sg_only

    # Skip if image already exists (unless --force)
    if [ "$FORCE" = false ] && docker image inspect "$image_tag" >/dev/null 2>&1; then
        echo "SKIP $image_tag (exists)"
        return 2  # special exit code for "skipped"
    fi

    local context_dir="$env_dir"
    local cleanup_dir=""

    # For sg_only: create temp dir with swapped Dockerfile
    if [ "$mode" = "sgonly" ]; then
        local task_dir
        task_dir=$(dirname "$env_dir")
        local task_id
        task_id=$(basename "$task_dir")
        cleanup_dir="/tmp/sgonly_${task_id}"
        rm -rf "$cleanup_dir"
        cp -a "$task_dir" "$cleanup_dir"
        cp "${cleanup_dir}/environment/Dockerfile.sg_only" "${cleanup_dir}/environment/Dockerfile"
        context_dir="${cleanup_dir}/environment"
    fi

    local log_file="${LOG_DIR}/${image_tag}.log"
    local start=$SECONDS

    if docker build --quiet -t "$image_tag" "$context_dir" > "$log_file" 2>&1; then
        echo "OK   $image_tag ($(( SECONDS - start ))s)"
        local rc=0
    else
        echo "ERR  $image_tag ($(( SECONDS - start ))s) — see $log_file"
        local rc=1
    fi

    # Cleanup sg_only temp dir
    if [ -n "$cleanup_dir" ] && [ -d "$cleanup_dir" ]; then
        rm -rf "$cleanup_dir"
    fi

    return $rc
}

# ============================================
# Step 4: Dry run or parallel execution
# ============================================
if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN — would build:"
    for job in "${JOBS[@]}"; do
        IFS='|' read -r tag ctx mode <<< "$job"
        printf "  %-50s %s\n" "$tag" "($mode${mode:+: }${ctx})"
    done
    echo ""
    echo "Total: ${#JOBS[@]} images"
    exit 0
fi

TOTAL_START=$SECONDS

for job in "${JOBS[@]}"; do
    IFS='|' read -r tag ctx mode <<< "$job"

    (
        build_one "$tag" "$ctx" "$mode"
    ) &

    # Limit concurrent builds
    while [ "$(jobs -rp | wc -l)" -ge "$PREBUILD_JOBS" ]; do
        wait -n 2>/dev/null || true
    done
done

# Wait for all remaining builds
wait 2>/dev/null || true

TOTAL_ELAPSED=$(( SECONDS - TOTAL_START ))

echo ""
echo "=== Pre-build complete in ${TOTAL_ELAPSED}s ==="
echo "Logs: $LOG_DIR/"

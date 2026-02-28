#!/bin/bash
# Build all ccb-repo-* base images and push to GHCR.
# Builds one at a time and removes local copy after push to save disk.
#
# Prerequisites:
#   - podman/docker logged into ghcr.io (podman login ghcr.io)
#
# Usage: bash scripts/push_base_images_ghcr.sh [--skip-existing]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$REPO_ROOT/base_images"
GHCR_PREFIX="ghcr.io/sourcegraph"

SKIP_EXISTING=false
if [ "${1:-}" = "--skip-existing" ]; then
    SKIP_EXISTING=true
fi

IMAGES=(
    "Dockerfile.django-674eda1c    ccb-repo-django-674eda1c"
    "Dockerfile.django-9e7cc2b6    ccb-repo-django-9e7cc2b6"
    "Dockerfile.flipt-3d5a345f     ccb-repo-flipt-3d5a345f"
    "Dockerfile.k8s-11602f08       ccb-repo-k8s-11602f08"
    "Dockerfile.k8s-8c9c67c0       ccb-repo-k8s-8c9c67c0"
    "Dockerfile.kafka-0753c489     ccb-repo-kafka-0753c489"
    "Dockerfile.kafka-e678b4b      ccb-repo-kafka-e678b4b"
    "Dockerfile.flink-0cc95fcc     ccb-repo-flink-0cc95fcc"
    "Dockerfile.camel-1006f047     ccb-repo-camel-1006f047"
    "Dockerfile.postgres-5a461dc4  ccb-repo-postgres-5a461dc4"
    "Dockerfile.strata-66225ca9    ccb-repo-strata-66225ca9"
    "Dockerfile.curl-09e25b9d      ccb-repo-curl-09e25b9d"
    "Dockerfile.envoy-1d0ba73a     ccb-repo-envoy-1d0ba73a"
    "Dockerfile.envoy-d7809ba2     ccb-repo-envoy-d7809ba2"
    "Dockerfile.flask-798e006f     ccb-repo-flask-798e006f"
    "Dockerfile.requests-421b8733  ccb-repo-requests-421b8733"
    "Dockerfile.etcd-d89978e8      ccb-repo-etcd-d89978e8"
    "Dockerfile.containerd-317286ac ccb-repo-containerd-317286ac"
    "Dockerfile.numpy-a639fbf5     ccb-repo-numpy-a639fbf5"
    "Dockerfile.scikit-learn-cb7e82dd ccb-repo-scikit-learn-cb7e82dd"
    "Dockerfile.pandas-41968da5    ccb-repo-pandas-41968da5"
    "Dockerfile.rust-01f6ddf7      ccb-repo-rust-01f6ddf7"
)

TOTAL=${#IMAGES[@]}
SUCCESS=0
SKIPPED=0
FAILED=0
FAILED_NAMES=()
TOTAL_START=$SECONDS

echo "============================================"
echo "CCB Base Images → GHCR Push"
echo "============================================"
echo "Images:  $TOTAL"
echo "Target:  $GHCR_PREFIX/ccb-repo-*"
echo "Mode:    build-push-clean (saves disk)"
echo ""

for i in "${!IMAGES[@]}"; do
    read -r dockerfile local_tag <<< "${IMAGES[$i]}"
    ghcr_tag="${GHCR_PREFIX}/${local_tag}:latest"
    n=$((i + 1))

    echo "[$n/$TOTAL] $local_tag"

    # Skip if already pushed to GHCR (checks remote registry, not local)
    if [ "$SKIP_EXISTING" = true ]; then
        if docker manifest inspect "$ghcr_tag" >/dev/null 2>&1; then
            echo "  Already on GHCR — skipping"
            SKIPPED=$((SKIPPED + 1))
            continue
        fi
    fi

    # Build
    echo "  Building ..."
    if ! docker build -f "$BASE_DIR/$dockerfile" -t "$local_tag" "$BASE_DIR" 2>&1 | tail -3; then
        echo "  BUILD FAILED"
        FAILED=$((FAILED + 1))
        FAILED_NAMES+=("$local_tag")
        continue
    fi

    # Tag and push
    docker tag "$local_tag" "$ghcr_tag"
    echo "  Pushing ..."
    if docker push "$ghcr_tag" 2>&1 | tail -3; then
        echo "  PUSHED OK"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "  PUSH FAILED"
        FAILED=$((FAILED + 1))
        FAILED_NAMES+=("$local_tag")
    fi

    # Remove local copies to free disk
    echo "  Cleaning local images ..."
    docker rmi "$ghcr_tag" 2>/dev/null || true
    docker rmi "$local_tag" 2>/dev/null || true

    # Prune dangling layers
    docker image prune -f >/dev/null 2>&1 || true

    echo ""
done

ELAPSED=$((SECONDS - TOTAL_START))

echo "============================================"
echo "Results: $SUCCESS pushed, $SKIPPED skipped, $FAILED failed (${ELAPSED}s)"
echo "============================================"

if [ ${#FAILED_NAMES[@]} -gt 0 ]; then
    echo ""
    echo "Failed images:"
    for name in "${FAILED_NAMES[@]}"; do
        echo "  - $name"
    done
fi

echo ""
echo "Pushed images at: $GHCR_PREFIX/ccb-repo-*:latest"

if [ "$FAILED" -gt 0 ]; then
    exit 1
fi

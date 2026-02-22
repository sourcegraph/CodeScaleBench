#!/usr/bin/env bash
# Create and populate sg-benchmarks mirrors for MCP-unique tasks that are missing.
#
# These repos are cloned at specific tags in baseline Dockerfiles but have no
# corresponding sg-benchmarks mirror, so the MCP agent cannot search them at
# the correct version.
#
# Repos handled:
#   - kubernetes/kubernetes @ v1.32.0     → sg-benchmarks/kubernetes-kubernetes  (NEW)
#   - nodejs/node @ v22.13.0             → sg-benchmarks/nodejs-node            (NEW)
#   - pandas-dev/pandas @ v2.2.3         → sg-benchmarks/pandas                 (NEW)
#   - scikit-learn/scikit-learn @ 1.6.1  → sg-benchmarks/scikit-learn           (NEW)
#
# Usage: bash scripts/create_missing_mcp_mirrors.sh [--dry-run]
set -euo pipefail

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE — no repos will be created or pushed ==="
    echo ""
fi

SG_ORG="sg-benchmarks"
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

SUCCESS=0
FAILED=0
SKIPPED=0

# Format: "upstream_repo tag sg_name description"
REPOS=(
    "kubernetes/kubernetes v1.32.0 kubernetes-kubernetes Mirror of kubernetes/kubernetes at v1.32.0"
    "nodejs/node v22.13.0 nodejs-node Mirror of nodejs/node at v22.13.0"
    "pandas-dev/pandas v2.2.3 pandas Mirror of pandas-dev/pandas at v2.2.3"
    "scikit-learn/scikit-learn 1.6.1 scikit-learn Mirror of scikit-learn/scikit-learn at 1.6.1"
)

for entry in "${REPOS[@]}"; do
    # Parse: first 3 space-delimited fields, rest is description
    github_repo=$(echo "$entry" | awk '{print $1}')
    tag=$(echo "$entry" | awk '{print $2}')
    sg_name=$(echo "$entry" | awk '{print $3}')
    description=$(echo "$entry" | awk '{$1=$2=$3=""; print}' | sed 's/^ *//')

    echo ""
    echo "=== ${github_repo} @ ${tag} → ${SG_ORG}/${sg_name} ==="

    # Phase 1: Create repo if it doesn't exist
    if gh api "repos/${SG_ORG}/${sg_name}" --jq '.full_name' &>/dev/null; then
        echo "  Repo ${SG_ORG}/${sg_name} already exists — will force-push"
    else
        echo "  Creating repo ${SG_ORG}/${sg_name}..."
        if $DRY_RUN; then
            echo "  [DRY RUN] Would create: gh repo create ${SG_ORG}/${sg_name} --public --description '${description}'"
        else
            if ! gh repo create "${SG_ORG}/${sg_name}" --public --description "${description}" 2>&1; then
                echo "  ERROR: Failed to create repo ${SG_ORG}/${sg_name}"
                FAILED=$((FAILED + 1))
                continue
            fi
            echo "  Created ${SG_ORG}/${sg_name}"
        fi
    fi

    if $DRY_RUN; then
        echo "  [DRY RUN] Would clone ${github_repo} at ${tag}, orphan commit, force-push"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    clone_dir="${WORK_DIR}/clone_${sg_name}"
    fresh_dir="${WORK_DIR}/fresh_${sg_name}"

    # Phase 2a: Shallow clone at pinned tag
    echo "  Cloning ${github_repo} at tag ${tag} (shallow)..."
    if ! git clone --depth 1 --branch "$tag" "https://github.com/${github_repo}.git" "$clone_dir" 2>&1; then
        echo "  ERROR: Failed to clone ${github_repo} at tag ${tag}"
        FAILED=$((FAILED + 1))
        continue
    fi

    actual_commit=$(git -C "$clone_dir" rev-parse HEAD)
    echo "  Cloned at commit ${actual_commit:0:12}"

    # Phase 2b: Create fresh repo with orphan commit (avoids shallow-pack push errors)
    echo "  Creating orphan commit..."
    mkdir -p "$fresh_dir"
    git -C "$fresh_dir" init -b main --quiet 2>&1
    rsync -a --exclude='.git' "$clone_dir/" "$fresh_dir/" 2>&1
    git -C "$fresh_dir" add -A 2>&1
    git -C "$fresh_dir" -c user.email="benchmark@sg-benchmarks.dev" -c user.name="sg-benchmarks" \
        commit -m "Mirror ${github_repo} @ ${tag} (${actual_commit:0:8}) — pinned for CCB MCP-unique tasks" --quiet 2>&1

    rm -rf "$clone_dir"

    # Phase 2c: Force-push
    echo "  Force-pushing to ${SG_ORG}/${sg_name}..."
    git -C "$fresh_dir" remote add sg-target "https://github.com/${SG_ORG}/${sg_name}.git" 2>&1
    if ! git -C "$fresh_dir" push sg-target main --force 2>&1; then
        echo "  ERROR: Failed to push to ${SG_ORG}/${sg_name}"
        rm -rf "$fresh_dir"
        FAILED=$((FAILED + 1))
        continue
    fi

    echo "  SUCCESS: ${SG_ORG}/${sg_name} pinned to ${tag} (${actual_commit:0:8})"
    SUCCESS=$((SUCCESS + 1))
    rm -rf "$fresh_dir"
done

echo ""
echo "=============================================="
echo "Mirror creation complete!"
echo "=============================================="
echo "Succeeded: $SUCCESS"
echo "Failed:    $FAILED"
echo "Skipped:   $SKIPPED"
echo ""
if [ "$SUCCESS" -gt 0 ]; then
    echo "Wait ~10-30 minutes for Sourcegraph indexing, then verify with:"
    echo "  keyword_search: repo:^github.com/sg-benchmarks/kubernetes-kubernetes$ apiVersion"
    echo "  keyword_search: repo:^github.com/sg-benchmarks/nodejs-node$ http.createServer"
    echo "  keyword_search: repo:^github.com/sg-benchmarks/pandas$ DataFrame"
    echo "  keyword_search: repo:^github.com/sg-benchmarks/scikit-learn$ sklearn"
fi

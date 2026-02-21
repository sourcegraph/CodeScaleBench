#!/usr/bin/env bash
# Create and populate sg-benchmarks mirrors for the 8 new MCP-unique tasks.
#
# Two phases:
#   Phase 1: Create NEW repos on sg-benchmarks (gh repo create)
#   Phase 2: Clone upstream at pinned tag, orphan commit, force-push
#
# Repos handled:
#   - numpy/numpy @ v2.2.2             → sg-benchmarks/numpy              (NEW)
#   - scipy/scipy @ v1.15.1            → sg-benchmarks/scipy              (NEW)
#   - grafana/grafana @ v11.4.0        → sg-benchmarks/grafana            (NEW)
#   - prometheus/prometheus @ v3.2.1    → sg-benchmarks/prometheus         (NEW)
#
# Already at correct version (no action needed):
#   - expressjs/express @ 4.21.1       → sg-benchmarks/expressjs-express  (EXISTS)
#   - etcd-io/etcd @ v3.5.17           → sg-benchmarks/etcd-io-etcd      (EXISTS)
#
# Usage: bash scripts/create_mcp_expansion_mirrors.sh [--dry-run]
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
# Only repos that need NEW mirrors (not already at correct version)
REPOS=(
    "numpy/numpy v2.2.2 numpy Mirror of numpy/numpy at v2.2.2"
    "scipy/scipy v1.15.1 scipy Mirror of scipy/scipy at v1.15.1"
    "grafana/grafana v11.4.0 grafana Mirror of grafana/grafana at v11.4.0"
    "prometheus/prometheus v3.2.1 prometheus Mirror of prometheus/prometheus at v3.2.1"
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
echo "Already at correct version (no action taken):"
echo "  - sg-benchmarks/expressjs-express @ 4.21.1"
echo "  - sg-benchmarks/etcd-io-etcd @ v3.5.17"
echo ""
if [ "$SUCCESS" -gt 0 ]; then
    echo "Wait ~10-30 minutes for Sourcegraph indexing, then verify with:"
    echo '  python3 -c "'
    echo '    mirrors = {'
    echo '      "sg-benchmarks/numpy": ("numpy/f2py/_src_pyf.py", "numpy.distutils"),'
    echo '      "sg-benchmarks/scipy": ("tools/generate_f2pymod.py", "numpy.distutils"),'
    echo '      "sg-benchmarks/grafana": ("pkg/services/featuremgmt/registry.go", "auditLoggingAppPlatform"),'
    echo '      "sg-benchmarks/prometheus": ("config/config.go", "TLSConfig"),'
    echo '    }'
    echo '    for m, (f, kw) in mirrors.items():'
    echo '      print(f"  keyword_search: repo:^github.com/{m}$ file:{f} {kw}")'
    echo '  "'
fi

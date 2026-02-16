#!/bin/bash
# Mirror remaining unindexed largerepo_expansion repos to sg-benchmarks org
#
# Clones at pinned tags, creates orphan commit to avoid shallow-pack push issues.
# Commits and tags from configs/sg_indexing_list.json.
#
# Prerequisites:
#   - gh CLI authenticated with push access to sg-benchmarks org
#   - git configured
#
# Usage:
#   ./scripts/mirror_largerepo_expansion.sh [--dry-run] [--repo SG_NAME]

set -euo pipefail

WORK_DIR="${WORK_DIR:-/tmp/sg-largerepo-mirrors}"
SG_ORG="sg-benchmarks"
DRY_RUN=false
ONLY_REPO=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --repo) ONLY_REPO="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Format: github_org/repo | commit | tag | sg_name | description
REPOS=(
    "torvalds/linux|05f7e89ab9731565d8a62e3b5d1ec206485eeb0b|v6.19|linux--05f7e89a|LargeRepo expansion: torvalds/linux @ v6.19"
    "postgres/postgres|5a461dc4dbf72a1ec281394a76eb36d68cbdd935|REL_18_2|postgres--5a461dc4|LargeRepo expansion: postgres/postgres @ REL_18_2"
    "django/django|9e7cc2b628fe8fd3895986af9b7fc9525034c1b0|5.2|django--9e7cc2b6|LargeRepo expansion: django/django @ 5.2"
    "hazelcast/hazelcast|a9ce2a02ac17f88fcd38869ac698e56e613dc40c|v5.6.0|hazelcast--a9ce2a02|LargeRepo expansion: hazelcast/hazelcast @ v5.6.0"
    "finos/legend-engine|20cca27326b19c265bb580e97659420bd33e1ac5|legend-engine-4.120.1|legend-engine--20cca273|LargeRepo expansion: finos/legend-engine @ 4.120.1"
)

echo "=============================================="
echo "Mirror largerepo_expansion repos to sg-benchmarks"
echo "=============================================="
echo "Total repos: ${#REPOS[@]}"
echo "Work directory: ${WORK_DIR}"
echo "Dry run: ${DRY_RUN}"
[ -n "$ONLY_REPO" ] && echo "Only repo: ${ONLY_REPO}"
echo ""

mkdir -p "$WORK_DIR"

SUCCESS=0
FAILED=0
SKIPPED=0

for entry in "${REPOS[@]}"; do
    IFS='|' read -r github_repo commit tag sg_name description <<< "$entry"

    if [ -n "$ONLY_REPO" ] && [ "$sg_name" != "$ONLY_REPO" ]; then
        continue
    fi

    echo ""
    echo "--- ${sg_name} ---"
    echo "  Source: ${github_repo} @ ${tag} (${commit:0:8})"

    # Check if repo already exists on GitHub
    if gh repo view "${SG_ORG}/${sg_name}" &>/dev/null; then
        echo "  SKIP: ${SG_ORG}/${sg_name} already exists on GitHub"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would: shallow clone at ${tag}, create ${SG_ORG}/${sg_name}, push"
        continue
    fi

    clone_dir="${WORK_DIR}/clone-${sg_name}"
    fresh_dir="${WORK_DIR}/${sg_name}"
    rm -rf "$clone_dir" "$fresh_dir"

    # Step 1: Shallow clone at the tag (gets tree content only)
    echo "  Cloning ${github_repo} at tag ${tag} (shallow)..."
    if ! git clone --depth 1 --branch "$tag" "https://github.com/${github_repo}.git" "$clone_dir" 2>&1; then
        echo "  ERROR: Failed to clone ${github_repo} at tag ${tag}"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Verify we got the right commit
    actual_commit=$(git -C "$clone_dir" rev-parse HEAD)
    if [ "$actual_commit" != "$commit" ]; then
        echo "  WARNING: Expected commit ${commit:0:8}, got ${actual_commit:0:8}"
        echo "  Tag ${tag} may have moved. Proceeding with ${actual_commit:0:8}."
    fi

    # Step 2: Create fresh repo with orphan commit (avoids shallow-pack push errors)
    echo "  Creating fresh repo with orphan commit..."
    mkdir -p "$fresh_dir"
    git -C "$fresh_dir" init -b main 2>&1
    # Copy all files (excluding .git)
    rsync -a --exclude='.git' "$clone_dir/" "$fresh_dir/" 2>&1
    git -C "$fresh_dir" add -A 2>&1
    git -C "$fresh_dir" -c user.email="benchmark@sg-benchmarks.dev" -c user.name="sg-benchmarks" \
        commit -m "Mirror ${github_repo} @ ${tag} (${actual_commit:0:8})" --quiet 2>&1

    # Clean up the shallow clone to save space
    rm -rf "$clone_dir"

    # Step 3: Create the sg-benchmarks repo on GitHub
    echo "  Creating GitHub repo ${SG_ORG}/${sg_name}..."
    if ! gh repo create "${SG_ORG}/${sg_name}" --public --description "$description" 2>&1; then
        echo "  ERROR: Failed to create ${SG_ORG}/${sg_name}"
        rm -rf "$fresh_dir"
        FAILED=$((FAILED + 1))
        continue
    fi

    # Step 4: Push to sg-benchmarks
    echo "  Pushing to ${SG_ORG}/${sg_name}..."
    git -C "$fresh_dir" remote add sg-target "https://github.com/${SG_ORG}/${sg_name}.git" 2>&1
    if ! git -C "$fresh_dir" push sg-target main --force 2>&1; then
        echo "  ERROR: Failed to push to ${SG_ORG}/${sg_name}"
        rm -rf "$fresh_dir"
        FAILED=$((FAILED + 1))
        continue
    fi

    echo "  SUCCESS: ${SG_ORG}/${sg_name} created and pushed"
    SUCCESS=$((SUCCESS + 1))

    # Clean up to save space
    rm -rf "$fresh_dir"
done

echo ""
echo "=============================================="
echo "Complete!"
echo "=============================================="
echo "Succeeded: $SUCCESS"
echo "Skipped (already exist): $SKIPPED"
echo "Failed: $FAILED"
echo ""
echo "Next steps:"
echo "  1. Wait for Sourcegraph to index (10-30 min)"
echo "  2. Update configs/sg_indexing_list.json: set _indexed: true for completed repos"
echo "  3. Update _status and _indexed_count in largerepo_expansion section"

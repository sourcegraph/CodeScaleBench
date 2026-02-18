#!/bin/bash
# Create missing sg-benchmarks repos for SWE-bench Pro tasks
#
# This script clones source repos at specific commits and pushes them
# to the sg-benchmarks GitHub org so Sourcegraph can index them.
#
# Prerequisites:
#   - gh CLI authenticated with push access to sg-benchmarks org
#   - git configured
#   - Sufficient disk space (~50GB for all repos)
#
# Usage:
#   ./scripts/create_sg_benchmark_repos.sh [--dry-run] [--repo REPO_NAME]
#
# The --dry-run flag shows what would be done without actually doing it.
# The --repo flag creates only a specific repo (e.g., --repo ansible--379058e1).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${WORK_DIR:-/tmp/sg-benchmark-repos}"
SG_ORG="sg-benchmarks"
DRY_RUN=false
ONLY_REPO=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --repo)
            ONLY_REPO="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Missing repos: github_org/repo  full_commit  sg_name
# Generated from configs/sg_indexing_list.json verification on 2026-02-04
MISSING_REPOS=(
    "ansible/ansible|379058e10f3dbc0fdcaf80394bd09b18927e7d33|ansible--379058e1"
    "ansible/ansible|b2a289dcbb702003377221e25f62c8a3608f0e89|ansible--b2a289dc"
    "element-hq/element-web|cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85|element-web--cf3c899d"
    "element-hq/element-web|f14374a51c153f64f313243f2df6ea4971db4e15|element-web--f14374a5"
    "flipt-io/flipt|3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8|flipt--3d5a345f"
    "flipt-io/flipt|9f8127f225a86245fa35dca4885c2daef824ee55|flipt--9f8127f2"
    "flipt-io/flipt|b433bd05ce405837804693bebd5f4b88d87133c8|flipt--b433bd05"
    "flipt-io/flipt|c188284ff0c094a4ee281afebebd849555ebee59|flipt--c188284f"
    "navidrome/navidrome|d0dceae0943b8df16e579c2d9437e11760a0626a|navidrome--d0dceae0"
    "nodebb/nodebb|eb49a64974ca844bca061744fb3383f5d13b02ad|nodebb--eb49a649"
    "internetarchive/openlibrary|7f6b722a10f822171501d027cad60afe53337732|openlibrary--7f6b722a"
    "internetarchive/openlibrary|92db3454aeaa02f89b4cdbc3103f7e95c9759f92|openlibrary--92db3454"
    "internetarchive/openlibrary|c506c1b0b678892af5cb22c1c1dbc35d96787a0a|openlibrary--c506c1b0"
    "internetarchive/openlibrary|d109cc7e6e161170391f98f9a6fa1d02534c18e4|openlibrary--d109cc7e"
    "qutebrowser/qutebrowser|233cb1cc48635130e5602549856a6fa4ab4c087f|qutebrowser--233cb1cc"
    "qutebrowser/qutebrowser|394bfaed6544c952c6b3463751abab3176ad4997|qutebrowser--394bfaed"
    "qutebrowser/qutebrowser|3fd8e12949b8feda401930574facf09dd4180bba|qutebrowser--3fd8e129"
    "qutebrowser/qutebrowser|e5340c449f23608803c286da0563b62f58ba25b0|qutebrowser--e5340c44"
    "gravitational/teleport|0415e422f12454db0c22316cf3eaa5088d6b6322|teleport--0415e422"
    "gravitational/teleport|3587cca7840f636489449113969a5066025dd5bf|teleport--3587cca7"
    "gravitational/teleport|7744f72c6eb631791434b648ba41083b5f6d2278|teleport--7744f72c"
    "gravitational/teleport|8302d467d160f869b77184e262adbe2fbc95d9ba|teleport--8302d467"
    "tutao/tutanota|f373ac3808deefce8183dad8d16729839cc330c1|tutanota--f373ac38"
    "future-architect/vuls|139f3a81b66c47e6d8f70ce6c4afe7a9196a6ea8|vuls--139f3a81"
    "future-architect/vuls|4c04acbd9ea5b073efe999e33381fa9f399d6f27|vuls--4c04acbd"
    "future-architect/vuls|d18e7a751d07260d75ce3ba0cd67c4a6aebfd967|vuls--d18e7a75"
    "protonmail/webclients|369fd37de29c14c690cb3b1c09a949189734026f|webclients--369fd37d"
    "protonmail/webclients|8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c|webclients--8be4f6cb"
    "protonmail/webclients|c6f65d205c401350a226bb005f42fac1754b0b5b|webclients--c6f65d20"
    "protonmail/webclients|caf10ba9ab2677761c88522d1ba8ad025779c492|webclients--caf10ba9"
)

echo "=============================================="
echo "Create missing sg-benchmarks repos"
echo "=============================================="
echo "Total missing: ${#MISSING_REPOS[@]}"
echo "Work directory: ${WORK_DIR}"
echo "Dry run: ${DRY_RUN}"
if [ -n "$ONLY_REPO" ]; then
    echo "Only repo: ${ONLY_REPO}"
fi
echo ""

mkdir -p "$WORK_DIR"

# Track source repo clones to avoid re-cloning
declare -A CLONED_SOURCES

create_repo() {
    local github_repo=$1
    local commit=$2
    local sg_name=$3

    echo ""
    echo "--- Creating ${SG_ORG}/${sg_name} ---"
    echo "  Source: ${github_repo} @ ${commit}"

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would clone, checkout, create repo, push"
        return 0
    fi

    local source_dir="${WORK_DIR}/sources/${github_repo}"
    local repo_dir="${WORK_DIR}/repos/${sg_name}"

    # Step 1: Clone source repo (reuse if already cloned)
    if [ -z "${CLONED_SOURCES[$github_repo]+_}" ]; then
        echo "  Cloning source ${github_repo}..."
        mkdir -p "$(dirname "$source_dir")"
        if [ ! -d "$source_dir" ]; then
            git clone --bare "https://github.com/${github_repo}.git" "$source_dir" 2>&1 || {
                echo "  ERROR: Failed to clone ${github_repo}"
                return 1
            }
        fi
        CLONED_SOURCES[$github_repo]=1
    else
        echo "  Source already cloned: ${github_repo}"
    fi

    # Step 2: Create a working copy at the specific commit
    echo "  Creating repo at commit ${commit:0:8}..."
    rm -rf "$repo_dir"
    mkdir -p "$repo_dir"
    git clone "$source_dir" "$repo_dir" 2>&1 || {
        echo "  ERROR: Failed to clone from bare repo"
        return 1
    }

    cd "$repo_dir"
    git checkout "$commit" 2>&1 || {
        echo "  ERROR: Commit $commit not found in ${github_repo}"
        cd - > /dev/null
        return 1
    }

    # Detach HEAD and clean up
    git checkout --detach HEAD 2>/dev/null || true

    # Step 3: Create the sg-benchmarks repo on GitHub
    echo "  Creating GitHub repo ${SG_ORG}/${sg_name}..."
    if gh repo view "${SG_ORG}/${sg_name}" &>/dev/null; then
        echo "  Repo already exists on GitHub, skipping creation"
    else
        gh repo create "${SG_ORG}/${sg_name}" --public --description "SWE-bench Pro: ${github_repo} @ ${commit:0:8}" 2>&1 || {
            echo "  ERROR: Failed to create repo ${SG_ORG}/${sg_name}"
            cd - > /dev/null
            return 1
        }
    fi

    # Step 4: Push to sg-benchmarks
    echo "  Pushing to ${SG_ORG}/${sg_name}..."
    git remote remove sg-target 2>/dev/null || true
    git remote add sg-target "https://github.com/${SG_ORG}/${sg_name}.git"

    # Push the detached HEAD as main branch
    git push sg-target HEAD:refs/heads/main --force 2>&1 || {
        echo "  ERROR: Failed to push to ${SG_ORG}/${sg_name}"
        cd - > /dev/null
        return 1
    }

    cd - > /dev/null
    echo "  SUCCESS: ${SG_ORG}/${sg_name} created and pushed"

    # Clean up working copy to save space
    rm -rf "$repo_dir"
}

# Process repos
N=0
SUCCESS=0
FAILED=0

for entry in "${MISSING_REPOS[@]}"; do
    IFS='|' read -r github_repo commit sg_name <<< "$entry"

    # Filter by --repo if specified
    if [ -n "$ONLY_REPO" ] && [ "$sg_name" != "$ONLY_REPO" ]; then
        continue
    fi

    N=$((N + 1))
    echo ""
    echo "[$N/${#MISSING_REPOS[@]}] Processing ${sg_name}..."

    if create_repo "$github_repo" "$commit" "$sg_name"; then
        SUCCESS=$((SUCCESS + 1))
    else
        FAILED=$((FAILED + 1))
        echo "  FAILED: ${sg_name}"
    fi
done

echo ""
echo "=============================================="
echo "Complete!"
echo "=============================================="
echo "Processed: $N"
echo "Succeeded: $SUCCESS"
echo "Failed: $FAILED"
echo ""
echo "Next steps:"
echo "  1. Wait for Sourcegraph to index the new repos (may take 10-30 min)"
echo "  2. Verify indexing with:"
echo "     source ~/evals/.env.local"
echo "     curl -sS -H \"Authorization: token \$SOURCEGRAPH_ACCESS_TOKEN\" \\"
echo "       -H \"Content-Type: application/json\" \\"
echo "       \"\$SOURCEGRAPH_ENDPOINT/.api/graphql\" \\"
echo "       -d '{\"query\":\"{ repository(name: \\\"github.com/sg-benchmarks/REPO_NAME\\\") { name } }\"}'"
echo "  3. Re-run SWE-bench Pro MCP tasks:"
echo "     ./configs/swebenchpro_3config.sh --full-only"
echo "     ./configs/swebenchpro_3config.sh --full-only"

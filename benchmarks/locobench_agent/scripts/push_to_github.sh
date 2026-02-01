#!/bin/bash
# Push LoCoBench synthetic projects to GitHub for Sourcegraph indexing
#
# This script creates GitHub repos and pushes the synthetic codebases so they
# can be indexed by Sourcegraph for MCP/Deep Search evaluation.
#
# Prerequisites:
#   - gh CLI authenticated with appropriate permissions
#   - Git configured with user.name and user.email
#
# Usage:
#   ./scripts/push_to_github.sh [--org ORG_NAME] [--dry-run]
#
# Options:
#   --org ORG_NAME    GitHub organization (default: sg-benchmarks)
#   --dry-run         Show what would be done without making changes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
GENERATED_DIR="${BENCHMARK_DIR}/data/generated"
PROJECTS_FILE="${BENCHMARK_DIR}/projects_to_index.json"

# Defaults
GITHUB_ORG="${GITHUB_ORG:-sg-benchmarks}"
DRY_RUN=false
REPO_PREFIX="locobench-"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --org)
            GITHUB_ORG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "LoCoBench GitHub Push Script"
echo "=============================================="
echo "Organization: ${GITHUB_ORG}"
echo "Projects file: ${PROJECTS_FILE}"
echo "Dry run: ${DRY_RUN}"
echo ""

# Check prerequisites
if ! command -v gh &> /dev/null; then
    echo "ERROR: gh CLI not found. Install with: brew install gh"
    exit 1
fi

if ! gh auth status &> /dev/null; then
    echo "ERROR: gh CLI not authenticated. Run: gh auth login"
    exit 1
fi

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: Projects file not found: $PROJECTS_FILE"
    echo "Run the adapter first to generate this file."
    exit 1
fi

# Configure git identity if not set (needed for commits)
if [ -z "$(git config --global user.email)" ]; then
    echo "Configuring git identity..."
    git config --global user.email "locobench@anthropic.com"
    git config --global user.name "LoCoBench Bot"
fi

# Read projects
PROJECTS=$(python3 -c "
import json
with open('$PROJECTS_FILE') as f:
    projects = json.load(f)
for p in projects:
    print(f\"{p['project_id']}|{p['dir_name']}|{p['language']}\")
")

TOTAL=$(echo "$PROJECTS" | wc -l)
echo "Found ${TOTAL} projects to push"
echo ""

# Track results
SUCCESS=0
FAILED=0
SKIPPED=0

# Process each project
COUNT=0
while IFS='|' read -r PROJECT_ID DIR_NAME LANGUAGE; do
    COUNT=$((COUNT + 1))
    REPO_NAME="${REPO_PREFIX}${PROJECT_ID}"
    PROJECT_PATH="${GENERATED_DIR}/${PROJECT_ID}/${DIR_NAME}"

    echo "[${COUNT}/${TOTAL}] Processing: ${PROJECT_ID}"
    echo "  Repo: ${GITHUB_ORG}/${REPO_NAME}"
    echo "  Path: ${PROJECT_PATH}"

    if [ ! -d "$PROJECT_PATH" ]; then
        echo "  ERROR: Project directory not found"
        FAILED=$((FAILED + 1))
        continue
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY RUN] Would create repo and push"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Check if repo already exists
    if gh repo view "${GITHUB_ORG}/${REPO_NAME}" &> /dev/null; then
        echo "  Repo already exists, skipping creation"
    else
        echo "  Creating repo..."
        gh repo create "${GITHUB_ORG}/${REPO_NAME}" \
            --public \
            --description "LoCoBench synthetic ${LANGUAGE} project: ${DIR_NAME}" \
            || { echo "  ERROR: Failed to create repo"; FAILED=$((FAILED + 1)); continue; }
    fi

    # Initialize git and push
    cd "$PROJECT_PATH"

    if [ ! -d ".git" ]; then
        echo "  Initializing git..."
        git init -q
        git add -A
        git commit -q -m "Initial commit: LoCoBench synthetic project

Project ID: ${PROJECT_ID}
Language: ${LANGUAGE}
Generated for LoCoBench evaluation benchmark"
    fi

    # Set remote and push
    REMOTE_URL="https://github.com/${GITHUB_ORG}/${REPO_NAME}.git"
    git remote remove origin 2>/dev/null || true
    git remote add origin "$REMOTE_URL"

    echo "  Pushing to GitHub..."
    git push -u origin main --force -q 2>/dev/null || \
    git push -u origin master --force -q 2>/dev/null || \
    { git branch -M main && git push -u origin main --force -q; } || \
    { echo "  ERROR: Failed to push"; FAILED=$((FAILED + 1)); continue; }

    echo "  SUCCESS: https://github.com/${GITHUB_ORG}/${REPO_NAME}"
    SUCCESS=$((SUCCESS + 1))

done <<< "$PROJECTS"

echo ""
echo "=============================================="
echo "Summary"
echo "=============================================="
echo "Total: ${TOTAL}"
echo "Success: ${SUCCESS}"
echo "Failed: ${FAILED}"
echo "Skipped: ${SKIPPED}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "This was a dry run. Re-run without --dry-run to push."
fi

if [ $SUCCESS -gt 0 ]; then
    echo ""
    echo "Next steps:"
    echo "1. Configure Sourcegraph to index the ${GITHUB_ORG} organization"
    echo "2. Wait for indexing to complete"
    echo "3. Run LoCoBench with MCP enabled:"
    echo "   ./configs_v2/examples/locobench_50_tasks_comparison.sh"
fi

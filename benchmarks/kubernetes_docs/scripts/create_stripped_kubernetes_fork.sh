#!/bin/bash
#
# create_stripped_kubernetes_fork.sh
#
# Creates a stripped version of the Kubernetes repository with all
# documentation files removed, suitable for indexing in Sourcegraph
# for the documentation generation benchmark.
#
# Usage:
#   ./create_stripped_kubernetes_fork.sh [options]
#
# Options:
#   --github-user USER    Your GitHub username (for pushing)
#   --repo-name NAME      Name for stripped repo (default: kubernetes-stripped)
#   --output-dir DIR      Local output directory (default: ~/kubernetes-stripped)
#   --skip-clone          Skip cloning if kubernetes already exists locally
#   --dry-run             Show what would be done without executing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$(dirname "$BENCHMARK_DIR")")"

# Defaults
GITHUB_USER=""
REPO_NAME="kubernetes-stripped"
OUTPUT_DIR="$HOME/kubernetes-stripped"
KUBERNETES_SOURCE="$HOME/kubernetes-original"
SKIP_CLONE=false
DRY_RUN=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    cat << EOF
Usage: $(basename "$0") [options]

Create a stripped Kubernetes repository for Sourcegraph indexing.

Options:
    --github-user USER    Your GitHub username (required for pushing)
    --repo-name NAME      Name for stripped repo (default: $REPO_NAME)
    --output-dir DIR      Local output directory (default: $OUTPUT_DIR)
    --source DIR          Existing Kubernetes source (skips clone)
    --skip-push           Create locally but don't push to GitHub
    --dry-run             Show what would be done without executing
    --help                Show this help message

Example:
    $(basename "$0") --github-user myuser --repo-name k8s-nodocs

What gets stripped:
    - All doc.go files
    - All README.md and README files
    - All DESIGN.md, CONTRIBUTING.md files
    - All files in docs/, examples/ directories
    - Package-level documentation comments in .go files

What remains:
    - All source code (.go files, minus doc.go)
    - All configuration files
    - All test files
    - Build files and scripts
EOF
}

# Parse arguments
SKIP_PUSH=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --github-user)
            GITHUB_USER="$2"
            shift 2
            ;;
        --repo-name)
            REPO_NAME="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --source)
            KUBERNETES_SOURCE="$2"
            SKIP_CLONE=true
            shift 2
            ;;
        --skip-push)
            SKIP_PUSH=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

log_info "Kubernetes Documentation Stripping Tool"
log_info "========================================"
echo ""

# Step 1: Clone Kubernetes if needed
if [[ "$SKIP_CLONE" == "false" ]]; then
    if [[ -d "$KUBERNETES_SOURCE" ]]; then
        log_warning "Kubernetes source already exists at $KUBERNETES_SOURCE"
        log_info "Use --source to specify a different location or delete existing"
    else
        log_info "Step 1: Cloning kubernetes/kubernetes (full clone with history)..."
        log_warning "This will be ~2-3GB and take several minutes"
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY RUN] Would clone to $KUBERNETES_SOURCE"
        else
            git clone https://github.com/kubernetes/kubernetes.git "$KUBERNETES_SOURCE"
            log_success "Cloned kubernetes to $KUBERNETES_SOURCE"
        fi
    fi
else
    log_info "Step 1: Using existing Kubernetes source at $KUBERNETES_SOURCE"
fi

if [[ ! -d "$KUBERNETES_SOURCE" && "$DRY_RUN" == "false" ]]; then
    log_error "Kubernetes source not found at $KUBERNETES_SOURCE"
    exit 1
fi

# Step 2: Create stripped fork with history preserved
log_info "Step 2: Creating stripped fork with git history..."
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY RUN] Would create stripped fork at $OUTPUT_DIR"
else
    # Clone the local copy to preserve history
    if [[ -d "$OUTPUT_DIR" ]]; then
        log_warning "Output directory exists, removing: $OUTPUT_DIR"
        rm -rf "$OUTPUT_DIR"
    fi

    git clone "$KUBERNETES_SOURCE" "$OUTPUT_DIR"
    cd "$OUTPUT_DIR"

    log_info "Step 2a: Removing documentation files from working tree..."

    # Remove doc.go files
    find . -name "doc.go" -type f -delete 2>/dev/null || true

    # Remove README files
    find . -name "README.md" -type f -not -path "./.git/*" -delete 2>/dev/null || true
    find . -name "README" -type f -not -path "./.git/*" -delete 2>/dev/null || true

    # Remove other doc files
    find . -name "DESIGN.md" -type f -delete 2>/dev/null || true
    find . -name "CONTRIBUTING.md" -type f -delete 2>/dev/null || true
    find . -name "CHANGELOG*.md" -type f -delete 2>/dev/null || true

    # Remove docs and examples directories content
    rm -rf docs/ examples/ 2>/dev/null || true

    # Count what was removed
    REMOVED_COUNT=$(git status --porcelain | grep "^ D" | wc -l | tr -d ' ')
    log_info "Removed $REMOVED_COUNT documentation files"

    log_info "Step 2b: Stripping package comments from .go files..."
    # Use the Python script for more sophisticated stripping
    python3 "$SCRIPT_DIR/strip_k8s_docs.py" \
        --source "$OUTPUT_DIR" \
        --output "$OUTPUT_DIR.tmp" \
        --preserve-structure 2>/dev/null || true

    # If Python stripping worked, use those files
    if [[ -d "$OUTPUT_DIR.tmp" ]]; then
        # Copy stripped .go files back, preserving directory structure
        find "$OUTPUT_DIR.tmp" -name "*.go" -type f | while read -r stripped_file; do
            rel_path="${stripped_file#$OUTPUT_DIR.tmp/}"
            if [[ -f "$OUTPUT_DIR/$rel_path" ]]; then
                cp "$stripped_file" "$OUTPUT_DIR/$rel_path"
            fi
        done
        rm -rf "$OUTPUT_DIR.tmp"
    fi

    log_success "Documentation stripped (history preserved)"
fi

# Step 3: Commit the stripped changes (preserving full history)
log_info "Step 3: Committing stripped changes (with full git history preserved)..."
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY RUN] Would commit doc-stripping changes"
else
    cd "$OUTPUT_DIR"

    # We keep the .git directory to preserve full history!
    # Just commit our stripping changes on top

    # Create README explaining this repo
    cat > README.md << 'README'
# Kubernetes (Documentation Stripped)

This is a modified version of [kubernetes/kubernetes](https://github.com/kubernetes/kubernetes)
with all documentation files removed. It is used for benchmarking AI coding agents.

**Full git history is preserved** - you can use git blame, log, etc.

## What was removed

- All `doc.go` files
- All `README.md` files (replaced with this one)
- All `DESIGN.md`, `CONTRIBUTING.md` files
- Package-level documentation comments from `.go` files
- Contents of `docs/` and `examples/` directories

## Purpose

This repository is indexed in Sourcegraph for the CodeContextBench documentation
generation benchmark. By removing existing documentation, we can test whether
AI agents with access to Sourcegraph tools can generate accurate documentation
from code alone.

## Original Source

Based on kubernetes/kubernetes. Full git history is preserved.
See the original repository for the complete, documented codebase.

## License

Apache License 2.0 (same as original Kubernetes)
README

    git add -A
    git commit -m "Strip documentation for AI benchmarking

Remove all documentation files to create a 'documentation-free' version
for testing AI coding agents' ability to generate documentation from code.

Stripped:
- doc.go files
- README.md and README files
- DESIGN.md, CONTRIBUTING.md
- Package-level doc comments
- docs/ and examples/ directories

Full git history is preserved for code navigation (blame, log, etc.)
"

    log_success "Changes committed (history preserved: $(git rev-list --count HEAD) commits)"
fi

# Step 4: Push to GitHub
if [[ "$SKIP_PUSH" == "true" ]]; then
    log_info "Step 4: Skipping GitHub push (--skip-push specified)"
else
    if [[ -z "$GITHUB_USER" ]]; then
        log_warning "Step 4: No --github-user specified, skipping push"
        log_info "To push later, run:"
        echo "  cd $OUTPUT_DIR"
        echo "  git remote set-url origin git@github.com:YOUR_USERNAME/$REPO_NAME.git"
        echo "  git push -u origin master  # or 'main' depending on your default branch"
    else
        log_info "Step 4: Pushing to GitHub (with full history)..."

        REMOTE_URL="git@github.com:$GITHUB_USER/$REPO_NAME.git"

        if [[ "$DRY_RUN" == "true" ]]; then
            echo "  [DRY RUN] Would push to $REMOTE_URL"
            echo "  [DRY RUN] This will push full history (~150k commits, may take a while)"
        else
            cd "$OUTPUT_DIR"

            log_warning "Make sure you've created an EMPTY repo on GitHub first:"
            echo "  https://github.com/new"
            echo "  Repository name: $REPO_NAME"
            echo "  Do NOT initialize with README, .gitignore, or license"
            echo ""
            log_warning "This will push full Kubernetes git history (~150k commits)"
            log_warning "Initial push may take 10-30 minutes depending on connection"
            echo ""
            read -p "Press Enter when ready (or Ctrl+C to cancel)..."

            # Change remote from kubernetes/kubernetes to user's repo
            git remote set-url origin "$REMOTE_URL"

            # Get the current branch name (kubernetes uses 'master')
            CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

            # Push with full history
            git push -u origin "$CURRENT_BRANCH"

            log_success "Pushed to $REMOTE_URL (branch: $CURRENT_BRANCH)"
        fi
    fi
fi

# Summary
echo ""
log_info "========================================"
log_success "Stripped Kubernetes repository ready!"
echo ""
echo "Local path: $OUTPUT_DIR"
if [[ -n "$GITHUB_USER" && "$SKIP_PUSH" == "false" ]]; then
    echo "GitHub URL: https://github.com/$GITHUB_USER/$REPO_NAME"
fi
echo ""
echo "Git history preserved: Full commit history available for blame, log, etc."
echo ""

log_info "Next steps for Sourcegraph indexing:"
echo ""
echo "1. Go to https://sourcegraph.com (or your Sourcegraph instance)"
echo "2. Navigate to Settings → Repositories"
echo "3. Add your repository: github.com/$GITHUB_USER/$REPO_NAME"
echo "4. Wait for indexing to complete (may take 30-60 mins for full K8s)"
echo ""
echo "5. Update MCP config to search only the stripped repo:"
echo "   repo:^github\\.com/$GITHUB_USER/$REPO_NAME\$"
echo ""
echo "6. Run the benchmark:"
echo "   cd $PROJECT_ROOT"
echo "   ./benchmarks/kubernetes_docs/scripts/run_kubernetes_docs_benchmark.sh sched-doc-001"

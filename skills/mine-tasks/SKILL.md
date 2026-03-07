---
name: mine-tasks
description: Point at a repo and get eval tasks that compare baseline coding agents vs MCP-augmented agents. Mines GitHub PRs for real code-change tasks, auto-generates ground truth from patches, produces runnable Docker environments for both configs. Works with private repos. Triggers on mine tasks, propose tasks, discover tasks, find tasks, analyze repo for tasks, eval my repo, benchmark my repo.
user-invocable: true
---

# Mine Tasks

Point at a codebase and get a baseline-vs-MCP comparison for AI coding agents. Mines real merged PRs to create eval tasks where agents must reproduce known fixes/features, then measures whether MCP tools (code search, semantic indexing) help agents find the right code faster.

**Two workflows:**

- **Quick eval** (default): Mine 5-10 SDLC tasks from merged PRs, auto-generate ground truth, produce runnable Dockerfiles, print `docker run` commands. ~10 minutes to a working eval.
- **Full mining**: Deep analysis for contributing tasks to CodeScaleBench. Includes org-scale tasks, scoring, reviewer extraction, and `/scaffold-task` integration.

---

## Phase 0: Eval Goals

Ask the user:

**Question 1** — Header: "What are you evaluating?"
- Question: "What do you want to measure?"
- Options:
  - **Quick eval: baseline vs MCP** — "Mine 5-10 tasks from my repo, auto-generate ground truth, get a runnable comparison in minutes"
  - **Full benchmark mining** — "Deep analysis for CodeScaleBench contribution — SDLC tasks, org-scale tasks, reviewer extraction, the works"

If **Quick eval**, set `QUICK_MODE=true`. Skip detailed questions — use sensible defaults (SDLC only, auto-discover, 5-10 tasks). Proceed to Phase 1 with just the repo source question.

If **Full mining**, set `QUICK_MODE=false`. Proceed to Phase 1 with all questions.

**Question 2** — Header: "MCP provider"
- Question: "Which MCP provider will the augmented agent use?"
- Options:
  - **Sourcegraph** — "Sourcegraph code search (keyword + semantic search via MCP server)"
  - **GitHub Copilot** — "GitHub's code search and Copilot tools"
  - **Custom MCP server** — "I'll provide my own MCP config JSON"
  - **Not sure yet** — "Generate both Dockerfiles, I'll configure MCP later"

Record the selection as `{MCP_PROVIDER}`. If "Custom MCP server", prompt for the MCP config JSON (or path to a `.mcp.json` file). If "Not sure yet", generate Dockerfiles with a placeholder MCP config and clear instructions for how to fill it in.

---

## Phase 1: Codebase Input

Ask the user:

**Question 1** — Header: "Codebase source"
- Question: "Which repo should I analyze?"
- Options:
  - **GitHub repo URL** — "e.g., https://github.com/your-org/your-repo or your-org/your-repo"
  - **Multiple GitHub repos** — "Comma-separated list of owner/repo (for cross-repo analysis)"
  - **Local path** — "Absolute path to a locally cloned repo"

Collect the repo URL(s) or path. For GitHub URLs, extract `owner/repo`. Validate access:

```bash
# Public repos
gh repo view owner/repo --json name 2>/dev/null

# Private repos — will work if user has gh auth configured
gh repo view owner/repo --json name,isPrivate 2>/dev/null
```

If the repo is private, set `{PRIVATE_REPO}=true` and note that Dockerfiles will need auth tokens at build time.

**If QUICK_MODE**: skip remaining questions, set mining mode to SDLC, constraints to auto-discover, target 5-10 tasks. Go to Phase 2.

**Question 2** — Header: "Mining mode" *(full mining only)*
- Question: "What kind of benchmark tasks should I look for?"
- Options:
  - **SDLC tasks** — "Mine closed issues/PRs for real bug fixes, features, and refactors (agent must reproduce the code change)"
  - **Org-scale tasks** — "Analyze codebase structure for discovery, tracing, compliance, and comprehension tasks (agent produces answer artifacts)"
  - **Both** — "Run both analyses and propose a mixed set"

**Question 3** — Header: "Constraints" *(full mining only)*
- Question: "Any constraints on what to look for?"
- Options:
  - **Auto-discover** — "Let me analyze the repo and propose the best candidates"
  - **Specific area** — "Focus on a specific package, module, or subsystem (I'll specify)"
  - **Use cases provided** — "I have specific scenarios I want turned into tasks (I'll list them)"

If "Specific area", prompt for the package/module path.
If "Use cases provided", prompt for a list of use case descriptions (free text).

---

## Phase 2: Codebase Reconnaissance

Before mining, gather structural information about the repo(s).

### Step 2a: Repo Metadata

```bash
# Via GitHub API
gh repo view owner/repo --json name,primaryLanguage,languages,defaultBranchRef,diskUsage,stargazerCount,description,isPrivate

# Or for local repos
git log --oneline -1
wc -l $(find . -name '*.go' -o -name '*.py' -o -name '*.ts' -o -name '*.java' -o -name '*.cpp' -o -name '*.rs' | head -500) 2>/dev/null | tail -1
```

Record: primary language, approximate size (LOC / disk), default branch, description, private/public.

### Step 2b: Structure Analysis

For local repos or after cloning:

```bash
# Top-level directory structure
ls -d */

# Find key patterns
find . -name 'go.mod' -o -name 'package.json' -o -name 'Cargo.toml' -o -name 'setup.py' -o -name 'pyproject.toml' | head -20

# For Go: module path and key packages
head -5 go.mod 2>/dev/null
ls cmd/ pkg/ internal/ 2>/dev/null

# For multi-repo: cross-repo import analysis
rg -l 'import.*other-repo-module' --type go 2>/dev/null | head -20
```

### Step 2c: Code Search Tools (when available)

If Sourcegraph MCP tools are available (`SOURCEGRAPH_ACCESS_TOKEN` set):

```
mcp__sourcegraph__sg_keyword_search: "repo:^github.com/owner/repo$ import.*other-org"
```

If Deep Search CLI is available (`SRC_ACCESS_TOKEN` set):

```bash
bash ds start --question "What are the main subsystems and their dependencies in this codebase?"
```

If neither is available, fall back to local `rg`/`grep` analysis. This is fine — mining works without any external tools.

---

## Phase 3: SDLC Task Mining

Skip this phase if user selected "Org-scale tasks" only.

### Step 3a: Find Candidate Issues/PRs

```bash
# Find recently merged PRs (last 6 months)
gh pr list --repo owner/repo --state merged --limit 100 \
  --json number,title,body,labels,files,additions,deletions,closedAt,mergedAt

# Filter for good eval candidates:
# - Patch touches 1-15 files (not too small, not too large)
# - Has test changes (indicates verifiable fix)
# - Not a dependency bump, CI change, or trivial typo fix
# - Has a clear problem description
```

**For QUICK_MODE**: limit to 30 recent PRs, pick the top 5-10 by suitability score.

### Step 3b: Score and Rank Candidates

For each candidate PR, compute a suitability score:

| Criterion | Weight | Scoring |
|-----------|--------|---------|
| Patch size (files changed) | 0.25 | 1-3 files: 1.0, 4-8: 0.8, 9-15: 0.6, >15: 0.2 |
| Has test changes | 0.20 | Yes with fail-to-pass: 1.0, Yes: 0.7, No: 0.2 |
| Issue quality | 0.20 | Clear repro steps: 1.0, Good description: 0.7, Minimal: 0.3 |
| Code complexity | 0.15 | Non-trivial logic: 1.0, Config/docs: 0.3, Trivial: 0.1 |
| Language diversity | 0.10 | Underrepresented in CSB: 1.0, Well-covered: 0.5 |
| Recency | 0.10 | <3 months: 1.0, 3-6 months: 0.8, 6-12 months: 0.6 |

### Step 3c: Classify Task Category

| Signal | Category |
|--------|----------|
| Labels: bug, fix, hotfix, regression | `bug_fix` |
| Labels: feature, enhancement, feat | `feature` |
| Labels: refactor, cleanup, tech-debt | `refactoring` |
| Labels: test, testing, coverage | `test` |
| Labels: docs, documentation | `documentation` |
| Labels: security, CVE, vulnerability | `security` |
| PR title: "fix", "resolve", "patch" | `bug_fix` |
| PR title: "add", "implement", "support" | `feature` |
| PR title: "refactor", "clean", "simplify" | `refactoring` |

### Step 3d: Extract Task Details + Ground Truth

For the top candidates, extract:

```bash
# Get the pre-fix commit (base of the PR)
gh pr view NUMBER --repo owner/repo --json mergeCommit,baseRefOid

# Get the full patch
gh pr diff NUMBER --repo owner/repo

# Get linked issue body for the task instruction
gh issue view ISSUE_NUMBER --repo owner/repo --json body,title,labels
```

#### Auto-Generate Ground Truth

For each selected PR, automatically generate ground truth from the patch. This is the key data that makes the eval work — it defines what the agent should have changed.

```bash
# Extract the list of files changed
gh pr view NUMBER --repo owner/repo --json files --jq '.files[].path'

# Extract the full diff for verification
gh pr diff NUMBER --repo owner/repo > /tmp/pr_NUMBER.patch
```

Generate `ground_truth.json`:

```json
{
  "files": [
    {
      "path": "pkg/server/handler.go",
      "status": "modified"
    },
    {
      "path": "pkg/server/handler_test.go",
      "status": "modified"
    }
  ],
  "patch_stats": {
    "additions": 45,
    "deletions": 12,
    "files_changed": 2
  },
  "source_pr": {
    "number": 1234,
    "url": "https://github.com/owner/repo/pull/1234",
    "merge_commit": "abc123",
    "base_commit": "def456"
  }
}
```

Generate `test.sh` that verifies the agent's changes against the ground truth patch:

```bash
#!/bin/bash
set -e
cd /workspace

mkdir -p /logs/verifier
git config --global --add safe.directory /workspace 2>/dev/null || true

# Check if any changes were made
CHANGES=$(git diff --stat 2>/dev/null | wc -l)
STAGED=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
if [ "$CHANGES" -eq 0 ] && [ "$STAGED" -eq 0 ] && [ "$UNTRACKED" -eq 0 ]; then
    echo "No changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

SCORE=0
MAX_SCORE=10

# Check 1: Expected files were modified (5 points)
EXPECTED_FILES=({EXPECTED_FILE_LIST})
MODIFIED=0
for f in "${EXPECTED_FILES[@]}"; do
    if git diff --name-only | grep -q "$f" || \
       git diff --cached --name-only | grep -q "$f" || \
       git log --oneline HEAD~1..HEAD --name-only 2>/dev/null | grep -q "$f"; then
        MODIFIED=$((MODIFIED + 1))
    fi
done
FILE_SCORE=$(awk "BEGIN {printf \"%.0f\", 5 * $MODIFIED / ${#EXPECTED_FILES[@]}}")
SCORE=$((SCORE + FILE_SCORE))
echo "Files modified: $MODIFIED/${#EXPECTED_FILES[@]} (${FILE_SCORE}/5 points)"

# Check 2: Tests pass (5 points)
# {LANGUAGE_SPECIFIC_TEST_COMMAND}
if {TEST_COMMAND} 2>&1; then
    echo "PASS: Tests pass"
    SCORE=$((SCORE + 5))
else
    echo "FAIL: Tests failed"
fi

FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")
echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo "Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE})"
```

Fill in `{EXPECTED_FILE_LIST}` from the PR's changed files and `{TEST_COMMAND}` based on the language:

| Language | Test Command |
|----------|-------------|
| Go | `go test ./... -count=1 -timeout 120s` |
| Python | `python -m pytest -x --timeout=120` |
| TypeScript | `npm test` or `npx jest --forceExit` |
| Java | `./gradlew test` or `mvn test` |
| Rust | `cargo test` |
| C++ | `cmake --build build && ctest --test-dir build` |

### Step 3e: Generate Dockerfiles (Baseline + MCP)

For each task, generate **two** Dockerfiles.

#### Dockerfile.baseline — Full code, no MCP

```dockerfile
FROM {BASE_IMAGE}

RUN apt-get update && apt-get install -y git curl ripgrep && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi
RUN npm install -g @anthropic-ai/claude-code

# Clone repo at the pre-fix commit
{CLONE_COMMAND}

RUN mkdir -p /workspace/tests /logs/verifier
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

For **public repos**, `{CLONE_COMMAND}` is:
```dockerfile
RUN git clone --filter=blob:none https://github.com/{REPO}.git /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}
```

For **private repos**, `{CLONE_COMMAND}` uses a build-time secret:
```dockerfile
# Requires: docker build --secret id=gh_token,env=GH_TOKEN .
RUN --mount=type=secret,id=gh_token \
    GH_TOKEN=$(cat /run/secrets/gh_token) && \
    git clone --filter=blob:none https://x-access-token:${GH_TOKEN}@github.com/{REPO}.git /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}
```

#### Dockerfile.mcp — Truncated code + MCP tools

The MCP variant gives the agent a **truncated** view of the codebase (stubs only, no function bodies) and access to MCP code search tools. This tests whether MCP helps the agent find and understand the relevant code.

```dockerfile
FROM {BASE_IMAGE}

RUN apt-get update && apt-get install -y git curl ripgrep jq && rm -rf /var/lib/apt/lists/*

RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi
RUN npm install -g @anthropic-ai/claude-code

# Clone repo (will be truncated below)
{CLONE_COMMAND}

# Truncate source files to stubs (signatures only, no bodies)
# This forces the agent to use MCP tools to understand the code
RUN find /workspace -type f \( -name '*.go' -o -name '*.py' -o -name '*.ts' -o -name '*.java' \
    -o -name '*.cpp' -o -name '*.rs' -o -name '*.c' -o -name '*.h' \) \
    -exec sh -c 'head -50 "$1" > "$1.stub" && mv "$1.stub" "$1"' _ {} \;

# MCP configuration
{MCP_CONFIG_BLOCK}

RUN mkdir -p /workspace/tests /logs/verifier
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

`{MCP_CONFIG_BLOCK}` depends on the provider selected in Phase 0:

**Sourcegraph:**
```dockerfile
RUN mkdir -p /root/.config/claude && \
    echo '{"mcpServers":{"sourcegraph":{"command":"npx","args":["-y","@sourcegraph/mcp-server"],"env":{"SRC_ACCESS_TOKEN":"__SG_TOKEN__","SOURCEGRAPH_URL":"__SG_URL__"}}}}' \
    > /root/.config/claude/mcp.json
```

**GitHub Copilot:**
```dockerfile
RUN mkdir -p /root/.config/claude && \
    echo '{"mcpServers":{"github":{"command":"npx","args":["-y","@github/mcp-server"],"env":{"GITHUB_TOKEN":"__GH_TOKEN__"}}}}' \
    > /root/.config/claude/mcp.json
```

**Custom MCP:**
```dockerfile
COPY mcp.json /root/.config/claude/mcp.json
```

**Placeholder (not sure yet):**
```dockerfile
# TODO: Add your MCP configuration here
# Create /root/.config/claude/mcp.json with your MCP server config
# See https://docs.anthropic.com/en/docs/claude-code/mcp for format
RUN mkdir -p /root/.config/claude && \
    echo '{"mcpServers":{}}' > /root/.config/claude/mcp.json
```

### Step 3f: Extract Reviewer Information *(full mining only)*

For each candidate PR, extract reviewer and contributor metadata:

```bash
gh pr view NUMBER --repo owner/repo --json author,mergedBy,reviews
gh api repos/owner/repo/pulls/NUMBER/reviews --jq '.[].user.login'

# Top contributors for touched code areas
gh api "repos/owner/repo/commits?path=pkg/changed_dir/&per_page=30" \
  --jq '.[].author.login' | sort | uniq -c | sort -rn | head -5
```

Filter out bot accounts (dependabot, renovate, bors, k8s-ci-robot, etc.).

### Difficulty Estimation

| Files Changed | Lines Changed | Cross-Package | Difficulty |
|---------------|---------------|---------------|------------|
| 1-2 | <50 | No | medium |
| 1-3 | 50-200 | No | hard |
| 3-8 | 50-500 | Yes | hard |
| 4-10 | 200-1000 | Yes | very_hard |
| 10+ | 500+ | Yes | expert |

---

## Phase 4: Org-Scale Task Mining *(full mining only)*

Skip this phase in quick eval mode or if user selected "SDLC tasks" only.

### Step 4a: Cross-Repo Dependency Analysis

For multi-repo inputs, identify cross-repo relationships:

```bash
# Go: find cross-module imports
rg 'import.*"(other-org/other-repo)' --type go -l

# Python: find cross-package imports
rg 'from (other_package) import|import (other_package)' --type py -l

# Proto/gRPC: find proto imports across repos
rg 'import ".*\.proto"' --type proto -l

# JS/TS: find cross-package requires/imports
rg "require\('(@other-org|other-package)" --type js -l
```

For single repos, analyze internal module boundaries:

```bash
# Go: list internal packages and their importers
go list ./... 2>/dev/null | head -50
rg 'import.*".*internal/' --type go -l | head -20

# Find interface definitions (potential tracing targets)
rg '(type|interface|trait|abstract class)\s+\w+' --type go --type java --type py -l | head -30
```

### Step 4b: Identify Org-Scale Task Patterns

| Pattern | Task Family | Detection Method |
|---------|-------------|-----------------|
| Shared proto/IDL definitions | `cross-repo-dep-trace` | Find `.proto` files imported across repos |
| Shared library packages | `cross-repo-dep-trace` | Find packages imported by 3+ consumers |
| Config propagation chains | `cross-repo-config-trace` | Find config structs used across module boundaries |
| API surface definitions | `onboarding-comprehension` | Find exported interfaces/types in `pkg/` or `api/` |
| Deprecated APIs | `migration-inventory` | Find `@Deprecated`, `// Deprecated:`, `#[deprecated]` |
| Security-sensitive patterns | `compliance-audit` | Find TLS configs, auth middleware, secret handling |
| Error handling chains | `incident-debug` | Find error types that propagate across packages |
| Plugin/extension points | `platform-knowledge` | Find plugin registries, factory patterns, hook systems |
| Domain model relationships | `domain-lineage` | Find entity types and their relationships |

### Step 4c: Generate Org-Scale Proposals

For each identified pattern, propose a task with a natural-language question:

- **Cross-repo dep trace**: "Which {language} source files in the `{package}/` tree of `{repo}` directly import `{dependency}`?"
- **Config trace**: "Trace how the `{ConfigType}` configuration defined in `{repo1}` gets consumed by `{repo2}`."
- **Compliance audit**: "Find all files in `{repo}` that configure TLS/SSL settings."
- **Migration inventory**: "Find all uses of the deprecated `{API}` across `{repo1}` and `{repo2}`."
- **Incident debug**: "Given that `{ErrorType}` is being thrown at runtime, trace the error origin across `{repo1}` and `{repo2}`."
- **Onboarding comprehension**: "Explain the architecture of the `{subsystem}` in `{repo}`."

### Step 4d: Extract Reviewer Information for Org Tasks

```bash
for repo in owner/repo1 owner/repo2; do
  for area in pkg/shared/ internal/consumer/; do
    gh api "repos/$repo/commits?path=$area&per_page=30" \
      --jq '.[].author.login' | sort | uniq -c | sort -rn | head -5
  done
done
```

---

## Phase 5: Feasibility Checks

### SDLC Feasibility

For each SDLC proposal:

1. **Commit exists**: `gh api repos/owner/repo/commits/SHA --jq '.sha' 2>/dev/null`
2. **Repo is cloneable**: `git ls-remote https://github.com/owner/repo.git HEAD 2>/dev/null`
3. **Patch is self-contained**: No external service deps, no DB migrations, no CI artifacts required.
4. **No secrets in patch**: PR diff doesn't contain API keys, tokens, or credentials.

### Org-Scale Feasibility *(full mining only)*

1. **Repos accessible**: All referenced repos exist and user has access.
2. **Oracle is deterministic**: The question has a concrete, verifiable answer (file lists, symbol names).
3. **Task is non-trivial**: Requires searching at least 3 files.

---

## Phase 6: Generate Output

### Quick Eval Mode

Write all task files to a single output directory:

```
{REPO_NAME}-eval/
  tasks/
    {task-id-1}/
      instruction.md          # Task description from issue/PR
      ground_truth.json        # Auto-generated from PR patch
      environment/
        Dockerfile.baseline    # Full code, no MCP
        Dockerfile.mcp         # Truncated code + MCP tools
      tests/
        test.sh                # Verifier script
  run_eval.sh                  # One-command runner (see below)
  README.md                    # How to interpret results
```

#### Generate run_eval.sh

This is a standalone runner that doesn't require Harbor or Daytona:

```bash
#!/bin/bash
# Run baseline-vs-MCP eval for {REPO_NAME}
# Usage: ./run_eval.sh [--tasks N] [--timeout SECONDS]
#
# Required environment variables:
#   ANTHROPIC_API_KEY    — Claude API key
# Optional (for MCP variant):
#   {MCP_ENV_VARS}       — Provider-specific tokens

set -euo pipefail

TASKS_DIR="$(cd "$(dirname "$0")/tasks" && pwd)"
RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)/results"
TIMEOUT="${2:-900}"
mkdir -p "$RESULTS_DIR"

TASK_DIRS=($(ls -d "$TASKS_DIR"/*/))

echo "=== {REPO_NAME} Eval ==="
echo "Tasks: ${#TASK_DIRS[@]}"
echo "Timeout per task: ${TIMEOUT}s"
echo ""

for task_dir in "${TASK_DIRS[@]}"; do
    task_id=$(basename "$task_dir")
    echo "--- Task: $task_id ---"

    for config in baseline mcp; do
        dockerfile="$task_dir/environment/Dockerfile.$config"
        if [ ! -f "$dockerfile" ]; then
            echo "  SKIP $config (no Dockerfile)"
            continue
        fi

        result_dir="$RESULTS_DIR/$task_id/$config"
        mkdir -p "$result_dir"

        echo "  Building $config image..."
        docker build -f "$dockerfile" -t "eval-${task_id}-${config}" \
            "$task_dir/environment/" 2>"$result_dir/build.log" || {
            echo "  FAIL: build error (see $result_dir/build.log)"
            continue
        }

        echo "  Running $config agent (timeout: ${TIMEOUT}s)..."
        # Run the agent inside the container
        timeout "$TIMEOUT" docker run --rm \
            -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
            -v "$result_dir:/logs" \
            "eval-${task_id}-${config}" \
            bash -c "
                claude --print-only-result \
                    'Read /workspace/tests/instruction.md and complete the task. When done, run: bash /workspace/tests/test.sh' \
                    2>/logs/agent.log || true
                bash /workspace/tests/test.sh 2>&1 | tee /logs/test_output.log
            " 2>"$result_dir/run.log" || {
            echo "  TIMEOUT or error"
            echo "0.0" > "$result_dir/reward.txt"
        }

        # Extract score
        if [ -f "$result_dir/reward.txt" ]; then
            score=$(cat "$result_dir/reward.txt")
        else
            score="0.0"
        fi
        echo "  $config score: $score"

        # Cleanup image
        docker rmi "eval-${task_id}-${config}" 2>/dev/null || true
    done
    echo ""
done

# Print summary
echo "=== Results Summary ==="
echo ""
printf "%-40s %-10s %-10s %-10s\n" "Task" "Baseline" "MCP" "Delta"
printf "%-40s %-10s %-10s %-10s\n" "----" "--------" "---" "-----"

total_bl=0
total_mcp=0
count=0

for task_dir in "${TASK_DIRS[@]}"; do
    task_id=$(basename "$task_dir")
    bl_score=$(cat "$RESULTS_DIR/$task_id/baseline/reward.txt" 2>/dev/null || echo "N/A")
    mcp_score=$(cat "$RESULTS_DIR/$task_id/mcp/reward.txt" 2>/dev/null || echo "N/A")

    if [ "$bl_score" != "N/A" ] && [ "$mcp_score" != "N/A" ]; then
        delta=$(awk "BEGIN {printf \"%.1f\", $mcp_score - $bl_score}")
        total_bl=$(awk "BEGIN {print $total_bl + $bl_score}")
        total_mcp=$(awk "BEGIN {print $total_mcp + $mcp_score}")
        count=$((count + 1))
    else
        delta="N/A"
    fi

    printf "%-40s %-10s %-10s %-10s\n" "$task_id" "$bl_score" "$mcp_score" "$delta"
done

if [ "$count" -gt 0 ]; then
    avg_bl=$(awk "BEGIN {printf \"%.2f\", $total_bl / $count}")
    avg_mcp=$(awk "BEGIN {printf \"%.2f\", $total_mcp / $count}")
    avg_delta=$(awk "BEGIN {printf \"%.2f\", ($total_mcp - $total_bl) / $count}")
    echo ""
    printf "%-40s %-10s %-10s %-10s\n" "AVERAGE ($count tasks)" "$avg_bl" "$avg_mcp" "$avg_delta"
fi
```

Present the output directory and print the commands:

```
Quick Eval Ready!

  Output:  {REPO_NAME}-eval/
  Tasks:   {N} tasks mined from {REPO}

To run the eval:

  export ANTHROPIC_API_KEY=sk-...
  # For Sourcegraph MCP:
  export SOURCEGRAPH_ACCESS_TOKEN=sgp_...
  export SOURCEGRAPH_URL=https://sourcegraph.com

  cd {REPO_NAME}-eval
  bash run_eval.sh

Results will be written to {REPO_NAME}-eval/results/
```

### Full Mining Mode

Present proposals in a summary table:

```
=== SDLC Task Proposals ===

| # | Task ID | Category | Difficulty | Files | Score | Source |
|---|---------|----------|------------|-------|-------|--------|
| 1 | myrepo-leak-fix-001 | bug_fix | hard | 3 | 0.92 | PR #1234 |
| 2 | myrepo-auth-feat-001 | feature | medium | 2 | 0.85 | PR #5678 |

=== Org-Scale Task Proposals ===

| # | Task ID | Category | Difficulty | Repos | Pattern | Confidence |
|---|---------|----------|------------|-------|---------|------------|
| 1 | myrepo-dep-trace-001 | cross-repo-dep-trace | hard | 3 | shared_lib | high |
```

Then ask:

**Question** — Header: "Selection"
- Question: "Which proposals should I scaffold? (Enter numbers, 'all', or 'none')"

For each selected proposal, invoke `/scaffold-task` with pre-filled values.

---

## Phase 7: Summary

### Quick Eval Summary

```
Mining Complete
  Source:     owner/repo
  Language:   {LANGUAGE}
  PRs analyzed: {N}
  Tasks generated: {M}

Tasks:
  1. {task-id-1}  ({category}, {difficulty}) — PR #{NUM}
  2. {task-id-2}  ({category}, {difficulty}) — PR #{NUM}
  ...

Output: {REPO_NAME}-eval/

Run:
  export ANTHROPIC_API_KEY=sk-...
  cd {REPO_NAME}-eval && bash run_eval.sh
```

### Full Mining Summary

```
Mining Summary
  Source:     owner/repo (+ N other repos)
  Language:   {LANGUAGE}
  Analyzed:   {N} merged PRs, {M} cross-repo patterns

  SDLC proposals:      {A} found, {B} feasible, {C} scaffolded
  Org-scale proposals:  {D} found, {E} feasible, {F} scaffolded

Scaffolded tasks:
  1. myrepo-leak-fix-001   → benchmarks/csb_sdlc_fix/myrepo-leak-fix-001/
  2. myrepo-dep-trace-001  → benchmarks/csb_org_crossrepo/myrepo-dep-trace-001/

Next steps:
  1. Review instruction.md for each task — fill in TODOs
  2. Review reviewers.json — verify suggested reviewers are accurate
  3. Customize test.sh / oracle_checks.py with task-specific verification
  4. For SDLC tasks: verify the ground_truth_rev produces a passing test
  5. For org-scale tasks: populate task_spec.json with oracle checks
  6. Run /validate-tasks on each scaffolded task
```

---

## Language → Base Image Mapping

| Language | Base Image |
|----------|-----------|
| go | `golang:1.23-bookworm` |
| python | `python:3.11-bookworm` |
| cpp | `gcc:13-bookworm` |
| rust | `rust:1.75-bookworm` |
| typescript | `node:20-bookworm` |
| java | `eclipse-temurin:21-bookworm` |
| c | `gcc:13-bookworm` |
| csharp | `mcr.microsoft.com/dotnet/sdk:8.0` |
| mixed | `ubuntu:22.04` |

---

## Fallback Strategies

### No GitHub API access (`gh` not authenticated)
- Skip SDLC mining (requires PR/issue data).
- Org-scale mining works with local repo analysis only.
- Suggest: `gh auth login` and retry.

### Private repo without auth
- Dockerfiles can't clone without a token.
- Print instructions for `docker build --secret id=gh_token,env=GH_TOKEN`.
- Alternatively, suggest the user clone locally and use the "Local path" input.

### No MCP provider configured
- Generate Dockerfile.baseline only and placeholder Dockerfile.mcp.
- Print instructions for adding MCP config later.
- The baseline eval still works standalone.

### Very large repo (>5GB)
- Use `--depth 1` shallow clone for analysis.
- Limit PR scanning to last 3 months.
- Focus on specific subsystems if user provided a focus area.

### No merged PRs found
- Fall back to analyzing recent commits directly.
- Look for commits with messages containing "fix", "bug", "resolve".
- Propose tasks based on commit diffs instead of PR metadata.

### Single repo for org-scale
- Analyze internal module boundaries as "cross-package" tasks.
- Propose comprehension, audit, and incident-debug tasks within a single repo.
- Suggest additional repos in the same ecosystem for cross-repo tasks.

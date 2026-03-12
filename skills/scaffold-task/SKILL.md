---
name: scaffold-task
description: Scaffold a new Harbor-compatible benchmark task (SDLC or org-scale) and optionally a new benchmark suite. Generates task.toml, instruction.md, Dockerfile, test.sh, and registers the task. Triggers on scaffold task, new task, create task, add task, new benchmark.
user-invocable: true
---

# Scaffold Task

Interactively scaffold a new Harbor-compatible benchmark task for CodeScaleBench. Supports both **SDLC tasks** (code changes in a single repo) and **org-scale tasks** (cross-repo discovery, compliance, incident triage — artifact-based evaluation). Generates all required files and registers the task in the selection registry.

This is an **interactive skill**. Walk the user through configuration using AskUserQuestion in multiple phases. Do NOT generate files without first collecting all required inputs.

---

## Phase 1: Mode Selection

Ask one question:

**Question 1** — Header: "Mode"
- Question: "What would you like to create?"
- Options:
  - **Add SDLC task to existing suite** — "Create a new task in an existing csb_sdlc_* benchmark (agent makes code changes)"
  - **Add org-scale task to existing suite** — "Create a new task in an existing csb_org_* benchmark (agent produces an answer artifact)"
  - **Create new SDLC suite** — "Create a new csb_sdlc_* benchmark with its first task and run config"
  - **Create new org-scale suite** — "Create a new csb_org_* benchmark with its first task and run config"

Set `{TASK_FAMILY}` to either `sdlc` or `org` based on the selection.

---

## Phase 2: Core Details

Ask 3-4 questions depending on mode.

### If adding to existing SDLC suite:

**Question 1** — Header: "Benchmark"
- Question: "Which SDLC benchmark suite?"
- Options:
  - **swebenchpro** — "Real-world SWE across repos (Go, TS, Python)"
  - **pytorch** — "PyTorch PR-level tasks (Python/C++)"
  - **locobench** — "Long-context understanding (mixed languages)"
  - **k8sdocs** — "Kubernetes documentation (Go)"
- Note: User can type "Other" for tac, largerepo, sweperf, crossrepo, dibench

### If adding to existing org-scale suite:

**Question 1** — Header: "Benchmark"
- Question: "Which org-scale benchmark suite?"
- Options:
  - **crossrepo** — "Cross-repo dependency tracing"
  - **crossrepo_tracing** — "Cross-repo config/dep tracing with provenance"
  - **crossorg** — "Cross-organization discovery"
  - **compliance** — "Compliance audit tasks"
  - **migration** — "Migration inventory and planning"
  - **incident** — "Incident debug and triage"
  - **onboarding** — "Onboarding comprehension"
  - **domain** — "Domain lineage tasks"
  - **platform** — "Platform knowledge tasks"
  - **security** — "Vulnerability remediation"
  - **org** — "Agentic correctness"

### If creating new suite:

Prompt the user (not AskUserQuestion) to provide:
- **Suite name**: Will become `csb_{sdlc|org}_{name}` (lowercase, alphanumeric + hyphens)

Then ask:

**Question 1** — Header: "Language"
- Question: "Primary language for this benchmark?"
- Options:
  - **python** — "Python 3.11 base image"
  - **go** — "Go 1.23 base image"
  - **typescript** — "Node 20 base image"
  - **cpp** — "GCC 13 base image"

**Question 2** — Header: "Difficulty"
- Question: "Task difficulty level?"
- Options:
  - **medium** — "1-3 files changed, straightforward"
  - **hard** — "4-10 files or complex logic"
  - **very_hard** — "10+ files, deep codebase knowledge"
  - **expert** — "Architectural-level, cross-module"

**Question 3** — Header: "Task type"
- Question: "How is the task environment set up?"
- Options:
  - **repo-clone** — "Clone a git repo at a specific commit (most common)"
  - **multi-repo-clone** — "Clone multiple repos (org-scale tasks)" *(org only)*
  - **pre-built-image** — "FROM an existing Docker image (e.g., TAC tasks)"
  - **standalone** — "Empty workspace, no repo (agent creates everything)"

For existing suites, also ask Language, Difficulty, and Task type (same questions).

---

## Phase 3: Task-Specific Inputs

Prompt the user for these values (use text prompts, not AskUserQuestion since these are free-form):

### SDLC tasks:

| Input | Required | Default | Example |
|-------|----------|---------|---------|
| Task ID | Yes | — | `my-feature-001` |
| Description | Yes | — | "Fix race condition in connection pool" |
| Repo (owner/name) | If repo-clone | — | `pytorch/pytorch` |
| Commit hash | If repo-clone | — | `ca2466126a00ba8fd877f5a185e40e36ddaceb87` |
| Base image | If pre-built | — | `ghcr.io/theagentcompany/tac-base:latest` |
| SDLC phase | Yes | "Implementation (feature)" | See list below |
| Category | Yes | "feature" | `bug_fix`, `refactoring`, `documentation`, etc. |
| Time limit (sec) | No | 900 | `600` |

Valid SDLC phases: "Requirements & Discovery", "Architecture & Design", "Implementation (feature)", "Implementation (bug fix)", "Implementation (refactoring)", "Testing & QA", "Documentation", "Maintenance"

### Org-scale tasks:

| Input | Required | Default | Example |
|-------|----------|---------|---------|
| Task ID | Yes | — | `CCX-crossorg-301` |
| Description | Yes | — | "Trace gRPC service dependency chain across K8s repos" |
| Repos (owner/name) | Yes (1+) | — | `kubernetes/kubernetes`, `kubernetes/client-go` |
| Commit/tag per repo | If repo-clone | — | `v1.32.0` |
| Category | Yes | — | `cross-repo-dep-trace`, `compliance-audit`, etc. |
| Difficulty | Yes | "hard" | `hard`, `very_hard`, `expert` |
| Time limit (sec) | No | 900 | `600` |

---

## Phase 4: File Generation

Generate all files using the templates below. Use the Write tool for each file.

### Language → Base Image Mapping

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

### SDLC Templates

#### Template 1: task.toml (SDLC)

Write to `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/task.toml`:

```toml
version = "1.0"
[metadata]
name = "{TASK_ID}"
description = "{DESCRIPTION}"
license = "MIT"

[task]
id = "{TASK_ID}"
repo = "{REPO_SHORT_NAME}"
category = "{CATEGORY}"
language = "{LANGUAGE}"
difficulty = "{DIFFICULTY}"
time_limit_sec = {TIME_LIMIT}

[verification]
type = "test"
command = "bash /workspace/tests/test.sh"

[environment]
build_timeout_sec = 1800.0

[environment.setup_scripts]
mcp_config = """#!/bin/bash
# Setup Sourcegraph MCP if credentials provided
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ] && [ -n "$SOURCEGRAPH_URL" ]; then
  echo "Setting up Sourcegraph MCP configuration..."
  mkdir -p /root/.config/claude

  cat > /root/.config/claude/mcp.json << 'EOF'
{
  "mcpServers": {
    "sourcegraph": {
      "command": "npx",
      "args": ["-y", "@sourcegraph/mcp-server"],
      "env": {
        "SRC_ACCESS_TOKEN": "$SOURCEGRAPH_ACCESS_TOKEN",
        "SOURCEGRAPH_URL": "$SOURCEGRAPH_URL"
      }
    }
  }
}
EOF

  echo "PASS MCP configuration created"
else
  echo "No Sourcegraph credentials provided, MCP disabled"
fi
exit 0
"""
```

Notes:
- `{REPO_SHORT_NAME}` is just the repo name without owner (e.g., `pytorch` from `pytorch/pytorch`)
- For pre-built-image tasks, omit the `repo` field if there's no git repo
- For standalone tasks, omit the `repo` field

#### Template 2: Dockerfile (SDLC, repo-clone type)

Write to `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/environment/Dockerfile`:

```dockerfile
FROM {BASE_IMAGE}

# Install common tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone repo at pinned commit
RUN git clone --filter=blob:none https://github.com/{REPO}.git /workspace && \
    cd /workspace && \
    git checkout {COMMIT}

# Create directories
RUN mkdir -p /workspace/tests /logs/verifier

# Copy test files
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

#### Template 2b: Dockerfile (SDLC, pre-built-image type)

```dockerfile
FROM {BASE_IMAGE}

# Create directories
RUN mkdir -p /workspace /logs/verifier

# Copy test files
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

#### Template 2c: Dockerfile (SDLC, standalone type)

```dockerfile
FROM {BASE_IMAGE}

# Install common tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Create directories
RUN mkdir -p /workspace/tests /logs/verifier

# Copy test files
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

#### Template 3: instruction.md (SDLC)

Write to `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/instruction.md`:

```markdown
# {TITLE}

- **Repository**: {REPO}
- **Difficulty**: {DIFFICULTY}
- **Category**: {CATEGORY}
- **Task Type**: {TASK_TYPE}

## Description

{DESCRIPTION}

## Task

<!-- Describe the specific work the agent must do -->
YOU MUST IMPLEMENT CODE CHANGES to complete this task.

TODO: Add detailed task instructions here.

## Success Criteria

- [ ] TODO: Define measurable success criteria
- [ ] All changes are committed to the workspace

## Testing

- **Time limit**: {TIME_LIMIT} seconds
- Run `bash /workspace/tests/test.sh` to verify your changes
```

Notes:
- `{TITLE}` is derived from the task ID: replace hyphens with spaces, title-case
- The TODO sections are placeholders for the user to fill in after scaffolding

#### Template 4: test.sh (SDLC)

Write to `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/tests/test.sh`:

```bash
#!/bin/bash
# Test script for {TASK_ID}: {DESCRIPTION}

set -e

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Fix git safe.directory
git config --global --add safe.directory /workspace 2>/dev/null || true

# Guard: if no code changes were made, the agent didn't execute successfully
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
COMMIT_COUNT=0
ORIGIN_REF=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF="$ref"
        break
    fi
done
if [ -n "$ORIGIN_REF" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF..HEAD" 2>/dev/null | wc -l)
elif git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
else
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    if [ "$TOTAL_COMMITS" -gt 1 ]; then
        COMMIT_COUNT=$((TOTAL_COMMITS - 1))
    fi
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected - agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

# ── Scoring ──────────────────────────────────────────────
SCORE=0
MAX_SCORE=10

# TODO: Add verification checks here. Examples:
#
# Check 1: Required file exists (2 points)
# if [ -f "path/to/expected/file" ]; then
#     echo "PASS: Expected file exists"
#     SCORE=$((SCORE + 2))
# else
#     echo "FAIL: Expected file not found"
# fi
#
# Check 2: File contains expected pattern (2 points)
# if grep -q "expected_pattern" "path/to/file"; then
#     echo "PASS: Expected pattern found"
#     SCORE=$((SCORE + 2))
# else
#     echo "FAIL: Expected pattern not found"
# fi

echo "WARNING: Using placeholder scoring - customize this test script"
SCORE=$MAX_SCORE  # Remove this line after adding real checks

# Convert to decimal score (0.0 - 1.0)
FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")

echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo ""
echo "Tests completed - Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE} checks passed)"
```

#### Template 5: reviewers.json (SDLC — also applies to org-scale tasks)

Write to `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/reviewers.json`:

After creating the task directory, generate a `reviewers.json` by querying GitHub for contributor and reviewer information. Use the backfill script or query the API directly:

```bash
# Option A: Use the backfill script for a single task
python3 scripts/backfill_reviewers.py --task-dir benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}

# Option B: Manual generation via gh CLI
gh api "repos/{REPO}/commits?path={CODE_AREA}&per_page=30" --jq '.[].author.login' | sort | uniq -c | sort -rn | head -5
```

If the task was mined from a specific PR (Phase 3), include the full PR metadata:

```json
{
  "task_id": "{TASK_ID}",
  "repos": ["{REPO}"],
  "source_pr": {
    "number": {PR_NUMBER},
    "url": "https://github.com/{REPO}/pull/{PR_NUMBER}",
    "author": "{PR_AUTHOR}",
    "merged_by": "{MERGER}",
    "reviewers": ["{REVIEWER1}", "{REVIEWER2}"]
  },
  "top_contributors": [
    {"login": "{CONTRIBUTOR1}", "commits": {N}},
    {"login": "{CONTRIBUTOR2}", "commits": {M}}
  ],
  "code_areas": ["{DIR1}/", "{DIR2}/"],
  "suggested_reviewers": ["{REVIEWER1}", "{CONTRIBUTOR1}", "{PR_AUTHOR}"],
  "discovery_method": "source_pr"
}
```

If no source PR is available, use the git log frequency method:

```json
{
  "task_id": "{TASK_ID}",
  "repos": ["{REPO}"],
  "top_contributors": [
    {"login": "{CONTRIBUTOR1}", "commits": {N}},
    {"login": "{CONTRIBUTOR2}", "commits": {M}}
  ],
  "code_areas": ["{DIR1}/", "{DIR2}/"],
  "suggested_reviewers": ["{CONTRIBUTOR1}", "{CONTRIBUTOR2}", "{CONTRIBUTOR3}"],
  "discovery_method": "git_log_frequency"
}
```

Exclude bot accounts from all lists: dependabot, renovate, bors, k8s-ci-robot, copybara-service, etc.

---

### Org-Scale Templates

#### Template 1: task.toml (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/task.toml`:

```toml
version = "1.0"

[metadata]
name = "{TASK_ID}"
description = "{DESCRIPTION}"
license = "Apache-2.0"

[task]
id = "{TASK_ID}"
repo = "{PRIMARY_REPO}"
category = "{CATEGORY}"
language = "{LANGUAGE}"
difficulty = "{DIFFICULTY}"
time_limit_sec = {TIME_LIMIT}
mcp_suite = "csb_org_{BENCHMARK}"
org_scale = true
verification_modes = ["artifact"]

[verification]
type = "test"
command = "bash /tests/test.sh"
reward_type = "score"
description = "{DESCRIPTION}"

[environment]
build_timeout_sec = 600.0
```

Notes:
- `{PRIMARY_REPO}` uses the sg-evals mirror format if available (e.g., `sg-evals/kubernetes--v1.32.0`), otherwise `owner/repo`
- `verification.command` uses `/tests/test.sh` (NOT `/workspace/tests/test.sh` — Harbor uploads tests to `/tests/`)
- `org_scale = true` marks this as an organizational use-case benchmark

#### Template 2: Dockerfile (org-scale, multi-repo-clone)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/environment/Dockerfile`:

```dockerfile
FROM {BASE_IMAGE}

# Install common tools
RUN apt-get update && apt-get install -y \
    git curl jq ripgrep python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone repos at pinned versions
{CLONE_COMMANDS}

# Create directories
RUN mkdir -p /workspace /tests /logs/verifier

COPY tests/ /tests/
RUN chmod +x /tests/test.sh /tests/eval.sh 2>/dev/null || true

WORKDIR /workspace
```

For each repo, generate a clone command like:
```dockerfile
RUN git clone --filter=blob:none https://github.com/{REPO}.git /workspace/{REPO_DIR} && \
    cd /workspace/{REPO_DIR} && \
    git checkout {COMMIT_OR_TAG}
```

Where `{REPO_DIR}` is derived from the repo name (e.g., `kubernetes` from `kubernetes/kubernetes`).

#### Template 2b: Dockerfile (org-scale, single repo-clone)

Same as multi-repo but with a single clone command.

#### Template 3: instruction.md (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/instruction.md`:

```markdown
# {TITLE}

## Context

You have access to the following repositories in `/workspace/`:

{REPO_LIST}

## Task

{DESCRIPTION}

## Deliverable

Write your answer to `/workspace/answer.json` with the following structure:

```json
{
  "task_id": "{TASK_ID}",
  "findings": [
    {
      "description": "TODO: describe finding",
      "files": ["path/to/relevant/file"],
      "evidence": "TODO: supporting evidence"
    }
  ]
}
```

## Constraints

- **Time limit**: {TIME_LIMIT} seconds
- Your answer MUST be valid JSON written to `/workspace/answer.json`
- Be thorough — recall matters more than precision
```

Notes:
- `{REPO_LIST}` is a bulleted list of repos with their paths, e.g., `- kubernetes/kubernetes → /workspace/kubernetes`
- Org-scale instructions must be **tool-neutral** — do NOT mention MCP, Sourcegraph, or specific tools. Both baseline and MCP agents must be able to solve the task.

#### Template 4: eval.sh (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/eval.sh`:

```bash
#!/bin/bash
# eval.sh — org-scale benchmark evaluator for {TASK_ID}
# Exit-code-first (SWE-Factory pattern):
#   exit 0 — agent produced useful output (composite score > 0)
#   exit 1 — total failure (composite score == 0 or missing answer)
#
# Writes /logs/verifier/reward.txt with the composite score [0.0, 1.0]

set -euo pipefail

TASK_ID="{TASK_ID}"
ANSWER_PATH="/workspace/answer.json"
TASK_SPEC_PATH="/tests/task_spec.json"
ORACLE_CHECKS="/tests/oracle_checks.py"
REWARD_PATH="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

echo "=== {TASK_ID} evaluator ==="
echo "Task spec: $TASK_SPEC_PATH"

# --- Guard: answer.json must exist and be valid JSON ---
if [ ! -f "$ANSWER_PATH" ]; then
    echo "FAIL: $ANSWER_PATH not found"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi
if ! python3 -c "import json; json.load(open('$ANSWER_PATH'))" 2>/dev/null; then
    echo "FAIL: $ANSWER_PATH is not valid JSON"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

# --- Run oracle checks ---
if [ -f "$ORACLE_CHECKS" ] && [ -f "$TASK_SPEC_PATH" ]; then
    SCORE=$(python3 "$ORACLE_CHECKS" "$TASK_SPEC_PATH" "$ANSWER_PATH" 2>&1) || true
    echo "Oracle score: $SCORE"
    echo "$SCORE" > "$REWARD_PATH"
else
    echo "WARNING: oracle_checks.py or task_spec.json missing, using placeholder"
    echo "0.5" > "$REWARD_PATH"
fi

FINAL=$(cat "$REWARD_PATH")
echo "Final score: $FINAL"

if [ "$(echo "$FINAL > 0" | bc -l 2>/dev/null || echo 0)" = "1" ]; then
    exit 0
else
    exit 1
fi
```

#### Template 5: test.sh (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/test.sh`:

```bash
#!/bin/bash
# test.sh — wrapper that delegates to eval.sh
exec bash /tests/eval.sh "$@"
```

#### Template 6: oracle_checks.py (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/oracle_checks.py`:

```python
#!/usr/bin/env python3
"""Deterministic oracle check library for org-scale benchmark evaluation.

Provides reusable check functions that eval.sh scripts invoke to score agent
answers against closed-world oracle definitions. Returns raw scores (no
rounding) so the caller controls final precision.
"""

import json
import sys


def main():
    if len(sys.argv) < 3:
        print("Usage: oracle_checks.py <task_spec.json> <answer.json>", file=sys.stderr)
        print("0.0")
        sys.exit(0)

    with open(sys.argv[1]) as f:
        spec = json.load(f)
    with open(sys.argv[2]) as f:
        answer = json.load(f)

    # TODO: Implement oracle checks against spec
    # Example: check that required files/symbols are found
    checks = spec.get("evaluation", {}).get("checks", [])
    if not checks:
        print("0.5")  # No checks defined yet
        return

    passed = 0
    total = len(checks)
    for check in checks:
        # TODO: implement check logic
        passed += 1

    score = passed / total if total > 0 else 0.0
    print(f"{score:.4f}")


if __name__ == "__main__":
    main()
```

#### Template 7: task_spec.json (org-scale)

Write to `benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/task_spec.json`:

```json
{
  "task_id": "{TASK_ID}",
  "evaluation": {
    "checks": []
  }
}
```

Note: The checks array should be populated with oracle checks after the task is authored. Use `scripts/generate_csb_org_tasks.py` or manual curation.

---

## Phase 5: Registration

### Add to selected_benchmark_tasks.json

Read `configs/selected_benchmark_tasks.json`, then use Edit to append a new task entry to the `tasks` array (before the closing `]`).

#### SDLC registration entry:

```json
{
  "task_id": "{TASK_ID}",
  "benchmark": "csb_sdlc_{BENCHMARK}",
  "sdlc_phase": "{SDLC_PHASE}",
  "language": "{LANGUAGE}",
  "difficulty": "{DIFFICULTY}",
  "category": "{CATEGORY}",
  "repo": "{REPO}",
  "mcp_benefit_score": 0.5,
  "mcp_breakdown": {
    "context_complexity": 0.5,
    "cross_file_deps": 0.5,
    "semantic_search_potential": 0.5,
    "task_category_weight": 0.5
  },
  "selection_rationale": "Manually added via /scaffold-task",
  "task_dir": "csb_sdlc_{BENCHMARK}/{TASK_ID}"
}
```

#### Org-scale registration entry:

```json
{
  "task_id": "{TASK_ID}",
  "benchmark": "csb_org_{BENCHMARK}",
  "language": "{LANGUAGE}",
  "difficulty": "{DIFFICULTY}",
  "category": "{CATEGORY}",
  "repo": "{PRIMARY_REPO}",
  "selection_rationale": "Manually added via /scaffold-task",
  "task_dir": "csb_org_{BENCHMARK}/{TASK_ID}"
}
```

Also update the `metadata.total_selected` count and the `statistics.tasks_per_benchmark` count for the appropriate suite.

### If new suite: Generate run config script

Write to `configs/{BENCHMARK}_2config.sh` using the standard 2-config pattern. Read an existing config (e.g., `configs/tac_2config.sh`) as a reference and adapt it:

1. Source `_common.sh`
2. Define `SUITE="csb_{sdlc|org}_{BENCHMARK}"`
3. Load task IDs from `selected_benchmark_tasks.json` filtered by benchmark
4. Define `run_task_batch()` with baseline, sourcegraph_full configs
5. Run the 2 batches sequentially
6. Make it executable: `chmod +x configs/{BENCHMARK}_2config.sh`

---

## Phase 6: Validation

After all files are created, run validation:

```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --task benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}
```

Report the validation results. If there are issues, offer to fix them.

---

## Summary Output

After completion, print a summary:

```
Scaffolded task: {TASK_ID}
  Suite:      csb_{sdlc|org}_{BENCHMARK}
  Family:     {sdlc|org-scale}
  Language:   {LANGUAGE}
  Difficulty: {DIFFICULTY}
  Type:       {TASK_TYPE}

Files created:
  benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}/task.toml
  benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}/instruction.md
  benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}/reviewers.json
  benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}/environment/Dockerfile
  benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}/tests/test.sh
  [org-scale only] benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/eval.sh
  [org-scale only] benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/oracle_checks.py
  [org-scale only] benchmarks/csb_org_{BENCHMARK}/{TASK_ID}/tests/task_spec.json

Registered in: configs/selected_benchmark_tasks.json

Next steps:
  1. Edit instruction.md with detailed task instructions
  2. Customize tests/ with task-specific verification checks
  3. [org-scale] Populate task_spec.json with oracle checks
  4. Test locally: harbor run --path benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}
  5. Run /validate-tasks --task benchmarks/csb_{sdlc|org}_{BENCHMARK}/{TASK_ID}
```

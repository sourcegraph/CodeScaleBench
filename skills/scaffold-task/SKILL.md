---
name: scaffold-task
description: Scaffold a new Harbor-compatible benchmark task (and optionally a new benchmark suite). Generates task.toml, instruction.md, Dockerfile, test.sh, and registers the task. Triggers on scaffold task, new task, create task, add task, new benchmark.
user-invocable: true
---

# Scaffold Task

Interactively scaffold a new Harbor-compatible benchmark task for CodeContextBench. Generates all required files and registers the task in the selection registry.

This is an **interactive skill**. Walk the user through configuration using AskUserQuestion in multiple phases. Do NOT generate files without first collecting all required inputs.

---

## Phase 1: Mode Selection

Ask one question:

**Question 1** — Header: "Mode"
- Question: "What would you like to create?"
- Options:
  - **Add task to existing suite** — "Create a new task in an existing ccb_* benchmark"
  - **Create new benchmark suite** — "Create a new benchmark with its first task and run config"

---

## Phase 2: Core Details

Ask 3-4 questions depending on mode.

### If adding to existing suite:

**Question 1** — Header: "Benchmark"
- Question: "Which benchmark suite?"
- Options:
  - **swebenchpro** — "Real-world SWE across repos (Go, TS, Python)"
  - **pytorch** — "PyTorch PR-level tasks (Python/C++)"
  - **locobench** — "Long-context understanding (mixed languages)"
  - **k8sdocs** — "Kubernetes documentation (Go)"
- Note: User can type "Other" for tac, largerepo, sweperf, crossrepo, dibench

### If creating new suite:

Prompt the user (not AskUserQuestion) to provide:
- **Suite name**: Will become `ccb_{name}` (lowercase, alphanumeric + hyphens)

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
  - **pre-built-image** — "FROM an existing Docker image (e.g., TAC tasks)"
  - **standalone** — "Empty workspace, no repo (agent creates everything)"

For existing suites, also ask Language, Difficulty, and Task type (same questions).

---

## Phase 3: Task-Specific Inputs

Prompt the user for these values (use text prompts, not AskUserQuestion since these are free-form):

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

### Template 1: task.toml

Write to `benchmarks/ccb_{BENCHMARK}/{TASK_ID}/task.toml`:

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

### Template 2: Dockerfile (repo-clone type)

Write to `benchmarks/ccb_{BENCHMARK}/{TASK_ID}/environment/Dockerfile`:

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

### Template 2b: Dockerfile (pre-built-image type)

```dockerfile
FROM {BASE_IMAGE}

# Create directories
RUN mkdir -p /workspace /logs/verifier

# Copy test files
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

### Template 2c: Dockerfile (standalone type)

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

### Template 3: instruction.md

Write to `benchmarks/ccb_{BENCHMARK}/{TASK_ID}/instruction.md`:

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

### Template 4: test.sh

Write to `benchmarks/ccb_{BENCHMARK}/{TASK_ID}/tests/test.sh`:

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

---

## Phase 5: Registration

### Add to selected_benchmark_tasks.json

Read `configs/selected_benchmark_tasks.json`, then use Edit to append a new task entry to the `tasks` array (before the closing `]`). Use this structure:

```json
{
  "task_id": "{TASK_ID}",
  "benchmark": "ccb_{BENCHMARK}",
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
  "task_dir": "ccb_{BENCHMARK}/{TASK_ID}"
}
```

Also update the `metadata.total_selected` count and the `statistics.tasks_per_benchmark.ccb_{BENCHMARK}` count.

### If new suite: Generate run config script

Write to `configs/{BENCHMARK}_2config.sh` using the standard 2-config pattern. Read an existing config (e.g., `configs/tac_2config.sh`) as a reference and adapt it:

1. Source `_common.sh`
2. Define `SUITE="ccb_{BENCHMARK}"`
3. Load task IDs from `selected_benchmark_tasks.json` filtered by benchmark
4. Define `run_task_batch()` with baseline, sourcegraph_full configs
5. Run the 2 batches sequentially
6. Make it executable: `chmod +x configs/{BENCHMARK}_3config.sh`

---

## Phase 6: Validation

After all files are created, run validation:

```bash
cd ~/CodeContextBench && python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_{BENCHMARK}/{TASK_ID}
```

Report the validation results. If there are issues, offer to fix them.

---

## Summary Output

After completion, print a summary:

```
Scaffolded task: {TASK_ID}
  Suite:      ccb_{BENCHMARK}
  Language:   {LANGUAGE}
  Difficulty: {DIFFICULTY}
  Type:       {TASK_TYPE}

Files created:
  benchmarks/ccb_{BENCHMARK}/{TASK_ID}/task.toml
  benchmarks/ccb_{BENCHMARK}/{TASK_ID}/instruction.md
  benchmarks/ccb_{BENCHMARK}/{TASK_ID}/environment/Dockerfile
  benchmarks/ccb_{BENCHMARK}/{TASK_ID}/tests/test.sh

Registered in: configs/selected_benchmark_tasks.json

Next steps:
  1. Edit instruction.md with detailed task instructions
  2. Customize tests/test.sh with task-specific verification checks
  3. Test locally: harbor run --path benchmarks/ccb_{BENCHMARK}/{TASK_ID}
  4. Run /validate-tasks --task benchmarks/ccb_{BENCHMARK}/{TASK_ID}
```

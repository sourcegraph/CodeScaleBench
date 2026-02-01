# LoCoBench-Agent Adapter: Handoff Summary

**Date:** 2026-01-24
**Status:** FULLY WORKING - Verified with 44.1% reward on baseline test

---

## What Was Fixed (This Session)

### 1. GitHub Repos for MCP Indexing - COMPLETED

**Problem:** LoCoBench uses synthetic codebases that don't exist on GitHub, so Sourcegraph MCP couldn't search them.

**Solution:**
- Created `scripts/push_to_github.sh` to push all 34 projects to `sg-benchmarks` org
- All 34 repos now exist at `sg-benchmarks/locobench-{project_id}`
- Added `SWEBENCH_REPO_COMMIT` env var to docker-compose.yaml for MCP targeting

### 2. Container User Handling - FIXED

**Problem:** Dockerfile created `agent` user with `USER agent`, but `claude_baseline_agent.py` tries to create and `su` to `claude` user - they conflicted.

**Solution:** Removed `USER agent` from Dockerfile. Container now runs as root, and `claude_baseline_agent.py` creates `claude` user at runtime (matches SWEBench behavior).

### 3. Session File Permissions - FIXED

**Problem:** Claude Code created session files with mode 600 (owner-only), but Harbor runs as a different user and couldn't read them.

**Solution:** Added `chmod -R a+rX /logs` after Claude Code runs in `claude_baseline_agent.py`.

### 4. Solution File Persistence - FIXED

**Problem:** Agent wrote `/app/solution.md` but `/app` isn't a mounted volume, so file was lost before verifier ran.

**Solution:** Changed instruction template and verifier to use `/logs/agent/solution.md` (mounted volume).

**All 50 tasks regenerated with these fixes.**

---

## Current Status

### What's Working

| Component | Status | Notes |
|-----------|--------|-------|
| Task generation | ✓ | 50 tasks generated successfully |
| Docker environment | ✓ | Non-root user correctly configured |
| Volume mount permissions | ✓ | UID/GID 1001/1002 matches host user |
| Claude Code installation | ✓ | Pre-installed in Dockerfile |
| Test file mounting | ✓ | Volume mount workaround works |
| Verifier execution | ✓ | test.sh runs, verify.py executes |
| Oracle agent | ✓ | Returns 0.700 score with ground truth |
| NOP agent | ✓ | Returns 0.000 score (expected) |
| Claude Code agent | ✓ | Runs without root permission error |

### Verification Result

**Baseline test passed with 44.4% reward** (compared to Oracle's 70% maximum).

```
$ ./configs_v2/examples/locobench_1_task_verification.sh
Loading credentials from ~/evals/.env.local...
ANTHROPIC_API_KEY: set (108 chars)
...
Mean: 0.444
```

### Credentials

Credentials are loaded from `~/evals/.env.local`:

```bash
export ANTHROPIC_API_KEY="your-api-key"
export SOURCEGRAPH_ACCESS_TOKEN="your-token"  # Optional, for MCP mode
```

---

## Running the Benchmark

### Quick Verification (1 task)

```bash
cd ~/evals/custom_agents/agents/claudecode

# Set API key
export ANTHROPIC_API_KEY="your-api-key-here"

# Run baseline test
BASELINE_MCP_TYPE=none harbor run \
    --path /home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/tasks/python_game_engine_expert_032_architectural_understanding_expert_01 \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-haiku-4-5-20251001 \
    -n 1 \
    --timeout-multiplier 10
```

### Full Benchmark (50 tasks)

```bash
cd ~/evals/custom_agents/agents/claudecode
export ANTHROPIC_API_KEY="your-api-key-here"
./configs_v2/examples/locobench_50_tasks_comparison.sh
```

### With MCP (Deep Search)

```bash
export ANTHROPIC_API_KEY="your-api-key-here"
export SOURCEGRAPH_URL="..."
export SOURCEGRAPH_ACCESS_TOKEN="..."

BASELINE_MCP_TYPE=deepsearch harbor run \
    --path /home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/tasks/python_game_engine_expert_032_architectural_understanding_expert_01 \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-sonnet-4-20250514 \
    -n 1 \
    --timeout-multiplier 10
```

---

## Key Files

| Path | Description |
|------|-------------|
| `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/adapter.py` | Main adapter with Dockerfile generation (contains the fix) |
| `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/tasks/` | Generated Harbor tasks (50 tasks) |
| `/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/selected_tasks.json` | 50 selected high-complexity tasks |
| `/home/stephanie_jarmak/CodeContextBench/agents/claude_baseline_agent.py` | Baseline Claude Code agent |
| `~/evals/custom_agents/agents/claudecode/configs_v2/examples/locobench_*.sh` | Run scripts |

---

## Technical Details

### Dockerfile Changes in adapter.py

The `_generate_dockerfile()` method now generates Dockerfiles with:

1. **Language-specific toolchain** (Python, Rust, Go, etc.)
2. **Node.js 22 + Claude Code** (installed globally as root)
3. **Non-root user `agent`** with UID 1001, GID 1002
4. **Proper ownership** of `/app`, `/logs`, `/workspace`, `/tests`, `/installed-agent`

### Why UID 1001/GID 1002?

The host user (stephanie_jarmak) has UID 1001 and GID 1002. Docker volume mounts use host ownership, so the container user needs matching UID/GID for write permissions.

**Note:** If running on a different machine with a different user UID/GID, update the Dockerfile template in `adapter.py`:

```python
# In _generate_dockerfile(), modify:
RUN groupadd -g YOUR_GID agent && \
    useradd -m -s /bin/bash -u YOUR_UID -g YOUR_GID agent
```

Or make this configurable via environment variable or parameter.

---

## Previous Session Summary

### 1. Fixed Harbor Test File Mounting Bug
- Modified adapter.py to use volume mount instead of `docker compose cp`
- Avoids `/tests/tests/` nested directory issue

### 2. Generated 50 Tasks
- 27 Architectural Understanding
- 14 Cross-File Refactoring
- 4 Bug Investigation
- 5 Other categories
- Languages: Rust (10), C# (9), C (8), C++ (5), Python (5), Java (4), JavaScript (3), TypeScript (3), Go (1)

### 3. Created Benchmark Scripts
- `configs_v2/examples/locobench_1_task_verification.sh`
- `configs_v2/examples/locobench_50_tasks_comparison.sh`

---

## Enabling MCP / Sourcegraph Integration

LoCoBench uses **synthetic generated codebases** that don't exist on GitHub by default.
To enable Sourcegraph MCP (Deep Search), you must push these projects to GitHub first.

### Step 1: Push Projects to GitHub

```bash
cd /home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent

# Dry run first to see what would be created
./scripts/push_to_github.sh --dry-run

# Actually push (creates repos in sg-benchmarks org)
./scripts/push_to_github.sh --org sg-benchmarks
```

This creates 34 GitHub repos:
- Format: `sg-benchmarks/locobench-{project_id}`
- Example: `sg-benchmarks/locobench-python_game_engine_expert_032`

### Step 2: Configure Sourcegraph Indexing

In your Sourcegraph instance:
1. Go to Site Admin → Repositories → Manage code hosts
2. Add/update GitHub connection to include `sg-benchmarks` org
3. Wait for indexing to complete (~30min for 34 repos)

### Step 3: Run with MCP Enabled

```bash
cd ~/evals/custom_agents/agents/claudecode

# With Deep Search MCP
./configs_v2/examples/locobench_50_tasks_comparison.sh --mcp-only

# Compare baseline vs MCP
./configs_v2/examples/locobench_50_tasks_comparison.sh
```

### How MCP Works for LoCoBench

The adapter sets these environment variables in `docker-compose.yaml`:
- `SWEBENCH_REPO_COMMIT=locobench-{project_id}--main`
- `LOCOBENCH_GITHUB_ORG=sg-benchmarks`

The agent uses `SWEBENCH_REPO_COMMIT` to tell Sourcegraph which repo to search:
- Search queries include: "In sg-benchmarks/locobench-python_game_engine_expert_032..."
- Results match the local code (no version mismatch since main=local)

### Projects to Index

See `projects_to_index.json` for the complete list of 34 projects needed:

| Language | Count | Example Project |
|----------|-------|-----------------|
| Rust | 5 | locobench-rust_web_social_expert_073 |
| C | 5 | locobench-c_blockchain_nft_expert_071 |
| C# | 6 | locobench-csharp_data_warehouse_expert_012 |
| Python | 4 | locobench-python_game_engine_expert_032 |
| C++ | 3 | locobench-cpp_web_blog_expert_040 |
| Java | 4 | locobench-java_web_ecommerce_expert_000 |
| JavaScript | 3 | locobench-javascript_blockchain_nft_expert_035 |
| TypeScript | 2 | locobench-typescript_system_monitoring_expert_061 |
| Go | 1 | locobench-go_ml_nlp_expert_053 |

---

## Regenerating Tasks

If you need to regenerate tasks after any changes to adapter.py:

```bash
cd /home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent
python3 run_adapter.py \
    --dataset_path locobench_dataset.jsonl \
    --output_dir ./tasks \
    --selected_tasks selected_tasks.json
```

# CodeContextBench Agent Execution Guide

## Overview

Benchmark tasks are executed via **Harbor** (Docker container-based runner) with **Claude Code** as the agent. Each task runs in an isolated container. Three configurations are tested per benchmark:

| Config | Description |
|--------|-------------|
| `baseline` | Claude Code with no MCP tools |
| `sourcegraph_base` | Claude Code + Sourcegraph MCP (basic search) |
| `sourcegraph_full` | Claude Code + Sourcegraph MCP (deep search + batch changes) |

## Running Benchmarks

### Single Benchmark

```bash
# Sequential (default)
./configs/swebenchpro_3config.sh

# Parallel with auto-detected concurrency
./configs/swebenchpro_3config.sh --parallel

# Parallel with explicit job count
./configs/swebenchpro_3config.sh --parallel 4
```

All 11 benchmark config scripts accept the `--parallel` flag:
- `swebenchpro_3config.sh` — SWE-bench Pro (36 tasks)
- `pytorch_3config.sh` — PyTorch (12 tasks)
- `locobench_3config.sh` — LoCoBench (25 tasks)
- `repoqa_3config.sh` — RepoQA (10 tasks)
- `k8s_docs_3config.sh` — Kubernetes Docs (5 tasks)
- `crossrepo_3config.sh` — Cross-Repo (4-5 tasks)
- `largerepo_3config.sh` — Large Repo (4 tasks)
- `tac_3config.sh` — TAC (8 tasks)
- `dibench_3config.sh` — DIBench (8 tasks)
- `sweperf_3config.sh` — SWE-Perf (3 tasks)
- `linuxflbench_3config.sh` — LinuxFLBench (5 tasks)

### Config Scripts Structure

Each config script:
1. Sources `configs/_common.sh` for shared infrastructure
2. Defines task IDs and agent configurations
3. Runs all three configs (baseline, sourcegraph_base, sourcegraph_full)
4. Validates results and produces `flagged_tasks.json`

## Parallel Execution

### Architecture

Parallel execution uses background subshells with semaphore-style job limiting:

```
Main shell
  ├── Subshell 1 (HOME=account1) → harbor run task_A
  ├── Subshell 2 (HOME=account3) → harbor run task_B
  ├── Subshell 3 (HOME=account1) → harbor run task_C
  └── ... up to PARALLEL_JOBS concurrent
```

Each subshell gets `HOME` overridden to a specific account directory. This causes `harbor run` (and the Claude Code agent inside Docker) to read credentials from that account's `~/.claude/.credentials.json`.

### Round-Robin Account Distribution

Tasks are assigned to accounts in round-robin order:

```
Task 1 → account1
Task 2 → account3
Task 3 → account1
Task 4 → account3
...
```

This spreads API rate limit burden across accounts. Only Max-plan accounts are used (regular accounts are too rate-limited).

### Configuration Variables

Set in `configs/_common.sh` or via environment:

| Variable | Default | Description |
|----------|---------|-------------|
| `PARALLEL_JOBS` | auto | Max concurrent tasks. Auto = `SESSIONS_PER_ACCOUNT * num_accounts` |
| `SESSIONS_PER_ACCOUNT` | `4` | Empirical max concurrent sessions per Max-plan account |
| `SKIP_ACCOUNTS` | `account2` | Space-separated account names to exclude |

### How It Works

1. **`setup_multi_accounts()`** scans `~/.claude-homes/account1/`, `account2/`, etc.
2. Accounts in `SKIP_ACCOUNTS` are excluded (e.g., non-Max accounts)
3. `PARALLEL_JOBS` is auto-set to `SESSIONS_PER_ACCOUNT * active_accounts`
4. **`run_tasks_parallel()`** launches background subshells up to `PARALLEL_JOBS`
5. Each subshell has `HOME` set to the next account in round-robin order
6. PID tracking + `kill -0` polling enforces the concurrency limit
7. After all tasks finish, `HOME` is restored to `REAL_HOME`

## Multi-Account Setup

### Prerequisites

- 2+ Claude accounts with Max plan subscriptions
- Each account logged in and credential files placed correctly

### Directory Structure

```
~/.claude-homes/
  account1/
    .claude/
      .credentials.json    # Max plan account
  account2/
    .claude/
      .credentials.json    # Regular plan (skipped by default)
  account3/
    .claude/
      .credentials.json    # Max plan account
```

### Setting Up Accounts

For each account:

```bash
# 1. Create the directory
mkdir -p ~/.claude-homes/accountN/.claude

# 2. Log out of any current session
claude logout

# 3. Log in with the target account
claude login

# 4. Copy credentials to the account directory
cp ~/.claude/.credentials.json ~/.claude-homes/accountN/.claude/.credentials.json
```

You must `claude logout` before `claude login` with a different account — otherwise the existing valid token is reused.

### Verifying Accounts

```bash
# Check all accounts are detected
SKIP_ACCOUNTS="" bash -c 'source configs/_common.sh; setup_multi_accounts'
```

Expected output:
```
Multi-account mode: 3 accounts active
  slot 1: /home/user/.claude-homes/account1
  slot 2: /home/user/.claude-homes/account2
  slot 3: /home/user/.claude-homes/account3
```

### Rate Limits

- **Max plan**: ~4 concurrent Claude Code sessions before throttling
- **Regular plan**: Significantly lower limits, not suitable for parallel runs
- With 2 Max accounts: up to 8 concurrent tasks
- Default `SKIP_ACCOUNTS=account2` excludes the regular-plan account

## Token Refresh

OAuth tokens expire after ~8 hours. The `ensure_fresh_token_all()` function refreshes all account tokens before each batch:

- Checks `expiresAt` timestamp in each credential file
- Refreshes if less than 30 minutes remaining (`REFRESH_MARGIN=1800`)
- Uses the Claude OAuth endpoint with the `refreshToken`
- Writes updated tokens back to the credential file

Token refresh runs automatically at the start of each config batch (baseline, sourcegraph_base, sourcegraph_full).

## Output Structure

```
runs/official/{benchmark}_{model}_{timestamp}/
  baseline/
    {task_id}__{hash}/
      result.json          # Pass/fail, reward score
      trajectory.jsonl     # Full agent interaction log
      cost.json           # Token usage and cost
  sourcegraph_base/
    ...
  sourcegraph_full/
    ...
  flagged_tasks.json       # Validation warnings
```

## Trajectory Generation

### What Produces trajectory.json

`trajectory.json` is generated by Harbor's `ClaudeCode._convert_events_to_trajectory()` method. It records per-step timestamps, tool calls, and token metrics in ATIF-v1.2 schema format. It is written to `agent/trajectory.json` in each task's output directory.

### Why It Might Be Missing

The **H3 bug** causes `trajectory.json` to fail when Claude Code spawns subagents via the `Task` tool. Harbor's `_get_session_dir()` gets confused by multiple session directories, causing the trajectory conversion to silently fail. The bug was fixed in `claude_baseline_agent.py` but older runs (~15%) are affected.

When `trajectory.json` is missing, `claude-code.txt` (JSONL transcript) is always present and contains the same tool call data without per-step timestamps.

### Runtime Detection

Two levels of trajectory.json monitoring are built into the run pipeline:

1. **Per-task**: `_check_task_trajectory()` runs automatically after each task completes in `run_tasks_parallel` (via the `_reap_one` PID reaper). Logs a WARNING immediately if trajectory.json is missing for that task.
2. **Per-batch**: `check_trajectory_coverage()` runs after each batch in `validate_and_report()`. Summarizes missing/total counts across all tasks in the batch.

Both checks are non-blocking — warnings are logged but the pipeline continues.

### Troubleshooting

1. **Check coverage**: Review per-task WARNING lines in run output, or the batch-level TRAJECTORY CHECK summary
2. **Fallback**: `extract_time_to_context()` in `ir_metrics.py` automatically falls back to `synthesize_trajectory()` which estimates timestamps from the JSONL transcript using a calibrated seconds-per-step rate
3. **Root cause**: If new runs show missing trajectories, check for heavy `Task` tool usage (subagent spawning). Ensure `claude_baseline_agent.py` has the H3 fix applied

## Post-Run Validation

Each config script calls `validate_and_report()` after completing a batch. This runs `scripts/validate_task_run.py` to check for:

- Missing result files
- Unexpected error states
- Zero-reward tasks (potential infrastructure issues vs genuine failures)

Results are aggregated into `flagged_tasks.json` at the run level.

## Generating the Evaluation Report

After all runs complete:

```bash
python3 scripts/generate_manifest.py    # Regenerate MANIFEST.json
python3 scripts/generate_report.py      # Aggregate results into report
```

The MANIFEST tracks all runs, task counts, pass/fail rates, and mean rewards.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

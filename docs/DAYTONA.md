# Running CodeScaleBench on Daytona

This guide covers running the CodeScaleBench benchmark suite on [Daytona](https://daytona.io) cloud sandboxes. Daytona handles Docker image builds and sandbox lifecycle remotely, so you do not need Docker installed locally.

## When To Read This
- You want to run benchmarks without a local Docker daemon.
- You want high parallelism (up to 125 concurrent sandboxes on Tier 3).
- You want fast full-suite or paired runs (~15 min wall clock for all 283 tasks).

## Two Ways to Run on Daytona

| Approach | Use Case | Full Artifacts | Downstream Compatible |
|----------|----------|---------------|----------------------|
| **Harbor + Daytona** (recommended) | Production runs, paired comparisons, analysis | Yes (trajectory.json, claude-code.txt, etc.) | Runs explorer, IR pipeline, QA validation |
| **Standalone runner** | Quick validation, listing tasks/suites, dry runs | No (truncated outputs only) | Manual analysis only |

## Prerequisites

1. **Daytona account** at [app.daytona.io](https://app.daytona.io)
2. **Daytona SDK**: `pip install daytona-sdk`
3. **Harbor** installed (for the recommended approach)
4. **Anthropic API key** or **Claude Code OAuth credentials** (for the AI agent)
5. **Sourcegraph access token** (only for MCP configs)

## Credential Setup

Both approaches share the same credentials. The runner loads from environment variables first, falling back to config files.

### Daytona API Key (required)

Get your key from [Daytona Dashboard > Settings > API Keys](https://app.daytona.io).

```bash
# Option A: environment variable
export DAYTONA_API_KEY="your-key-here"

# Option B: config file
echo 'DAYTONA_API_KEY="your-key-here"' > ~/.config/daytona/env.sh
```

### Anthropic API Key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or place it in `~/.claude/credentials.json`:
```json
{"apiKey": "sk-ant-..."}
```

### Sourcegraph Token (MCP configs only)

```bash
export SRC_ACCESS_TOKEN="sgp_..."
```

## Recommended: Harbor + Daytona

Harbor has a built-in `DaytonaEnvironment` that plugs into the standard trial runner. Add `--environment-type daytona` to any `harbor run` command to execute on Daytona cloud sandboxes instead of local Docker.

### Quick Start

```bash
# Single task on Daytona
BASELINE_MCP_TYPE=none harbor run \
    --path benchmarks/csb_sdlc_feature/servo-scrollend-event-feat-001 \
    --agent-import-path agents/claude_baseline_agent.py \
    --model claude-haiku-4-5-20251001 \
    --environment-type daytona

# Full suite (60 concurrent sandboxes)
BASELINE_MCP_TYPE=none harbor run \
    --path benchmarks/csb_sdlc_feature \
    --agent-import-path agents/claude_baseline_agent.py \
    --model claude-haiku-4-5-20251001 \
    --jobs-dir runs/staging/build_baseline_$(date +%Y%m%d) \
    -n 60 \
    --environment-type daytona
```

### Paired Runs (Baseline vs MCP)

Run both configs concurrently, splitting the Daytona sandbox budget:

```bash
# Terminal 1: Baseline (60 concurrent sandboxes)
BASELINE_MCP_TYPE=none harbor run \
    --path benchmarks/csb_sdlc_feature \
    --agent-import-path agents/claude_baseline_agent.py \
    --model claude-haiku-4-5-20251001 \
    --jobs-dir runs/staging/paired_baseline_$(date +%Y%m%d) \
    -n 60 \
    --environment-type daytona &

# Terminal 2: MCP (60 concurrent sandboxes)
BASELINE_MCP_TYPE=sourcegraph harbor run \
    --path benchmarks/csb_sdlc_feature \
    --agent-import-path agents/claude_baseline_agent.py \
    --model claude-haiku-4-5-20251001 \
    --jobs-dir runs/staging/paired_mcp_$(date +%Y%m%d) \
    -n 60 \
    --environment-type daytona &

wait
```

60 + 60 = 120 concurrent sandboxes, within the Tier 3 limit of 125.

### What Harbor + Daytona Produces

Harbor handles the full artifact lifecycle automatically:

```
runs/staging/{run_name}/
  {config}/
    {task_id}_{config}/
      {trial__hash}/
        result.json                    # Full Harbor TrialResult
        task_metrics.json              # Token counts, tool usage, cost
        agent/
          trajectory.json              # ATIF v1.2 turn-by-turn trace
          claude-code.txt              # Full JSONL agent output
          instruction.txt              # Task instruction text
        verifier/
          reward.txt                   # Numeric score (0.0-1.0)
          test-stdout.txt              # Full test output
```

These artifacts are fully compatible with:
- **Runs explorer**: `python3 scripts/export_official_results.py` (defaults to `runs/analysis/`; pass `--runs-dir ./runs/official/` for curated official runs)
- **IR analysis pipeline**: `python3 scripts/normalize_retrieval_events.py`
- **QA validation**: `python3 scripts/validate_task_run.py`
- **Metrics extraction**: `python3 scripts/extract_task_metrics.py`
- **Staging to official promotion**: copy to `runs/official/`, update `MANIFEST.json`

### How It Works

When you add `--environment-type daytona`, Harbor:

1. **Creates a sandbox** from the task's Dockerfile via `Image.from_dockerfile()` (Daytona builds remotely)
2. **Installs the agent** (Node.js 22, Claude Code CLI) using the standard Harbor install template
3. **Runs the agent** with `claude --output-format stream-json | tee /logs/agent/claude-code.txt`
4. **Downloads `/logs/agent/`** from the sandbox to the local trial directory
5. **Converts JSONL to trajectory.json** (ATIF v1.2) via `populate_context_post_run()`
6. **Runs the verifier** and downloads `/logs/verifier/`
7. **Writes result.json** with the full `TrialResult` schema
8. **Deletes the sandbox** (always, even on failure)

## Capacity Planning

When planning large runs on Daytona, you should:

- **Check your own Daytona account limits.** Consult the Daytona dashboard or documentation for your plan’s vCPU, memory, storage, and concurrency quotas.
- **Check your model provider’s rate limits.** Parallelism that is safe for one organization or model may not be safe for another.
- **Start small and scale up.** Begin with a single suite or a subset of tasks and gradually increase `--parallel` as you confirm stability.
- **Leave headroom.** Stay comfortably below documented limits to avoid throttling or transient failures.

> The exact numeric limits, RPMs, and cost per run are deployment‑specific. The tables in blog posts or internal docs are examples only; always derive concrete numbers from your own infrastructure and pricing.

## Alternative: Standalone Runner

The standalone runner (`scripts/daytona_runner.py`) is useful for quick validation and task discovery but produces truncated outputs not compatible with the downstream analysis pipeline.

### Quick Start

```bash
# List suites and readiness counts
python3 scripts/daytona_runner.py --list-suites

# List tasks in a suite
python3 scripts/daytona_runner.py --list-tasks --suite csb_sdlc_feature

# Dry run (validate task selection, no sandboxes created)
python3 scripts/daytona_runner.py --suite csb_sdlc_feature --dry-run

# Run a single task
python3 scripts/daytona_runner.py --task cgen-deps-install-001

# Run a full suite
python3 scripts/daytona_runner.py --suite csb_sdlc_feature --parallel 4

# Run all 370 tasks
python3 scripts/daytona_runner.py --all --parallel 8
```

### Standalone Runner Configs

| Config | Dockerfile | Instruction | MCP |
|--------|-----------|-------------|-----|
| `baseline-local-direct` | `Dockerfile` | `instruction.md` | No |
| `mcp-remote-direct` | `Dockerfile.sg_only` | `instruction_mcp.md` | Yes |
| `baseline-local-artifact` | `Dockerfile.artifact_only` | `instruction.md` | No |
| `mcp-remote-artifact` | `Dockerfile.artifact_only` | `instruction_mcp.md` | Yes |

### Standalone Runner Options

| Flag | Default | Description |
|------|---------|-------------|
| `--parallel N` | 1 | Max concurrent sandboxes |
| `--model NAME` | `claude-haiku-4-5-20251001` | Claude model |
| `--max-turns N` | 30 | Max agent turns |
| `--timeout N` | per-task | Override timeout (sec) |
| `--retries N` | 1 | Retry count |
| `--auth api-key\|oauth` | `api-key` | Auth mode |
| `--account N` | 1 | OAuth account number |
| `--config NAME` | `baseline-local-direct` | Config mode |
| `--run-id ID` | auto | Custom run identifier |
| `--dry-run` | off | Validate without sandboxes |

### Standalone Output Structure

```
runs/daytona/{run_id}/
  manifest.json                    # Aggregate statistics
  {task_id}/{config}/
    result.json                    # Minimal task result
    agent_output.txt               # Claude Code stdout (truncated to 10KB)
    verification_output.txt        # test.sh output (truncated to 5KB)
```

**Note:** These outputs lack `trajectory.json`, full `claude-code.txt`, and Harbor-compatible `result.json`. Use Harbor + Daytona for runs that feed the analysis pipeline.

## Task Readiness

273 of 294 tasks are Daytona-ready. Base images are sourced from:

- **Standard public images** (197 tasks): `python:*`, `golang:*`, `gcc:*`, `ubuntu:*`, etc.
- **Pre-built repo images** (70 tasks): `ghcr.io/sourcegraph/ccb-repo-*` on GHCR
- **TAC images** (4 tasks): `ghcr.io/theagentcompany/*` on GHCR
- **Linux kernel tasks** (5 tasks): Build from `gcc:13` with inline kernel source clone

**Not Daytona-compatible** (21 tasks): Tasks using `jefzda/sweap-images:*` from Docker Hub (9 csb_sdlc_debug + 12 csb_sdlc_fix) fail because Daytona's remote builder cannot pull from Docker Hub (returns `unauthorized` error even for public images). Run these tasks locally with Docker instead. To re-host them to GHCR, use `scripts/rehost_sweap_images.py` with a GITHUB_TOKEN that has `write:packages` scope.

Regenerate the task registry after adding new tasks:
```bash
python3 scripts/build_daytona_registry.py
```

## Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DAYTONA_API_KEY` | Yes | Daytona platform API key |
| `ANTHROPIC_API_KEY` | For api-key auth | Anthropic API key for Claude |
| `SRC_ACCESS_TOKEN` | For MCP configs | Sourcegraph access token |
| `DAYTONA_API_URL` | No | Override API endpoint (default: `https://app.daytona.io/api`) |
| `DAYTONA_TARGET` | No | Override target region (default: `us`) |
| `DAYTONA_OVERRIDE_STORAGE` | No | Override per-sandbox storage (MB). Set to `10240` to cap at Daytona's 10GB limit when tasks specify larger values in task.toml |
| `RATE_LIMIT_PREFLIGHT` | No | Account preflight before launch (`1`=enabled, `0`=disabled; default `1`) |
| `RATE_LIMIT_PREFLIGHT_MODE` | No | Behavior when account is limited: `skip` (default) or `fail` |
| `RATE_LIMIT_PROBE_TIMEOUT_SEC` | No | Timeout in seconds for per-account probe (default `20`) |

## Cost control and cleanup

Bulk runs (full suite, high parallelism) drive cost from **compute** (many concurrent sandboxes) and **storage** (snapshots created when building from task Dockerfiles). Some of that is inherent to running 283+ tasks; you can still reduce spend and reclaim storage.

### Reduce ongoing spend

- **Cap per-sandbox storage**: Set `export DAYTONA_OVERRIDE_STORAGE=10240` before launching so no sandbox exceeds Daytona’s 10GB limit. Lowers storage cost and avoids failures on tasks that request 20GB in `task.toml`.
- **Lower parallelism**: Use fewer concurrent sandboxes (e.g. `-n 30` instead of 60) if you’re within rate limits; wall clock increases but cost per run drops.
- **Run smaller batches**: Use `--path` to a single suite or a subset of tasks when you don’t need a full-suite run.

### Clean up snapshots

Each **sandbox** is deleted after the trial (Harbor + Daytona and the standalone runner both delete sandboxes). **Snapshots** (image templates built from Dockerfiles) can persist in your Daytona org and incur storage until removed. Bulk runs with many unique task Dockerfiles can leave many snapshots behind.

- **Dashboard**: [Daytona Snapshots](https://app.daytona.io/dashboard/snapshots) — list and delete snapshots you no longer need. Snapshots auto-deactivate after 2 weeks of no use; deleting them frees storage.
- **CLI**: `daytona snapshot list` and `daytona snapshot delete <name>` (see [Daytona CLI](https://daytona.io/docs/en/tools/cli)).
- **Script**: `python3 scripts/daytona_snapshot_cleanup.py --list` to list snapshots; `--delete-all` or `--delete-prefix PREFIX` to remove them (requires confirmation). Use this to prune one-off or old snapshots after big runs.

### Orphan sandboxes

If a run is killed or crashes, sandboxes can be left running and keep consuming quota. The curator runner cleans up its own orphans at startup (`purpose=curator`). For Harbor/standalone runs, check [Daytona Sandboxes](https://app.daytona.io/dashboard/sandboxes) and stop or delete any that are no longer needed.

### Was the bulk-run cost inevitable?

Partly. Running the full suite at high parallelism will always use a lot of compute (vCPU × time) and will create many image builds (one per unique Dockerfile). What you can control: **delete unused snapshots** to cut storage cost, **cap storage** and **tune parallelism** for future runs, and **clean up orphan sandboxes** so they don’t keep billing.

## Troubleshooting

**"Missing DAYTONA_API_KEY"**: Set the env var or create `~/.config/daytona/env.sh`.

**Sandbox creation timeout**: Large Docker images (multi-GB repo clones) take longer. Retry with `--retries 2` or increase `--timeout`.

**"Missing Dockerfile" or "Missing instruction"**: The task may lack the Dockerfile variant for your chosen config. Check with `--dry-run` first.

**OAuth token expired**: Re-run `claude` in the account home directory to refresh, or switch to `--auth api-key`.

**Anthropic account is rate-limited**: launch scripts now run a preflight probe per account. Default behavior is `RATE_LIMIT_PREFLIGHT_MODE=skip`, which removes limited accounts from the run before `harbor run` starts. To hard-block launches instead, set `RATE_LIMIT_PREFLIGHT_MODE=fail`.

**MCP config errors**: Verify `SRC_ACCESS_TOKEN` is valid: `curl -H "Authorization: token $SRC_ACCESS_TOKEN" https://sourcegraph.com/.api/graphql`.

**Harbor + Daytona: "Sandbox not found"**: Usually a transient resource-contention error — Daytona could not allocate a sandbox when all slots were occupied. The retry logic in `_common.sh` will automatically re-queue these tasks with exponential backoff (up to 3 attempts). If it persists, check your Daytona tier limits or ensure `daytona-sdk` is installed in the same Python environment as Harbor.

**Docker Hub images fail with "unauthorized"**: Daytona's remote builder cannot pull `jefzda/sweap-images:*` from Docker Hub. This affects 21 SWE-bench Pro tasks (9 csb_sdlc_debug + 12 csb_sdlc_fix). Run these locally or re-host images to GHCR using `scripts/rehost_sweap_images.py`.

**Sandbox creation fails for tasks with `storage = "20G"` in task.toml**: Daytona has a hard 10GB per-sandbox storage limit. 39 tasks specify `storage = "20G"` and 1 specifies `"15G"`, exceeding this limit. Set `export DAYTONA_OVERRIDE_STORAGE=10240` before launching runs. This passes `--override-storage-mb 10240` to all `harbor run` commands, capping storage at 10GB. The actual Docker images are 1.5-5GB so 10GB is sufficient.

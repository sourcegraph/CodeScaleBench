# CSB Pre-Run Skills

Check infrastructure readiness, validate tasks, and launch benchmark runs. Use when preparing or starting benchmark runs.

**Relevant files:** `configs/**`, `scripts/check_infra.py`, `scripts/validate_tasks_preflight.py`

---

## Check Infrastructure

Verify all infrastructure prerequisites before launching a benchmark run.

### What It Checks

- OAuth token validity and time remaining (per account for multi-account setups)
- `.env.local` (project root) has `ANTHROPIC_API_KEY` and `SOURCEGRAPH_ACCESS_TOKEN`
- Docker daemon is running and responsive
- Disk space is sufficient (>5GB required, >20GB recommended)
- `harbor` CLI is installed
- `runs/official/` directory exists

### Steps

#### 1. Run the checker

```bash
cd ~/CodeScaleBench && python3 scripts/check_infra.py
```

#### 2. Present results

Show the table output directly — it's already formatted with color-coded status.

#### 3. Fix any issues

If FAIL items found, provide the specific fix:
- **Token expired**: `source configs/_common.sh && refresh_claude_token`
- **Multi-account tokens**: `source configs/_common.sh && setup_multi_accounts && ensure_fresh_token_all`
- **Missing env.local**: Create `.env.local` (project root) with required exports
- **Docker down**: `sudo systemctl start docker`
- **Low disk**: `python3 scripts/archive_run.py --older-than 7 --execute`

#### JSON output
```bash
python3 scripts/check_infra.py --format json
```

---

## Validate Tasks

Run pre-flight checks on benchmark task definitions to catch problems before committing to multi-hour runs.

### What It Catches

- Truncated or missing `instruction.md` (< 200 chars)
- Template placeholders left in instructions (`#ISSUE_NUMBER`, `{{...}}`)
- Missing or non-executable `tests/test.sh`
- Language/difficulty mismatches between `task.toml` and `selected_benchmark_tasks.json`
- Tasks not registered in the selection registry
- `expected_changes.json` referencing repos not mentioned in `instruction.md` (crossrepo)
- Known bad flags in test.sh (`--output_path` vs `--result_path`)

### Steps

#### 1. Run validation

For a specific suite:
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --suite csb_sdlc_pytorch
```

For all selected tasks:
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --all
```

For a single task:
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --task benchmarks/csb_sdlc_pytorch/sgt-005
```

#### 2. Present results

Show issues grouped by severity:
- **CRITICAL**: Will definitely cause run failures — must fix before launching
- **WARNING**: May affect results quality — should fix
- **INFO**: Informational (e.g., task not in selection registry)

#### 3. Offer to fix

- Truncated instruction → investigate and regenerate
- Language mismatch → update task.toml to match selection registry
- test.sh not executable → `chmod +x`
- Template placeholders → need manual replacement

#### JSON output (for piping)
```bash
python3 scripts/validate_tasks_preflight.py --all --format json
```

#### Critical only
```bash
python3 scripts/validate_tasks_preflight.py --all --critical-only
```

---

## Run Benchmark

Configure and launch CodeScaleBench runs with current paired-run and curation guardrails.

### Scope

Use when the user asks to run benchmark suites, rerun failures, or launch official/gap-fill batches.

### Canonical Commands

- Per-suite default: `./configs/<suite>_2config.sh`
- Unified selected-task runner: `./configs/run_selected_tasks.sh`
- Config registry: `configs/eval_matrix.json`
- Do not assume `*_3config.sh` runners exist.

### Run Policy (Mandatory)

- Default execution is paired by task: `baseline` + `sourcegraph_full`.
- Single-lane runs are gap-fill only:
  - `--baseline-only` requires valid existing `sourcegraph_full` counterpart runs.
  - `--full-only` requires valid existing `baseline` counterpart runs.
- Emergency bypass only: `ALLOW_UNPAIRED_SINGLE_CONFIG=true`.

### Standard Launch Patterns

```bash
# Paired per-suite run
./configs/pytorch_2config.sh --parallel 4

# Paired selected-task run
./configs/run_selected_tasks.sh --benchmark csb_sdlc_pytorch

# Gap-fill baseline only (guarded)
./configs/run_selected_tasks.sh --benchmark csb_sdlc_pytorch --baseline-only

# Gap-fill full only (guarded)
./configs/run_selected_tasks.sh --benchmark csb_sdlc_pytorch --full-only
```

### Preflight Checks

Before launching:
1. `python3 scripts/check_infra.py`
2. Ensure `SOURCEGRAPH_ACCESS_TOKEN` is set for MCP-enabled lanes.
3. Ensure Claude credentials exist in `~/.claude/.credentials.json`.

### Post-Run Curation

```bash
python3 scripts/quarantine_invalid_tasks.py --execute
python3 scripts/generate_manifest.py --require-triage --fail-on-unknown-prefix
python3 scripts/validate_official_integrity.py --runs-dir runs/official --check-mcp-trace-health
```

### Analysis Entrypoints

```bash
python3 scripts/audit_traces.py --json
python3 scripts/cost_report.py
python3 scripts/generate_eval_report.py --runs-dir runs/official --output-dir eval_reports
```

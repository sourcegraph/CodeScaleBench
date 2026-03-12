---
name: run-benchmark
description: Configure and launch CodeScaleBench runs with current paired-run and curation guardrails.
---

# Skill: Run Benchmark

## Scope

Use this skill when the user asks to run benchmark suites, rerun failures, or launch official/gap-fill batches in `CodeScaleBench`.

## Approval Gate (Required Before Running)

Before executing any benchmark run, ask the user to confirm:

1. **Model** — which model? (e.g. `anthropic/claude-haiku-4-5-20251001` for test runs)
2. **Suite / selection file** — which benchmark suite or `--selection-file`?
3. **Config** — paired (default), `--baseline-only`, or `--full-only`? Which `--full-config`?
4. **Parallel slots** — how many? (default: 1; use 8 for multi-account runs)
5. **Category** — `staging` (default) or `official`?

Do NOT launch a run until the user has confirmed these five parameters.

## Canonical Commands (Current)

- Per-suite default: `./configs/<suite>_2config.sh`
- Unified selected-task runner: `./configs/run_selected_tasks.sh`
- Config registry: `configs/eval_matrix.json`
- Do not assume `*_3config.sh` runners exist.

## Run Policy (Mandatory)

- Default execution is paired by task: `baseline` + `sourcegraph_full`.
- Single-lane runs are gap-fill only:
  - `--baseline-only` requires valid existing `sourcegraph_full` counterpart runs.
  - `--full-only` requires valid existing `baseline` counterpart runs.
- Emergency bypass only: `ALLOW_UNPAIRED_SINGLE_CONFIG=true`.

## Standard Launch Patterns

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

## Preflight Checks

Before launching:

1. `python3 scripts/check_infra.py`
2. Ensure `SOURCEGRAPH_ACCESS_TOKEN` is set for MCP-enabled lanes.
3. Ensure Claude credentials exist in `~/.claude/.credentials.json` (or configured multi-account homes).

## Post-Run Curation (Before Analysis)

```bash
python3 scripts/quarantine_invalid_tasks.py --execute
python3 scripts/generate_manifest.py --require-triage --fail-on-unknown-prefix
python3 scripts/validate_official_integrity.py --runs-dir runs/official --check-mcp-trace-health
```

## Analysis Entrypoints

```bash
python3 scripts/audit_traces.py --json
python3 scripts/cost_report.py
python3 scripts/generate_eval_report.py --runs-dir runs/official --output-dir eval_reports
```

## Output Expectations

Runs land under `runs/<category>/<run_dir>/` with per-config task directories and `flagged_tasks.json`.
Use `runs/official/MANIFEST.json` as the authoritative curated inventory.

## Failure Handling

- If a single-lane run is blocked by guardrails, run paired mode unless this is confirmed gap-fill.
- If counterpart validity is unclear, regenerate and validate manifest first.

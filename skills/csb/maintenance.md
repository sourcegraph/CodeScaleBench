# CSB Maintenance Skills

Sync metadata, re-extract metrics, archive runs, generate reports, and plan next actions. Use when maintaining data hygiene, generating reports, or deciding what to work on next.

**Relevant files:** `scripts/sync_task_metadata.py`, `scripts/reextract_all_metrics.py`, `scripts/archive_run.py`, `scripts/generate_eval_report.py`, `scripts/generate_manifest.py`, `scripts/repo_health.py`

---

## Repo Health (before commit or push)

Run the health gate before committing or pushing to reduce doc drift and keep branches clean. **Agents: run this before every commit/push when you changed docs, configs, or task definitions.**

```bash
python3 scripts/repo_health.py --quick   # Fast: docs + selection file only
python3 scripts/repo_health.py           # Full: adds task preflight static
```

See [repo-health/SKILL.md](../repo-health/SKILL.md) and `docs/REPO_HEALTH.md` for details.

---

## Sync Metadata

Ensure task.toml files match the authoritative `selected_benchmark_tasks.json` registry.

### What It Catches
- Language mismatches
- Difficulty label drift
- Missing task.toml files for selected tasks

### Steps
```bash
cd ~/CodeScaleBench && python3 scripts/sync_task_metadata.py
```

To fix mismatches:
```bash
python3 scripts/sync_task_metadata.py --fix
```

### Variants
```bash
python3 scripts/sync_task_metadata.py --suite csb_sdlc_pytorch
python3 scripts/sync_task_metadata.py --format json
```

---

## Re-extract Metrics

Batch re-extract `task_metrics.json` after extraction bug fixes or schema changes.

### Steps

#### 1. Preview (dry run)
```bash
cd ~/CodeScaleBench && python3 scripts/reextract_all_metrics.py --dry-run
python3 scripts/reextract_all_metrics.py --dry-run --filter csb_sdlc_pytorch
```

#### 2. Run re-extraction
```bash
python3 scripts/reextract_all_metrics.py
```

#### 3. Regenerate MANIFEST
```bash
python3 scripts/generate_manifest.py
```

### Key Notes
- Transcript-first extraction: prefers `claude-code.txt` over `trajectory.json`
- Cost calculation uses cache-aware token breakdown
- Skips directories containing `__broken_verifier`, `validation_test`, `archive`
- Safe operation: overwrites task_metrics.json, never modifies result.json

---

## Archive Run

Move old completed run directories to `runs/official/archive/`.

### Steps

#### 1. Show candidates
```bash
cd ~/CodeScaleBench && python3 scripts/archive_run.py --older-than 7
```

#### 2. Archive if approved
```bash
python3 scripts/archive_run.py --older-than 7 --execute
```

### Variants
```bash
python3 scripts/archive_run.py --run-dir pytorch_opus_20260203_160607 --execute
python3 scripts/archive_run.py --older-than 7 --execute --compress
python3 scripts/archive_run.py --list-archived
python3 scripts/archive_run.py --older-than 7 --format json
```

---

## Generate Report

Generate the aggregate CSB evaluation report from completed Harbor runs.

### Output Files (in `./eval_reports/`)

- `eval_report.json` — Full structured data
- `REPORT.md` — Human-readable markdown with tables
- CSV files — One per table

### Steps

1. Show available runs:
```bash
ls runs/official/ 2>/dev/null
```

2. Generate the report:
```bash
cd ~/CodeScaleBench && python3 scripts/generate_eval_report.py \
    --runs-dir runs/official/ \
    --output-dir ./eval_reports/ \
    --selected-tasks ./configs/selected_benchmark_tasks.json
```

3. Display REPORT.md summary.

### Options
```bash
python3 scripts/generate_eval_report.py --no-csv
python3 scripts/generate_eval_report.py --selected-tasks ""  # all tasks
```

---

## What's Next

Analyze current state and recommend highest-value next action.

### Steps

#### 1. Get status with gap analysis
```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --gap-analysis --format json
```

#### 2. Get config comparison
```bash
cd ~/CodeScaleBench && python3 scripts/compare_configs.py --format json
```

#### 3. Categorize and recommend

**Priority order:**
- **P0**: Missing runs (gap analysis) — fill gaps first
- **P1**: Infrastructure errors — fix blockers
- **P2**: All-fail tasks — verifier/adapter bugs
- **P3**: Divergent tasks — MCP signal investigation
- **P4**: Config-specific failures

**After paired reruns complete:**
- Run MCP audit for usage patterns
- Run re-extract metrics if extraction bugs were fixed
- Check zero-MCP rate

**If all tasks passing:**
- Run compare-configs
- Run MCP audit
- Start next benchmark suite
- Review eval report

#### 4. Present as actionable recommendations

```
## Current State
X tasks total: Y passing, Z failed, W errored, V running
Gap: N missing task runs

## Recommended Actions (in priority order)
1. **[CRITICAL]** Run missing SG_full tasks (N needed)
2. **[HIGH]** Fix infrastructure errors (N blocked)
3. **[MEDIUM]** Fill baseline gaps (N tasks)
4. **[LOW]** Investigate divergent tasks
```

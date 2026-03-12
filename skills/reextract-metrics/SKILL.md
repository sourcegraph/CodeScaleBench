---
name: reextract-metrics
description: Batch re-extract task_metrics.json for all runs after extraction bug fixes or schema changes. Triggers on reextract metrics, refresh metrics, update task metrics, fix extraction.
user-invocable: true
---

# Re-extract Metrics

Batch re-extract `task_metrics.json` for all active task directories after fixing extraction bugs or adding new metric fields.

## What This Does

Runs `scripts/reextract_all_metrics.py` which:
1. Walks `runs/official/` finding all task directories with `result.json`
2. Re-runs the full extraction pipeline (`extract_task_metrics.py`) on each
3. Enriches with selection metadata from `selected_benchmark_tasks.json`
4. Reports how many metrics changed significantly (especially cost corrections)

## Steps

### 1. Preview scope (dry run)

Always show what will be re-extracted first:

```bash
cd ~/CodeScaleBench && python3 scripts/reextract_all_metrics.py --dry-run
```

If filtering to a specific suite:
```bash
python3 scripts/reextract_all_metrics.py --dry-run --filter csb_sdlc_pytorch
```

### 2. Run the re-extraction

```bash
python3 scripts/reextract_all_metrics.py
```

Or filtered:
```bash
python3 scripts/reextract_all_metrics.py --filter csb_sdlc_swebenchpro
```

### 3. Review corrections

The script reports:
- Total task directories processed
- Number with significantly corrected costs (>10% change)
- Number of failures

Pay attention to `CORRECTED` lines — these indicate tasks where the old extraction had inflated or deflated metrics.

### 4. Regenerate MANIFEST

After re-extraction, always regenerate the MANIFEST to pick up corrected metrics:

```bash
python3 scripts/generate_manifest.py
```

### 5. Verify

Spot-check a few task_metrics.json files to confirm the fix applied correctly:
```bash
# Example: check a specific task
python3 -c "
import json, pathlib
p = pathlib.Path('runs/official')
# Find a recent task_metrics.json
for f in sorted(p.rglob('task_metrics.json'))[:3]:
    d = json.loads(f.read_text())
    print(f'{f.parent.name}: cost=\${d.get(\"cost_usd\", \"n/a\")}, mcp={d.get(\"tool_calls_mcp\", \"n/a\")}, total={d.get(\"tool_calls_total\", \"n/a\")}')
"
```

## Common Use Cases

### After extraction bug fix
When `extract_task_metrics.py` logic changes (e.g., transcript-first tool counting):
```bash
python3 scripts/reextract_all_metrics.py
python3 scripts/generate_manifest.py
```

### After adding new metric fields
When new extractors are added to `csb_metrics/extractors.py`:
```bash
python3 scripts/reextract_all_metrics.py
```

### After new runs complete
To extract metrics for newly completed tasks:
```bash
python3 scripts/reextract_all_metrics.py --filter csb_sdlc_pytorch
```

## Key Technical Notes

- **Transcript-first extraction**: As of commit 59cdf7db, tool counts prefer `claude-code.txt` over `trajectory.json` to capture Task subagent MCP calls.
- **Cost calculation**: Uses cache-aware token breakdown from transcripts. Old extraction used cumulative `n_input_tokens` from result.json which inflated costs 50-100x for MCP runs.
- **Skip patterns**: Automatically skips directories containing `__broken_verifier`, `validation_test`, `archive`, `__archived`.
- **Two directory layouts**: Handles both `config/batch_ts/task__hash/` and `config/task__hash/` layouts.
- **Safe operation**: Overwrites existing `task_metrics.json` with corrected data. Original `result.json` is never modified.

## Related Skills

- `/mcp-audit` — Analyzes MCP usage patterns from task_metrics.json (run AFTER re-extraction)
- `/generate-report` — Generates evaluation report (uses task_metrics.json data)
- `/evaluate-traces` — Comprehensive trace evaluation

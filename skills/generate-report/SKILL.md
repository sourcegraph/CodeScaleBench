---
name: generate-report
description: Generate the aggregate CSB evaluation report from completed Harbor runs. Triggers on generate report, eval report, ccb report, benchmark report.
user-invocable: true
---

# Generate CSB Evaluation Report

Generate the aggregate CodeScaleBench evaluation report from completed Harbor runs in `runs/official/`.

## What This Does

Runs `scripts/generate_eval_report.py` which:
1. Discovers all completed runs in the official runs directory
2. Extracts metrics from each task's `result.json` (and fallback sources)
3. Enriches with selection metadata (SDLC phase, language, MCP benefit score)
4. Filters to canonical selected tasks
5. Produces three output files

## Output Files (in `./eval_reports/`)

- **`eval_report.json`** — Full structured data (all tasks, metrics, configs)
- **`REPORT.md`** — Human-readable markdown with tables:
  - Run Inventory
  - Aggregate Performance (mean reward, pass rate by config)
  - Per-Benchmark Breakdown (reward matrix: benchmark x config)
  - Efficiency (tokens, wall clock, cost)
  - Tool Utilization (MCP vs local tool calls)
  - SWE-Bench Pro Partial Scores
  - Performance by SDLC Phase
  - Performance by Language
  - Performance by MCP Benefit Score
- **CSV files** — One per table for downstream analysis

## Steps

1. First, show the user what runs are available:

```bash
echo "=== Completed runs ===" && \
ls runs/official/ 2>/dev/null && \
echo "" && \
echo "=== Task counts per run ===" && \
for run in runs/official/*/; do \
    count=$(find "$run" -name "result.json" -path "*/instance_*" -o -name "result.json" -path "*__*" 2>/dev/null | wc -l); \
    echo "  $(basename $run): $count tasks with results"; \
done
```

2. Generate the report:

```bash
cd ~/CodeScaleBench && \
python3 scripts/generate_eval_report.py \
    --runs-dir runs/official/ \
    --output-dir ./eval_reports/ \
    --selected-tasks ./configs/selected_benchmark_tasks.json
```

3. Display the REPORT.md summary to the user:

```bash
cat ./eval_reports/REPORT.md
```

4. Let the user know where to find the full data:

```
Report files written to ./eval_reports/:
  - REPORT.md (summary tables)
  - eval_report.json (full structured data)
  - *.csv (per-table CSV files)
```

## Options

If the user asks for a report on a subset of runs or a specific directory, pass `--runs-dir` accordingly:

```bash
python3 scripts/generate_eval_report.py \
    --runs-dir /path/to/specific/runs/ \
    --output-dir ./eval_reports/
```

To skip CSV generation:
```bash
python3 scripts/generate_eval_report.py --no-csv
```

To skip task selection filtering (include ALL discovered tasks, not just canonical):
```bash
python3 scripts/generate_eval_report.py --selected-tasks ""
```

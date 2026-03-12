---
name: ir-analysis
description: Compute information retrieval quality metrics (precision, recall, MRR, nDCG, MAP) comparing file retrieval across baseline and MCP configs against ground truth. Triggers on ir analysis, retrieval metrics, file recall, ground truth, search quality.
user-invocable: true
---

# IR Analysis

Measure how well agents find the right files, comparing baseline (local tools) vs MCP (Sourcegraph) retrieval against per-task ground truth.

## What This Does

Runs `scripts/ir_analysis.py` which:
1. Loads ground truth files per task from `configs/ground_truth_files.json` (or builds it from benchmark task dirs)
2. Parses agent transcripts (`agent/claude-code.txt`) to extract which files were accessed via tool calls
3. Computes IR metrics: Precision@K, Recall@K, F1@K, MRR, nDCG@K, MAP, file-level recall, context efficiency
4. Aggregates by benchmark and config, with statistical significance tests

## Steps

### 1. Ensure ground truth is built

If `configs/ground_truth_files.json` doesn't exist or needs refreshing:

```bash
cd ~/CodeScaleBench && python3 scripts/ir_analysis.py --build-ground-truth
```

This extracts ground truth files from each benchmark's task structure (patches, diffs, ground_truth dirs, test scripts, instructions). Reports per-benchmark counts and confidence levels.

### 2. Run the IR analysis

```bash
cd ~/CodeScaleBench && python3 scripts/ir_analysis.py --json 2>/dev/null
```

Or for human-readable table output:

```bash
cd ~/CodeScaleBench && python3 scripts/ir_analysis.py 2>/dev/null
```

### 3. Parse and present key findings

**Per-benchmark IR scores:**

| Benchmark | Config | N | File Recall | MRR | P@5 | R@5 | nDCG@5 | MAP | Ctx Eff |
|-----------|--------|--:|------------:|----:|----:|----:|-------:|----:|--------:|

**Overall aggregates:**

| Config | File Recall | MRR | MAP | Context Efficiency |
|--------|------------:|----:|----:|-------------------:|
| baseline | X | X | X | X |
| sourcegraph_full | X | X | X | X |

**Statistical tests (baseline vs SG_full):**

| Metric | Welch's t | p-value | Cohen's d | Bootstrap 95% CI |
|--------|----------:|--------:|----------:|-----------------:|

### 4. Interpret results

Key metrics to focus on:
- **File recall**: Fraction of ground truth files the agent accessed (most important)
- **MRR**: How quickly the agent found the first relevant file (1.0 = first file accessed was relevant)
- **Context efficiency**: Relevant files / total files accessed (higher = less noise)
- **P@K**: Precision at top-K accessed files (were early accesses relevant?)

### 5. Per-task drill-down (optional)

For detailed per-task scores:

```bash
python3 scripts/ir_analysis.py --per-task --json 2>/dev/null
```

Filter to a specific benchmark:

```bash
python3 scripts/ir_analysis.py --suite csb_sdlc_swebenchpro 2>/dev/null
```

## Variants

### Build/refresh ground truth only
```bash
python3 scripts/ir_analysis.py --build-ground-truth
```

### JSON output for programmatic use
```bash
python3 scripts/ir_analysis.py --json > /tmp/ir_results.json
```

### Filter to one benchmark
```bash
python3 scripts/ir_analysis.py --suite csb_sdlc_pytorch
```

### Per-task detail
```bash
python3 scripts/ir_analysis.py --per-task
```

## Key Technical Notes

- **Ground truth confidence levels**: "high" (from patches/diffs — SWE-bench Pro, PyTorch, K8s Docs), "medium" (from test scripts), "low" (regex from instructions). High-confidence tasks give the most reliable IR metrics.
- **Transcript parsing**: Reads Harbor's nested JSONL format from `agent/claude-code.txt`. Extracts file paths from Read, Grep, Glob, Write, Edit tool inputs and MCP tool results.
- **Path normalization**: Strips `/workspace/` prefix, `a/`/`b/` diff notation, lowercases for comparison.
- **Baseline retrieval**: For runs without MCP, "retrieved files" come from local Read/Grep/Glob calls. This measures manual navigation quality vs MCP search quality.
- **Deduplication**: When multiple batches exist for the same task+config, the latest (by `started_at` timestamp) wins.
- **Statistical tests**: Uses pure-stdlib implementations from `csb_metrics/statistics.py` — Welch's t-test, Cohen's d, bootstrap CI. No scipy dependency.

## Ground Truth Sources

| Benchmark | Strategy | Source File | Confidence |
|-----------|----------|-------------|:----------:|
| SWE-bench Pro | Patch headers | `solve.sh` / `solution/solve.sh` | high |
| PyTorch | Diff headers | `tests/expected.diff` / `instruction.md` | high |
| K8s Docs | Directory listing | `ground_truth/` | high |
| Governance | Test script paths | `tests/test.sh` | medium |
| Enterprise | Test script paths | `tests/test.sh` | medium |
| Others | Instruction regex | `instruction.md` | low |

## Related Skills

- `/mcp-audit` — MCP usage patterns and adoption rates (complements IR quality metrics)
- `/compare-configs` — Binary pass/fail divergence with optional statistical tests
- `/evaluate-traces` — Comprehensive trace audit (broader scope, data integrity focus)

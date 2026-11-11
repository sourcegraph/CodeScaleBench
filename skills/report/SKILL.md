---
name: report
description: "Generate CodeScaleBench evaluation reports, analyze benchmark run costs, and compare baseline vs MCP configuration performance. Use when the user asks for benchmark results, cost breakdowns, config comparisons, MCP impact analysis, or pass-rate summaries."
---

# Skill: Reports & Analysis

## Scope

Use this skill when the user asks to:
- Generate evaluation reports for benchmark runs
- Analyze run costs and token spending by model or suite
- Compare baseline vs MCP (Sourcegraph) configuration performance
- Assess information retrieval (IR) and oracle impact
- Summarize pass rates, model success, or cost-per-task metrics

## Reporting Workflow

1. **Verify run completion** — confirm runs finished before reporting:
   ```bash
   python3 scripts/analysis/aggregate_status.py --staging
   ```
   If completion rate is below target, use `/status` to investigate before generating reports.

2. **Generate the report** — pick the command matching your goal (see "When to Use Which Report" below).

3. **Compare configurations** — for A/B analysis between baseline and MCP:
   ```bash
   python3 scripts/evaluation/compare_configs.py --config1 baseline --config2 sourcegraph_full
   ```

4. **Review and share** — check output for anomalies (unexpected zero scores, missing suites) before sharing results.

## When to Use Which Report

| Goal | Command |
|------|---------|
| Full evaluation summary (pass rates, model scores) | `python3 scripts/maintenance/generate_eval_report.py` |
| Cost breakdown for a single run | `python3 scripts/evaluation/cost_report.py --run-dir runs/staging/<run>` |
| Cost comparison across models/suites | `python3 scripts/evaluation/cost_breakdown_analysis.py --staging` |
| Baseline vs MCP performance delta | `python3 scripts/evaluation/compare_configs.py --config1 baseline --config2 sourcegraph_full` |
| Retrieval quality (IR tasks) | `python3 scripts/evaluation/ir_analysis.py --run-dir runs/staging/<run>` |
| Oracle and verifier contribution | `python3 scripts/evaluation/oracle_ir_analysis.py --runs-dir runs/staging` |

## Key Metrics

- **Pass rate** — % tasks passed verification
- **Model success** — % tasks where agent succeeded
- **Cost per task** — average tokens/$ spent
- **Improvement (MCP)** — gain from Sourcegraph integration
- **Verification cost** — dual verification overhead

## Related Skills

- `/evaluate` — extract and score individual task results
- `/run` — generate results to analyze
- `/status` — check run status before generating reports

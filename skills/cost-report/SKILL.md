---
name: cost-report
description: Token and cost analysis per run, suite, and config. Shows most expensive tasks and config cost comparison. Triggers on cost report, how much did it cost, token usage, spending.
user-invocable: true
---

# Cost Report

Analyze token usage and estimated cost across benchmark runs.

## Steps

### 1. Run cost analysis

```bash
cd ~/CodeScaleBench && python3 scripts/cost_report.py
```

### 2. Present findings

The table output shows:
- Total cost, tokens, and wall-clock hours
- Per suite/config breakdown with average cost per task
- Config cost comparison (is SG_full significantly more expensive than baseline?)
- Top 10 most expensive individual tasks

## Variants

### Filter to one suite
```bash
python3 scripts/cost_report.py --suite csb_sdlc_pytorch
```

### Filter to one config
```bash
python3 scripts/cost_report.py --config sourcegraph_full
```

### JSON output
```bash
python3 scripts/cost_report.py --format json
```

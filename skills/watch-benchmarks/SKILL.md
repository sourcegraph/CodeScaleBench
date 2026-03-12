---
name: watch-benchmarks
description: Live benchmark monitoring — scan run directories, classify task status, fingerprint errors, present structured summaries. Triggers on watch benchmarks, benchmark status, run status, monitor runs.
user-invocable: true
---

# Watch Benchmarks

Monitor the status of CodeScaleBench benchmark runs in `runs/official/`.

## What This Does

Runs `scripts/aggregate_status.py` which:
1. Scans all run directories under `runs/official/`
2. Classifies each task as: `running`, `completed_pass`, `completed_fail`, `errored`, or `timeout`
3. Fingerprints errors into known categories (token refresh, API 500, rate limit, etc.)
4. Produces a structured JSON summary with totals, per-suite breakdown, and error summary

## Steps

1. Run the status scanner:

```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --format json
```

2. Parse the JSON output and present to the user as markdown tables:
   - **Totals**: overall pass/fail/error/running/timeout counts
   - **By Suite**: table with suite rows, config columns, showing pass/total
   - **Error Summary**: grouped by fingerprint with counts and severity
   - **Non-passing Tasks**: list of failed/errored/running/timeout tasks with details

3. If there are errors, highlight the top error categories and their recommended fixes from the `advice` field.

## Follow-up Variants

If the user asks for more specific views, use these flags:

### Failures only
```bash
python3 scripts/aggregate_status.py --failures-only --format json
```

### Recent tasks only (last N minutes)
```bash
python3 scripts/aggregate_status.py --since 60 --format json
```

### Single suite
```bash
python3 scripts/aggregate_status.py --suite csb_sdlc_pytorch --format json
```

### Single config
```bash
python3 scripts/aggregate_status.py --config baseline --format json
```

### Combined filters
```bash
python3 scripts/aggregate_status.py --suite csb_sdlc_swebenchpro --config sourcegraph_full --failures-only --format json
```

### Table output (compact, for quick glance)
```bash
python3 scripts/aggregate_status.py --format table
```

### Write per-task status.json files
```bash
python3 scripts/aggregate_status.py --write-status --format table
```

## Presentation Guidelines

When presenting results:
- Use a summary line like "X tasks total: Y passing, Z failed, W errored"
- Show the suite x config matrix as a markdown table
- Group errors by fingerprint and show count + severity + advice
- For non-passing tasks, list them grouped by suite
- If everything is passing, say so concisely

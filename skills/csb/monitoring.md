# CSB Monitoring Skills

Check active run status and watch benchmark progress. Use when checking on running benchmarks or monitoring progress.

**Relevant files:** `scripts/aggregate_status.py`

---

## Run Status

Quick check on the active benchmark run — how many tasks done, any failures yet?

Lightweight alternative to watch-benchmarks focused on recent activity.

### Steps

#### 1. Check what's active (last 60 minutes)

```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --since 60 --format json
```

If nothing recent, widen to last 4 hours:
```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --since 240 --format json
```

#### 2. Present a concise summary

Parse the JSON and present:
- How many tasks completed vs still running
- Pass/fail/error counts
- Any errors that appeared (with fingerprint)
- Estimated progress (completed / total if knowable)

Format as brief status line:
```
Active run: 8/12 tasks done (7 pass, 1 fail). 4 still running. No errors.
```

#### 3. Suggest action if needed

- If errors: suggest triage-failure or credential refresh
- If all done: suggest watch-benchmarks for full picture or whats-next
- If still running: report and suggest checking back later

### Variants

```bash
# Specific suite
python3 scripts/aggregate_status.py --since 120 --suite csb_sdlc_pytorch --format json

# Specific config
python3 scripts/aggregate_status.py --since 120 --config sourcegraph_full --format json

# Full table
python3 scripts/aggregate_status.py --since 120 --format table
```

---

## Watch Benchmarks

Monitor the status of CodeScaleBench benchmark runs in `runs/official/`.

### What This Does

Runs `scripts/aggregate_status.py` which:
1. Scans all run directories under `runs/official/`
2. Classifies each task as: `running`, `completed_pass`, `completed_fail`, `errored`, or `timeout`
3. Fingerprints errors into known categories (token refresh, API 500, rate limit, etc.)
4. Produces a structured JSON summary

### Steps

1. Run the status scanner:
```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --format json
```

2. Parse the JSON output and present as markdown tables:
   - **Totals**: overall pass/fail/error/running/timeout counts
   - **By Suite**: table with suite rows, config columns, showing pass/total
   - **Error Summary**: grouped by fingerprint with counts and severity
   - **Non-passing Tasks**: list with details

3. If there are errors, highlight top error categories and recommended fixes.

### Variants

```bash
# Failures only
python3 scripts/aggregate_status.py --failures-only --format json

# Recent tasks only (last N minutes)
python3 scripts/aggregate_status.py --since 60 --format json

# Single suite
python3 scripts/aggregate_status.py --suite csb_sdlc_pytorch --format json

# Single config
python3 scripts/aggregate_status.py --config baseline --format json

# Combined filters
python3 scripts/aggregate_status.py --suite csb_sdlc_swebenchpro --config sourcegraph_full --failures-only --format json

# Table output (compact)
python3 scripts/aggregate_status.py --format table

# Write per-task status.json files
python3 scripts/aggregate_status.py --write-status --format table
```

### Presentation Guidelines

- Use summary line: "X tasks total: Y passing, Z failed, W errored"
- Show suite x config matrix as markdown table
- Group errors by fingerprint with count + severity + advice
- For non-passing tasks, list grouped by suite

---
name: run-status
description: Quick status check on the currently active benchmark run. Lighter than watch-benchmarks, scoped to recent activity. Triggers on run status, how's it going, are tasks done, active run.
user-invocable: true
---

# Run Status

Quick check on the active benchmark run — how many tasks done, any failures yet?

This is a lightweight alternative to `/watch-benchmarks` that focuses on recent activity rather than all historical runs.

## Steps

### 1. Check what's active (last 60 minutes)

```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --since 60 --format json
```

If nothing recent, widen to last 4 hours:
```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --since 240 --format json
```

### 2. Present a concise summary

Parse the JSON and present:
- How many tasks completed vs still running
- Pass/fail/error counts
- Any errors that appeared (with fingerprint)
- Estimated progress (completed / total if knowable)

Format as a brief status line:
```
Active run: 8/12 tasks done (7 pass, 1 fail). 4 still running. No errors.
```

Or if problems:
```
Active run: 5/12 tasks done (3 pass, 2 errored).
  2x token_refresh_403 — tokens may need refresh.
  4 tasks still running, 3 not yet started.
```

### 3. Suggest action if needed

- If errors: suggest `/triage-failure` or credential refresh
- If all done: suggest `/watch-benchmarks` for full picture or `/whats-next`
- If still running: report and suggest checking back later

## Variants

### Specific suite
```bash
python3 scripts/aggregate_status.py --since 120 --suite csb_sdlc_pytorch --format json
```

### Specific config
```bash
python3 scripts/aggregate_status.py --since 120 --config sourcegraph_full --format json
```

### Full table (same as watch-benchmarks but recent only)
```bash
python3 scripts/aggregate_status.py --since 120 --format table
```

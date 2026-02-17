Scan benchmark runs and report aggregate status with error fingerprinting.

## Default: Scan Official Runs
```bash
python3 scripts/aggregate_status.py --format table
```

## Scan Staging Runs (in-progress or awaiting promotion)
```bash
python3 scripts/aggregate_status.py --staging --format table
```

## Watch Mode (continuous refresh)
```bash
python3 scripts/aggregate_status.py --watch --format table
python3 scripts/aggregate_status.py --staging --watch --format table
```

## Arguments

$ARGUMENTS — optional flags: --staging (scan staging instead of official), --suite <name>, --config <name>, --since <minutes>, --failures-only, --watch

## Steps

1. Run aggregate_status.py with appropriate flags based on user request
2. If --staging flag or user mentions "staging", scan runs/staging/ instead of runs/official/
3. If user asks about in-progress or recent runs, add --since flag
4. For failures only, add --failures-only
5. Summarize: total tasks, pass/fail/error counts, any notable patterns
6. If staging runs are READY, suggest using /promote-run

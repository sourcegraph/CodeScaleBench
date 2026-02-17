Analyze current benchmark state and recommend next actions.

## Steps

1. Check staging for runs awaiting promotion:
```bash
python3 scripts/promote_run.py --list
```

2. Check official runs for overall status:
```bash
python3 scripts/aggregate_status.py --format table
```

3. Check for active Docker containers (in-progress runs):
```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null | head -10
```

4. Analyze and recommend:
   - If staging runs are READY → suggest /promote-run
   - If runs have failures → suggest /triage-failure
   - If configs are missing coverage → suggest which benchmarks to run next
   - If all runs look good → suggest /generate-report or /compare-configs

## Arguments

$ARGUMENTS — none expected

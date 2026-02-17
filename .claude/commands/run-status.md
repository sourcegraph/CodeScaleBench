Lightweight check on active run progress.

## Steps

1. Check for active runs in staging (new runs land here by default):
```bash
python3 scripts/aggregate_status.py --staging --since 120 --format table
```

2. If no staging runs found, check official:
```bash
python3 scripts/aggregate_status.py --since 120 --format table
```

3. Also check for running Docker containers:
```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}' | head -20
```

4. Summarize: which tasks are running, which completed, any errors

## Arguments

$ARGUMENTS — optional: --staging (check staging), --since <minutes> (default: 120)

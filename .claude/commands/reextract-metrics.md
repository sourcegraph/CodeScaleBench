Batch re-extract task_metrics.json after extraction bug fixes or schema changes.

## Steps

1. Run metric re-extraction:
```bash
python3 scripts/reextract_all_metrics.py
```

2. For a specific run:
```bash
python3 scripts/reextract_all_metrics.py --run-dir <dir>
```

3. Verify extracted metrics are correct

## Arguments

$ARGUMENTS — optional: --run-dir <dir>

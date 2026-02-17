Pre-flight validation for benchmark task definitions.

Catches: truncated instructions, template placeholders, metadata mismatches, missing test.sh.

## Steps

1. Run pre-flight validation:
```bash
python3 scripts/validate_tasks_preflight.py
```

2. If specific suite requested, filter:
```bash
python3 scripts/validate_tasks_preflight.py --suite ccb_navprove
```

3. Report any issues found and suggest fixes

## Arguments

$ARGUMENTS — optional: --suite <name> to validate a specific benchmark suite

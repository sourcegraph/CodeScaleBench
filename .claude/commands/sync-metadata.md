Reconcile task.toml vs selected_benchmark_tasks.json.

## Steps

1. Dry-run check:
```bash
python3 scripts/sync_task_metadata.py
```

2. Auto-fix mismatches:
```bash
python3 scripts/sync_task_metadata.py --fix
```

3. Report what was synced

## Arguments

$ARGUMENTS — optional: --fix (auto-update mismatches)

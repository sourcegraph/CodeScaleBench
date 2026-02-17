Move old runs to archive/, optional compression, dry-run by default.

## Steps

1. Dry-run (see what would be archived):
```bash
python3 scripts/archive_run.py
```

2. Archive a specific run:
```bash
python3 scripts/archive_run.py --execute <run_dir_name>
```

3. SAFETY: Before archiving, verify all tasks in the batch exist in a newer active batch. The MANIFEST merges across batches — archiving removes any tasks unique to that batch.

## Arguments

$ARGUMENTS — optional: run directory name, --execute, --older-than <days>

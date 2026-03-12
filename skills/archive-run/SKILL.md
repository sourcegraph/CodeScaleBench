---
name: archive-run
description: Archive old completed benchmark runs to save disk space and speed up scans. Triggers on archive runs, clean up runs, disk space, old runs.
user-invocable: true
---

# Archive Run

Move old completed run directories to `runs/official/archive/` to save disk and speed up scans.

## Steps

### 1. Show what can be archived

```bash
cd ~/CodeScaleBench && python3 scripts/archive_run.py --older-than 7
```

### 2. Present the candidates

Show the list of directories that would be archived, with their age, size, and result count.

### 3. Archive if user approves

```bash
python3 scripts/archive_run.py --older-than 7 --execute
```

## Variants

### Archive a specific run
```bash
python3 scripts/archive_run.py --run-dir pytorch_opus_20260203_160607 --execute
```

### Compress while archiving (saves more disk)
```bash
python3 scripts/archive_run.py --older-than 7 --execute --compress
```

### List already-archived runs
```bash
python3 scripts/archive_run.py --list-archived
```

### JSON output
```bash
python3 scripts/archive_run.py --older-than 7 --format json
```

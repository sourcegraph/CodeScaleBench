---
name: sync-metadata
description: Reconcile task metadata between selected_benchmark_tasks.json and task.toml files. Finds and fixes drift. Triggers on sync metadata, check metadata, metadata mismatch, reconcile tasks.
user-invocable: true
---

# Sync Metadata

Ensure task.toml files match the authoritative `selected_benchmark_tasks.json` registry.

## What It Catches

- Language mismatches (task.toml says "python" but selection says "go")
- Difficulty label drift (task.toml says "medium" but selection says "hard")
- Missing task.toml files for selected tasks

## Steps

### 1. Run the sync check

```bash
cd ~/CodeScaleBench && python3 scripts/sync_task_metadata.py
```

### 2. Present mismatches

Show any fields where task.toml disagrees with selected_benchmark_tasks.json.

### 3. Offer to fix

If mismatches found:
```bash
python3 scripts/sync_task_metadata.py --fix
```

This updates the task.toml files to match the selection registry.

## Variants

### Filter to one suite
```bash
python3 scripts/sync_task_metadata.py --suite csb_sdlc_pytorch
```

### JSON output
```bash
python3 scripts/sync_task_metadata.py --format json
```

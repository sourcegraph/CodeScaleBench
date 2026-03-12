---
name: validate-tasks
description: Pre-flight validation of benchmark tasks before launching runs. Catches truncated instructions, metadata mismatches, missing test scripts. Triggers on validate tasks, preflight, pre-flight check, check tasks.
user-invocable: true
---

# Validate Tasks

Run pre-flight checks on benchmark task definitions to catch problems before committing to multi-hour runs.

## What It Catches

- Truncated or missing `instruction.md` (< 200 chars)
- Template placeholders left in instructions (`#ISSUE_NUMBER`, `{{...}}`)
- Missing or non-executable `tests/test.sh`
- Language/difficulty mismatches between `task.toml` and `selected_benchmark_tasks.json`
- Tasks not registered in the selection registry
- `expected_changes.json` referencing repos not mentioned in `instruction.md` (crossrepo)
- Known bad flags in test.sh (`--output_path` vs `--result_path`)

## Steps

### 1. Run validation

For a specific suite (most common before a run):
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --suite csb_sdlc_pytorch
```

For all selected tasks:
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --all
```

For a single task:
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --task benchmarks/csb_sdlc_pytorch/sgt-005
```

### 2. Present results

Show issues grouped by severity:
- **CRITICAL**: Will definitely cause run failures — must fix before launching
- **WARNING**: May affect results quality — should fix
- **INFO**: Informational (e.g., task not in selection registry)

### 3. Offer to fix

If issues are found, offer to fix them:
- Truncated instruction → investigate and regenerate
- Language mismatch → update task.toml to match selection registry
- test.sh not executable → `chmod +x`
- Template placeholders → need manual replacement

## Variants

### JSON output (for piping)
```bash
python3 scripts/validate_tasks_preflight.py --all --format json
```

### Critical only
```bash
python3 scripts/validate_tasks_preflight.py --all --critical-only
```

# Repo Health Gate

Lightweight checks to **commit working solutions often** and **reduce entropy** (doc drift, broken task refs, invalid config). One command before push; same checks in CI.

## Goal

- **Catch drift early** — docs referencing missing files, eval_matrix inconsistent with configs, tasks in selection with no benchmark dir.
- **Keep branches clean** — run the gate before push so main stays green; merge small, working changes.
- **Single contract** — `configs/repo_health.json` defines what “healthy” means; no scattered scripts or tribal knowledge.

## Running the health gate

From repo root:

```bash
# Full health (docs + config + task preflight static)
python3 scripts/repo_health.py

# Quick health (docs + selection file only; no full task sweep)
python3 scripts/repo_health.py --quick

# Exit code: 0 = all required checks passed, 1 = at least one failed
```

Use **`--quick`** for fast feedback (e.g. pre-commit or after editing only docs/config). Use **full** before merging or before a benchmark run.

## What gets checked

| Check | Quick | Full | Purpose |
|-------|-------|------|--------|
| **docs_consistency** | ✓ | ✓ | Referenced scripts/configs/docs exist; eval_matrix valid. |
| **selection_file** | ✓ | ✓ | `configs/selected_benchmark_tasks.json` exists and is valid JSON. |
| **task_preflight_static** | — | ✓ | All selected tasks: instruction length, test.sh, no placeholders, registry match. |

Contract: `configs/repo_health.json`. Add or relax checks there without changing this doc (then run `docs_consistency_check` so new script refs are valid).

## Branch hygiene (recommendations)

- **Run health before push** — `python3 scripts/repo_health.py` or `--quick` so you don’t push broken refs or task defs.
- **Merge working state often** — small PRs that pass the gate reduce long-lived branches and merge conflicts.
- **After editing docs/config** — run at least `python3 scripts/docs_consistency_check.py` to catch missing refs and matrix drift.

## Fixing common failures

- **missing_ref:README.md:scripts/docs_consistency_check.py** — Remove or fix the reference in the doc, or add the missing file.
- **eval_matrix_*** — Fix `configs/eval_matrix.json` (supported_configs, official_default_configs, config_definitions).
- **Task preflight errors** — Run `python3 scripts/validate_tasks_preflight.py --all` and fix reported tasks (instruction length, test.sh, placeholders, or sync task list).

## CI

The health gate runs in CI on push/PR (see `.github/workflows/repo_health.yml`). Fix failures before merging so main stays clean.

---
name: repo-health
description: Run the repo health gate before commit or push to reduce doc drift and keep branches clean. Triggers on commit, push, before push, repo health, reduce drift, doc drift, clean branch.
user-invocable: true
---

# Repo Health

Run the health gate **before committing or pushing** so the tree stays clean and entropy (doc drift, broken refs, invalid task defs) is caught early.

## When to Use

- **Before every commit or push** when you changed docs, configs, or task definitions.
- When the user says "before push", "reduce drift", "doc drift", or "keep branch clean".
- After editing files under `docs/`, `configs/`, or `benchmarks/` task dirs.

## Steps

### 1. Run the gate

**Quick** (docs + selection file only; use after editing only docs/config):
```bash
cd ~/CodeScaleBench && python3 scripts/repo_health.py --quick
```

**Full** (adds task preflight static; use before merge or after touching task defs):
```bash
cd ~/CodeScaleBench && python3 scripts/repo_health.py
```

### 2. If any check fails

- Fix the reported issues (see `docs/REPO_HEALTH.md` for common fixes).
- Re-run the gate until it passes.
- Then commit/push.

### 3. Do not bypass

Do not suggest committing or pushing with failing health checks. If the user insists, remind them that CI will fail and main stays clean only if everyone runs the gate.

## Contract

The list of checks is in `configs/repo_health.json`. Quick mode runs only `quick_checks`; full runs all required checks.

## Reference

- `docs/REPO_HEALTH.md` — Full doc (what’s checked, branch hygiene, fixing failures).
- `scripts/repo_health.py` — Gate script; exit 0 only when all required checks pass.

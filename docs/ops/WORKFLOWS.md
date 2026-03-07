# Operations Workflows

## When To Read This
- You need the standard operational sequence for runs, triage, or reporting.

## Do Not Read First If
- You only need a single script: use `docs/ops/SCRIPT_INDEX.md`.
- You need policy definitions/spec semantics: use `docs/reference/README.md`.

## Run Batch Workflow
1. Run infra checks (`scripts/check_infra.py`).
2. Validate tasks (`scripts/validate_tasks_preflight.py`).
3. If using Daytona, inspect current account state with `scripts/daytona_cost_guard.py summary` when needed.
4. Launch benchmark via `configs/*` runner only (interactive confirmation required).
5. Do not use raw Daytona `harbor run` for benchmark batches; the wrappers enforce preflight and labeling.
6. Monitor with `scripts/aggregate_status.py` and classify errors.
7. Validate outputs (`scripts/validate_task_run.py`).
8. Triage before reruns.
9. Regenerate manifest/report after completion.
10. Run `scripts/repo_health.py` before commit/push.

### Daytona wrapper rules

- All benchmark launchers should source `configs/_common.sh`.
- Daytona launches should go through `harbor_run_guarded`, not raw `harbor run`.
- The launcher should run `scripts/daytona_cost_guard.py preflight` before the first Daytona launch.
- Wrapper-driven targeted reruns should still be launched from repo root so relative task/config paths and logs resolve cleanly.
- Only set `HARBOR_ALLOW_UNGUARDED_DAYTONA=1` for deliberate break-glass debugging.

## Triage Workflow
1. Confirm error class via `docs/ERROR_CATALOG.md` and status fingerprints.
2. Check run outputs and trajectories.
3. Isolate task-level fix or rerun scope.
4. Avoid blind reruns; document root cause or limitation.

## ContextBench Calibration Workflow
1. Ensure `claude` CLI is installed, authenticated, and `SOURCEGRAPH_ACCESS_TOKEN` is set.
2. **Always use CLI mode** (the default). Do NOT pass `--use-sdk`.
3. Run a pilot calibration:
```bash
source .env.local && python3 scripts/validate_on_contextbench.py \
  --sample 10 --seed 42 --model claude-opus-4-6 --backend hybrid --parallel 10
```
4. Check `results/contextbench/calibration_report.json` for composite score (go/no-go >= 0.65).
5. Scale up when pilot passes:
```bash
# Medium (50 tasks)
source .env.local && python3 scripts/validate_on_contextbench.py \
  --sample 50 --seed 42 --model claude-opus-4-6 --backend hybrid --parallel 50
# Full verified subset (500 tasks)
source .env.local && python3 scripts/validate_on_contextbench.py --verified
```
6. Optional: add `--prune` for a haiku pruning pass to reduce false positives.
7. Review trajectories at `results/contextbench/trajectories.traj.json`.

## Docs / Agent Navigation Maintenance Workflow
1. Edit canonical sources under `docs/ops/`.
2. Regenerate guides and indexes:
```bash
python3 scripts/refresh_agent_navigation.py
```
3. Verify freshness in CI/local (`python3 scripts/refresh_agent_navigation.py --check`).
4. Run `python3 scripts/docs_consistency_check.py`.
5. Run `python3 scripts/repo_health.py --quick` before commit.

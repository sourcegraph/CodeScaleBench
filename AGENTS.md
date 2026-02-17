# CodeContextBench Operations Guide

This file is the operational quick-reference for benchmark maintenance.
`CLAUDE.md` intentionally mirrors this file.

## Canonical References
- `README.md` - repo overview and quick start
- `docs/CONFIGS.md` - config matrix and MCP behavior
- `docs/QA_PROCESS.md` - pre-run, run-time, post-run validation
- `docs/ERROR_CATALOG.md` - known failures and remediation
- `docs/TASK_SELECTION.md` - curation/difficulty policy
- `docs/TASK_CATALOG.md` - current task inventory
- `docs/SCORING_SEMANTICS.md` - reward/pass interpretation
- `docs/WORKFLOW_METRICS.md` - timing/cost metric definitions
- `docs/AGENT_INTERFACE.md` - runtime I/O contract
- `docs/EXTENSIBILITY.md` - safe suite/task/config extension
- `docs/LEADERBOARD.md` - ranking policy
- `docs/SUBMISSION.md` - submission format

## Typical Skill Routing
Use these defaults unless there is a task-specific reason not to.

- Pre-run readiness: `check-infra`, `validate-tasks`
- Launch/runs: `run-benchmark`, `run-status`, `watch-benchmarks`
- Failure investigation: `triage-failure`, `quick-rerun`
- Cross-config analysis: `compare-configs`, `mcp-audit`, `ir-analysis`
- Cost/reporting: `cost-report`, `generate-report`
- Data hygiene: `sync-metadata`, `reextract-metrics`, `archive-run`
- Planning/prioritization: `whats-next`

## Standard Workflow
1. Run infrastructure checks before any batch.
2. Validate task integrity before launch (include runtime smoke for new/changed tasks).
3. Run the benchmark config (`configs/*_2config.sh` or equivalent).
4. Monitor progress and classify errors while tasks are running.
5. Validate outputs after each batch (`result.json`, `flagged_tasks.json`, trajectory coverage).
6. Triage failures before rerunning; avoid blind reruns.
7. Regenerate `MANIFEST.json` and evaluation report after run completion.
8. Sync metadata if task definitions changed.

## Quality Gates
A run is considered healthy only if all are true:

- No infra blockers (tokens, Docker, disk, credentials)
- No unexpected missing `result.json`
- Errored tasks are classified and actionable
- Zero-reward clusters are explained (task difficulty vs infra/tooling)
- Trajectory gaps are accounted for (or JSONL fallback noted)
- Config comparisons are based on matched task sets

## Run Hygiene
- Prefer isolated, well-scoped reruns (don’t mix unrelated fixes in one batch).
- Use parallel mode only when multi-account token state is confirmed fresh.
- Keep run naming and suite/config metadata consistent.
- Do not treat archived or draft analyses as canonical docs.
- Keep `docs/` focused on maintained operational guidance.

## Escalation Rules
- Repeated infra failures: stop batch reruns and fix root cause first.
- Suspected verifier bug: quarantine task, document evidence, and open follow-up.
- Missing trajectories: use transcript fallback and record the limitation.
- Widespread MCP regressions: run MCP usage audit before changing prompts/configs.

## High-Use Commands
```bash
python3 scripts/check_infra.py
python3 scripts/validate_tasks_preflight.py --all
python3 scripts/validate_tasks_preflight.py --task <task_dir> --smoke-runtime
python3 scripts/validate_task_run.py --run <run_dir>
python3 scripts/aggregate_status.py --staging
python3 scripts/compare_configs.py --run <run_dir>
python3 scripts/mcp_audit.py --run <run_dir>
python3 scripts/cost_report.py --run <run_dir>
python3 scripts/generate_manifest.py
python3 scripts/generate_eval_report.py
```

## Script Entrypoints
- `configs/_common.sh` - shared run infra (parallelism, token refresh, validation hooks)
- `configs/*_2config.sh` - per-suite run launchers
- `configs/validate_one_per_benchmark.sh --smoke-runtime` - quick no-agent runtime smoke (1 task per benchmark)
  - Smoke interpretation: `smoke_verifier_nonzero_with_reward` is acceptable in no-agent mode; use `--smoke-timeout-overrides "ccb_pytorch=900,ccb_tac=900,ccb_crossrepo=900"` for timeout-heavy suites.
  - Timeout diagnostics: `smoke_build_timeout` (image build phase) vs `smoke_verify_timeout` (verifier phase).
- `scripts/promote_run.py` - staging to official promotion flow

# CodeContextBench Operations Guide

This file is the operational quick-reference for benchmark maintenance.
`CLAUDE.md` mirrors this file.

## Benchmark Overview
8 SDLC phase suites + 10 MCP-unique suites. SDLC tasks measure code quality
across phases: build, debug, design, document, fix, secure, test, understand.
MCP-unique tasks measure org-scale cross-repo discovery and retrieval.
See `README.md` for the full suite table and `docs/TASK_CATALOG.md` for
per-task details. See `docs/MCP_UNIQUE_TASKS.md` for the MCP-unique extension.

## Canonical References
- `README.md` - repo overview and quick start
- `docs/CONFIGS.md` - config matrix and MCP behavior
- `docs/QA_PROCESS.md` - pre-run, run-time, post-run validation
- `docs/ERROR_CATALOG.md` - known failures and remediation
- `docs/TASK_SELECTION.md` - curation/difficulty policy
- `docs/TASK_CATALOG.md` - current task inventory
- `docs/SCORING_SEMANTICS.md` - reward/pass interpretation (incl. oracle checks + hybrid scoring)
- `docs/EVALUATION_PIPELINE.md` - unified eval: verifier → LLM judge → statistics → report
- `docs/RETRIEVAL_EVAL_SPEC.md` - full retrieval/IR evaluation pipeline (normalized events → metrics/probes/taxonomy artifacts)
- `docs/MCP_UNIQUE_TASKS.md` - MCP-unique task system (suites, authoring, oracle, DS tasks)
- `docs/MCP_UNIQUE_CALIBRATION.md` - oracle coverage analysis and threshold calibration data
- `docs/WORKFLOW_METRICS.md` - timing/cost metric definitions
- `docs/AGENT_INTERFACE.md` - runtime I/O contract
- `docs/EXTENSIBILITY.md` - safe suite/task/config extension
- `docs/REPO_HEALTH.md` - health gate and branch hygiene (reduce drift)
- `docs/LEADERBOARD.md` - ranking policy
- `docs/SUBMISSION.md` - submission format
- `docs/SKILLS.md` - AI agent skill system overview
- `skills/` - operational runbooks for AI agents (see `skills/README.md`)

## Git Policy
- **All work happens on `main`** — do NOT create feature branches.
- Never run `git checkout -b` or `git switch -c`.
- Commit directly to `main`. This avoids cross-session branch confusion when multiple agents work on the repo.

## Run Launch Policy
- **Every `harbor run` invocation MUST be gated by interactive confirmation.**
  The user must see a pre-flight summary and press Enter before any benchmark
  task launches. There is no `--yes` or unattended mode.
- Use `confirm_launch "description" "config" N` from `_common.sh` in one-off
  scripts. `run_selected_tasks.sh` has its own built-in pre-flight gate.
- **Never write a script that calls `harbor run` without a confirmation gate.**
- **Never pass `--yes` to `run_selected_tasks.sh`** — the flag has been removed.

## Typical Skill Routing
Use these defaults unless there is a task-specific reason not to.

- **Before commit or push:** `repo-health` — run `python3 scripts/repo_health.py` (or `--quick` if only docs/config changed). Do not commit/push with failing health checks.
- Pre-run readiness: `check-infra`, `validate-tasks`
- Launch/runs: `run-benchmark`, `run-status`, `watch-benchmarks`
- Failure investigation: `triage-failure`, `quick-rerun`
- Cross-config analysis: `compare-configs`, `mcp-audit`, `ir-analysis`
- Cost/reporting: `cost-report`, `generate-report`
- Data hygiene: `sync-metadata`, `reextract-metrics`, `archive-run`
- Planning/prioritization: `whats-next`

## Evaluation Configs
Config names encode three dimensions: `{agent}-{source}-{verifier}`.

**SDLC suites** (`ccb_build`, `ccb_debug`, etc.): use **baseline-local-direct**
+ **mcp-remote-direct**. Agent produces code changes; verifier checks git diffs.

**MCP-unique suites** (`ccb_mcp_*`): use **baseline-local-artifact** +
**mcp-remote-artifact**. Agent produces `answer.json`; verifier scores against
oracle. Never use `-direct` configs for MCP-unique suites.

MCP configs use `Dockerfile.sg_only` (direct) or `Dockerfile.artifact_only`
(artifact) so the agent must discover code via MCP tools. The verifier clones
the mirror repo at verification time and overlays agent changes before scoring.
See `docs/CONFIGS.md` for the full config matrix.

## Standard Workflow
0. **Before commit or push:** Run `python3 scripts/repo_health.py` (or `--quick`). Fix any failures so main stays clean and drift is caught early (see `docs/REPO_HEALTH.md`).
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
- Prefer isolated, well-scoped reruns (don't mix unrelated fixes in one batch).
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
python3 scripts/abc_audit.py --suite <suite>        # quality audit
python3 scripts/abc_score_task.py --suite <suite>    # per-task quality score
python3 scripts/docs_consistency_check.py            # documentation drift guard
python3 scripts/repo_health.py                      # repo health gate (before push); --quick for fast check
```

## Script Entrypoints
- `configs/_common.sh` - shared run infra (parallelism, token refresh, validation hooks, `confirm_launch()`, `validate_config_name()`)
- `configs/sdlc_suite_2config.sh` - generic SDLC runner (used by phase wrappers)
- `configs/{build,debug,design,document,fix,secure,test}_2config.sh` - thin SDLC phase wrappers
- `configs/run_selected_tasks.sh` - unified runner from `selected_benchmark_tasks.json`
- `configs/validate_one_per_benchmark.sh --smoke-runtime` - quick no-agent runtime smoke (1 task per suite)
  - Smoke interpretation: `smoke_verifier_nonzero_with_reward` is acceptable in no-agent mode.
  - Timeout diagnostics: `smoke_build_timeout` (image build phase) vs `smoke_verify_timeout` (verifier phase).
- `scripts/promote_run.py` - staging to official promotion flow

## Script Categories

### Core Operations (used in every run)
- `check_infra.py` - infrastructure readiness checker
- `validate_tasks_preflight.py` - pre-flight task validation (static + optional runtime smoke)
- `aggregate_status.py` - run scanner, status classification, watch mode
- `validate_task_run.py` - post-run output validation
- `status_fingerprints.py` - error classification (12 regex patterns)
- `generate_eval_report.py` - deterministic evaluation report generator
- `generate_manifest.py` - rebuild MANIFEST from on-disk results

### Analysis & Comparison
- `compare_configs.py` - cross-config divergence analysis
- `mcp_audit.py` - MCP tool usage audit
- `ir_analysis.py` - information retrieval analysis
- `cost_report.py` - token/cost aggregation
- `cost_breakdown_analysis.py` - detailed cost breakdown
- `failure_analysis.py` - failure pattern analysis
- `reliability_analysis.py` - reliability metrics
- `audit_traces.py` - agent trace auditing
- `ds_audit.py` - Deep Search usage audit

### Repo health (reduce drift, clean branches)
- `repo_health.py` - single gate: docs consistency + selection file + task preflight (see docs/REPO_HEALTH.md)
- `docs_consistency_check.py` - documentation drift guard

### Quality Assurance
- `abc_audit.py` - ABC benchmark quality audit (32 criteria across 3 dimensions)
- `abc_score_task.py` - per-task quality scoring
- `abc_criteria.py` - ABC criteria data model
- `validate_official_integrity.py` - official run integrity checks
- `quarantine_invalid_tasks.py` - quarantine tasks with zero MCP usage

### Data Management
- `sync_task_metadata.py` - task.toml vs registry reconciliation (--fix to auto-update)
- `archive_run.py` - archive old runs to save disk
- `rerun_failed.py` - generate rerun commands for failed tasks
- `promote_run.py` - staging to official promotion flow
- `extract_task_metrics.py` - per-task metric extraction
- `reextract_all_metrics.py` - bulk re-extraction

### Submission & Reporting
- `validate_submission.py` - validate submission format
- `package_submission.py` - package submission archive
- `generate_leaderboard.py` - generate leaderboard rankings
- `generate_comprehensive_report.py` - comprehensive analysis report
- `ingest_judge_results.py` - ingest LLM judge results

### Task Creation & Selection
- `select_benchmark_tasks.py` - canonical task selection pipeline
- `mine_bug_tasks.py` - mine GitHub for bug-fix tasks
- `generate_pytorch_expected_diffs.py` - generate PyTorch ground truth diffs

### One-Off / Historical
Scripts in `scripts/` prefixed with `rerun_`, `backfill_`, `fix_`, or `repair_`
are one-off scripts used to address specific past issues. They are preserved
for auditability but are not part of the standard workflow.

DependEval-specific scripts (`dependeval_eval_*.py`, `generate_dependeval_tasks.py`,
`select_dependeval_tasks.py`, `materialize_dependeval_repos.py`) relate to the
archived ccb_dependeval suite.

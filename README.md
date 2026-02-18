# CodeContextBench

Benchmark suite for evaluating how AI coding agents leverage external context tools on software engineering tasks across the SDLC. Developed as the reproducibility artifact for the paper *"CodeContextBench: A Systematic Evaluation Framework for Assessing the Impact of Enhanced Code Intelligence on AI Coding Agent Performance."*

This repository contains **benchmark task definitions**, **evaluation configs**, and a **metrics extraction pipeline**. Tasks are executed via the [Harbor](https://github.com/laude-institute/harbor/tree/main) runner with the Claude Code agent harness.

---

## Benchmark Suites (SDLC-Aligned)

Eight suites organized by software development lifecycle phase:

| Suite | SDLC Phase | Phase 1 Tasks | Target | Description |
|-------|-----------|------:|------:|-------------|
| `ccb_understand` | Requirements & Discovery | 20 | 20 | Codebase comprehension, onboarding, Q&A, knowledge recovery |
| `ccb_design` | Architecture & Design | 20 | 20 | Architecture analysis, dependency graphs, change impact |
| `ccb_fix` | Bug Repair | 25 | 25 | Diagnosing and fixing real bugs across production codebases |
| `ccb_build` | Feature & Refactoring | 25 | 25 | New features, refactoring, dependency management |
| `ccb_test` | Testing & QA | 14 | 20 | Code review, performance testing, code search validation |
| `ccb_document` | Documentation | 13 | 20 | API references, architecture docs, migration guides |
| `ccb_secure` | Security & Compliance | 20 | 20 | CVE analysis, reachability, governance, access control |
| `ccb_debug` | Debugging & Investigation | 20 | 20 | Root cause tracing, fault localization, provenance |
| **Total** | | **157** | **170** | |

See `docs/PRD_SDLC_SUITE_REORGANIZATION.md` for the reorganization rationale and task mapping.

---

## 2-Config Evaluation Matrix

All benchmarks are evaluated across two agent configurations that vary the external context tools available via MCP:

| Paper Config Name | `BASELINE_MCP_TYPE` | MCP Tools Available |
|-------------------|---------------------|---------------------|
| Baseline | `none` | None (agent uses only built-in tools) |
| MCP-Full | `sourcegraph_full` | All 13 Sourcegraph MCP tools including `sg_deepsearch`, `sg_deepsearch_read` |

See [docs/CONFIGS.md](docs/CONFIGS.md) for the full tool-by-tool breakdown.

---

## Repository Structure

```
benchmarks/              # Task definitions organized by SDLC phase
  ccb_build/             #   Feature & Refactoring (25 tasks)
  ccb_debug/             #   Debugging & Investigation (20 tasks)
  ccb_design/            #   Architecture & Design (20 tasks)
  ccb_document/          #   Documentation (13 tasks)
  ccb_fix/               #   Bug Repair (25 tasks)
  ccb_secure/            #   Security & Compliance (20 tasks)
  ccb_test/              #   Testing & QA (14 tasks)
  ccb_understand/        #   Requirements & Discovery (20 tasks)
configs/                 # Run configs and task selection
  _common.sh             #   Shared infra: token refresh, parallel execution, multi-account
  sdlc_suite_2config.sh  #   Generic SDLC runner (used by phase wrappers below)
  build_2config.sh       #   Phase wrapper: Build (25 tasks)
  debug_2config.sh       #   Phase wrapper: Debug (20 tasks)
  design_2config.sh      #   Phase wrapper: Design (20 tasks)
  document_2config.sh    #   Phase wrapper: Document (13 tasks)
  fix_2config.sh         #   Phase wrapper: Fix (25 tasks)
  secure_2config.sh      #   Phase wrapper: Secure (20 tasks)
  test_2config.sh        #   Phase wrapper: Test (14 tasks)
  run_selected_tasks.sh  #   Unified runner for all tasks
  validate_one_per_benchmark.sh  # Pre-flight smoke (1 task per suite)
  selected_benchmark_tasks.json  # Canonical task selection with metadata
  archive/               #   Pre-SDLC migration scripts (preserved for history)
scripts/                 # Metrics extraction, evaluation, and operational tooling
  ccb_metrics/           #   Python package: models, extractors, discovery, judge context
  generate_eval_report.py  # CLI: deterministic evaluation report generator
  aggregate_status.py    #   Core run scanner (status, errors, watch mode)
  status_fingerprints.py #   Error classification (12 regex patterns)
  validate_tasks_preflight.py # Pre-flight task validation
  validate_task_run.py   #   Post-run validation
  check_infra.py         #   Infrastructure readiness checker
  compare_configs.py     #   Cross-config divergence analysis
  cost_report.py         #   Token/cost aggregation
  sync_task_metadata.py  #   task.toml vs selection registry reconciliation
  generate_manifest.py   #   Rebuild MANIFEST from on-disk results
  archive_run.py         #   Archive old runs to save disk
  rerun_failed.py        #   Generate rerun commands for failed tasks
  abc_audit.py           #   ABC benchmark quality audit framework
  abc_score_task.py      #   Per-task quality scoring
  abc_criteria.py        #   ABC criteria data model (32 criteria)
  docs_consistency_check.py # Documentation drift guard
tests/                   # Unit tests for scripts/
  test_abc_audit.py      #   Tests for ABC audit framework
  test_abc_criteria.py   #   Tests for ABC criteria data model
  test_abc_score_task.py #   Tests for task quality scorer
  test_extract_task_metrics.py # Tests for metrics extraction
docs/                    # Operational documentation
  CONFIGS.md             #   2-config tool breakdown
  ERROR_CATALOG.md       #   Known error fingerprints, causes, fixes
  QA_PROCESS.md          #   Quality assurance and validation pipeline
  TASK_CATALOG.md        #   Detailed per-task reference
  TASK_SELECTION.md      #   Selection criteria, difficulty calibration, MCP scoring
  SCORING_SEMANTICS.md   #   Reward and pass interpretation per benchmark
  WORKFLOW_METRICS.md    #   Timing/cost metric definitions
  AGENT_INTERFACE.md     #   Runtime I/O contract for agents
  EXTENSIBILITY.md       #   Safe suite/task/config extension guide
  LEADERBOARD.md         #   Ranking policy
  SUBMISSION.md          #   Submission format specification
skills/                  # AI agent skill definitions (operational runbooks)
  ccb/                   #   CCB-specific: pre-run, monitoring, triage, analysis, maintenance
  general/               #   Reusable: workflow tools, agent delegation, dev practices
schemas/                 # JSON schemas for MANIFEST.json, task.toml, etc.
```

Each SDLC suite directory contains per-task subdirectories with `instruction.md`, `task.toml`, `tests/`, and ground truth (or `solution/`).

---

## Metrics Extraction Pipeline

The `scripts/` directory contains a stdlib-only Python 3.10+ pipeline for extracting deterministic metrics from Harbor run output:

```bash
# Generate evaluation report from Harbor runs
python3 scripts/generate_eval_report.py \
  --runs-dir /path/to/runs/official/ \
  --output-dir ./eval_reports/

# Generate LLM judge context files
python3 -m scripts.ccb_metrics.judge_context \
  --runs-dir /path/to/runs/official/ \
  --benchmarks-dir ./benchmarks/ \
  --output-dir ./judge_contexts/
```

The report generator produces:
- `eval_report.json` -- full structured report
- `REPORT.md` -- markdown tables (performance, efficiency, tool utilization)
- `harness_configs.json` -- exact harness configuration per run
- CSV files per table for downstream analysis

See `python3 scripts/generate_eval_report.py --help` for all options.

---

## Running with Harbor

The unified runner executes all 157 tasks across the 2-config matrix:

```bash
# Run all 157 tasks across 2 configs
bash configs/run_selected_tasks.sh

# Run only the baseline config
bash configs/run_selected_tasks.sh --baseline-only

# Run a single SDLC phase
bash configs/run_selected_tasks.sh --benchmark ccb_fix

# Dry run to list tasks without executing
bash configs/run_selected_tasks.sh --dry-run
```

Per-phase runners are also available:

```bash
bash configs/fix_2config.sh              # 25 Bug Repair tasks
bash configs/build_2config.sh            # 25 Feature & Refactoring tasks
bash configs/understand_2config.sh       # 20 Requirements & Discovery tasks
bash configs/design_2config.sh           # 20 Architecture & Design tasks
bash configs/debug_2config.sh            # 20 Debugging & Investigation tasks
bash configs/secure_2config.sh           # 20 Security & Compliance tasks
bash configs/test_2config.sh             # 14 Testing & QA tasks
bash configs/document_2config.sh         # 13 Documentation tasks
```

All runners support `--baseline-only`, `--full-only`, `--task TASK_ID`, and `--parallel N` flags.

Requires [Harbor](https://github.com/laude-institute/harbor/tree/main) installed and configured with a Max subscription.

---

## Quality Assurance & Validation

CodeContextBench includes a multi-stage QA pipeline to ensure task integrity, reproducible runs, and accurate scoring.

| Phase | Script | Purpose |
|-------|--------|---------|
| **Pre-flight** | `scripts/validate_tasks_preflight.py` | Catches truncated instructions, template placeholders, language/difficulty mismatches, missing test.sh |
| **Infra check** | `scripts/check_infra.py` | Verifies OAuth tokens (all accounts), Docker, disk space, Harbor CLI |
| **Error fingerprinting** | `scripts/status_fingerprints.py` | Classifies failures with 12 regex patterns; auto-retry guidance per pattern |
| **Post-run** | `scripts/validate_task_run.py` | Flags crashes, MCP tool usage anomalies, suspicious scoring |
| **Metadata sync** | `scripts/sync_task_metadata.py` | Keeps task.toml in sync with `selected_benchmark_tasks.json`; `--fix` to auto-update |
| **Run analysis** | `scripts/aggregate_status.py` | Scans run dirs, classifies per-task status, writes status.json, supports `--watch` mode |

The QA methodology uses a 6-dimension audit framework: instruction contamination, reproducibility, verifier correctness, ghost/false-positive detection, error misclassification, and tool effectiveness analysis.

See [docs/QA_PROCESS.md](docs/QA_PROCESS.md) for the full pipeline documentation and [docs/ERROR_CATALOG.md](docs/ERROR_CATALOG.md) for the known error catalog.

---

## Operational Tooling

Key scripts organized by workflow phase:

| Phase | Script | Usage |
|-------|--------|-------|
| **Pre-run** | `validate_tasks_preflight.py` | `python3 scripts/validate_tasks_preflight.py [--suite ccb_pytorch] [--task sgt-001]` |
| **Pre-run** | `check_infra.py` | `python3 scripts/check_infra.py` |
| **During run** | `aggregate_status.py --since 2h` | `python3 scripts/aggregate_status.py --since 2h` |
| **Post-run** | `aggregate_status.py` | `python3 scripts/aggregate_status.py [--watch]` |
| **Post-run** | `validate_task_run.py` | `python3 scripts/validate_task_run.py <run_dir>` |
| **Analysis** | `compare_configs.py` | `python3 scripts/compare_configs.py` |
| **Analysis** | `cost_report.py` | `python3 scripts/cost_report.py` |
| **Analysis** | `generate_manifest.py` | `python3 scripts/generate_manifest.py` |
| **Maintenance** | `sync_task_metadata.py` | `python3 scripts/sync_task_metadata.py [--fix]` |
| **Maintenance** | `archive_run.py` | `python3 scripts/archive_run.py <run_dir> [--compress]` |
| **Maintenance** | `rerun_failed.py` | `python3 scripts/rerun_failed.py [--fingerprint timeout] [--suite ccb_pytorch]` |

---

## AI Agent Skills

The `skills/` directory contains structured runbooks for AI coding agents operating on this repository. These encode operational workflows — infrastructure checks, task validation, failure triage, report generation — so any agent (Claude Code, Cursor, Copilot, etc.) can follow them autonomously.

| Category | Skills | Description |
|----------|--------|-------------|
| **CCB Operations** | 20 skills in 6 files | Pre-run checks, monitoring, triage, analysis, maintenance, task authoring |
| **General Purpose** | 11 skills in 4 files | Session management, agent delegation, search patterns, dev practices |

Skills are plain markdown and tool-agnostic. See [`skills/README.md`](skills/README.md) for the full index and integration guides for Cursor, Claude Code, and other agents. See [`docs/SKILLS.md`](docs/SKILLS.md) for background on the skills system.

---

## License

See [LICENSE](LICENSE).

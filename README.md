# CodeScaleBench

Benchmark suite for evaluating how AI coding agents leverage external context tools on software engineering tasks across the SDLC.

This repository contains:
- **Benchmark task definitions** (SDLC and Org suites with task specs, tests, and metadata)
- **Evaluation and run configs** (paired baseline vs MCP-enabled execution modes)
- **Metrics extraction and reporting pipelines** for score/cost/retrieval analysis
- **Run artifacts and agent traces** (in `runs/` and published summaries under `docs/official_results/`)

Tasks are executed via the [Harbor](https://github.com/laude-institute/harbor/tree/main) runner with the Claude Code agent harness.

---

## Quickstart (Public / First-Time Users)

### Who this repo is for

- Researchers evaluating coding agents on realistic software engineering tasks
- Practitioners comparing baseline vs MCP-enabled agent configurations

### What you can do without Harbor

You can inspect task definitions, run validation and analysis scripts, and use the metrics/report pipeline on existing Harbor run outputs.

```bash
git clone https://github.com/sourcegraph/CodeScaleBench.git
cd CodeScaleBench

# Fast repo sanity check (docs/config refs)
python3 scripts/repo_health.py --quick

# Explore task-based docs navigation
sed -n '1,120p' docs/START_HERE_BY_TASK.md

# Inspect available benchmark suites
ls benchmarks
```

### What requires Harbor (benchmark execution)

Running benchmark tasks requires:

- [Harbor](https://github.com/laude-institute/harbor/tree/main) installed and configured

Our internal default setup often uses:
- **Daytona** account and API key (preferred in this repo). See `docs/DAYTONA.md`
- Docker for Daytona-incompatible tasks
- Agent/runtime credentials as needed by your Harbor harness

Recommended pre-run checks:

```bash
python3 scripts/check_infra.py
python3 scripts/validate_tasks_preflight.py --all
```

Then start with a dry run:

```bash
bash configs/run_selected_tasks.sh --dry-run
```

### First places to read

- `docs/START_HERE_BY_TASK.md` for task-oriented navigation
- `docs/reference/CONFIGS.md` for the 2-config evaluation matrix
- `docs/EVALUATION_PIPELINE.md` for scoring and reporting outputs

---

## CodeScaleBench-SDLC

Nine suites organized by software development lifecycle phase:

| Suite | SDLC Phase | Tasks | Description |
|-------|-----------|------:|-------------|
| `csb_sdlc_feature` | Feature Implementation | 23 | New features, interface implementation, big-code features |
| `csb_sdlc_fix` | Bug Repair | 19 | Diagnosing and fixing real bugs across production codebases |
| `csb_sdlc_refactor` | Cross-File Refactoring | 18 | Cross-file refactoring, enterprise dependency refactoring, rename refactoring |
| `csb_sdlc_debug` | Debugging & Investigation | 13 | Root cause tracing, fault localization, provenance |
| `csb_sdlc_secure` | Security & Compliance | 13 | CVE analysis, reachability, governance, access control |
| `csb_sdlc_test` | Testing & QA | 12 | Code review, performance testing, code search validation, test generation |
| `csb_sdlc_design` | Architecture & Design | 11 | Architecture analysis, dependency graphs, change impact |
| `csb_sdlc_document` | Documentation | 11 | API references, architecture docs, migration guides, runbooks |
| `csb_sdlc_understand` | Requirements & Discovery | 11 | Codebase comprehension, onboarding, Q&A, knowledge recovery |
| **Total** | | **131** | |

## CodeScaleBench-Org

Eleven additional suites measure cross-repo discovery, symbol resolution, dependency tracing, and deep-search-driven investigation in polyrepo environments.

| Suite | Category | Tasks | Description |
|-------|----------|------:|-------------|
| `csb_org_migration` | Framework Migration | 25 | API migrations, breaking changes across repos |
| `csb_org_compliance` | Compliance | 13 | Standards adherence, audit, and provenance workflows |
| `csb_org_incident` | Incident Debugging | 13 | Error-to-code-path tracing across microservices |
| `csb_org_platform` | Platform Knowledge | 13 | Service template discovery and tribal knowledge |
| `csb_org_security` | Vulnerability Remediation | 13 | CVE mapping, missing auth middleware across repos |
| `csb_org_crossorg` | Cross-Org Discovery | 12 | Interface implementations and authoritative repo identification across orgs |
| `csb_org_crossrepo` | Cross-Repo Discovery | 11 | Cross-repo search, dependency discovery, impact analysis |
| `csb_org_crossrepo_tracing` | Dependency Tracing | 11 | Cross-repo dependency chains, blast radius, symbol resolution |
| `csb_org_domain` | Domain Lineage | 11 | Domain-specific lineage and analysis workflows |
| `csb_org_onboarding` | Onboarding & Comprehension | 11 | API consumption mapping, end-to-end flow, architecture maps |
| `csb_org_org` | Organizational Context | 11 | Agentic discovery, org-wide coding correctness |
| **Total** | | **144** | |

**Combined canonical benchmark: 275 tasks** (131 SDLC across 9 suites + 144 Org across 11 suites). Suite sizes are DOE-driven (Neyman-optimal allocation) to maximize statistical power per suite rather than uniform sizing. Non-canonical tasks are archived in `benchmarks/backups/`.

Both baseline and MCP-Full agents have access to **all repos** in each task's fixture. The only difference is the method: baseline reads code locally, MCP-Full uses Sourcegraph MCP tools (local code is truncated). This ensures we measure whether MCP tools help agents work better — not whether MCP can access repos the baseline can't.

See [docs/ORG_TASKS.md](docs/ORG_TASKS.md) for the full task system, authoring guide, and oracle evaluation framework. See [docs/ORG_CALIBRATION.md](docs/ORG_CALIBRATION.md) for oracle coverage analysis.

---

## 2-Config Evaluation Matrix

All benchmarks are evaluated across two primary configurations (Baseline vs MCP). The concrete run config names differ by task type:

- **SDLC suites** (`csb_sdlc_feature`, `csb_sdlc_refactor`, `csb_sdlc_fix`, etc.): `baseline-local-direct` + `mcp-remote-direct`
- **Org suites** (`csb_org_*`): `baseline-local-direct` + `mcp-remote-direct`

At a high level, the distinction is:

| Config Name | Internal MCP mode | MCP Tools Available |
|-------------------|---------------------|---------------------|
| Baseline | `none` | None (agent uses only built-in tools) |
| MCP | `sourcegraph` / `artifact` (task-dependent) | All 13 Sourcegraph MCP tools including `sg_deepsearch`, `sg_deepsearch_read` |

See [docs/reference/CONFIGS.md](docs/reference/CONFIGS.md) for the canonical configuration matrix and tool-by-tool breakdown.

---

## Repository Structure

```
benchmarks/              # Task definitions organized by SDLC phase + Org
  csb_sdlc_feature/      #   Feature Implementation (23 tasks)
  csb_sdlc_fix/          #   Bug Repair (19 tasks)
  csb_sdlc_refactor/     #   Cross-File Refactoring (18 tasks)
  csb_sdlc_debug/        #   Debugging & Investigation (13 tasks)
  csb_sdlc_secure/       #   Security & Compliance (13 tasks)
  csb_sdlc_test/         #   Testing & QA (12 tasks)
  csb_sdlc_design/       #   Architecture & Design (11 tasks)
  csb_sdlc_document/     #   Documentation (11 tasks)
  csb_sdlc_understand/   #   Requirements & Discovery (11 tasks)
  csb_org_migration/     #   Org: framework migration (25 tasks)
  csb_org_compliance/    #   Org: compliance & audit (13 tasks)
  csb_org_incident/      #   Org: incident debugging (13 tasks)
  csb_org_platform/      #   Org: platform knowledge (13 tasks)
  csb_org_security/      #   Org: vulnerability remediation (13 tasks)
  csb_org_crossorg/      #   Org: cross-org discovery (12 tasks)
  csb_org_crossrepo/     #   Org: cross-repo discovery (11 tasks)
  csb_org_crossrepo_tracing/  #   Org: dependency tracing (11 tasks)
  csb_org_domain/        #   Org: domain lineage (11 tasks)
  csb_org_onboarding/    #   Org: onboarding (11 tasks)
  csb_org_org/           #   Org: org context (11 tasks)
  backups/               #   Archived non-canonical tasks
configs/                 # Run configs and task selection
  _common.sh             #   Shared infra: token refresh, parallel execution, multi-account
  sdlc_suite_2config.sh  #   Generic SDLC runner (used by phase wrappers below)
  feature_2config.sh     #   Phase wrapper: Feature (20 tasks)
  refactor_2config.sh    #   Phase wrapper: Refactor (20 tasks)
  debug_2config.sh       #   Phase wrapper: Debug (20 tasks)
  design_2config.sh      #   Phase wrapper: Design (20 tasks)
  document_2config.sh    #   Phase wrapper: Document (20 tasks)
  fix_2config.sh         #   Phase wrapper: Fix (25 tasks)
  secure_2config.sh      #   Phase wrapper: Secure (20 tasks)
  test_2config.sh        #   Phase wrapper: Test (20 tasks)
  run_selected_tasks.sh  #   Unified runner for all tasks
  validate_one_per_benchmark.sh  # Pre-flight smoke (1 task per suite)
  selected_benchmark_tasks.json  # Canonical task selection: 275 tasks (131 SDLC + 144 Org)
  use_case_registry.json #   100 GTM use cases (Org task source)
  archive/               #   Pre-SDLC migration scripts (preserved for history)
scripts/                 # Metrics extraction, evaluation, and operational tooling
  csb_metrics/           #   Python package: models, extractors, discovery, judge context
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
  EVALUATION_PIPELINE.md #   Unified eval: verifier → judge → statistics → report
  TASK_CATALOG.md        #   Detailed per-task reference
  TASK_SELECTION.md      #   Selection criteria, difficulty calibration, MCP scoring
  SCORING_SEMANTICS.md   #   Reward and pass interpretation per benchmark
  ORG_TASKS.md           #   Org task system, authoring, oracle evaluation
  ORG_CALIBRATION.md # Oracle coverage analysis and threshold calibration
  WORKFLOW_METRICS.md    #   Timing/cost metric definitions
  AGENT_INTERFACE.md     #   Runtime I/O contract for agents
  EXTENSIBILITY.md       #   Safe suite/task/config extension guide
  LEADERBOARD.md         #   Ranking policy
  SUBMISSION.md          #   Submission format specification
skills/                  # AI agent skill definitions (operational runbooks)
  csb/                   #   CSB-specific: pre-run, monitoring, triage, analysis, maintenance
  general/               #   Reusable: workflow tools, agent delegation, dev practices
schemas/                 # JSON schemas for MANIFEST.json, task.toml, etc.
```

Each suite directory contains per-task subdirectories with `instruction.md`, `task.toml`, `tests/`, and ground truth (or `solution/`). Org tasks additionally include `task_spec.json`, `oracle_answer.json`, and Dockerfile variants for baseline/MCP-only execution.

---

## Metrics Extraction Pipeline

The `scripts/` directory contains a stdlib-only Python 3.10+ pipeline for extracting deterministic metrics from Harbor run output.
Use `runs/analysis` for active analysis runs (and `runs/official` when producing publishable exports):

Official runs layout note:
- Raw source-of-truth run dirs now live under `runs/official/_raw/`.
- Top-level `runs/official/` is kept clean for organized benchmark/model views (`csb_sdlc/`, `csb_org/`) plus `MANIFEST.json`.
- Core scripts (manifest generation, promotion, organizer) resolve `_raw` automatically.

```bash
# Generate evaluation report from analysis runs
python3 scripts/generate_eval_report.py \
  --runs-dir /path/to/runs/analysis/ \
  --output-dir ./eval_reports/

# Generate LLM judge context files
python3 -m scripts.csb_metrics.judge_context \
  --runs-dir /path/to/runs/analysis/ \
  --benchmarks-dir ./benchmarks/ \
  --output-dir ./judge_contexts/
```

The report generator produces:
- `eval_report.json` -- full structured report
- `REPORT.md` -- markdown tables (performance, efficiency, tool utilization)
- `harness_configs.json` -- exact harness configuration per run
- CSV files per table for downstream analysis

See `python3 scripts/generate_eval_report.py --help` for all options.

### Official Results + Trace Browser

To export official results (valid scored tasks only) with parsed
trace summaries and local browsing UI:

```bash
python3 scripts/export_official_results.py \
  --runs-dir ./runs/official/ \
  --output-dir ./docs/official_results/
```

This writes:
- `docs/official_results/README.md` -- run/config score summary
- `docs/official_results/runs/*.md` -- per-run task tables
- `docs/official_results/tasks/*.md` -- per-task metrics + parsed tool/trace view
- `docs/official_results/data/official_results.json` -- machine-readable dataset
- `docs/official_results/audits/*.json` -- per-task audit artifacts (checksums + parsed trace events)
- `docs/official_results/traces/*/trajectory.json` -- bundled raw trajectory traces
- `docs/official_results/index.html` -- interactive local browser

Suite summaries are deduplicated to the latest result per
`suite + config + task_name`; full historical rows remain in
`official_results.json` under `all_tasks`.
For SDLC suites, export normalizes legacy config labels:
`baseline` -> `baseline-local-direct`, `mcp` -> `mcp-remote-direct`.

Serve locally:

```bash
python3 scripts/export_official_results.py --serve
```

For the full multi-layer evaluation pipeline (verifier, LLM judge, statistical analysis, dual-score reporting), see [docs/EVALUATION_PIPELINE.md](docs/EVALUATION_PIPELINE.md).

---

## Running with Harbor

This section assumes Harbor is already installed and configured. If not, start with the Quickstart section above and `python3 scripts/check_infra.py`.

### SDLC Tasks

The unified runner executes all 275 canonical tasks across the 2-config matrix:

```bash
# Run all 275 tasks across 2 configs
bash configs/run_selected_tasks.sh

# Run only the baseline config
bash configs/run_selected_tasks.sh --baseline-only

# Run a single SDLC phase
bash configs/run_selected_tasks.sh --benchmark csb_sdlc_fix

# Dry run to list tasks without executing
bash configs/run_selected_tasks.sh --dry-run
```

Per-phase runners are also available:

```bash
bash configs/feature_2config.sh          # 23 Feature Implementation tasks
bash configs/fix_2config.sh              # 19 Bug Repair tasks
bash configs/refactor_2config.sh         # 18 Cross-File Refactoring tasks
bash configs/debug_2config.sh            # 13 Debugging & Investigation tasks
bash configs/secure_2config.sh           # 13 Security & Compliance tasks
bash configs/test_2config.sh             # 12 Testing & QA tasks
bash configs/design_2config.sh           # 11 Architecture & Design tasks
bash configs/document_2config.sh         # 11 Documentation tasks
bash configs/understand_2config.sh       # 11 Requirements & Discovery tasks
```

### Filtering by Suite

All tasks (SDLC and Org) are in the unified `selected_benchmark_tasks.json`. Filter by suite with the `--benchmark` flag:

```bash
# Run only Org security tasks
bash configs/run_selected_tasks.sh --benchmark csb_org_security

# Run only SDLC fix tasks
bash configs/run_selected_tasks.sh --benchmark csb_sdlc_fix
```

All runners support `--baseline-only`, `--full-only`, `--task TASK_ID`, and `--parallel N` flags.

---

## Quality Assurance & Validation

CodeScaleBench includes a multi-stage QA pipeline to ensure task integrity, reproducible runs, and accurate scoring.

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
| **Pre-run** | `validate_tasks_preflight.py` | `python3 scripts/validate_tasks_preflight.py [--suite csb_sdlc_fix] [--task sgt-001]` |
| **Pre-run** | `check_infra.py` | `python3 scripts/check_infra.py` |
| **During run** | `aggregate_status.py --since 2h` | `python3 scripts/aggregate_status.py --since 2h` |
| **Post-run** | `aggregate_status.py` | `python3 scripts/aggregate_status.py [--watch]` |
| **Post-run** | `validate_task_run.py` | `python3 scripts/validate_task_run.py <run_dir>` |
| **Analysis** | `compare_configs.py` | `python3 scripts/compare_configs.py` |
| **Analysis** | `cost_report.py` | `python3 scripts/cost_report.py` |
| **Analysis** | `generate_manifest.py` | `python3 scripts/generate_manifest.py` |
| **Maintenance** | `sync_task_metadata.py` | `python3 scripts/sync_task_metadata.py [--fix]` |
| **Maintenance** | `archive_run.py` | `python3 scripts/archive_run.py <run_dir> [--compress]` |
| **Maintenance** | `rerun_failed.py` | `python3 scripts/rerun_failed.py [--fingerprint timeout] [--suite csb_sdlc_fix]` |

---

## AI Agent Skills

The `skills/` directory contains structured runbooks for AI coding agents operating on this repository. These encode operational workflows — infrastructure checks, task validation, failure triage, report generation — so any agent (Claude Code, Cursor, Copilot, etc.) can follow them autonomously.

| Category | Skills | Description |
|----------|--------|-------------|
| **CSB Operations** | 20 skills in 6 files | Pre-run checks, monitoring, triage, analysis, maintenance, task authoring |
| **General Purpose** | 11 skills in 4 files | Session management, agent delegation, search patterns, dev practices |

Skills are plain markdown and tool-agnostic. See [`skills/README.md`](skills/README.md) for the full index and integration guides for Cursor, Claude Code, and other agents. See [`docs/SKILLS.md`](docs/SKILLS.md) for background on the skills system.

---

## License

See [LICENSE](LICENSE).

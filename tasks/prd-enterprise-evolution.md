# PRD: Enterprise Engineering Outcomes Evaluation System

## Introduction

Evolve CodeContextBench from a research-oriented agent performance benchmark into an enterprise-grade evaluation system that demonstrates operational, economic, and governance impact of context infrastructure in real software organizations. The benchmark must produce results directly usable by platform engineering leaders, VP Engineering / CTO stakeholders, and enterprise procurement / security teams.

The existing benchmark core (reproducibility, deterministic runs, multi-config comparison, task harness, validation pipeline) remains intact. All new work layers on top of this foundation.

## Goals

- Validate the enterprise report pipeline end-to-end (generate_enterprise_report.py + all 4 sub-reports)
- Implement the governance evaluator for post-hoc compliance checking of agent behavior
- Add new benchmark tasks that model genuine enterprise complexity (ambiguity, knowledge fragmentation, institutional memory loss)
- Expand governance task coverage with permission-scoped repos, role-based access, and policy enforcement
- Enhance the comparative framework to support 4-way baseline analysis
- Ensure the benchmark can definitively answer 5 key enterprise validation questions
- Produce audience-specific reports (technical, workflow, executive, failure dossier)

## User Stories

### US-001: Validate enterprise report pipeline end-to-end
**Description:** As a platform engineer, I want to run `generate_enterprise_report.py` against current runs and get valid output so that I can verify the reporting infrastructure works before adding new features.

**Acceptance Criteria:**
- [ ] `python3 scripts/generate_enterprise_report.py` runs without errors against `runs/official/`
- [ ] Produces `enterprise_report.json` with all 4 sections populated (workflow, economic, reliability, failure)
- [ ] Produces `ENTERPRISE_REPORT.md` with human-readable tables
- [ ] Produces `EXECUTIVE_SUMMARY.md` under 500 words
- [ ] Any bugs found during validation are fixed inline
- [ ] All 4 sub-scripts (`workflow_metrics.py`, `economic_analysis.py`, `reliability_analysis.py`, `failure_analysis.py`) produce non-None output

### US-002: Implement governance evaluator for compliance checking
**Description:** As a security reviewer, I want automated post-hoc analysis of agent traces to verify the agent respected permission boundaries so that I can certify governance compliance.

**Acceptance Criteria:**
- [ ] `scripts/governance_evaluator.py` exists and is importable by `generate_enterprise_report.py`
- [ ] Reads agent traces (`agent/claude-code.txt`) from governance run directories
- [ ] Checks file read/write operations against `permitted_paths` and `restricted_paths` from task.toml metadata
- [ ] Checks `writable_paths` constraints (read-only vs read-write boundaries)
- [ ] For `audit-trail-001`, validates audit log completeness (every file access logged)
- [ ] Produces per-task compliance score (0.0-1.0) and violation list
- [ ] Output includes: `{"compliance_score": float, "violations": [...], "files_accessed": [...], "boundary_respected": bool}`
- [ ] Integrates into `generate_enterprise_report.py` governance section (replaces placeholder)

### US-003: Add enterprise task — stale-architecture-001
**Description:** As a developer evaluator, I want a task where the agent encounters stale architecture documentation that contradicts the actual code so that I can test whether MCP helps agents navigate misleading institutional artifacts.

**Acceptance Criteria:**
- [ ] Task directory exists at `benchmarks/ccb_enterprise/stale-architecture-001/`
- [ ] `task.toml` has valid metadata (name, difficulty, time_limit_sec, language)
- [ ] `instruction.md` describes a realistic scenario: outdated architecture diagram references deprecated service names, agent must find the actual current implementation
- [ ] No implementation hints (file paths, method names, line numbers) in instruction.md
- [ ] `environment/Dockerfile` sets up workspace with stale docs + actual codebase
- [ ] `tests/test.sh` validates the correct fix (not the fix suggested by stale docs)
- [ ] Task registered in `configs/selected_benchmark_tasks.json`
- [ ] Task added to `configs/enterprise_2config.sh` task list

### US-004: Add enterprise task — knowledge-fragmentation-001
**Description:** As a developer evaluator, I want a task where critical information is spread across multiple files in non-obvious locations so that I can test whether MCP helps agents discover scattered context.

**Acceptance Criteria:**
- [ ] Task directory exists at `benchmarks/ccb_enterprise/knowledge-fragmentation-001/`
- [ ] `task.toml` has valid metadata
- [ ] `instruction.md` describes a realistic scenario: a feature request requires understanding conventions defined in 3+ separate files across different directories
- [ ] No implementation hints in instruction.md
- [ ] `environment/Dockerfile` sets up workspace with fragmented knowledge
- [ ] `tests/test.sh` validates correct implementation that incorporates all scattered requirements
- [ ] Task registered in `configs/selected_benchmark_tasks.json`
- [ ] Task added to `configs/enterprise_2config.sh`

### US-005: Add governance task — role-based-access-001
**Description:** As a security evaluator, I want a task with explicit role-based access constraints (read-only for some repos, read-write for others) so that I can test whether the agent respects role boundaries.

**Acceptance Criteria:**
- [ ] Task directory exists at `benchmarks/ccb_governance/role-based-access-001/`
- [ ] `task.toml` metadata includes `permitted_paths`, `restricted_paths`, `writable_paths`
- [ ] `instruction.md` describes a realistic scenario: agent is a "junior developer" with read access to core libraries but write access only to a feature module
- [ ] No implementation hints in instruction.md
- [ ] `environment/Dockerfile` sets up multi-module workspace
- [ ] `tests/test.sh` validates correct fix AND checks no writes outside `writable_paths`
- [ ] Task registered in `configs/selected_benchmark_tasks.json`
- [ ] Task added to `configs/governance_2config.sh`

### US-006: Add governance task — policy-enforcement-001
**Description:** As a compliance officer, I want a task where the agent must follow explicit coding policies (e.g., no direct database queries, must use ORM; no hardcoded secrets) so that I can verify policy compliance.

**Acceptance Criteria:**
- [ ] Task directory exists at `benchmarks/ccb_governance/policy-enforcement-001/`
- [ ] `task.toml` metadata includes policy rules
- [ ] `instruction.md` describes a realistic scenario with explicit policy constraints embedded in the task
- [ ] `tests/test.sh` validates both functional correctness AND policy compliance (e.g., grep for raw SQL, hardcoded credentials)
- [ ] Task registered in `configs/selected_benchmark_tasks.json`
- [ ] Task added to `configs/governance_2config.sh`

### US-007: Add enterprise task — institutional-memory-001
**Description:** As a developer evaluator, I want a task simulating institutional memory loss (key developer left, commit messages unhelpful, no onboarding docs) so that I can test whether MCP helps agents recover lost context.

**Acceptance Criteria:**
- [ ] Task directory exists at `benchmarks/ccb_enterprise/institutional-memory-001/`
- [ ] `task.toml` has valid metadata
- [ ] `instruction.md` describes a scenario where an incident occurs in code owned by a departed team member, with minimal documentation
- [ ] No implementation hints in instruction.md — agent must discover code structure through exploration
- [ ] `environment/Dockerfile` sets up workspace with sparse documentation
- [ ] `tests/test.sh` validates correct fix
- [ ] Task registered and added to config

### US-008: Enhance comparative analysis with 4-way baseline labels
**Description:** As a report reader, I want the comparison framework to explicitly label 4 baseline tiers (no-context, IDE-native search, Copilot-style, centralized context) so that results contextualize where each approach excels.

**Acceptance Criteria:**
- [ ] `scripts/compare_configs.py` accepts a `--baseline-labels` flag mapping config names to baseline tiers
- [ ] Default labels: `baseline` → "IDE-native navigation + search", `sourcegraph_full` → "Centralized context infrastructure"
- [ ] `ENTERPRISE_REPORT.md` comparative section uses human-readable tier names instead of config slugs
- [ ] `generate_enterprise_report.py` executive summary references baseline tier labels
- [ ] No breaking changes to existing compare_configs.py output format

### US-009: Add validation checklist script
**Description:** As a benchmark operator, I want a script that checks whether the benchmark can answer the 5 key enterprise validation questions so that I can verify completeness before presenting results.

**Acceptance Criteria:**
- [ ] `scripts/validate_enterprise_readiness.py` exists
- [ ] Checks Q1: "Does centralized context materially improve agent reliability?" → requires ≥2 configs with ≥20 tasks each
- [ ] Checks Q2: "Does it reduce engineering navigation time?" → requires workflow_metrics output with time deltas
- [ ] Checks Q3: "Does it enable AI under enterprise security constraints?" → requires ≥3 governance tasks with compliance scores
- [ ] Checks Q4: "Does it improve productivity relative to cost?" → requires economic_analysis output with ROI
- [ ] Checks Q5: "Is performance consistent across organizational complexity?" → requires reliability_analysis output with CI
- [ ] Outputs pass/fail per question with evidence references
- [ ] Exit code 0 only if all 5 questions are answerable

### US-010: Generate presentation-ready executive summary
**Description:** As a VP Engineering, I want the executive summary to include key headline metrics formatted for slide decks so that I can present benchmark results to leadership without reformatting.

**Acceptance Criteria:**
- [ ] `EXECUTIVE_SUMMARY.md` includes: headline metric, reliability improvement %, time savings estimate, cost efficiency, governance readiness statement
- [ ] Each metric has a one-sentence interpretation (not just numbers)
- [ ] Summary includes "Key Findings" section with 3-5 bullet points
- [ ] Summary includes "Limitations & Caveats" section
- [ ] Format is clean markdown that renders well in presentation tools (Marp, Slides.com)
- [ ] Total length under 500 words

## Functional Requirements

- FR-1: The governance evaluator must parse agent trace JSONL files (`claude-code.txt`) to extract file read/write operations
- FR-2: The governance evaluator must compare file operations against task.toml metadata constraints
- FR-3: New benchmark tasks must follow the existing Harbor task format (task.toml, instruction.md, environment/Dockerfile, tests/test.sh)
- FR-4: New task instructions must contain zero implementation hints (no file paths, method names, class names, line numbers)
- FR-5: All new tasks must be registered in `configs/selected_benchmark_tasks.json` with difficulty, language, MCP score fields
- FR-6: The enterprise report pipeline must produce valid output from current run data without manual intervention
- FR-7: The validation checklist must be deterministic and produce consistent pass/fail results
- FR-8: Report generation must not modify run data or MANIFEST

## Non-Goals

- Not implementing OS-level ACLs or sandboxing for governance (permission enforcement remains declarative)
- Not creating real Copilot or IDE comparison runs (framework labels only; actual comparison runs are a separate effort)
- Not building a web dashboard or visualization layer
- Not implementing real-time monitoring dashboards
- Not adding new agent implementations or model integrations
- Not modifying the Harbor task harness or verifier pipeline
- Not implementing longitudinal trend analysis or time-series forecasting

## Technical Considerations

- All scripts must use stdlib-only dependencies (matching existing convention) unless ccb_metrics package is used
- New tasks must use existing Harbor infrastructure (`--path` mode for local tasks)
- Governance evaluator should reuse trace parsing from `audit_traces.py` where possible
- Task registration requires both `selected_benchmark_tasks.json` AND the relevant `*_2config.sh` script
- The enterprise report schema (`enterprise_report_schema.json`) may need updates for governance section

## Success Metrics

- Enterprise report pipeline generates complete output from current run data (4/4 sections populated)
- Governance evaluator produces compliance scores for all 6+ governance tasks
- All 5 enterprise validation questions are answerable (validation script passes)
- New tasks have verifiers that pass on correct solutions and fail on incorrect ones
- Executive summary is under 500 words and includes all headline metrics

## Open Questions

- Should the governance evaluator run during Harbor verification (blocking) or as post-hoc analysis only?
- What real-world codebases should back the new enterprise tasks (django/django and flipt-io/flipt are used currently)?
- Should new governance tasks test MCP-specific compliance (e.g., "agent should not use Sourcegraph to read restricted repos")?
- What constitutes "materially improve" for validation Q1 — statistical significance (p<0.05) or effect size (Cohen's d>0.2)?

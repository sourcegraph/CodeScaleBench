# CodeScaleBench Engineering Diary: Building a Benchmark That Could Survive Production

CodeScaleBench did not start as a polished benchmark. It started as a messy build loop where every system layer failed at least once.

We had to build and stabilize all of this at the same time:
- task creation across SDLC and org-scale work
- deterministic verification across direct and artifact modes
- retrieval evaluation that explained agent behavior instead of hiding it
- curation pipelines that produced trustworthy ground truth
- run orchestration that worked across Harbor, Docker, and Daytona
- quality gates strict enough to keep `runs/official` analysis-safe

[Insert Figure 1: `fig01_workstream_timeline.svg`]
[Supporting table: `table01_milestone_ledger.md`]

## 1. The Experiment Design Came First

The first hard decision was experiment design, not prompts.

We locked the benchmark to **paired comparisons** with information parity.
- `baseline-local-direct`: full local repo access, no MCP
- `mcp-remote-direct`: truncated local source, Sourcegraph MCP required

For org-style discovery work we kept an artifact track as well.
- `baseline-local-artifact`
- `mcp-remote-artifact`

That direct vs artifact split was non-negotiable. Direct mode tested whether an agent can change code that compiles and passes tests. Artifact mode tested whether an agent can retrieve and assemble the right files, symbols, and dependency chains into a structured `answer.json`.

This prevented a common benchmarking mistake where retrieval skill and code editing skill get mixed into one noisy score.

Implementation anchors:
- `docs/technical_reports/TECHNICAL_REPORT.md` (Sections 1, 3, 7)
- `docs/REPORT_CONTEXT.md` (Section 3)
- `docs/ORG_TASKS.md` (Dual-mode verification)

## 2. We Reused IR-SDLC-Factory Work Instead of Rebuilding From Scratch

A lot of the retrieval and analysis core came from IR-SDLC-Factory, then got adapted to CodeScaleBench task formats and run artifacts.

Three modules show that lineage clearly.
- `scripts/csb_metrics/ground_truth.py`
  - Ported from `IR-SDLC-Factory/app/ir_sdlc/ground_truth_extraction.py`
  - Adapted to CodeScaleBench task layouts and a simpler file-path data model
  - Added structured `DefectAnnotation` and `TaskGroundTruth` for fix, review, and mixed tasks
- `scripts/csb_metrics/ir_metrics.py`
  - Ported retrieval metrics layer to stdlib-only utilities
  - Added task-trace parsing for ordered retrieval events and cost-aware TTFR metrics
- `scripts/csb_metrics/statistics.py`
  - Ported comparative analysis utilities for Welch tests, effect sizes, McNemar, and bootstrap flows

This gave us a faster path to a tested metrics base while still letting us reshape the data model for benchmark operations.

## 3. Task Creation Became a Factory, Not a Folder of One-Offs

Task generation and curation had to be repeatable.

The benchmark settled at 370 tasks.
- 150 SDLC tasks across 9 suites
- 220 CodeScaleBench-Org tasks across 11 suites

Org tasks were generated from a use-case registry and closed-world oracles. SDLC tasks combined original tasks with adapted patterns, then converged on CSB-specific verifiers.

Task selection was not random. We scored MCP-lift potential with a weighted formula over context complexity, cross-file dependencies, semantic search potential, and task category affinity.

Oracle quality was gated before task inclusion with the fail2pass check.
- gold oracle answer must score `1.0`
- empty answer must score `0.0`

Implementation anchors:
- `configs/use_case_registry.json`
- `scripts/generate_mcp_unique_tasks.py`
- `scripts/customize_mcp_skeletons.py`
- `docs/technical_reports/TECHNICAL_REPORT.md` (Section 5)

## 4. The Curator Agent Was Calibrated Against ContextBench, Not “Best Guess”

Ground truth quality was a bottleneck, so we built a custom curator agent and calibrated it on ContextBench human annotations.

The calibration stack:
- Dataset: `data/contextbench/verified.parquet`
- Harness: `scripts/validate_on_contextbench.py`
- Curator runtime: `scripts/context_retrieval_agent.py`
- Agreement checks: `scripts/cross_validate_oracles.py`
- Promotion step: `scripts/promote_agent_oracles.py`

Important implementation detail:
We replaced conflicting prompt variants with one unified curator system prompt and parameterized backend behavior. This reduced SDK vs CLI drift.

Output contract per task:
- `ground_truth_agent.json`
- `oracle_answer_agent.json` for org tasks
- `ground_truth_meta.json` with provenance, confidence, cost, and timing

Ground truth resolution then followed a priority chain, with `_agent` files as medium-confidence fallback when human-authored files were absent.

Implementation anchors:
- `docs/CONTEXT_RETRIEVAL_AGENT.md`
- `scripts/csb_metrics/ground_truth.py`

[Insert Figure 2: `fig02_architecture_evolution.svg`]
[Supporting table: `table04_architecture_evolution.md`]

## 5. Verifier Architecture Had to Be Deterministic and Layered

Every task writes a scalar reward to `/logs/verifier/reward.txt` from an in-container verifier.

For SDLC tasks we used task-specific `test.sh` patterns.
- checklist composites for build and feature work
- test-ratio scoring for fix tasks
- rubric scoring for fault localization
- hybrid F1 + fix-quality for review tasks

For Org tasks we standardized `eval.sh` + `oracle_checks.py` with deterministic checks.
- file-set F1
- symbol recall
- dependency-chain recall
- provenance and keyword checks
- schema and optional test-ratio checks

SG-only parity was handled with clone-at-verify.
- agent runs on truncated source in `Dockerfile.sg_only`
- `sgonly_verifier_wrapper.sh` restores full repo state at verification time
- same verifier logic runs after overlaying agent edits

Implementation anchors:
- `scripts/csb_metrics/oracle_checks.py`
- `scripts/answer_json_verifier_lib.sh`
- `scripts/artifact_verifier_lib.sh`
- `docs/technical_reports/TECHNICAL_REPORT.md` (Section 7)

## 6. We Added LLM-as-Judge as a Secondary Lens, Not a Score Override

Deterministic verifier reward stayed primary. The LLM judge is post-hoc analysis.

Pipeline:
- entrypoint: `scripts/run_judge.py`
- core engine: `scripts/csb_metrics/judge/engine.py`
- oracle discovery: `scripts/csb_metrics/judge/oracle.py`

Judge dimensions and weights:
- correctness 0.30
- completeness 0.25
- code_quality 0.20
- retrieval_quality 0.15
- efficiency 0.10

Two operating modes mattered in practice.
- ensemble mode: multi-round majority voting per dimension
- hybrid mode: rubric criteria from `tests/criteria.json`, with `hybrid_composite = verifier_weight * verifier_reward + (1 - verifier_weight) * rubric_score` (default verifier weight 0.6)

Result artifacts are written per task as `judge_result.json`.

## 7. QA Became a Multi-Gate Pipeline

We stopped treating QA as a final step and made it part of the execution loop.

Operational gate chain:
- preflight static and runtime smoke: `scripts/validate_tasks_preflight.py`
- infrastructure readiness: `scripts/check_infra.py`
- post-run task validation: `scripts/validate_task_run.py`
- run-wide status + fingerprints: `scripts/aggregate_status.py`, `scripts/status_fingerprints.py`
- metadata drift checks: `scripts/sync_task_metadata.py`
- repo-level health gate before merge/push: `scripts/repo_health.py`

The audit layer had two tracks.
- 6-dimension operational QA framework
- ABC audit framework with 32 criteria and grading across Task Validity, Outcome Validity, and Reporting

ABC implementation details:
- criteria model: `scripts/abc_criteria.py`
- auditor: `scripts/abc_audit.py`
- grading rule highlights: critical failures force D/F outcomes

Implementation anchors:
- `docs/ops/QA_PROCESS.md`
- `docs/REPO_HEALTH.md`
- `docs/technical_reports/TECHNICAL_REPORT.md` (Appendix E)

## 8. Promotion to Official Runs Had Explicit Integrity Requirements

We built promotion as a controlled operation, not a directory move.

Promotion flow:
- staging validation and gates: `scripts/promote_run.py`
- official integrity validation: `scripts/validate_official_integrity.py` and `scripts/official_integrity.py`

Promotion gates include:
- no critical validation issues
- no missing `result.json` in run tasks
- warning count under threshold (default 10) unless forced
- `task_metrics.json` coverage generation before move

After move:
- regenerate manifest
- refresh official results export
- re-validate official integrity

Official integrity checks include:
- triage include or exclude consistency
- stale or unmanaged run detection
- manifest freshness against tracked run mtimes
- optional MCP trace health checks for failed MCP tasks with zero MCP calls

This is what kept `runs/official` usable for analysis and publication.

## 9. Harness and Infra Work Was Half the Project

A benchmark is only as good as its execution reliability.

What we actually shipped:
- Harbor as the orchestration and artifact contract layer
- Daytona as default high-parallel remote execution for production-scale runs
- local Docker fallback for incompatible task images
- multi-account OAuth refresh logic and rate-limit preflight

For cross-agent evaluation we also built multi-harness scaffolding.
- `configs/multi_harness_compare.sh` for Codex, Cursor, Gemini, Copilot, OpenHands
- `scripts/check_harness_readiness.py` for registry and credential gating

Implementation anchors:
- `docs/DAYTONA.md`
- `scripts/daytona_runner.py`
- `scripts/check_harness_readiness.py`
- `configs/multi_harness_compare.sh`

[Insert Figure 4: `fig04_issue_resolution_timeline.svg`]
[Insert Figure 5: `fig05_issue_cluster_heatmap.svg`]
[Supporting table: `table03_issue_resolution_playbook.md`]

## 10. Retrieval, Cost, Timing, and DOE Were Built as Analysis Systems

### Retrieval evaluation pipeline

We formalized retrieval analysis into a five-stage pipeline.
1. normalize retrieval events
2. file-level IR metrics
3. chunk-level relevance
4. utilization probes plus error taxonomy
5. artifact emission and run summaries

Core scripts:
- `scripts/normalize_retrieval_events.py`
- `scripts/retrieval_eval_pipeline.py`
- `scripts/retrieval_impact_analysis.py`

Key policy choice:
Retrieval metrics are standalone and non-ranking in v1. They diagnose behavior without rewriting primary reward semantics.

From the March 3, 2026 technical report run set, curated-ground-truth retrieval moved from:
- `P@10`: `0.095 -> 0.313`
- `R@10`: `0.120 -> 0.272`
- `F1@10`: `0.091 -> 0.240`

### Cost and timing analysis

Canonical cost analysis from official raw runs used normalized task IDs and valid-pair filters.

Core scripts:
- `scripts/analyze_paired_cost_official_raw.py`
- `scripts/cost_report.py`
- `scripts/mcp_cost_analysis.py`

Pairing and validity rules:
- pair by model and normalized task id
- require both arms present
- filter out zero-output runs and near-zero agent execution runs

Canonical haiku paired result from `docs/analysis/mcp_cost_pairs_official_raw_20260304.json`:
- baseline: `$0.7333/task`
- MCP: `$0.5121/task`
- delta: `-30.16%`

Timing deltas in the same paired set:
- mean wall clock: `-36.22s`
- mean agent execution: `-101.06s`

### DOE and Neyman balancing

Uniform suite sizes left power on the table. We moved to DOE-driven allocation.

Variance decomposition:
- `sigma2_task` for between-task heterogeneity
- `sigma2_rep` for within-task replicate noise
- ICC for signal partitioning

Allocation and selection scripts:
- `scripts/doe_variance_analysis.py`
- `scripts/doe_select_tasks.py`
- `scripts/doe_power_curves.py`

Power model used in `doe_variance_analysis.py`:
- `n >= 2 * (sigma2_task + sigma2_rep / n_reps) * (z_alpha/2 + z_beta)^2 / delta^2`
- defaults were `alpha=0.05`, `power=0.80`, with `z_alpha/2=1.96` and `z_beta=0.842`

Selection logic in practice:
- compute per-task information value from effect magnitude, variance, and non-ceiling behavior:
  `info_value = 0.5*delta_norm + 0.3*var_norm + 0.2*ceiling_bonus`
- keep, move, promote-from-backup, or scaffold based on suite targets

Neyman balancing then resized SDLC suites instead of keeping uniform `n=20`.
- grow high-variance suites like `csb_sdlc_fix`, `csb_sdlc_test`, `csb_sdlc_feature`
- shrink low-information suites like `csb_sdlc_understand` and `csb_sdlc_secure`

This turned task budgeting into a measurable design choice instead of a fixed round number.

[Insert Figure 3: `fig03_decision_theme_mix.svg`]
[Supporting table: `table02_decisions_tradeoffs.md`]

## 11. What Was Reusable

The reusable output is not just tasks.

It is an operating model for benchmark engineering:
- controlled paired-run design with information parity
- dual verifier modes for code-change and discovery work
- curator calibration loop with explicit promotion policy
- deterministic scoring plus optional judge layer
- retrieval pipeline that explains failures without contaminating ranking
- promotion and official-integrity gates that protect analysis quality
- DOE-driven allocation to keep statistical power under budget constraints

[Insert Figure 6: `fig06_reusable_components.svg`]
[Insert Figure 7: `fig07_commit_signal.svg`]
[Supporting table: `table05_reusable_components.md`]

## 12. The Practical Lesson

If you are building your own coding-agent benchmark, build it like production infra from the start.

Do not wait to add:
- task preflight and runtime smoke
- verifier quality audits
- retrieval diagnostics
- promotion and integrity gates
- budget-aware DOE planning

Those are not polish tasks. They are what make results believable.

## Asset Placement

Use `tables/table06_post_asset_placement.md` for exact placement in this post.
Use `tables/table07_execution_checklist.md` for reproducible regeneration steps.

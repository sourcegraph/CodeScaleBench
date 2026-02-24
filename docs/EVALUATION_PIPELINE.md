# Unified Evaluation Pipeline

CodeContextBench uses a multi-layer evaluation pipeline: deterministic verifiers
run first (every task), then an optional LLM judge adds qualitative scoring,
and statistical modules provide confidence intervals and correlation analysis.

This document covers the pipeline architecture. For per-benchmark scoring
details, see [SCORING_SEMANTICS.md](SCORING_SEMANTICS.md). For MCP-unique
oracle checks, see [MCP_UNIQUE_TASKS.md](MCP_UNIQUE_TASKS.md). For the full
retrieval/IR evaluation pipeline (normalized retrieval events, file/chunk IR
metrics, utilization probes, taxonomy, and emitted artifacts), see
[RETRIEVAL_EVAL_SPEC.md](RETRIEVAL_EVAL_SPEC.md).

---

## Pipeline Layers

```
Harbor run output (result.json, transcript)
        │
        ▼
┌──────────────────────────────┐
│  Layer 1: Deterministic      │  Always runs. Exit-code + reward.txt.
│  Verifier (test.sh / eval.sh)│  Per-task, in-container.
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Layer 2: LLM Judge          │  Optional. Multi-round voting, 5 dimensions.
│  (scripts/run_judge.py)      │  Post-run, host-side. Needs API key.
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Layer 3: Statistical        │  Bootstrap CIs, paired delta tests,
│  Analysis                    │  Spearman correlation, retrieval metrics.
│  (scripts/ccb_metrics/)      │  Post-run, deterministic.
└──────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│  Layer 4: Report Generator   │  Aggregates all layers into REPORT.md
│  (generate_eval_report.py)   │  and eval_report.json.
└──────────────────────────────┘
```

---

## Layer 1: Deterministic Verifiers

Every task ships a `tests/test.sh` (SDLC tasks) or `tests/eval.sh` (MCP-unique
tasks) that runs inside the Docker container after the agent finishes. The
verifier writes a reward (0.0–1.0) to `/logs/verifier/reward.txt` and exits 0
on success, non-zero on failure.

Verifier types are documented in [SCORING_SEMANTICS.md](SCORING_SEMANTICS.md).

### Verifier Debug Mode

Set `DEBUG_MODE=true` to capture full diagnostics before verification runs:

```bash
DEBUG_MODE=true ./configs/fix_2config.sh --task my-task-001
```

Debug output goes to `/logs/verifier/debug/`:
- `environment.txt` — filtered env (secrets redacted)
- `workspace_git_status.txt` / `workspace_git_diff.txt`
- `workspace_file_tree.txt`

### Verifier Self-Tests (Fixtures)

Tasks can include `tests/fixtures/` directories with known-score inputs to
validate that the verifier itself is correct:

```
tests/fixtures/
├── metadata.json           # Expected score ranges + verifier type
├── perfect_input/          # Golden input → expected score ≥ 0.9
└── empty_input/            # Empty input → expected score ≤ 0.05
```

Run fixture self-tests:

```bash
python3 scripts/validate_tasks_preflight.py --fixture-tests
python3 scripts/validate_tasks_preflight.py --smoke-runtime   # includes fixtures + idempotency
```

Idempotency checks run the verifier twice on the same input and assert scores
match within epsilon (0.001). Non-idempotent verifiers are logged as warnings.

---

## Layer 2: LLM Judge

The judge system provides qualitative scoring across five dimensions, using
multi-round voting for reliability. It runs post-hoc on completed runs — it
does not affect the deterministic verifier score.

### Components

| Module | Path | Purpose |
|--------|------|---------|
| Data models | `scripts/ccb_metrics/judge/models.py` | `JudgeInput`, `JudgeResult`, `OracleBundle` dataclasses |
| Prompt templates | `scripts/ccb_metrics/judge/prompts.py` | Reference correctness, completeness, and direct review prompts |
| API backend | `scripts/ccb_metrics/judge/backends.py` | Anthropic API wrapper with exponential backoff (3 retries) |
| Engine | `scripts/ccb_metrics/judge/engine.py` | Core `LLMJudge` class: prompt selection, dimension scoring, multi-round voting |
| Agreement metrics | `scripts/ccb_metrics/judge/agreement.py` | Cohen's kappa, Fleiss' kappa, Landis-Koch interpretation |
| Oracle discovery | `scripts/ccb_metrics/judge/oracle.py` | Auto-loads ground truth from task data (6-source priority chain) |

### Scoring Dimensions

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Correctness | 0.30 | Does the output match ground truth? |
| Completeness | 0.25 | Are all required elements present? |
| Code quality | 0.20 | Is the code well-structured and idiomatic? |
| Retrieval quality | 0.15 | Did the agent find the right context? |
| Efficiency | 0.10 | Was the approach reasonably efficient? |

The judge score is a weighted average of dimension scores. Each dimension is
scored on a 3-point scale: 1.0 (pass), 0.5 (partial), 0.0 (fail).

### Oracle Auto-Discovery

The judge auto-loads ground truth via a 6-source priority chain:

1. `tests/ground_truth.json` — structured ground truth (high confidence)
2. `tests/expected_defects.json` — code review defect lists (high confidence)
3. `tests/expected_changes.json` — expected file changes (high confidence)
4. `solution/solve.sh` — patch extraction (medium confidence)
5. `instruction.md` — keyword extraction (medium confidence)
6. `configs/ground_truth_files.json` — fallback registry (low confidence)

Confidence level flows into the judge result for downstream filtering.

### Running the Judge

```bash
# Score all tasks in a run
python3 scripts/run_judge.py --run runs/official/my_run/

# Score a specific suite with 3-round voting
python3 scripts/run_judge.py --run runs/official/my_run/ --suite ccb_fix --ensemble

# Dry run — show tasks and oracle confidence without calling API
python3 scripts/run_judge.py --run runs/official/my_run/ --dry-run

# Force re-score tasks that already have judge results
python3 scripts/run_judge.py --run runs/official/my_run/ --force
```

Output: `judge_result.json` written alongside each task's `result.json`.

### Hybrid Scoring (MCP-Unique Tasks)

MCP-unique tasks with `tests/criteria.json` support hybrid evaluation:
`composite = 0.6 * verifier_reward + 0.4 * rubric_score`. Enable with
`--hybrid` flag on `run_judge.py`.

---

## Layer 3: Statistical Analysis

### Bootstrap Confidence Intervals

```python
from ccb_metrics.statistics import bootstrap_ci, paired_bootstrap_delta

# Single-sample CI
mean, ci_lower, ci_upper = bootstrap_ci(scores, n_bootstrap=1000, ci=0.95)

# Paired config comparison (baseline vs MCP-Full)
delta, ci_lower, ci_upper, p_value = paired_bootstrap_delta(
    baseline_scores, mcp_scores, n_bootstrap=1000, ci=0.95
)
```

All functions are stdlib-only (uses `random.choices`) with `random.seed(42)` for
reproducibility.

### Retrieval-Outcome Correlation

Spearman rank correlation between IR metrics and task rewards, stratified by
suite:

```bash
python3 scripts/ir_analysis.py --correlate --min-confidence medium
```

### Defect Annotation Model

Code review tasks in `ccb_test` support structured defect annotations in
`expected_defects.json`:

```json
{
  "defects": [{
    "description": "Null pointer dereference on empty input",
    "defect_type": "null-deref",
    "line_start": 42,
    "line_end": 45
  }]
}
```

Supported types: `null-deref`, `resource-leak`, `race-condition`, `injection`,
`logic-error`, `buffer-overflow`, `use-after-free`, `other`.

---

## Layer 4: Dual-Score Reporting

When judge results are available, the evaluation report and MANIFEST include
both scores:

### MANIFEST Fields

Each task entry gains optional fields:
- `judge_score` (float) — weighted judge score
- `judge_model` (string) — model used for judging
- `judge_dimensions` (dict) — per-dimension scores
- `judge_confidence` (float) — multi-round voting confidence

Tasks without judge data have these fields set to `null`.

### Report Tables

The eval report conditionally adds judge columns:

```
task_id          | verifier_reward | judge_score | delta  | oracle_confidence
-----------------+-----------------+-------------+--------+------------------
ccx-dep-trace-001|            0.85 |        0.90 |  +0.05 | high
my-fix-task-002  |            1.00 |        0.75 |  -0.25 | medium [DIVERGENT]
```

Tasks where `abs(verifier_reward - judge_score) > 0.3` are flagged `[DIVERGENT]`
for manual review.

---

## Generating Reports

```bash
# Full evaluation report (includes judge data if available)
python3 scripts/generate_eval_report.py \
  --runs-dir runs/official/ \
  --output-dir ./eval_reports/

# Generate LLM judge context files for manual review
python3 -m scripts.ccb_metrics.judge_context \
  --runs-dir runs/official/ \
  --benchmarks-dir ./benchmarks/ \
  --output-dir ./judge_contexts/
```

Output:
- `eval_report.json` — full structured report
- `REPORT.md` — markdown tables (performance, efficiency, tool utilization, judge correlation)
- `harness_configs.json` — exact harness configuration per run
- CSV files per table for downstream analysis

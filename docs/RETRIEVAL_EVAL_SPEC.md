# Retrieval Evaluation Specification

> **Status**: v1 — standalone, non-ranking.
> This framework evaluates retrieval quality and its downstream impact on task
> outcomes without changing primary CCB scoring or leaderboard semantics.

## Purpose

Measure three aspects of agent retrieval behavior:

1. **Retrieval quality** — did the agent find the right files/symbols?
2. **Utilization quality** — did the agent use retrieved evidence correctly?
3. **Downstream impact** — how do retrieval metrics correlate with task
   outcomes, cost, and time?

## Schema Overview

The normalized retrieval event schema
(`schemas/retrieval_events_schema.json`, version 1.0) defines a single
JSON document per task-config pair containing:

| Section | Purpose |
|---------|---------|
| `provenance` | Run/task/config identification |
| `coverage` | Trace and ground-truth availability flags |
| `ground_truth` | Expected files, optional symbols and chunks |
| `events` | Ordered step-level retrieval events |
| `summary` | Pre-computed aggregate counts (optional) |

## Field Semantics

### Provenance

Uniquely identifies the task execution:

- `run_id` — staging or official run directory name.
- `batch_timestamp` — batch subdirectory within the run.
- `task_name` — canonical task identifier (matches `task.toml` name).
- `config_name` — full config label (e.g. `baseline-local-direct`,
  `mcp-remote-direct`).
- `benchmark` — suite name (e.g. `ccb_fix`, `ccb_mcp_crossorg`).

### Coverage Flags

Every document reports trace availability explicitly so downstream stages
can filter or flag results:

- `has_trajectory` — `agent/trajectory.json` was found and parseable.
- `has_transcript` — `agent/claude-code.txt` (JSONL) was found and parseable.
- `has_ground_truth` — file-level expected files exist for the task.
- `has_chunk_ground_truth` — line-range annotations exist (e.g. defect
  locations in code-review tasks).
- `trace_source` — which source produced the events:
  - `trajectory` — events from `trajectory.json` only.
  - `transcript` — events from `claude-code.txt` only.
  - `merged` — events from both sources combined (trajectory preferred for
    tool calls, transcript for timestamps or subagent recovery).
  - `null` — degraded mode (no usable trace).
- `degraded_reason` — human-readable explanation when events are empty or
  incomplete.

### Ground Truth

Ground truth is loaded from the task definition directory using the existing
priority chain in `ccb_metrics/ground_truth.py`:

1. `tests/ground_truth.json` (high confidence)
2. `tests/expected_defects.json` (high confidence)
3. `tests/expected_changes.json` (high confidence)
4. `tests/reference_fix.patch` / `tests/expected.diff` (high confidence)
5. `solution/solve.sh` gold patch (medium confidence)
6. `instruction.md` / `tests/test.sh` regex extraction (medium/low confidence)

Three levels of ground truth are supported:

- **File-level** (`ground_truth.files`) — always populated when ground truth
  exists. Repo-relative paths.
- **Symbol-level** (`ground_truth.symbols`) — optional. Function/class names
  within ground-truth files, loaded from `task_spec.json` oracle items.
- **Chunk-level** (`ground_truth.chunks`) — optional. Line ranges within files,
  loaded from `expected_defects.json` annotations or similar.

When `coverage.has_ground_truth` is false, `ground_truth.files` is an empty
array and all IR metrics are marked as non-computable.

### Retrieval Events

Each event represents one retrieval-related tool call by the agent:

- `step_index` — zero-based position in the trace. Preserves execution order.
- `tool_name` — raw name from the trace (e.g. `Read`,
  `mcp__sourcegraph__sg_keyword_search`).
- `tool_category` — normalized category for cross-config comparison:

| Category | Local tools | MCP tools |
|----------|-------------|-----------|
| `file_read` | Read | read_file |
| `file_search` | Glob, Grep | list_files |
| `symbol_navigation` | — | find_references, go_to_definition |
| `code_search` | Grep (pattern) | keyword_search, nls_search |
| `commit_search` | — | commit_search, diff_search, compare_revisions |
| `deep_search` | — | deepsearch, deepsearch_read |
| `file_write` | Write, Edit | — |
| `other` | Bash, Task | get_contributor_repos, list_repos |

- `is_mcp` — true for any `mcp__sourcegraph__*` tool call.
- `target_files` — normalized file paths accessed or returned. Normalization
  strips `/workspace/`, `/repo_full/`, `/testbed/`, and diff `a/`/`b/` prefixes;
  paths are lowercased for matching.
- `hits_ground_truth` — true if any `target_file` matches a ground-truth file.
- `cumulative_tokens` — running token total up to this step (when available).
- `elapsed_seconds` — wall-clock time from agent execution start.

### Event Summary

Optional pre-computed counts to avoid re-scanning the events array:

- `total_events`, `mcp_events`, `local_events`
- `unique_files_accessed`, `ground_truth_files_hit`
- `first_ground_truth_hit_step`
- `events_by_category` (keyed by `tool_category`)

## Degraded Mode Behavior

The pipeline handles incomplete data gracefully:

| Condition | Behavior |
|-----------|----------|
| No trajectory AND no transcript | `events` is empty, `coverage.trace_source` is null, `coverage.degraded_reason` explains |
| Trajectory only (no transcript) | Events extracted from trajectory; timestamps may be absent for some steps |
| Transcript only (no trajectory) | Events extracted from transcript; subagent tool calls may be missed |
| No ground truth | `ground_truth.files` is empty; `hits_ground_truth` is false for all events; IR metrics non-computable |
| No chunk ground truth | `ground_truth.chunks` absent; chunk-level metrics emit `resolution: "file_level_only"` flag |

Downstream metric stages MUST check `coverage` flags before computing metrics
and propagate appropriate `non_computable` markers rather than emitting
misleading zeroes.

## Schema Versioning

- The `schema_version` field is a semver-style string (currently `"1.0"`).
- **Minor bumps** (1.1, 1.2, ...) add optional fields. Consumers of 1.0 data
  continue to work unchanged.
- **Major bumps** (2.0) change required fields or remove/rename existing ones.
  Consumers must update.
- The normalization CLI embeds the schema version it was built against.
  Metric stages validate `schema_version` on load and reject unknown major
  versions.

## Output Paths

Normalized retrieval event files are written to a parallel directory structure
that does not overwrite existing run artifacts:

```
runs/{staging|official}/{run_id}/retrieval_events/
  {config_name}/
    {task_name}.retrieval_events.json
```

Run-level aggregates are written alongside:

```
runs/{staging|official}/{run_id}/retrieval_events/
  run_retrieval_summary.json
```

## Pipeline Stages

The full evaluation pipeline (`scripts/retrieval_eval_pipeline.py`) runs five
stages on each normalized event document:

### Stage 1: File-Level IR Metrics

Standard information retrieval metrics computed from the ordered list of
retrieved files against ground-truth files:

- **Precision@K, Recall@K, F1@K** (K = 1, 3, 5, 10)
- **MRR** (Mean Reciprocal Rank)
- **nDCG@K** (normalized Discounted Cumulative Gain)
- **MAP** (Mean Average Precision)
- **File-level recall** (fraction of GT files found anywhere in retrieved list)
- **Context efficiency** (fraction of retrieved files that are relevant)
- **TTFR** (time-to-first-relevant file, in seconds and tokens)

Tasks without ground truth are marked `computable: false`.

### Stage 2: Chunk-Level Relevance Metrics

When chunk-level ground truth (line-range annotations) is available:

- **Chunk recall** = fraction of GT chunks whose file was accessed by the agent.
- **Resolution** field: `"chunk_level"` or `"file_level_only"`.
- **Validity** field: `"file_match_only"` (v1 granularity) or `"unsupported"`.

**Chunking assumption**: In v1, a retrieval event "covers" a ground-truth
chunk if any `target_file` matches the chunk's file path. Sub-line matching
(e.g. exact line range overlap) requires structured diff data and is deferred
to future schema versions.

### Stage 3: Utilization Probe Metrics

Measures whether retrieved evidence was actually *used* by the agent:

- **`util_referenced_file_correctness`** = |files_written ∩ GT| / |GT|.
  Measures whether the agent wrote to the correct files after retrieval.
- **`util_read_before_write_ratio`** = fraction of written files that were
  read by the agent before being written to. High values indicate deliberate
  evidence consumption.

**Coverage**: `probe_available: false` when the agent performed no file writes
or when no ground truth exists. The probe requires write events to measure
utilization — read-only tasks produce no utilization signal.

**Limitations**: These probes measure file-level correctness only. They do
not validate whether the *content* written was semantically correct (that is
the verifier's job). Future probes may add symbol-level or API-level checks.

### Stage 4: Error Taxonomy and Calibration Slices

Five taxonomy labels classify retrieval error modes per-task:

| Label | Definition |
|-------|-----------|
| `irrelevant_retrieval` | Files retrieved that are not in ground truth |
| `missed_key_evidence` | Ground truth files never retrieved |
| `wrong_evidence_used` | Non-GT files the agent wrote to |
| `unused_correct_retrieval` | GT files retrieved but never written to |
| `ambiguity_near_miss` | Retrieved files in the same directory as a GT file |

Two calibration slice dimensions:

- **Candidate set size**: `small` (≤5 files), `medium` (6–20), `large` (>20)
- **Evidence type**: `local` (no MCP tools used) or `mcp` (at least one MCP call)

### Stage 5: Artifact Emission

Per-task artifacts (`{task_name}.retrieval_metrics.json`) contain all four
metric stages plus provenance and coverage metadata. Run-level summaries
(`run_retrieval_summary.json`) contain aggregated statistics across all
computable tasks.

## Relationship to Existing Pipeline

This evaluation is **standalone and non-ranking** in v1:

- Does not modify `result.json`, `task_metrics.json`, or `MANIFEST.json`.
- Does not affect verifier rewards or leaderboard scoring.
- Consumes the same run artifacts as `ir_analysis.py` and `mcp_audit.py`.
- Future versions may feed retrieval metrics into `generate_eval_report.py`
  as an optional supplementary section.

## v1 Rollout Boundaries

### What v1 Does

- Normalizes agent traces into step-level retrieval events.
- Computes file-level IR metrics, chunk-level metrics (with fallback),
  utilization probes, and error taxonomy.
- Correlates retrieval metrics with task outcomes (association only).
- Generates matched task comparisons between baseline and MCP configs.
- Produces standalone human-readable reports.

### What v1 Does NOT Do

- Does not change verifier rewards, leaderboard scoring, or MANIFEST.json.
- Does not block or gate benchmark runs on retrieval quality.
- Does not modify existing evaluation pipeline outputs.
- Does not claim causal relationships between retrieval and outcomes.

### Comparability Requirements

Matched task comparisons require:

- **Same task** executed in both baseline and MCP configs.
- **Same model** and harness version across paired configs.
- **Result.json present** with valid reward for both configs.
- **At least 3 matched tasks** for aggregate statistics.

Unmatched tasks (present in one config but not the other) are excluded from
matched comparisons but included in per-config aggregates.

### Coverage Caveats

- Tasks without file-level ground truth (MCP-unique discovery tasks,
  write-only tasks) are excluded from IR metrics.
- Tasks in degraded mode (no trajectory or transcript) emit empty events
  and are flagged in coverage metadata.
- Chunk-level metrics operate at file-match granularity in v1.

## Future Integration Points

The following touchpoints exist for optional future integration. **None of
these should be implemented without explicit policy discussion.**

### `docs/EVALUATION_PIPELINE.md`

- **Optional Layer 5**: Add retrieval evaluation as an optional post-run
  analysis layer alongside the existing 4-layer pipeline.
- Retrieval metrics could appear as supplementary columns in the eval report
  tables without affecting the primary scoring dimensions.

### `docs/SCORING_SEMANTICS.md`

- **Retrieval-aware composite scores**: A future version could define a
  weighted composite that includes retrieval quality alongside verifier
  reward. This would require consensus on weight calibration and must not
  change existing per-task reward semantics.
- **Confidence gating**: Tasks with low retrieval coverage could receive
  confidence flags that downstream consumers use for filtering but not
  score modification.

### `docs/MCP_UNIQUE_TASKS.md` / `docs/MCP_UNIQUE_CALIBRATION.md`

- **Oracle coverage integration**: MCP-unique task oracle items could be
  mapped to retrieval events for oracle-aware retrieval scoring.
- **Deep Search effectiveness**: The `deep_search` tool category enables
  future analysis of Deep Search ROI versus keyword/NLS search.

### `docs/LEADERBOARD.md`

- **Retrieval-conditioned rankings**: Future leaderboard views could show
  rankings conditioned on retrieval quality tiers (e.g. "among tasks where
  the agent retrieved ≥50% of ground truth files"). This would be
  supplementary, not replacing the primary ranking.

### `scripts/generate_eval_report.py`

- **Supplementary tables**: A future version of the report generator could
  optionally include retrieval quality tables and correlation summaries
  from the retrieval pipeline output.

## See Also

- `schemas/retrieval_events_schema.json` — JSON Schema definition
- `docs/EVALUATION_PIPELINE.md` — primary evaluation pipeline
- `docs/SCORING_SEMANTICS.md` — reward interpretation
- `docs/MCP_UNIQUE_TASKS.md` — MCP-unique task system

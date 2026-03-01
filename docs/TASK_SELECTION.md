# Task Selection Methodology

## Overview

The benchmark uses **180 tasks** across **9 SDLC-phase suites** (plus 220 MCP-unique tasks across 11 suites = **400 total**). The canonical task list is in `configs/selected_benchmark_tasks.json` (version 2.0, last updated 2026-03-01). Tasks were selected and reorganized from legacy suites via the SDLC migration. The original `ccb_build` suite was split into `ccb_feature` (feature implementation) and `ccb_refactor` (cross-file refactoring) for finer-grained capability analysis. See `docs/TASK_CATALOG.md` for the per-task reference.

## SDLC Suite Coverage

| Suite | SDLC Phase | Tasks |
|-------|------------|------:|
| ccb_understand | Requirements & Discovery | 20 |
| ccb_design | Architecture & Design | 20 |
| ccb_fix | Bug Repair | 20 |
| ccb_feature | Feature Implementation | 20 |
| ccb_refactor | Cross-File Refactoring | 20 |
| ccb_test | Testing & QA | 20 |
| ccb_document | Documentation | 20 |
| ccb_secure | Security & Compliance | 20 |
| ccb_debug | Debugging & Investigation | 20 |
| **Total** | | **180** |

## MCP Benefit Scoring

Each task receives an MCP benefit score in [0.0, 1.0] computed as:

```
score = 0.25 * context_complexity
      + 0.30 * cross_file_deps
      + 0.20 * semantic_search_potential
      + 0.25 * task_category_weight
```

### Component Definitions

- **context_complexity**: Derived from codebase token count or benchmark-level proxy. Normalized: 1M+ tokens = 1.0
- **cross_file_deps**: From `files_count`, `solution_files_changed`, or parsed from instruction.md. Normalized: 20+ files = 1.0
- **semantic_search_potential**: High for large-repo tasks, find-in-codebase tasks, and tasks with large context
- **task_category_weight**: Per-category MCP affinity (architectural_understanding=1.0, cross_file_refactoring=0.9, etc.)

Scoring is used for monitoring and curation; it does not gate inclusion. Suite-level MCP usage is reported and reviewed.

## Difficulty Rescoring Formula

Difficulty labels are now recomputed deterministically from task metadata in
`configs/selected_benchmark_tasks.json` using `scripts/rescore_difficulty.py`.

### Score Definition

```
difficulty_score =
    0.40 * size_score
  + 0.35 * complexity_score
  + 0.25 * ground_truth_depth_score
```

Where:
- `size_score` is derived from `context_length` and `files_count` bucketed norms
- `complexity_score` is derived from cross-file dependency and semantic-reasoning
  proxies (`mcp_breakdown` where available), with category fallback heuristics
- `ground_truth_depth_score` is derived from verifier `reward_type` plus
  ground-truth artifact richness (`tests/ground_truth.json`, `tests/criteria.json`,
  `oracle_answer.json`)

### Label Thresholds

- `expert`: score >= 0.86
- `hard`: score >= 0.62 and < 0.86
- `medium`: score < 0.62

Override:
- `ccb_debug` tasks with `task_id` prefixed by `linux-` are forced to `expert`
  (kernel fault-localization set).

## Source of Truth

- **Task list:** `configs/selected_benchmark_tasks.json`
- **Per-task catalog:** `docs/TASK_CATALOG.md`
- **Archived suites:** Retired or pre-migration suites remain under `benchmarks/archive/` for reproducibility.

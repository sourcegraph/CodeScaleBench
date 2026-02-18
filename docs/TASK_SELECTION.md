# Task Selection Methodology

## Overview

The benchmark uses **157 tasks** across **8 SDLC-phase suites**. The canonical task list is in `configs/selected_benchmark_tasks.json` (version 2.0). Tasks were selected and reorganized from legacy suites via the SDLC migration; see `docs/PRD_SDLC_SUITE_REORGANIZATION.md` for the reorganization rationale and `docs/TASK_CATALOG.md` for the full per-task reference.

## SDLC Suite Coverage

| Suite | SDLC Phase | Tasks |
|-------|------------|------:|
| ccb_understand | Requirements & Discovery | 20 |
| ccb_design | Architecture & Design | 20 |
| ccb_fix | Bug Repair | 25 |
| ccb_build | Feature & Refactoring | 25 |
| ccb_test | Testing & QA | 14 |
| ccb_document | Documentation | 13 |
| ccb_secure | Security & Compliance | 20 |
| ccb_debug | Debugging & Investigation | 20 |
| **Total** | | **157** |

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

## Source of Truth

- **Task list:** `configs/selected_benchmark_tasks.json`
- **Per-task catalog:** `docs/TASK_CATALOG.md`
- **Archived suites:** Retired or pre-migration suites remain under `benchmarks/archive/` for reproducibility.

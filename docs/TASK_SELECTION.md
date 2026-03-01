# Task Selection Methodology

## Overview

Selected **0 tasks** from 0 available across 7 benchmarks, stratified by SDLC phase with MCP benefit scoring.

## SDLC Phase Coverage

| SDLC Phase | Tasks | Benchmarks |
|------------|-------|------------|
| Requirements & Discovery | 0 |  |
| Architecture & Design | 0 |  |
| Implementation (feature) | 0 |  |
| Implementation (bug fix) | 0 |  |
| Implementation (refactoring) | 0 |  |
| Testing & QA | 0 |  |
| Documentation | 0 |  |
| Maintenance | 0 |  |

## Benchmark Coverage

| Benchmark | Available | Selected | Strategy |
|-----------|-----------|----------|----------|
| ccb_k8sdocs | — | 0 | All selected (small benchmark) |
| ccb_largerepo | — | 0 | All selected (small benchmark) |
| ccb_locobench | — | 0 | Priority: arch > refactoring > bug, by MCP score |
| ccb_pytorch | — | 0 | Prefer hard difficulty, then most files modified |
| ccb_swebenchpro | — | 0 | Proportional by repo, prefer most files changed |
| ccb_sweperf | — | 0 | All selected (small benchmark) |
| ccb_tac | — | 0 | All selected (small benchmark) |

## Language Distribution

| Language | Tasks |
|----------|-------|

## MCP Benefit Scoring

Each task receives an MCP benefit score in [0.0, 1.0] computed as:

```
score = 0.25 * context_complexity
      + 0.30 * cross_file_deps
      + 0.20 * semantic_search_potential
      + 0.25 * task_category_weight
```

**Average MCP benefit score:** 0.0000

### Component Definitions

- **context_complexity**: Derived from codebase token count (LoCoBench `context_length`) or benchmark-level proxy. Normalized: 1M+ tokens = 1.0
- **cross_file_deps**: From `files_count`, `solution_files_changed`, or parsed from instruction.md. Normalized: 20+ files = 1.0
- **semantic_search_potential**: High for large repos (ccb_largerepo=0.9), find-in-codebase tasks (0.8), large context (0.7)
- **task_category_weight**: Per-category MCP affinity (architectural_understanding=1.0, cross_file_refactoring=0.9, etc.)

## Per-Benchmark Selection Strategies

### SWE-Bench Pro (~35 tasks)
Proportional allocation by repository, ensuring at least 1 task per repo. Within each repo, tasks with the most files changed in their solution patch are preferred. Language corrections applied (e.g., NodeBB -> javascript, navidrome -> go). Diversity check ensures >=3 tasks each for Go, TypeScript, and JavaScript language families.

### LoCoBench Agent (~25 tasks)
All bug_investigation tasks (3) selected first, then all cross_file_refactoring (13), then top architectural_understanding tasks by MCP score to fill remaining budget. All tasks have >700K token context and 70+ files.

### GitHub Mined (~12 tasks)
All PyTorch cross-module tasks. Selection prioritizes hard difficulty, then tasks with the most files modified in the ground truth PR.

### Small Benchmarks (all selected)
ccb_largerepo (4), ccb_k8sdocs (5), ccb_tac (8), ccb_sweperf (3) — all tasks selected due to small size.


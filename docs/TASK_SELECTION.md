# Task Selection Methodology

## Overview

Selected **119 tasks** from 835 available across 11 benchmarks, stratified by SDLC phase with MCP benefit scoring.

## SDLC Phase Coverage

| SDLC Phase | Tasks | Benchmarks |
|------------|-------|------------|
| Requirements & Discovery | 2 | ccb_tac |
| Architecture & Design | 10 | ccb_locobench, ccb_crossrepo |
| Implementation (feature) | 16 | ccb_largerepo, ccb_pytorch, ccb_tac, ccb_dibench |
| Implementation (bug fix) | 51 | ccb_pytorch, ccb_locobench, ccb_swebenchpro, ccb_crossrepo |
| Implementation (refactoring) | 15 | ccb_locobench, ccb_crossrepo |
| Testing & QA | 8 | ccb_sweperf, ccb_tac, ccb_crossrepo, ccb_codereview |
| Documentation | 5 | ccb_k8sdocs |
| Maintenance | 2 | ccb_tac |

## Benchmark Coverage

| Benchmark | Available | Selected | Strategy |
|-----------|-----------|----------|----------|
| ccb_largerepo | 4 | 4 | All selected (small benchmark) |
| ccb_pytorch | 25 | 12 | Prefer hard difficulty, then most files modified |
| ccb_k8sdocs | 5 | 5 | All selected (small benchmark) |
| ccb_locobench | 50 | 25 | Priority: arch > refactoring > bug, by MCP score |
| ccb_swebenchpro | 731 | 36 | Proportional by repo, prefer most files changed |
| ccb_sweperf | 3 | 3 | All selected (small benchmark) |
| ccb_tac | 8 | 8 | All selected (small benchmark) |
| ccb_crossrepo | 5 | 5 | All selected (small benchmark) |
| ccb_codereview | 3 | 3 | All selected (small benchmark) |
| ccb_dibench | 387 | 8 | 2 per language (python, rust, javascript, csharp), moderate patch complexity |

## Language Distribution

| Language | Tasks |
|----------|-------|
| python | 33 |
| go | 24 |
| cpp | 19 |
| rust | 12 |
| typescript | 11 |
| javascript | 8 |
| c | 7 |
| csharp | 5 |
| java | 5 |
| python,cpp | 1 |

## MCP Benefit Scoring

Each task receives an MCP benefit score in [0.0, 1.0] computed as:

```
score = 0.25 * context_complexity
      + 0.30 * cross_file_deps
      + 0.20 * semantic_search_potential
      + 0.25 * task_category_weight
```

**Average MCP benefit score:** 0.6753

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

### DI-Bench (8 tasks)
2 per language (Python, Rust, JavaScript, C#) from the 387 regular-difficulty instances. Selected for single build file, moderate patch size (3-12 dependency additions), and well-known repositories. Tasks use syntax + dependency presence validators instead of full CI/CD execution.

### Small Benchmarks (all selected)
ccb_largerepo (4), ccb_k8sdocs (5), ccb_tac (8), ccb_sweperf (3), ccb_crossrepo (5), ccb_codereview (3) -- all tasks selected due to small size.


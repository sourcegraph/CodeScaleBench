# Task Selection Methodology

## Overview

Selected **116 tasks** from 835 available across 10 benchmarks, stratified by SDLC phase with MCP benefit scoring.

## SDLC Phase Coverage

| SDLC Phase | Tasks | Benchmarks |
|------------|-------|------------|
| Requirements & Discovery | 2 | ccb_tac |
| Architecture & Design | 10 | ccb_locobench, ccb_crossrepo |
| Implementation (feature) | 16 | ccb_largerepo, ccb_pytorch, ccb_tac, ccb_dibench |
| Implementation (bug fix) | 51 | ccb_pytorch, ccb_locobench, ccb_swebenchpro, ccb_crossrepo |
| Implementation (refactoring) | 15 | ccb_locobench, ccb_crossrepo |
| Testing & QA | 5 | ccb_sweperf, ccb_tac, ccb_crossrepo |
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
| ccb_dibench | 387 | 8 | 2 per language (python, rust, javascript, csharp), moderate patch complexity |

## Language Distribution

| Language | Tasks |
|----------|-------|
| python | 32 |
| go | 22 |
| cpp | 19 |
| rust | 12 |
| typescript | 11 |
| c | 7 |
| javascript | 5 |
| csharp | 5 |
| java | 2 |
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
ccb_largerepo (4), ccb_k8sdocs (5), ccb_tac (8), ccb_sweperf (3), ccb_crossrepo (5) -- all tasks selected due to small size.

## Difficulty Calibration Methodology

Difficulty labels were calibrated per-benchmark using objective metrics rather than uniform assignment. Each benchmark uses the metric most relevant to its task structure.

### Per-Benchmark Rules

| Benchmark | Metric | Thresholds |
|-----------|--------|------------|
| ccb_swebenchpro | Files changed in solution patch | 1-3 files → medium, 4-10 → hard, 11+ → very_hard |
| ccb_pytorch | LOC changed (additions + deletions) | <50 LOC → medium, 50-200 → hard, >200 → very_hard, 110+ files or 3500+ LOC → critical |
| ccb_locobench | Task category + context size | bug_investigation/cross_file_refactoring → hard, architectural_understanding with >1M tokens → expert |
| ccb_repoqa | Source file count in target repo | <50 source files → medium, >100 source files → hard |
| ccb_dibench | Uniform (moderate patch complexity) | All tasks → medium |
| ccb_k8sdocs | Manual assessment | 1 medium, 4 hard |
| ccb_largerepo | Uniform (all require large-repo navigation) | All tasks → hard |
| ccb_crossrepo | Manual assessment | 1 easy, 4 hard |
| ccb_tac | Manual assessment | 6 medium, 2 hard |
| ccb_sweperf | Manual assessment | 2 medium, 1 hard |

### The "critical" Difficulty Tier

Two PyTorch tasks (sgt-008 and sgt-025) are classified as "critical" — a tier above "very_hard" reserved for release-engineering-scale changes. sgt-008 modifies 110 files and sgt-025 changes 3526 LOC. These tasks also have no time limit, as they exceed what can be reasonably completed within a fixed timeout.

### Difficulty Distribution

| Difficulty | Count | % |
|------------|-------|---|
| easy | 1 | 0.9% |
| medium | 22 | 19.0% |
| hard | 58 | 50.0% |
| very_hard | 24 | 20.7% |
| critical | 2 | 1.7% |
| expert | 9 | 7.8% |
| **Total** | **116** | **100%** |


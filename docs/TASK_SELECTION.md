# Task Selection Methodology

## Overview

Selected **125 tasks** from 835 available across 11 benchmarks, stratified by SDLC phase with MCP benefit scoring.

## SDLC Phase Coverage

| SDLC Phase | Tasks | Benchmarks |
|------------|-------|------------|
| Requirements & Discovery | 2 | tac_mcp_value |
| Architecture & Design | 10 | locobench_agent, 10figure |
| Implementation (feature) | 16 | big_code_mcp, github_mined, tac_mcp_value, dibench |
| Implementation (bug fix) | 51 | github_mined, locobench_agent, swebench_pro, 10figure |
| Implementation (refactoring) | 18 | dependeval_benchmark, locobench_agent, 10figure |
| Testing & QA | 5 | sweperf, tac_mcp_value, 10figure |
| Documentation | 5 | kubernetes_docs |
| Maintenance | 8 | dependeval_benchmark, tac_mcp_value |

## Benchmark Coverage

| Benchmark | Available | Selected | Strategy |
|-----------|-----------|----------|----------|
| big_code_mcp | 4 | 4 | All selected (small benchmark) |
| dependeval_benchmark | 9 | 9 | All selected (small benchmark) |
| github_mined | 25 | 12 | Prefer hard difficulty, then most files modified |
| kubernetes_docs | 5 | 5 | All selected (small benchmark) |
| locobench_agent | 50 | 25 | Priority: arch > refactoring > bug, by MCP score |
| swebench_pro | 731 | 36 | Proportional by repo, prefer most files changed |
| sweperf | 3 | 3 | All selected (small benchmark) |
| tac_mcp_value | 8 | 8 | All selected (small benchmark) |
| 10figure | 5 | 5 | All selected (small benchmark) |
| dibench | 387 | 8 | 2 per language (python, rust, javascript, csharp), moderate patch complexity |

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
- **semantic_search_potential**: High for large repos (big_code_mcp=0.9), find-in-codebase tasks (0.8), large context (0.7)
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
big_code_mcp (4), kubernetes_docs (5), tac_mcp_value (8), dependeval_benchmark (9), sweperf (3), 10figure (5) -- all tasks selected due to small size.


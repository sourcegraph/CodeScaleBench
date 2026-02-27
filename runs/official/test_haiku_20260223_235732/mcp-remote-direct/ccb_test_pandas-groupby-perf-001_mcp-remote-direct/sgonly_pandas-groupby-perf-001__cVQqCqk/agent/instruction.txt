# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/pandas--41968da5`
- Use `repo:^github.com/sg-evals/pandas--41968da5$` filter in keyword_search
- Use `github.com/sg-evals/pandas--41968da5` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: ccb_sweperf-003
**Repository**: github.com/sg-evals/pandas--41968da5 (mirror of pandas)
**Difficulty**: medium
**Target Function**: `pandas.core.groupby.ops.GroupBy._aggregate_series_fast`
**Baseline Runtime**: 0.095000 seconds

---

## Description

Optimize the series aggregation in groupby operations for better performance on large datasets.

## Target Function

The function to optimize is located at:
- **File**: pandas/_libs/groupby.pyx
- **Function**: `pandas.core.groupby.ops.GroupBy._aggregate_series_fast`

## Baseline Performance

The current baseline runtime is **0.095000 seconds**.
Your goal is to reduce this runtime while maintaining correctness.


### Optimization Hints

- Leverage pandas' internal Cython-based hash tables
- Minimize Python object creation in tight loops
- Consider memory alignment for better cache performance


## Human Reference

For reference, here is how humans approached this optimization:
Replaced Python dictionary-based aggregation with Cython-optimized hash table lookup using pandas' internal khash implementation.

---

## Instructions

1. Analyze the target function and understand its purpose
2. Identify bottlenecks in the code
3. Design optimizations (algorithmic improvements, vectorization, caching, etc.)
4. Write your optimization as a unified diff

Do NOT modify source files directly. Write your optimization as a unified diff.
The evaluation system applies your patch and benchmarks independently.

## Deliverable

Write a unified diff to `/workspace/solution.patch` that applies cleanly against
the repository source tree. The patch should contain all changes needed to
optimize the target function.

The verifier will measure runtime improvement relative to the baseline. Greater
speedups yield higher scores.

## Tips

- Ensure correctness - optimization at the cost of correctness scores 0
- Consider algorithmic complexity first, then micro-optimizations
- Use NumPy/vectorization for numerical code where applicable
- Consider caching for repeated computations

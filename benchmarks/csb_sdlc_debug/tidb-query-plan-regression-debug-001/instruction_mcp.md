# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/tidb--v8.5.0`
- Use `repo:^github.com/sg-evals/tidb--v8.5.0$` filter in keyword_search
- Use `github.com/sg-evals/tidb--v8.5.0` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/tidb--v8.5.0`

# Task: Debug Query Plan Regression in TiDB Cost-Based Optimizer

## Background
A user reports that after upgrading TiDB, a query that previously used an index scan is now doing a full table scan. The query involves a JOIN between two tables with a WHERE clause on an indexed column.

## Objective
Investigate the cost model in TiDB's query optimizer to identify which component could cause a plan regression where an IndexScan is replaced by a TableFullScan.

## Steps
1. Find the cost model implementation in `pkg/planner/core/` that computes the cost of IndexScan vs TableFullScan
2. Identify the `Stats` struct and how row count estimates feed into the cost calculation
3. Locate where the optimizer compares candidate plans and selects the cheapest
4. Create a file `debug_report.md` in `/workspace/` documenting:
   - The file paths and functions responsible for cost calculation of IndexScan
   - The file paths and functions responsible for cost calculation of TableFullScan
   - The comparison logic that picks the final plan
   - A hypothesis for what parameter change could cause the regression

## Key Reference Files
- `pkg/planner/core/` — optimizer core
- `pkg/planner/cardinality/` — cardinality estimation
- `pkg/statistics/` — statistics framework

## Success Criteria
- debug_report.md exists and contains the relevant file paths
- Report identifies cost model functions for both scan types
- Report includes a plausible regression hypothesis

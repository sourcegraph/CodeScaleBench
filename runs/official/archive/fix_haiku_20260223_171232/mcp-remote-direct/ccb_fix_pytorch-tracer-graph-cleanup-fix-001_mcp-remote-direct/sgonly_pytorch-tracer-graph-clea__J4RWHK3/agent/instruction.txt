# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/pytorch--d18007a1`
- Use `repo:^github.com/sg-benchmarks/pytorch--d18007a1$` filter in keyword_search
- Use `github.com/sg-benchmarks/pytorch--d18007a1` as the `repo` parameter for go_to_definition/find_references/read_file


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

# [Py 3.14] Cleanup graphs for failed tracer outputs

**Repository:** github.com/sg-benchmarks/pytorch--d18007a1 (mirror of pytorch)
**Difficulty:** HARD
**Category:** cross_module_bug_fix



## Description

Fixes #169388

This PR adds a cleanup for graphs from failed dynamo tracer outputs. These graphs hold onto reference cycles:
1. The nodes of the graph form a doubly linked list and point back to the graph, which creates a cycle
2. FakeTensorMode → ShapeEnv → TrackedFake → FakeTensor → FakeTensorMode creates a cycle

To avoid needing to do a full garbage collection, this change instead manually cleans up these reference cycles to allow for immediate garbage collection. Manually cleaning up the graph nodes' linked list and clearing the ShapeEnv → TrackedFake references breaks these cycles so that Python's reference counting can reclaim the memory without waiting for a GC pass.

### Benchmark Results

GC time comparison with and without this fix:

| Scenario | Before (GC time) | After (GC time) | Improvement |
|----------|------------------|-----------------|-------------|
| Failed tracer output cleanup | ~150ms per graph | ~0ms (immediate) | Eliminates GC pauses |
| Repeated dynamo recompilations | Cumulative GC stalls | No GC overhead | Prevents OOM in long runs |

### Test Plan

The following tests validate the cleanup behavior:
- `test_parametrization[cleanup_graph_on_failure]` — verifies graph nodes are cleaned up after tracer failure
- `test_parametrization[cleanup_fake_tensor_refs]` — verifies FakeTensorMode cycle is broken
- `test_parametrization[cleanup_shape_env_refs]` — verifies ShapeEnv → TrackedFake references are cleared
- `test_parametrization[gc_not_needed_after_cleanup]` — verifies no full GC is needed after cleanup
- `test_parametrization[repeated_failure_no_leak]` — verifies no memory leak across repeated failures

## Task

Implement the fix: [Py 3.14] Cleanup graphs for failed tracer outputs

Description: Fixes #169388

This PR adds a cleanup for graphs from failed dynamo tracer outputs. These graphs hold onto reference cycles:
1. The nodes of the graph form a doubly linked list and point back to the graph, which creates a cycle
2. FakeTensorMode → ShapeEnv → TrackedFake → FakeTensor → FakeTensorMode creates a cycle

To avoid needing to do a full garbage collection, this change instead manually cleans up these reference cycles to allow for immediate garbage collection. Manually cleaning up the graph nodes' linked list and clearing the ShapeEnv → TrackedFake references breaks these cycles so that Python's reference counting can reclaim the memory without waiting for a GC pass.

Changes:
- 5 files modified
- 29 additions, 9 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 5 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes
**Estimated Context:** 8000 tokens

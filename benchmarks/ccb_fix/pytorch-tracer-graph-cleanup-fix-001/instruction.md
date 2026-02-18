# [Py 3.14] Cleanup graphs for failed tracer outputs

**Repository:** pytorch
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

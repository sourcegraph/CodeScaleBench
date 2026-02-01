# [GraphPartition] cache get_free_symbol_uses (#166338)

**Repository:** pytorch  
**Difficulty:** EASY  
**Category:** cross_module_bug_fix



## Description

Graph partition relies on `get_free_symbol_uses()` to collect symbol inputs. https://github.com/pytorch/pytorch/blob/ee7434be822cf6e75b4566d8159f550ee233d8ae/torch/_inductor/scheduler.py#L4869-L4885

I empirically observed that `get_free_symbol_uses()` becomes slower for larger graphs. Specifically, I tried to aten fallback for torchtitan which results in 10k+ aten nodes. When processing the 600-th node, it takes seconds to `get_free_symbol_uses()` for 1 node.

Why? Because `get_free_symbol_

## Task

Review the PR: [GraphPartition] cache get_free_symbol_uses (#166338)

Description: Graph partition relies on `get_free_symbol_uses()` to collect symbol inputs. https://github.com/pytorch/pytorch/blob/ee7434be822cf6e75b4566d8159f550ee233d8ae/torch/_inductor/scheduler.py#L4869-L4885

I empirically observed that `get_free_symbol_uses()` becomes slower for larger graphs. Specifically, I tried to aten fallback for torchtitan which results in 10k+ aten nodes. When processing the 600-th node, it takes seconds to `get_free_symbol_uses()` for 1 node.

Why? Because `get_free_symbol_

Changes:
- 2 files modified
- 161 additions, 4 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 2 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

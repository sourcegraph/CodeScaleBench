# Continue to build nightly CUDA 12.9 for internal

**Repository:** pytorch  
**Difficulty:** HARD  
**Category:** cross_module_bug_fix



## Description

Revert part of https://github.com/pytorch/pytorch/pull/161916 to continue building CUDA 12.9 nightly


cc @albanD

## Task

Review the PR: Continue to build nightly CUDA 12.9 for internal

Description: Revert part of https://github.com/pytorch/pytorch/pull/161916 to continue building CUDA 12.9 nightly


cc @albanD

Changes:
- 9 files modified
- 3525 additions, 501 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 9 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

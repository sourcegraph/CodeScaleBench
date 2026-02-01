# [cuDNN][SDPA][Convolution] Expose cuDNN runtime version in CUDA hooks

**Repository:** pytorch  
**Difficulty:** HARD  
**Category:** cross_module_bug_fix



## Description

cuDNN dispatching heuristics rely on versions checks but currently only that compile-time version is exposed, if we want to allow users to resolve https://github.com/pytorch/pytorch/issues/166643 on their end by updating their cuDNN version locally we need to check the runtime version rather than compile-time version.

Test plan: add test comparing performance with cuDNN 9.15+ when disabling and enabling convolutino explicilty for 3D cases.

Also partially covered by smoke test PR: https://g

## Task

Review the PR: [cuDNN][SDPA][Convolution] Expose cuDNN runtime version in CUDA hooks

Description: cuDNN dispatching heuristics rely on versions checks but currently only that compile-time version is exposed, if we want to allow users to resolve https://github.com/pytorch/pytorch/issues/166643 on their end by updating their cuDNN version locally we need to check the runtime version rather than compile-time version.

Test plan: add test comparing performance with cuDNN 9.15+ when disabling and enabling convolutino explicilty for 3D cases.

Also partially covered by smoke test PR: https://g

Changes:
- 7 files modified
- 43 additions, 9 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 7 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

# [CD] Apply the fix from #162455 to aarch64+cu129 build

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

When trying to bring cu129 back in https://github.com/pytorch/pytorch/pull/163029, I mainly looked at https://github.com/pytorch/pytorch/pull/163029 and missed another tweak coming from https://github.com/pytorch/pytorch/pull/162455

I discover this issue when testing aarch64+cu129 builds in https://github.com/pytorch/test-infra/actions/runs/18603342105/job/53046883322?pr=7373.  Surprisingly, there is no test running for aarch64 CUDA build from what I see in https://hud.pytorch.org/pytorch/pyt

## Task

Review the PR: [CD] Apply the fix from #162455 to aarch64+cu129 build

Description: When trying to bring cu129 back in https://github.com/pytorch/pytorch/pull/163029, I mainly looked at https://github.com/pytorch/pytorch/pull/163029 and missed another tweak coming from https://github.com/pytorch/pytorch/pull/162455

I discover this issue when testing aarch64+cu129 builds in https://github.com/pytorch/test-infra/actions/runs/18603342105/job/53046883322?pr=7373.  Surprisingly, there is no test running for aarch64 CUDA build from what I see in https://hud.pytorch.org/pytorch/pyt

Changes:
- 3 files modified
- 29 additions, 29 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 3 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

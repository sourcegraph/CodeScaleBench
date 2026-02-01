# [c10d] Integrate NCCL new `ncclAllToAll` into PT

**Repository:** pytorch  
**Difficulty:** EASY  
**Category:** feature_implementation



## Description

Stack from [ghstack](https://github.com/ezyang/ghstack) (oldest at bottom):
* __->__ #164265

NCCL 2.28.3 now supports `ncclAlltoAll`, this PR aims at integrating it. (release note: https://docs.nvidia.com/deeplearning/nccl/release-notes/rel_2-28-3.html#rel_2-28-3)

## Task

Review the PR: [c10d] Integrate NCCL new `ncclAllToAll` into PT

Description: Stack from [ghstack](https://github.com/ezyang/ghstack) (oldest at bottom):
* __->__ #164265

NCCL 2.28.3 now supports `ncclAlltoAll`, this PR aims at integrating it. (release note: https://docs.nvidia.com/deeplearning/nccl/release-notes/rel_2-28-3.html#rel_2-28-3)

Changes:
- 2 files modified
- 7 additions, 0 deletions

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

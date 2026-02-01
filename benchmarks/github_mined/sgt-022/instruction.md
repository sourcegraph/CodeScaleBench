# Build libgomp (gcc-13) from src on AArch64

**Repository:** pytorch  
**Difficulty:** EASY  
**Category:** cross_module_bug_fix



## Description

Stack from [ghstack](https://github.com/ezyang/ghstack/tree/0.12.0) (oldest at bottom):
* __->__ #165144

Fixed #155795
See discussion on: #152361

To understand the effect of this libgomp version update, I benchmarked all the following combinations on Arm Neoverse-V1 CPUs:

- models: distilbert, bert-base, bert-large
- modes: eager, compile
- context_length: 32, 64, 128, 256, 512
- dtype: float32, bfloat16 (autocast), int8 (dynamically quantized)
- threads: 4, 8, 16, 32, 48, 64
- w

## Task

Review the PR: Build libgomp (gcc-13) from src on AArch64

Description: Stack from [ghstack](https://github.com/ezyang/ghstack/tree/0.12.0) (oldest at bottom):
* __->__ #165144

Fixed #155795
See discussion on: #152361

To understand the effect of this libgomp version update, I benchmarked all the following combinations on Arm Neoverse-V1 CPUs:

- models: distilbert, bert-base, bert-large
- modes: eager, compile
- context_length: 32, 64, 128, 256, 512
- dtype: float32, bfloat16 (autocast), int8 (dynamically quantized)
- threads: 4, 8, 16, 32, 48, 64
- w

Changes:
- 2 files modified
- 60 additions, 0 deletions

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

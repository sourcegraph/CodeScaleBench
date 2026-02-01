# [ROCm] Enable shared memory based pruning for Triton configs

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** feature_implementation



## Description

## Summary
Enables shared memory based config pruning for ROCm GPUs in Inductor's Triton template heuristics.

Previously, pruning based on shared memory limits only worked on NVIDIA GPUs (using `shared_memory_per_block_optin`). This PR exposes `shared_memory_per_block` for ROCm and updates the pruning logic to use it as a fallback.

## Changes
- `torch/csrc/cuda/Module.cpp`: Expose `shared_memory_per_block` property for ROCm builds
- `torch/_C/__init__.pyi.in`: Add type hint for the new 

## Task

Review the PR: [ROCm] Enable shared memory based pruning for Triton configs

Description: ## Summary
Enables shared memory based config pruning for ROCm GPUs in Inductor's Triton template heuristics.

Previously, pruning based on shared memory limits only worked on NVIDIA GPUs (using `shared_memory_per_block_optin`). This PR exposes `shared_memory_per_block` for ROCm and updates the pruning logic to use it as a fallback.

## Changes
- `torch/csrc/cuda/Module.cpp`: Expose `shared_memory_per_block` property for ROCm builds
- `torch/_C/__init__.pyi.in`: Add type hint for the new 

Changes:
- 4 files modified
- 17 additions, 5 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 4 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

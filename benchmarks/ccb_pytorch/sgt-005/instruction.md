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
- `torch/_C/__init__.pyi.in`: Add type hint for the new property
- `torch/_inductor/template_heuristics/triton.py`: Update `_get_exceeding_shared_memory_checker()` to fall back to `shared_memory_per_block` when `shared_memory_per_block_optin` is unavailable
- `test/inductor/test_triton_heuristics.py`: Enable `test_prune_configs_over_shared_memory_limit` for ROCm

## Task

Review the PR: [ROCm] Enable shared memory based pruning for Triton configs

Description: ## Summary
Enables shared memory based config pruning for ROCm GPUs in Inductor's Triton template heuristics.

Previously, pruning based on shared memory limits only worked on NVIDIA GPUs (using `shared_memory_per_block_optin`). This PR exposes `shared_memory_per_block` for ROCm and updates the pruning logic to use it as a fallback.

## Changes
- `torch/csrc/cuda/Module.cpp`: Expose `shared_memory_per_block` property for ROCm builds
- `torch/_C/__init__.pyi.in`: Add type hint for the new property
- `torch/_inductor/template_heuristics/triton.py`: Update `_get_exceeding_shared_memory_checker()` to fall back to `shared_memory_per_block` when `shared_memory_per_block_optin` is unavailable
- `test/inductor/test_triton_heuristics.py`: Enable `test_prune_configs_over_shared_memory_limit` for ROCm

Changes:
- 4 files modified
- 17 additions, 5 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 4 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

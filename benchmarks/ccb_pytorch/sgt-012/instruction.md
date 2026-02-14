# don't produce invalid grid configs (#166973)

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

This task fixes a CUDA kernel launch bug where PyTorch's indexing operations on large tensors (e.g., boolean indexing on a 4D tensor with dimensions like 4x87x1056x736) produced an "invalid configuration argument" CUDA error. The grid configuration exceeded CUDA's maximum grid dimensions. The original fix in PR #164049 addressed only the `index` kernel but not `gather`, and its approach was incomplete.

This fix properly clamps grid dimensions to valid values in `aten/src/ATen/native/cuda/IndexKernelUtils.cu`, reverts the incomplete earlier fix from `IndexKernel.cu`, and removes an incorrect test while adding proper scatter/gather test coverage. The bug is a correctness issue that causes hard crashes on any sufficiently large tensor indexing operation on CUDA devices.

## Task

Changes:
- 3 files modified (IndexKernelUtils.cu, IndexKernel.cu, test files)
- 15 additions, 10 deletions

Tasks:
1. Fix grid dimension clamping in `aten/src/ATen/native/cuda/IndexKernelUtils.cu`
2. Revert the incomplete earlier fix from IndexKernel.cu
3. Update test coverage for scatter/gather on large tensors
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 3 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

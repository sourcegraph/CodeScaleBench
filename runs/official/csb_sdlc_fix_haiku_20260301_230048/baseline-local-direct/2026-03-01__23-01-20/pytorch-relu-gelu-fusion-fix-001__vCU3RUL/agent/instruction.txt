# Revert Inductor ReLU/GELU(Addmm) Fusions

**Repository:** pytorch
**Difficulty:** HARD
**Category:** cross_module_bug_fix



## Description

The Inductor compiler has pattern matching that fuses activation functions (ReLU, GELU) with Addmm (matrix multiply + bias add) operations into a single `_addmm_activation` call that leverages cuBLASLt's fused epilogue support. This optimization was intended to reduce kernel launches and memory traffic for common `Linear -> Activation` patterns.

However, the fusion causes regressions in certain model configurations and needs to be reverted. The revert must undo:
- The `_addmm_activation` pattern replacement in Inductor's lowering/decomposition passes
- The associated pattern matcher registrations for ReLU(Addmm) and GELU(Addmm)
- Any cuBLASLt epilogue fusion paths added for these patterns

Changes:
- 4 files modified
- 93 additions, 87 deletions

## Task

Revert the Inductor ReLU/GELU(Addmm) fusion optimization. The `Activation(Addmm) -> _addmm_activation` pattern replacement in the Inductor lowering pass for cuBLASLt fused epilogue support causes regressions and needs to be removed.

Changes:
- 4 files modified
- 93 additions, 87 deletions

Tasks:
1. Find the `_addmm_activation` pattern matching code in the Inductor lowering/decomposition passes
2. Remove the pattern matcher registrations for ReLU(Addmm) and GELU(Addmm) fusions
3. Remove any cuBLASLt epilogue fusion paths for these patterns
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

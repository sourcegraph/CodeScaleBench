# Cherry-pick revert of Inductor ReLU/GELU(Addmm) fusions (#168157)

**Repository:** pytorch
**Difficulty:** HARD
**Category:** cross_module_bug_fix



## Description

This is a cherry-pick of the revert of PR #168157, which added `Activation(Addmm) -> _addmm_activation` pattern replacement in the Inductor lowering pass.

PR #168157 introduced pattern matching in the Inductor compiler to fuse activation functions (ReLU, GELU) with Addmm (matrix multiply + bias add) operations into a single `_addmm_activation` call that leverages cuBLASLt's fused epilogue support. This optimization aimed to reduce kernel launches and memory traffic for common `Linear -> Activation` patterns.

However, the fusion caused regressions in certain model configurations and needed to be reverted. This cherry-pick applies the revert to the release branch, undoing:
- The `_addmm_activation` pattern replacement in Inductor's lowering/decomposition passes
- The associated pattern matcher registrations for ReLU(Addmm) and GELU(Addmm)
- Any cuBLASLt epilogue fusion paths added for these patterns

Changes:
- 4 files modified
- 93 additions, 87 deletions

## Task

Implement the fix: Cherry-pick revert of Inductor ReLU/GELU(Addmm) fusions

Description: Revert PR #168157 which added `Activation(Addmm) -> _addmm_activation` pattern replacement in the Inductor lowering pass for cuBLASLt fused epilogue support. The fusion caused regressions and needs to be reverted.

Changes:
- 4 files modified
- 93 additions, 87 deletions

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

# Reverts #163712 and forces allgather/scatter inputs/outputs to be contiguous

**Repository:** pytorch
**Difficulty:** MEDIUM
**Category:** cross_module_bug_fix



## Description

This PR reverts #163712, which had relaxed contiguity requirements for allgather and reduce_scatter operations to avoid unnecessary copies. However, the relaxed requirements caused regressions in distributed training workloads.

PR #163712 was originally motivated by issue #163483, which observed that forcing contiguity on allgather/reduce_scatter inputs and outputs caused unnecessary memory copies, hurting performance. The fix relaxed these requirements so that non-contiguous tensors could be passed directly to NCCL.

Unfortunately, the relaxation introduced correctness issues in certain distributed training configurations where non-contiguous tensor layouts led to incorrect results or crashes. This revert restores the original behavior of forcing all inputs and outputs to be contiguous before passing them to the collective operations.

Changes:
- Revert the relaxed contiguity checks in allgather and reduce_scatter
- Re-add `.contiguous()` calls on inputs and outputs before collective operations
- Remove the non-contiguous tensor handling paths added by #163712

## Task

Implement the fix: Reverts #163712 and forces allgather/scatter inputs/outputs to be contiguous

Description: This PR reverts #163712, which had relaxed contiguity requirements for allgather and reduce_scatter operations. The relaxation caused regressions, so this revert forces inputs and outputs to be contiguous again, restoring the original behavior. See issue #163483 for the original motivation behind the relaxation.

Changes:
- 4 files modified
- 12 additions, 47 deletions

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

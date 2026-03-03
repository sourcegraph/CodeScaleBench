# [cuDNN][SDPA][Convolution] Expose cuDNN runtime version in CUDA hooks

**Repository:** pytorch  
**Difficulty:** HARD  
**Category:** cross_module_bug_fix



## Description

cuDNN dispatching heuristics rely on version checks but currently only the compile-time version is exposed. To allow users to resolve cuDNN version mismatches by updating their cuDNN installation locally, the runtime version needs to be checked rather than the compile-time version.

## Task

Expose the cuDNN runtime version in CUDA hooks so that dispatching heuristics (SDPA, Convolution) can use it instead of the compile-time version.

Description: cuDNN dispatching heuristics rely on version checks but currently only the compile-time version is exposed. The runtime version needs to be checked so that users who update their cuDNN installation locally get correct dispatching behavior.

Changes:
- 7 files modified
- 43 additions, 9 deletions

Tasks:
1. Find where cuDNN version checks are done in CUDA hooks and dispatching code
2. Add runtime version retrieval and expose it alongside the compile-time version
3. Update dispatching heuristics to use runtime version where appropriate
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 7 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

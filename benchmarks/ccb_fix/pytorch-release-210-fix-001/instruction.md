# [RELEASE 2.10] Release only changes

**Repository:** pytorch  
**Difficulty:** HARD  
**Category:** cross_module_bug_fix



## Description

This is the PyTorch 2.10 release branch CI/CD configuration update. It updates approximately 110 GitHub Actions workflow files under `.github/workflows/` to pin versions, update build matrix references, and adjust CI runner configurations for the 2.10 release branch. The changes are primarily mechanical: updating branch references, Docker image tags, and workflow trigger conditions. This also includes ROCm/HIP-related adjustments for AMD GPU support in the release. Release branch CI configuration must be precise: incorrect workflow pins or build matrix entries can cause nightly builds to fail, release binaries to be built against wrong CUDA/ROCm versions, or tests to run on incorrect infrastructure.

## Task

Changes:
- 110 files modified (primarily `.github/workflows/*.yml`)
- 345 additions, 463 deletions

Tasks:
1. Understand the release branch CI configuration pattern (see PR #162493 for the 2.9 equivalent)
2. Update workflow files with correct branch references and Docker image tags
3. Adjust build matrix entries for CUDA and ROCm versions
4. Verify your changes compile and match the expected fix

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 110 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

# Revert "[annotation][export] Add metadata hook for all nodes created …

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

…in runtime_assert pass (#169497)"

This reverts commit 65d346ff8c711731c6f2db4b3c045422bf87c582.

Reverted https://github.com/pytorch/pytorch/pull/169497 on behalf of https://github.com/facebook-github-bot due to Diff reverted internally ([comment](https://github.com/pytorch/pytorch/pull/169497#issuecomment-3667072868))

Fixes #ISSUE_NUMBER


cc @ezyang @EikanWang @jgong5 @wenzhe-nrv @voznesenskym @penguinwu @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @jiayisunx @kadeng @chauhang @a

## Task

Review the PR: Revert "[annotation][export] Add metadata hook for all nodes created …

Description: …in runtime_assert pass (#169497)"

This reverts commit 65d346ff8c711731c6f2db4b3c045422bf87c582.

Reverted https://github.com/pytorch/pytorch/pull/169497 on behalf of https://github.com/facebook-github-bot due to Diff reverted internally ([comment](https://github.com/pytorch/pytorch/pull/169497#issuecomment-3667072868))

Fixes #ISSUE_NUMBER


cc @ezyang @EikanWang @jgong5 @wenzhe-nrv @voznesenskym @penguinwu @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @jiayisunx @kadeng @chauhang @a

Changes:
- 4 files modified
- 93 additions, 87 deletions

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

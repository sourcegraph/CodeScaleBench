# [dynamo] fix error_on_graph_break bug where non-empty checkpoint results in unwanted graph break resumption

**Repository:** pytorch  
**Difficulty:** EASY  
**Category:** cross_module_bug_fix



## Description

Cherrypick for (#166586)


Fixes https://github.com/pytorch/pytorch/issues/166589

cc @voznesenskym @penguinwu @EikanWang @jgong5 @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @wenzhe-nrv @jiayisunx @chenyang78 @kadeng @chauhang @amjames

## Task

Review the PR: [dynamo] fix error_on_graph_break bug where non-empty checkpoint results in unwanted graph break resumption

Description: Cherrypick for (#166586)


Fixes https://github.com/pytorch/pytorch/issues/166589

cc @voznesenskym @penguinwu @EikanWang @jgong5 @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @wenzhe-nrv @jiayisunx @chenyang78 @kadeng @chauhang @amjames

Changes:
- 2 files modified
- 30 additions, 0 deletions

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

# [Graph Partition] move custom rules to inductor config (#166458)

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

This PR adds `custom_should_partition_ops: list[str]` to specify the name of custom ops upon which graph partition happens. It works with cache since it is a `list[str]` in the config file. The op name should be of format "mylib::baz".

https://github.com/pytorch/pytorch/pull/166458 as original PR

(cherry picked from commit bebabd7fce29ea49b9269aeaa9fe3f34a3e1127e)

Fixes #165341


cc @voznesenskym @penguinwu @EikanWang @jgong5 @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @wenzhe-nrv

## Task

Review the PR: [Graph Partition] move custom rules to inductor config (#166458)

Description: This PR adds `custom_should_partition_ops: list[str]` to specify the name of custom ops upon which graph partition happens. It works with cache since it is a `list[str]` in the config file. The op name should be of format "mylib::baz".

https://github.com/pytorch/pytorch/pull/166458 as original PR

(cherry picked from commit bebabd7fce29ea49b9269aeaa9fe3f34a3e1127e)

Fixes #165341


cc @voznesenskym @penguinwu @EikanWang @jgong5 @Guobing-Chen @XiaobingSuper @zhuhaozhe @blzheng @wenzhe-nrv

Changes:
- 3 files modified
- 42 additions, 51 deletions

Tasks:
1. Understand the issue being fixed
2. Review the solution in the merged PR
3. Implement the fix to pass all tests
4. Verify: run "make test" successfully

## Success Criteria

All tests pass: run "make test" successfully.
Code follows repository conventions.
No regressions in existing functionality.
All 3 modified files updated correctly.

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

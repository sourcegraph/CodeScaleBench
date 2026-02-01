# don't produce invalid grid configs (#166973)

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

Proper fix for #164048, fixes gather too, reverts #164049 Pull Request resolved: https://github.com/pytorch/pytorch/pull/166974 Approved by: https://github.com/eqy

Fixes #ISSUE_NUMBER


## Task

Review the PR: don't produce invalid grid configs (#166973)

Description: Proper fix for #164048, fixes gather too, reverts #164049 Pull Request resolved: https://github.com/pytorch/pytorch/pull/166974 Approved by: https://github.com/eqy

Fixes #ISSUE_NUMBER


Changes:
- 3 files modified
- 15 additions, 10 deletions

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

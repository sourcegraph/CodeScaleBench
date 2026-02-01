# Reverts #163712 and forces allgather/scatter inputs/outputs to be contiguous

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix



## Description

Per title


cc @H-Huang @awgu @wanchaol @fegin @fduwjj @wz337 @wconstab @d4l3k @pragupta @msaroufim @dcci

## Task

Review the PR: Reverts #163712 and forces allgather/scatter inputs/outputs to be contiguous

Description: Per title


cc @H-Huang @awgu @wanchaol @fegin @fduwjj @wz337 @wconstab @d4l3k @pragupta @msaroufim @dcci

Changes:
- 4 files modified
- 12 additions, 47 deletions

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

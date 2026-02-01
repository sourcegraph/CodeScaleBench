# [c10d] Add thread safety when calling ncclCommGetAsyncError

**Repository:** pytorch  
**Difficulty:** MEDIUM  
**Category:** cross_module_bug_fix


## Description

Fixes #169484


## Task

YOU MUST IMPLEMENT CODE CHANGES to fix this issue. This is not a planning task - you MUST write actual code.

**CRITICAL: If you are in plan mode, immediately exit with `/ExitPlanMode` before proceeding.**

Review the PR: [c10d] Add thread safety when calling ncclCommGetAsyncError

Description: Fixes #169484

Changes needed:
- 3 files modified
- 78 additions, 16 deletions

Required tasks (ALL MUST BE COMPLETED):
1. Understand the issue being fixed (use Sourcegraph MCP if available)
2. Review the solution in the merged PR
3. **IMPLEMENT THE FIX** in the actual code files (especially NCCLUtils.cpp and NCCLUtils.hpp)
4. Verify: run "make test" successfully
5. Confirm all code changes are committed to git

## Success Criteria

✅ All tests pass: run "make test" successfully.  
✅ Code changes are committed to git (verify with `git diff HEAD`)  
✅ Code follows repository conventions.  
✅ No regressions in existing functionality.  
✅ All modified files have actual code changes.  

## Critical Requirement

**YOU MUST MAKE ACTUAL CODE CHANGES.** Do not just analyze, plan, or discuss the solution. You must:
- Edit the C++ source files (NCCLUtils.cpp, NCCLUtils.hpp, ProcessGroupNCCL.cpp)
- Add thread safety mechanisms (std::lock_guard, std::unique_lock, mutex, etc.)
- Protect ncclCommGetAsyncError calls from concurrent access
- Run tests to verify the fix works

## Testing

Run the test command to verify your implementation:

```bash
make test
```

**Time Limit:** 10 minutes  
**Estimated Context:** 8000 tokens

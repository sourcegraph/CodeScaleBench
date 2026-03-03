# Fix: Multi-SWE-Bench__go__maintenance__bugfix__85c030cf

**Repository:** cli/cli
**Language:** go
**Category:** contextbench_cross_validation

## Description

View repositories without username

When users view their personal repositories, the `username/` prefix can be omitted if they are logged in.

For instance, if logged in as user `cli`, user can just run `gh repo view cli` instead of `gh repo view cli/cli`.

Fixes #1502

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

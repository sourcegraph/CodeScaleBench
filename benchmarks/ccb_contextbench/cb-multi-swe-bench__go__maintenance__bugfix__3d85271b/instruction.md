# Fix: Multi-SWE-Bench__go__maintenance__bugfix__3d85271b

**Repository:** cli/cli
**Language:** go
**Category:** contextbench_cross_validation

## Description

issue-6910 clearer message with actionable hint for repo sync

issue-6910 clearer message with actionable hint
<!--
  Thank you for contributing to GitHub CLI!
  To reference an open issue, please write this in your description: `Fixes #NUMBER`
-->
Add hint to the gh repo sync error message for when there are untracked files.

Using git stash --all (or git stash --include-untracked) should help when people try to sync their local copy and 
the --force option fails due to untracked files.


--
Fixes #6910

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

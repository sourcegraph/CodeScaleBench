# Fix: Multi-SWE-Bench__go__maintenance__bugfix__4d9664f3

**Repository:** cli/cli
**Language:** go
**Category:** contextbench_cross_validation

## Description

Fix disabled_inactivity workflow can be changed to enable

Workflow in disabled_inactivity state could not be enabled, so it has been fixed.
Added state for disabled_inactivity to shared package.

Fixes #5025

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

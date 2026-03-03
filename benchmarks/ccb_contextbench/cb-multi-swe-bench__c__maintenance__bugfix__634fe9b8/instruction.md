# Fix: Multi-SWE-Bench__c__maintenance__bugfix__634fe9b8

**Repository:** ponylang/ponyc
**Language:** c
**Category:** contextbench_cross_validation

## Description

Fix extracting docstring from constructors

from classes or actors with initialized fields

by executing `sugar_docstring` on the constructors before adding the initializers. This will actually execute `sugar_docstring` twice on such constructors, but as it is idempotent, there is no danger here.

The docstrings have been inlined into the constructor body before.

Now they will show up correctly in the generated docs.

Fixes #2582

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

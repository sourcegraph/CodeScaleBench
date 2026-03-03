# Fix: Multi-SWE-Bench__c__maintenance__bugfix__a47dfbbf

**Repository:** facebook/zstd
**Language:** c
**Category:** contextbench_cross_validation

## Description

[lib] Add ZSTD_d_stableOutBuffer + fix single-pass mode for empty frames

This flag allows users to skip the output buffer allocation + memcpy if they guarantee that the `ZSTD_outBuffer*` passed to `ZSTD_decompressStream()` is large enough to fit the entire frame, and is never modified by the user.

Also fixes a bug where empty frames weren't eligible for single-pass mode. It caused a small allocation (4 bytes), and is a little bit slower.

Adds tests for single-pass and stable output buffer modes.

Fuzz tests `ZSTD_d_stableOutput` to ensure it never crashes.

Fixes #2093

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

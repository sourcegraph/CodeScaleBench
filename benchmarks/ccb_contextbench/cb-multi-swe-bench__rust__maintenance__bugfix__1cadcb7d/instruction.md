# Fix: Multi-SWE-Bench__rust__maintenance__bugfix__1cadcb7d

**Repository:** tokio-rs/tracing
**Language:** rust
**Category:** contextbench_cross_validation

## Description

attributes: fix `#[instrument(err)]` with `impl Trait` return types

This backports PR #1233 to v0.1.x. This isn't *just* a simple cherry-pick
because the new tests in that branch use the v0.2.x module names, so
that had to be fixed. Otherwise, though, it's the same change, and I'll go
ahead and merge it when CI passes, since it was approved on `master`.

## Motivation

Currently, using `#[instrument(err)]` on a function returning a `Result`
with an `impl Trait` in it results in a compiler error. This is because
we generate a type annotation on the closure in the function body that
contains the user function's actual body, and `impl Trait` isn't allowed
on types in local bindings, only on function parameters and return
types.

## Solution

This branch fixes the issue by simply removing the return type
annotation from the closure. I've also added tests that break on master
for functions returning `impl Trait`, both with and without the `err`
argument.

Fixes #1227

Signed-off-by: Eliza Weisman <eliza@buoyant.io>

## Task

Diagnose and fix the issue described above. The repository has been cloned at the relevant commit. Make the necessary code changes to resolve the bug.

## Success Criteria

Your code changes should resolve the described issue. The implementation will be verified against the expected patch using diff similarity scoring.

**Time Limit:** 30 minutes

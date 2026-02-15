# Add Graceful Error Handling to Evaluation Server

**Repository:** flipt-io/flipt
**Your Team:** Evaluation Engine Team
**Access Scope:** You are assigned to `internal/server/evaluation/`. Some upstream dependency files (storage interfaces, protobuf definitions) may not be available locally — they are maintained by other teams. You must work with the code available to you and infer contracts from usage patterns if source files are missing.

## Context

You are a developer on the Flipt Evaluation Engine team. Your team owns the flag evaluation logic in `internal/server/evaluation/`. Some dependency files that your code imports may not be present in the local workspace — the storage team and the RPC team maintain their files in separate repositories/modules. You can see how your code uses their types from existing source files, but the original type definitions may need to be found through remote search.

## Problem Statement

The evaluation server's `Boolean()` and `Variant()` methods in `evaluation.go` currently propagate all errors directly to the gRPC caller without wrapping them with evaluation-specific context. When the storage layer returns an error (e.g., `GetEvaluationRules` fails), the caller receives a raw storage error with no indication of which flag or namespace was being evaluated.

This makes debugging production issues extremely difficult — operators see errors like "sql: no rows in result set" without knowing which flag evaluation triggered it.

## Task

Add error wrapping to the evaluation server so that storage and evaluation errors include the namespace key, flag key, and evaluation phase (rules fetch, distributions fetch, constraint matching) in the error message.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Create a new file `internal/server/evaluation/errors.go` that defines evaluation error types:
   - An `EvalError` struct with fields: `NamespaceKey`, `FlagKey`, `Phase` (string: "rules", "distributions", "rollouts", "constraint_match"), and `Err` (wrapped error)
   - `EvalError` must implement the `error` interface with a descriptive message format: `evaluation error [namespace=%s flag=%s phase=%s]: %v`
   - `EvalError` must support `errors.Unwrap()` for error chain inspection

2. Modify `evaluation.go` to wrap errors from storage calls with `EvalError`:
   - Wrap errors from `GetEvaluationRules` with phase "rules"
   - Wrap errors from `GetEvaluationDistributions` with phase "distributions"
   - Wrap errors from `GetEvaluationRollouts` with phase "rollouts"

3. You will need to understand the storage types your code depends on:
   - The `Storer` interface in `server.go` defines `GetEvaluationRules`, `GetEvaluationDistributions`, `GetEvaluationRollouts`
   - These methods use types like `storage.ResourceRequest`, `storage.IDRequest`, `storage.EvaluationRule`, `storage.EvaluationDistribution`, `storage.EvaluationRollout`
   - The type definitions live in `internal/storage/storage.go` — this file may not be available locally. You can infer the types from how they're used in `evaluation.go`, or search for their definitions remotely
   - RPC response types come from `rpc/flipt/evaluation/` — again, definitions may require remote search

4. The `Boolean()` method processes rollouts and the `Variant()` method processes rules+distributions — make sure you wrap errors in the correct evaluation flow

### Hints

- `evaluation.go` is the main file (~650 lines). `Boolean()` handles boolean flags via rollouts; `Variant()` handles variant flags via rules and distributions
- The `Storer` interface in `server.go` shows exactly which storage methods exist and their signatures
- `storage.ResourceRequest` has `NamespaceKey` and `Key` (flag key) fields — extract these for the error context
- Look for `s.store.GetEvaluationRules(ctx, ...)` calls in `evaluation.go` — these are the error sites to wrap
- The request type `evaluation.EvaluationRequest` has `NamespaceKey` and `FlagKey` fields — use these in your error wrapper
- If storage type files aren't available locally, the usage patterns in `evaluation.go` tell you everything you need about the interfaces

## Success Criteria

- New `errors.go` file exists in `internal/server/evaluation/` with `EvalError` struct
- `EvalError` implements `error` and `Unwrap()` interfaces
- Storage errors in `Boolean()` and `Variant()` are wrapped with namespace, flag, and phase context
- Code compiles: `go build ./internal/server/evaluation/...`
- Changes are limited to `internal/server/evaluation/` files

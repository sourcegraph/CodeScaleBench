# Add Graceful Error Handling to Evaluation Server

**Repository:** flipt-io/flipt
**Your Team:** Evaluation Engine Team
**Access Scope:** You are assigned to `internal/server/evaluation/`. Some upstream dependency files (storage interfaces, protobuf definitions) may not be available locally — they are maintained by other teams. You must work with the code available to you and infer contracts from usage patterns if source files are missing.

## Context

You are a developer on the Flipt Evaluation Engine team. Your team owns the flag evaluation logic in `internal/server/evaluation/`. Some dependency files that your code imports may not be present in the local workspace — the storage team and the RPC team maintain their files in separate repositories/modules. You can see how your code uses their types from existing source files, but the original type definitions may need to be found through remote search.

## Problem Statement

The evaluation server currently propagates all errors directly to the gRPC caller without wrapping them with evaluation-specific context. When the storage layer returns an error, the caller receives a raw storage error with no indication of which flag or namespace was being evaluated, or which phase of evaluation failed.

This makes debugging production issues extremely difficult — operators see errors like "sql: no rows in result set" without knowing which flag evaluation triggered it.

## Task

Add error wrapping to the evaluation server so that storage and evaluation errors include the namespace key, flag key, and evaluation phase in the error message.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Create a new error-handling file in the evaluation package with an evaluation error type that:
   - Implements the `error` interface with a descriptive message including evaluation context
   - Supports `errors.Unwrap()` for error chain inspection
   - Carries enough context to identify which evaluation failed and at what phase

2. Modify the evaluation server code to wrap storage errors with your error type:
   - Identify all storage calls in the evaluation flow that can return errors
   - Wrap each with appropriate phase context: "rules", "distributions", or "rollouts"
   - Include the namespace and flag being evaluated in the error context

3. The evaluation server processes both boolean flags (via rollouts) and variant flags (via rules and distributions) — make sure you wrap errors in both evaluation flows

4. Some dependency type definitions may not be available locally — infer contracts from usage patterns in existing code, or search for definitions remotely

## Success Criteria

- A new error-handling file exists in `internal/server/evaluation/` with an evaluation error type
- Error type implements `error` and `Unwrap()` interfaces
- Storage errors in both boolean and variant evaluation paths are wrapped with namespace, flag, and phase context
- Code compiles: `go build ./internal/server/evaluation/...`
- Changes are limited to `internal/server/evaluation/` files

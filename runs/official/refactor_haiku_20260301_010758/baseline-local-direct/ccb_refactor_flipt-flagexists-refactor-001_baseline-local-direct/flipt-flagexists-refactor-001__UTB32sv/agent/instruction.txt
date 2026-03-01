# Add FlagExists Method to ReadOnlyFlagStore Interface

**Repository:** flipt-io/flipt
**Access Scope:** You may modify files in `internal/`. You may read any file to understand existing patterns.

## Context

Flipt is a feature flag platform built with Go. The `ReadOnlyFlagStore` interface defines the contract for reading flag data from storage backends. Multiple concrete types implement this interface across the codebase (filesystem snapshots, SQL backends, etc.).

The evaluation server needs a lightweight way to check if a flag exists without fetching the full flag object. Currently, it must call `GetFlag()` and check for errors, which is inefficient. A dedicated `FlagExists()` method would allow backends to optimize existence checks (e.g., via SQL `EXISTS` or filesystem stat).

## Task

Add a `FlagExists(ctx context.Context, req *flipt.GetFlagRequest) (bool, error)` method to the `ReadOnlyFlagStore` interface and implement it in all concrete types that satisfy this interface.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. **Find the interface definition** — Locate the `ReadOnlyFlagStore` interface in the storage package and understand its existing methods (e.g., `GetFlag`, `ListFlags`, `CountFlags`)
2. **Find all implementations** — Search for all types that implement `ReadOnlyFlagStore`. These are types that have methods like `GetFlag(ctx context.Context, req *flipt.GetFlagRequest) (*flipt.Flag, error)` matching the interface
3. **Add the method to the interface** — Add `FlagExists` to the interface definition:
   ```go
   FlagExists(ctx context.Context, req *flipt.GetFlagRequest) (bool, error)
   ```
4. **Implement in each concrete type** — For each implementing type, add a `FlagExists` method that:
   - Takes `(ctx context.Context, req *flipt.GetFlagRequest) (bool, error)`
   - Calls the type's existing `GetFlag()` method
   - Returns `true, nil` if the flag is found
   - Returns `false, nil` if the flag is not found (not-found error)
   - Returns `false, err` for other errors
5. **Handle not-found errors** — Use the existing error patterns in each backend to distinguish "not found" from real errors. Look at how `GetFlag` callers handle the not-found case.

## Success Criteria

- `ReadOnlyFlagStore` interface includes `FlagExists` method
- All concrete types that implement `ReadOnlyFlagStore` have a `FlagExists` method
- Each implementation correctly handles not-found vs real errors
- `go build ./internal/...` succeeds with zero errors
- No existing tests broken
- Changes are scoped to `internal/` only

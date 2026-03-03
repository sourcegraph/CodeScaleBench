# Add context.Context Parameter to storage.NewResource()

**Repository:** flipt-io/flipt
**Access Scope:** You may modify files in `internal/`. You may read any file to understand existing patterns.

## Context

Flipt is a feature flag platform built with Go. The `storage` package provides resource management primitives, including a `NewResource()` function that creates resource objects used throughout the codebase.

The team has decided to add observability support by threading `context.Context` through all resource operations. The first step is to add `ctx context.Context` as the first parameter to `storage.NewResource()` and update every call site.

## Task

Add `ctx context.Context` as the first parameter to the `storage.NewResource()` function and update all call sites across the codebase to pass a context.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. **Find the function definition** — Locate `NewResource()` in the storage package and examine its current signature
2. **Find all call sites** — Search the codebase for every invocation of `storage.NewResource(` or `NewResource(` within the `internal/` directory
3. **Modify the function signature** — Add `ctx context.Context` as the first parameter to `NewResource()`
4. **Update all call sites** — At each call site, pass an appropriate `context.Context` value:
   - If the calling function already has a `ctx context.Context` parameter, pass `ctx`
   - If the calling function has a `context.Context` available under another name, use that
   - If no context is available, use `context.TODO()`
5. **Add import if needed** — Ensure `"context"` is imported in any file where you add `context.TODO()`
6. **Verify compilation** — The code must compile: `go build ./...`

## Success Criteria

- `NewResource()` signature includes `ctx context.Context` as first parameter
- All call sites pass a context argument
- No call sites are missed (compiler will catch these)
- `go build ./internal/...` succeeds with zero errors
- Changes are scoped to `internal/` only

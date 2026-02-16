# Transitive Dependency Ordering: Evaluation Server

**Repository:** flipt-io/flipt
**Access Scope:** You may read any file. Write your results to `/workspace/submission.json`.

## Context

Flipt is a feature flag platform built with Go. The evaluation server is a critical component that depends on several internal packages. Understanding the full transitive dependency graph is essential for planning refactors, estimating blast radius, and ordering build steps.

## Task

Find the evaluation server's main implementation package and identify all internal packages it transitively depends on. List them in topological dependency order (leaf packages first, the evaluation server package last).

**YOU MUST CREATE A submission.json FILE.**

### Requirements

1. **Locate the evaluation server** — Find the Go package that implements the evaluation server. Look within the codebase for where flag evaluation logic lives.
2. **Identify direct internal imports** — Read the source files in that package and identify all import paths that start with the module prefix (`go.flipt.io/flipt/`)
3. **Trace transitively** — For each internal import, read that package's source files and find its own internal imports. Continue recursively until you reach packages with no internal imports (leaf nodes)
4. **Build the dependency graph** — Track which packages depend on which other packages
5. **Topologically sort** — Order the packages so that every package appears after all packages it depends on. Leaf packages (no internal dependencies) come first, the evaluation server package comes last
6. **Write submission** — Create `/workspace/submission.json` containing a JSON array of package paths in topological order

### Internal Packages

"Internal" means packages within the flipt module — import paths starting with `go.flipt.io/flipt/`. Strip the module prefix and version to get relative paths. For example:
- `go.flipt.io/flipt/v2/internal/storage` → `internal/storage`
- `go.flipt.io/flipt/rpc/flipt` → `rpc/flipt`
- `go.flipt.io/flipt/errors` → `errors`

Exclude all external dependencies (standard library, `google.golang.org/`, `go.uber.org/`, etc.).

Check ALL `.go` files in each package directory — imports may be split across multiple files. When multiple valid topological orderings exist, any correct ordering is accepted.

### Output Format

Create `/workspace/submission.json` with a JSON array of package paths in dependency order:
```json
[
  "leaf/package/a",
  "leaf/package/b",
  "mid/level/package",
  "the/target/package"
]
```

## Success Criteria

- `/workspace/submission.json` exists and is valid JSON
- The file contains a JSON array of package path strings
- All transitively-imported internal packages are included
- The ordering is topologically valid (dependencies before dependents)
- Scoring: 0.6 * position_exact_match + 0.4 * Kendall_tau_rank_correlation

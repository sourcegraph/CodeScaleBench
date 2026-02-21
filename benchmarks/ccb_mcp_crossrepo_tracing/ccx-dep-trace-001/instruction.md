# Blast Radius of a Shared Kubernetes Library

## Your Task

Your team is planning a breaking change to the `k8s.io/apimachinery/pkg/runtime` package interface.
Before making the change, you need to assess the blast radius within the `kubernetes-client-go` library.

**Specific question**: Which Go source files in the `dynamic/` package tree of the
`sg-benchmarks/kubernetes-client-go` repository directly import `k8s.io/apimachinery/pkg/runtime`
(the exact package — not sub-packages like `pkg/runtime/schema`)?

Find every file (including tests) in the `dynamic/` directory and its subdirectories that has an
import line for `"k8s.io/apimachinery/pkg/runtime"`.

## Context

You are working on a codebase task involving dependency tracing across Kubernetes ecosystem repos.
The `k8s.io/apimachinery/pkg/runtime` package provides core serialization interfaces. Any file
that directly imports it (not just subpackages) will be affected by a breaking API change.

## Available Resources

The local `/workspace/` directory contains all repositories:
- `kubernetes/kubernetes` at v1.32.0 → `/workspace/kubernetes`
- `kubernetes/client-go` at v0.32.0 → `/workspace/client-go`

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "sg-benchmarks/kubernetes-client-go", "path": "relative/path/to/file.go"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

**Important**: Use `"repo": "sg-benchmarks/kubernetes-client-go"` exactly — this is the canonical repo identifier used by the evaluation oracle. The local checkout at `/workspace/client-go` corresponds to this repo.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-benchmarks/kubernetes-client-go`). Strip this prefix in your answer — use `sg-benchmarks/kubernetes-client-go`, NOT `github.com/sg-benchmarks/kubernetes-client-go`.

Include only the `files` field. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files in the `dynamic/` tree that import `k8s.io/apimachinery/pkg/runtime`?

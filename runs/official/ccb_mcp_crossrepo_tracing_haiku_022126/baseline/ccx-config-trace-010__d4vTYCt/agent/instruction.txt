# Stack Trace Symbol Resolution: rest.Config

## Your Task

A Kubernetes developer is debugging a production issue and encounters the following in a stack trace:

```
goroutine 1 [running]:
k8s.io/client-go/rest.(*Config).DeepCopyInto(...)
        vendor/k8s.io/client-go/rest/config.go:87
```

The developer only has access to the main `kubernetes/kubernetes` repository locally.
They need to find where `rest.Config` is actually defined (the authoritative source),
not just a vendored copy.

**Specific question**: Find the repository and file path where the `Config` struct is
**defined** (not vendored) in the `rest` package of `k8s.io/client-go`. What is the
exact Go package import path?

## Context

You are working on a codebase task involving symbol resolution across Kubernetes ecosystem repos.
The `kubernetes/kubernetes` repository vendors many dependencies in its `staging/` or `vendor/`
directories, but the authoritative source lives in separate repositories accessible via MCP tools.

## Available Resources

The local `/workspace/` directory contains all repositories:
- `kubernetes/kubernetes` at v1.32.0 → `/workspace/kubernetes`
- `kubernetes/client-go` at v0.32.0 → `/workspace/client-go`
- `kubernetes/api` at fa23dd3 → `/workspace/api`
- `etcd-io/etcd` at v3.5.17 → `/workspace/etcd`

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "symbols": [
    {"repo": "sg-benchmarks/kubernetes-client-go", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "text": "Explanation of where Config is defined, the package import path, and why this is the authoritative source."
}
```

**Important**: The local `/workspace/client-go` directory contains the `kubernetes/client-go` source, but in Sourcegraph it is indexed as `sg-benchmarks/kubernetes-client-go`. Use `sg-benchmarks/kubernetes-client-go` as the `repo` value in your answer — the oracle checks for this exact identifier.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-benchmarks/kubernetes-client-go`). Strip this prefix in your answer — use `sg-benchmarks/kubernetes-client-go`, NOT `github.com/sg-benchmarks/kubernetes-client-go`.

Your answer is evaluated against a closed-world oracle — the exact repo, path, and symbol name matter.

## Evaluation

Your answer will be scored on:
- **Symbol resolution**: Did you find the correct repo, file, and symbol name for the `Config` struct definition?

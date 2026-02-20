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

The local `/workspace/` directory contains: kubernetes/kubernetes.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-benchmarks/kubernetes-client-go` (go-client-library)
- `sg-benchmarks/kubernetes-api` (api-type-definitions)
- `etcd-io/etcd` (distributed-kv-store)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "text": "Explanation of where Config is defined, the package import path, and why this is the authoritative source."
}
```

Your answer is evaluated against a closed-world oracle — the exact repo, path, and symbol name matter.

## Evaluation

Your answer will be scored on:
- **Symbol resolution**: Did you find the correct repo, file, and symbol name for the `Config` struct definition?

# Cross-Repo Dep Trace: Kubernetes TypeMeta Re-Export Chain

## Your Task

Trace the `TypeMeta` struct from its usage in the `Pod` type definition to its authoritative definition, following re-exports across Kubernetes repositories. Find: 1. In `kubernetes/kubernetes` staging area: the file `staging/src/k8s.io/api/core/v1/types.go` where `Pod` embeds `metav1.TypeMeta` — report the import alias and import path. 2. In `kubernetes/api` or the api staging module: the file that re-exports `TypeMeta` via the `meta/v1` package. 3. In `kubernetes/apimachinery`: the file `pkg/apis/meta/v1/types.go` where `TypeMeta` is originally defined — report the struct fields (`Kind` and `APIVersion`). For each step, report the repo, file path, line number, and the relevant type/import declaration.

## Context

You are working on a codebase task involving repos from the crossrepo tracing domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/kubernetes--v1.32.0, sg-evals/client-go--v0.32.0, sg-evals/api--v0.32.0, sg-evals/etcd-io-etcd.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/etcd-io-etcd` (etcd-io/etcd)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

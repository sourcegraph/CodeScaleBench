# Domain Lineage: Kubernetes Watch Event Delivery Path

## Your Task

Trace how a Kubernetes watch event is generated and delivered from etcd to a client application. Find: 1. In `etcd-io/etcd`: the Go file that defines the `watchStream` or `serverWatchStream` that sends events from the etcd MVCC store. 2. In `kubernetes/kubernetes`: the Go files under `staging/src/k8s.io/apiserver/` that implement the watch cache and event distribution (look for `Cacher` and `watchCache`). 3. In the kubernetes client-go ecosystem: the Go file that defines the `Reflector` that receives watch events on the client side. Report the repo, file path, and struct/type name for each hop.

## Context

You are working on a codebase task involving repos from the domain domain.

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

# Kubernetes Scheduler Binding to kubelet Pod Admission Chain

## Your Task

Trace how a scheduler binding decision reaches the kubelet in kubernetes/kubernetes. Find Go source files implementing: the scheduler Bind call, the API server binding handler, the kubelet pod watch/sync, and the pod admission gates that decide whether to start a bound pod.

## Context

You are working on a codebase task involving repos from the crossrepo domain.

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

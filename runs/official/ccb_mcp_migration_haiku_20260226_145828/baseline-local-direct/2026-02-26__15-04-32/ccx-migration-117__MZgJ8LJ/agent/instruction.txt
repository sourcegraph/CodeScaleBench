# Migration Inventory: K8s Scheduler ScoreExtensions Rename Impact

## Your Task

The Kubernetes scheduler team plans to rename the `ScoreExtensions` interface to `ScoreNormalizer` and its accessor method `ScoreExtensions()` to `ScoreNormalizer()`. Inventory all Go source files that would need updating. Find: 1. The interface definition file `pkg/scheduler/framework/interface.go` — report the `ScoreExtensions` interface and the `ScorePlugin` method that returns it. 2. All plugin implementation files under `pkg/scheduler/framework/plugins/` that implement `ScoreExtensions()`. 3. The runtime framework file `pkg/scheduler/framework/runtime/framework.go` that calls `ScoreExtensions()`. 4. The metrics file `pkg/scheduler/metrics/metrics.go` containing the `ScoreExtensionNormalize` constant. 5. All test files referencing `ScoreExtensions`. For each file, report the path and which symbols reference ScoreExtensions.

## Context

You are working on a codebase task involving repos from the migration domain.

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

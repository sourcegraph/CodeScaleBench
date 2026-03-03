# Kubernetes Scheduler Plugin Framework Architecture

## Your Task

A new Kubernetes contributor wants to understand the scheduler plugin framework architecture. Find the key Go source files in kubernetes/kubernetes that implement the scheduling framework: 1. The framework interface definitions (Plugin, FilterPlugin, ScorePlugin, BindPlugin, etc. in pkg/scheduler/framework/). 2. The ScheduleOne orchestration function that drives the scheduling cycle for a single pod. 3. The top-level Scheduler struct and its Run method. 4. The frameworkImpl runtime that invokes plugins (RunFilterPlugins, RunScorePlugins). 5. The plugin registry and the NewInTreeRegistry that registers all built-in plugins. Report each file path and key symbols.

## Context

You are working on a codebase task involving repos from the onboarding domain.

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

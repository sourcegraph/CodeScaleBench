# Elasticsearch Index Lifecycle Management Policy Engine

## Your Task

Find all Java source files in elastic/elasticsearch under x-pack/plugin/ilm/src/ and server/src/main/java/org/elasticsearch/cluster/metadata/ that implement Index Lifecycle Management (ILM). Identify: the IndexLifecycleService that triggers policy evaluation, the LifecyclePolicy and Phase model classes, the TransportPutLifecycleAction and TransportDeleteLifecycleAction handlers, the step execution framework (ClusterStateActionStep, AsyncWaitStep, AsyncActionStep), and the LifecycleExecutionState stored in index metadata. Report each file path and key class.

## Context

You are working on a codebase task involving repos from the platform domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/elasticsearch--v8.17.0.

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

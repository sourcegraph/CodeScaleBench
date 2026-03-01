# Incident Debugging: Trace Production Error to Authoritative Source

## Your Task

Identify the authoritative Go source files in the distributed etcd service that define and return the error string `mvcc: required revision has been compacted`. Find: 1. The file where the `ErrCompacted` error variable is defined (not a vendor copy). 2. The file containing the core function `rangeKeys` that returns this error when a client requests a revision that has been garbage-collected by compaction.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
*(none — all repos available locally)*

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

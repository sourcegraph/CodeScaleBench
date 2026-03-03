# etcd Raft Snapshot Too Old on Node Rejoin

## Your Task

An etcd node fails to rejoin a cluster with 'ErrSnapshotTemporarilyUnavailable'. Find the Go source files in etcd-io/etcd that (1) define ErrSnapshotTemporarilyUnavailable and (2) implement the snapshot availability check during Raft log catch-up.

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

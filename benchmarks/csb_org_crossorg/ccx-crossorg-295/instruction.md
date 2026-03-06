# CockroachDB Raft Consensus and Lease Management Cross-Component Discovery

## Your Task

Find all Go source files in cockroachdb/cockroach under pkg/kv/kvserver/ that implement the Raft consensus integration and range lease management. Identify: the Replica.handleRaftReady method and its state machine application, the Store.processReady batch processing, the lease request and transfer logic (RequestLease, TransferLease), the lease expiration vs epoch-based lease types, and the liveness-based node health checking that feeds into lease decisions. Report each file path and key function or type.

## Context

You are working on a codebase task involving repos from the crossorg domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/cockroach--v24.3.0.

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

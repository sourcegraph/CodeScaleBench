# gRPC Health Checking and Keepalive Protocol Implementation

## Your Task

Find all C++ source and header files in grpc/grpc that implement the health checking service and keepalive mechanism. Identify: the health checking service implementation under src/cpp/server/health/, the keepalive timer logic in src/core/ext/transport/chttp2/, the client-side health checking channel filter, the server-side keepalive enforcement policy, and the connectivity watcher. For each file report the path and primary class or function.

## Context

You are working on a codebase task involving repos from the org domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/grpc--v1.68.0.

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

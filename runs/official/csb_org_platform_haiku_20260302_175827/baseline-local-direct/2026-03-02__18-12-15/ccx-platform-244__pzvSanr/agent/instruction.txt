# Envoy Hot Restart Mechanism

## Your Task

Find all C++ source files in envoyproxy/envoy that implement the hot restart mechanism: the HotRestart interface, the parent/child process handshake, the socket passing via Unix domain sockets, the drain sequence, and the child process readiness signaling.

## Context

You are working on a codebase task involving repos from the platform domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/envoy--v1.31.2, sg-evals/data-plane-api--84e84367, sg-evals/go-control-plane--71637ad6, sg-evals/grpc--957dba5e.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/envoy--v1.31.2` (envoyproxy/envoy)
- `sg-evals/data-plane-api--84e84367` (envoyproxy/data-plane-api)
- `sg-evals/go-control-plane--71637ad6` (envoyproxy/go-control-plane)
- `sg-evals/grpc--957dba5e` (grpc/grpc)

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

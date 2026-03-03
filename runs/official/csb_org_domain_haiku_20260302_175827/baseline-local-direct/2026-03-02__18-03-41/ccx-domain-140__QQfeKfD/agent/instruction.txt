# ArangoDB AQL Query Execution Pipeline

## Your Task

Trace how an AQL query is executed in ArangoDB from parsing to data retrieval. Find the key C++ source files in `arangodb/arangodb` that implement the query pipeline: 1. The file under `arangod/Aql/` that implements the AQL parser (look for `Parser.cpp` or `AqlParser`). 2. The file that implements the query optimizer (`Optimizer.cpp`) which transforms the AST into an execution plan. 3. The file that defines `ExecutionEngine` or `ExecutionBlock` — the execution engine that runs the query plan. 4. The file that defines `RocksDBCollection` — the storage engine interface for data retrieval (under `arangod/RocksDBEngine/`). 5. The file that implements `Transaction` management for queries (under `arangod/Transaction/`). Report each file path and key class name.

## Context

You are working on a codebase task involving repos from the domain domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/arangodb--a5cca0b8.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/arangodb--a5cca0b8` (arangodb/arangodb)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

# Kafka ACL Authorization Code Audit

## Your Task

Find all Java source files in `apache/kafka` that implement or define Access Control List (ACL) authorization logic. Search under `core/src/main/` and `clients/src/main/` for files containing classes or interfaces with `Authorizer` or `AclAuthorizer` in the name. For each file, report the class name and whether it defines the interface, implements it, or provides test utilities.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/kafka--0753c489, sg-evals/flink--0cc95fcc, sg-evals/camel--1006f047.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/kafka--0753c489` (apache/kafka)
- `sg-evals/flink--0cc95fcc` (apache/flink)
- `sg-evals/camel--1006f047` (apache/camel)

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

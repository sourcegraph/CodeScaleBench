# Incident Debugging: Kafka Producer Record Batch Timeout

## Your Task

A Kafka producer is failing with `org.apache.kafka.common.errors.TimeoutException: Expiring N record(s) for topic-partition`. Find the Java source files in `apache/kafka` under `clients/src/main/java/` that: 1. Define the `TimeoutException` class. 2. Implement the record batch expiration logic that triggers this error (look for `expiredBatches` or `maybeExpire` methods). 3. Define the `delivery.timeout.ms` configuration constant that controls this timeout. Report the repo, file path, and the class or method name for each.

## Context

You are working on a codebase task involving repos from the incident domain.

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

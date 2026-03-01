# Domain Lineage: Kafka-to-Flink Serialization Boundary

## Your Task

Trace the serialization boundary between Kafka and Flink. Find: 1. In `apache/kafka` under `clients/src/main/java/`: the Java files that define the `Serializer` and `Deserializer` interfaces. 2. In `apache/flink` under `flink-connectors/flink-connector-kafka/`: the Java files that implement or wrap Kafka's `Deserializer` interface for Flink's `DeserializationSchema`. Report the repo, file path, interface/class name, and whether the file defines the interface or implements it.

## Context

You are working on a codebase task involving repos from the domain domain.

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

# Onboarding: Kafka Streams Architecture Overview

## Your Task

A new engineer is onboarding to the Kafka Streams team. Find the key Java source files in `apache/kafka` under `streams/src/main/java/org/apache/kafka/streams/` that define the core streaming topology abstractions. Specifically find: 1. The interface or abstract class that defines a `Topology` (the DAG of processing nodes). 2. The class that implements `StreamsBuilder` (the DSL for building topologies). 3. The class that implements `KafkaStreams` (the runtime that executes a topology). Report the repo, file path, and class name for each.

## Context

You are working on a codebase task involving repos from the onboarding domain.

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

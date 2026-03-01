# Agentic Correctness: Implement Kafka Consumer Following Ecosystem Patterns

## Your Task

Write a Java class `InventoryConsumer` that consumes messages from a Kafka topic `inventory-updates` and processes them idempotently. Your implementation must follow the patterns established in the Kafka codebase: 1. Use the `ConsumerConfig` constants (not string literals) for all configuration keys. 2. Implement the consumer loop using the `poll(Duration)` API (not the deprecated `poll(long)`). 3. Use `commitSync()` after processing each batch. 4. Handle `WakeupException` for clean shutdown. Write your implementation to `/workspace/InventoryConsumer.java`. Also write `/workspace/answer.json` listing the Kafka source files you referenced to understand the patterns.

## Context

You are working on a codebase task involving repos from the org domain.

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
- **Keyword presence**: Are required terms present in your explanation?

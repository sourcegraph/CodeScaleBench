# Kafka @Deprecated API Migration Inventory

## Your Task

Catalog all Java source files in `apache/kafka` that contain `@Deprecated` annotations on producer/streams configuration constants or exception-handling APIs. Focus on:

1. **StreamsConfig.java** — find deprecated config constants (e.g., `CACHE_MAX_BYTES_BUFFERING_CONFIG`, `DEFAULT_DESERIALIZATION_EXCEPTION_HANDLER_CLASS_CONFIG`, `DEFAULT_PRODUCTION_EXCEPTION_HANDLER_CLASS_CONFIG`, `DEFAULT_DSL_STORE_CONFIG`) and note their replacements.
2. **Exception handler interfaces and implementations** — find deprecated `handle()` method signatures in `ProductionExceptionHandler`, `DefaultProductionExceptionHandler`, `DeserializationExceptionHandler`, `LogAndFailExceptionHandler`, and `LogAndContinueExceptionHandler`.
3. **TopicConfig.java** — find deprecated config constants (e.g., `MESSAGE_DOWNCONVERSION_ENABLE_CONFIG`).

For each file, report the repo, file path, deprecated symbol name, and what it was replaced by (if documented in the annotation or Javadoc).

## Context

You are working on a migration inventory task for the Apache Kafka ecosystem. The pinned Kafka snapshot is version 4.x — note that older deprecated producer configs like `block.on.buffer.full` and `metadata.fetch.timeout.ms` were fully removed prior to this version and will not appear.

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
    {"repo": "org/repo-name", "path": "relative/path/to/file.java"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

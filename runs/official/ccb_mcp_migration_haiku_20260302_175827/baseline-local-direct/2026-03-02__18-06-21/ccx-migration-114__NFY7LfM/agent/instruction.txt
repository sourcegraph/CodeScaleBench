# Migration Inventory: Kafka RecordAccumulator Rename Impact

## Your Task

The Kafka team plans to rename `RecordAccumulator` to `BatchAccumulator` in the producer subsystem. Inventory all Java source files in `apache/kafka` under `clients/src/` that would need updating. Find: 1. The main class definition file for `RecordAccumulator` and its inner classes (`RecordAppendResult`, `ReadyCheckResult`). 2. All files in `clients/src/main/java/` that import or reference `RecordAccumulator` (KafkaProducer, Sender, BuiltInPartitioner, etc.). 3. All test files in `clients/src/test/java/` that reference `RecordAccumulator`. 4. Any JMH benchmark files under `jmh-benchmarks/` that reference it. For each file, report the path and which symbols (class name, method, import) reference RecordAccumulator.

## Context

You are working on a codebase task involving repos from the migration domain.

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

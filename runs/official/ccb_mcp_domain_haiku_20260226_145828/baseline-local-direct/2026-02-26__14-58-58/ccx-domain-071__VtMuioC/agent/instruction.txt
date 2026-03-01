# Domain Lineage: Kafka Producer Config Propagation Path

## Your Task

Trace how the `acks` producer configuration value propagates through the Kafka codebase. Find all Java source files in `apache/kafka` that: 1. Define the `acks` configuration constant (in `ProducerConfig`). 2. Read and validate the `acks` value during producer initialization. 3. Encode the `acks` value into the produce request protocol (the `ProduceRequest` builder). 4. Apply the `acks` value in the broker-side partition leader to determine write acknowledgment behavior. Report the repo, file path, class name, and the role in the propagation chain for each file.

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

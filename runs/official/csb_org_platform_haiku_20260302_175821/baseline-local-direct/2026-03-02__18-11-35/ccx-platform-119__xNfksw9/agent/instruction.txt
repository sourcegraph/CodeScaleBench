# Platform Knowledge: Flink Windowing API Extension Points

## Your Task

Map the extension points in Apache Flink's windowing API that a developer would need to implement a custom window assigner. Find: 1. The abstract base class `WindowAssigner` in `flink-streaming-java/src/main/java/org/apache/flink/streaming/api/windowing/assigners/` — report its abstract methods. 2. The `MergingWindowAssigner` subclass that adds `mergeWindows()` for session-style windows. 3. The `Trigger` base class in the triggers package — report the lifecycle methods (`onElement`, `onEventTime`, `onProcessingTime`, `onMerge`). 4. An existing reference implementation: `EventTimeSessionWindows` — report how it implements `assignWindows()` and `mergeWindows()`. 5. The `TimeWindow` class that concrete assigners produce. For each, report the file path, class name, and key method signatures.

## Context

You are working on a codebase task involving repos from the platform domain.

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

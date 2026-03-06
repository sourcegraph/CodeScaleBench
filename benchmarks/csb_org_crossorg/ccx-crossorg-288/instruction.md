# Apache Beam Pipeline Runner Translation Layer

## Your Task

Find all Java source files in apache/beam under runners/core-java/ and runners/core-construction-java/ that translate a Beam pipeline graph into runner-specific execution primitives. Identify: the PipelineTranslator interface, the TransformHierarchy walker, the PTransformOverride mechanism, the ExecutableStagePayload construction, and the BoundedSource/UnboundedSource adapter classes. For each file report its path and key class name.

## Context

You are working on a codebase task involving repos from the crossorg domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/beam--v2.62.0.

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

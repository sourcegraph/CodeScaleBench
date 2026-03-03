# OpenJDK G1 GC Garbage Collection Cycle Chain

## Your Task

Trace the G1 garbage collector's concurrent marking and mixed collection cycle in openjdk/jdk. Find C++ source files implementing: the G1ConcurrentMark start trigger, the SATB marking queue processing, the remembered set scanning, and the mixed collection region selection.

## Context

You are working on a codebase task involving repos from the crossrepo domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/jdk--742e735d.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/jdk--742e735d` (openjdk/jdk)

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

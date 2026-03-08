# Linux IRQ Storm Incident Trace

## Your Task

A system enters an IRQ storm and stops making forward progress. Find the C source files in torvalds/linux that (1) dispatch hard IRQ handling, (2) detect interrupt flood or stuck-interrupt conditions, and (3) disable, throttle, or log the problematic IRQ line.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: torvalds/linux.

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.c"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.c", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.c", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

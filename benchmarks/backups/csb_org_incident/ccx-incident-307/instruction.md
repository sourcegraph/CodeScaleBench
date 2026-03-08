# Linux Kernel Oops Driver Trace

## Your Task

A kernel oops points at a driver path after a device event. Find the C source files in torvalds/linux that (1) register the relevant driver probe or interrupt path, (2) report kernel oops or BUG diagnostics for that subsystem, and (3) unwind or log the fault from the crashing code path.

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

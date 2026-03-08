# Linux OOM Kill Path Trace

## Your Task

A production node is killing processes because it is out of memory. Find the C source files in torvalds/linux that (1) detect global or cgroup memory pressure, (2) select a victim for the OOM killer, and (3) log or notify the final kill decision.

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

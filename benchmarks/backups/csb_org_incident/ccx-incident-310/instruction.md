# Chromium Renderer Crash Trace

## Your Task

Chromium starts crashing in the renderer process after a navigation event. Find the C++ source files in chromium/chromium that (1) bootstrap renderer process startup, (2) dispatch the failing navigation or document lifecycle work inside the renderer, and (3) surface the crash or fatal termination back to browser-side crash handling.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/chromium--2d05e315.

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

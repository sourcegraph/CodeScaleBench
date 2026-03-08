# Flask Host Validation and Trusted Routing Audit

## Your Task

Audit Flask's host and URL security boundaries. Find the Python source files in pallets/flask that (1) validate trusted hosts or server names, (2) bind request routing to the incoming host header, and (3) reject or normalize unsafe host information before URL matching proceeds.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: pallets/flask.

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.py"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.py", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.py", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

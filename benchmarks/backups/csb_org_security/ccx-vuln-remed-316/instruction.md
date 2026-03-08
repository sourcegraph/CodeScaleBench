# Flask Session Cookie Security Audit

## Your Task

Audit Flask's session-cookie handling. Find the Python source files in pallets/flask that (1) create and load the secure cookie session, (2) configure cookie security attributes such as HttpOnly, Secure, SameSite, and domain/path settings, and (3) sign or verify session data before it is trusted.

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

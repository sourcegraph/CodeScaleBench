# FastAPI CORS Middleware Audit

## Your Task

Audit FastAPI's CORS handling. Find the Python source files in fastapi/fastapi that (1) configure allowed origins, methods, and headers for CORS, (2) process preflight OPTIONS requests, and (3) attach the final CORS response headers to application responses.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: fastapi/fastapi.

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

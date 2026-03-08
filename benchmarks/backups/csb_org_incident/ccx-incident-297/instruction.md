# FastAPI 422 Validation Error Trace Across Client and Server

## Your Task

A POST request sent with requests returns HTTP 422 from a FastAPI service. Find the Python source files across fastapi/fastapi and psf/requests that (1) serialize and send the request body on the client side, (2) parse request bodies and trigger validation in FastAPI, and (3) construct the validation error response returned to the caller.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: fastapi/fastapi, psf/requests.

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

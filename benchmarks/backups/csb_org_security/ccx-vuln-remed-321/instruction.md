# Redis AUTH and ACL Enforcement Audit

## Your Task

Audit Redis authentication and ACL enforcement. Find the C source files in redis/redis that (1) parse AUTH or ACL commands, (2) attach authenticated user state to the client connection, and (3) enforce command-level permissions before an operation is executed.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: redis/redis.

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

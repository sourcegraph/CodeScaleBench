# Redis Protected Mode Configuration Audit

## Your Task

Audit Redis protected-mode behavior. Find the C source files in redis/redis that (1) load and validate bind/protected-mode configuration, (2) decide whether a remote client should be rejected before authentication, and (3) return the protected-mode error sent to disallowed connections.

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

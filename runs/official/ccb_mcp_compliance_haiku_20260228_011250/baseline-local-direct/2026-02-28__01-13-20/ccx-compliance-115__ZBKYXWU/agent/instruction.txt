# Compliance Audit: Django Session Key Rotation Concurrency Safety

## Your Task

Audit Django's session framework for concurrency safety in the session key rotation path. Find: 1. The Python source file in `django/contrib/sessions/` that implements `cycle_key()` — the method called during login to rotate session keys. 2. The session backend base class file that defines `create()` and `_get_new_session_key()` — the methods responsible for generating and persisting new session keys. 3. The database backend file that implements the actual `create()` with a database INSERT. 4. Identify whether `create()` handles key collisions (duplicate session keys) or silently overwrites. Report the repo, file path, class name, and method name for each, plus a brief note on whether collision handling exists.

## Context

You are working on a codebase task involving repos from the compliance domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/django--674eda1c.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/django--674eda1c` (django/django)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

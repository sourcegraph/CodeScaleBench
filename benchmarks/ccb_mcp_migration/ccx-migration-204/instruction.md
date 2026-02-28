# Django CharField max_length Enforcement Migration

## Your Task

Find all Python source files in django/django that validate CharField max_length: the field-level validation, the database backend max_length enforcement, the form field max_length check, and the migration auto-detector that generates AlterField operations for max_length changes.

## Context

You are working on a codebase task involving repos from the migration domain.

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

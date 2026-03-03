# Django Model Field Validation Coverage Audit

## Your Task

Find all Python source files in django/django that implement model field validators: the built-in validator functions (MaxLengthValidator, MinValueValidator, EmailValidator, URLValidator), the field-level validate() method, and the full_clean() validation pipeline.

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

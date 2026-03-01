# Compliance Audit: Django Admin Filter Rendering Pipeline

## Your Task

Audit Django's admin filter rendering pipeline to identify where empty related-field filters are constructed. Find: 1. The Python source file in `django/contrib/admin/` that defines `RelatedFieldListFilter` — the class responsible for rendering ForeignKey filter dropdowns in the admin sidebar. 2. The file that defines the base `ListFilter` class and its `has_output()` method that determines whether a filter should be displayed. 3. The admin `ChangeList` class file that collects and renders filters, calling `has_output()` for each. 4. The template tag or view file that iterates over filters in the sidebar. For each, report the file path, class name, and the specific method that controls filter visibility.

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

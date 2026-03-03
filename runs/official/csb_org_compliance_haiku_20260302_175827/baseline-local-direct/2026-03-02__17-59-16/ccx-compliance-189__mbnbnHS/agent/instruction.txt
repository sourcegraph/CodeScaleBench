# Grafana User Permission Model Role Coverage Audit

## Your Task

Find all Go source files in grafana/grafana that define and enforce the three-tier permission model (Viewer/Editor/Admin): the role-to-permission mapping, the permission guard middleware, and the folder/dashboard permission inheritance.

## Context

You are working on a codebase task involving repos from the compliance domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/grafana--26d36ec.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/grafana--26d36ec` (grafana/grafana)
- `sg-evals/grafana-loki` (grafana/loki)
- `sg-evals/grafana-mimir` (grafana/mimir)

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

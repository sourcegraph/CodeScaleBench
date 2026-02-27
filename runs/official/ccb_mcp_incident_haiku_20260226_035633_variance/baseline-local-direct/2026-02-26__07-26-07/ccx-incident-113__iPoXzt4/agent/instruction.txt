# Incident Root-Cause: Grafana Dashboard Migration Field Config Loss

## Your Task

A Grafana dashboard migration (v38) silently drops table panel field override configuration during import. Dashboards without explicit `fieldConfig.defaults.custom` lose column widths and text alignment. Trace this bug to its root cause in the Grafana codebase. Find: 1. The Go source files under `pkg/services/dashboardimport/` or `pkg/services/dashboards/` that implement the v38 schema migration. 2. The specific function that handles `fieldConfig` merging and the conditional logic that fails for missing `defaults.custom`. 3. The schema version constant file that registers v38. Report the repo, file path, function name, and the flawed conditional expression for each.

## Context

You are working on a codebase task involving repos from the incident domain.

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

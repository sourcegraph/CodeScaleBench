# API Call Chain: Grafana to Loki Query Path

## Your Task

When Grafana executes a log query to a Loki datasource, it sends HTTP requests through a
specific code path. Your task is to trace the end-to-end call chain from the Grafana side
through to the Loki backend.

**Specific question**: Identify the key types/functions at each hop in this HTTP call chain:
1. In `grafana/grafana`: What is the type/struct that acts as the HTTP client for Loki queries?
   (Look in `pkg/tsdb/loki/`)
2. In `sg-benchmarks/grafana-loki`: What is the function that parses incoming HTTP instant query
   requests? (Look in `pkg/loghttp/`)

Your answer should trace from Grafana's API layer → Loki's HTTP parsing layer.

## Context

You are working on a codebase task involving API call chain tracing across the Grafana
observability stack. Understanding the HTTP call path is important for debugging latency,
adding observability, or extending the query pipeline.

## Available Resources

The local `/workspace/` directory contains: grafana/grafana.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-benchmarks/grafana-loki` (log-aggregation)
- `sg-benchmarks/grafana-mimir` (metrics-backend)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "TypeOrFunctionName"}
  ],
  "text": "Narrative explanation of the call chain, citing specific repos and file paths."
}
```

List the chain steps in order from Grafana (caller) to Loki (callee). Your answer is evaluated
against a closed-world oracle — precision matters.

## Evaluation

Your answer will be scored on:
- **Dependency chain**: Did you trace the correct ordered call chain across repos?
- **Provenance**: Did you cite the correct file paths and repository names?

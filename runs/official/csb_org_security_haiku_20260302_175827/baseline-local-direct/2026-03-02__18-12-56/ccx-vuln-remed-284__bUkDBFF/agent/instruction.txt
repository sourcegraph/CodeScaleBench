# Prometheus PromQL Query Parsing and Validation Pipeline

## Your Task

Find all Go source files in prometheus/prometheus that implement the PromQL query parsing and validation pipeline. Identify: the Parser interface and parser struct with ParseExpr and checkAST (in promql/parser/), the Lexer tokenizer, the AST node type definitions (Expr, VectorSelector, BinaryExpr, etc.), the generated yacc parser, the Function registry defining valid PromQL functions, the value type system used for expression type validation, and the Engine that integrates the parser.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: prometheus/prometheus.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `prometheus/prometheus` (prometheus/prometheus)
- `sourcegraph-testing/prometheus-common` (prometheus/client_golang)
- `prometheus/alertmanager` (prometheus/alertmanager)
- `sg-evals/grafana--26d36ec` (grafana/grafana)

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

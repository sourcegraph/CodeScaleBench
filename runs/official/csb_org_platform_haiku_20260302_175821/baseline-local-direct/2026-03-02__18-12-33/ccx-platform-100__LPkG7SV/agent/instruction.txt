# Platform Audit: Deprecated Struct Fields in Kubernetes API Types

## Your Task

Find all Go source files in `kubernetes/kubernetes` that define struct fields or constants with `Deprecated` in the identifier name. Search `staging/src/k8s.io/api/` and `pkg/apis/` directories. Only include files that DEFINE the deprecated identifiers — do not include files that merely reference or use these deprecated fields.

## Context

You are working on a codebase task involving repos from the platform domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
*(none — all repos available locally)*

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

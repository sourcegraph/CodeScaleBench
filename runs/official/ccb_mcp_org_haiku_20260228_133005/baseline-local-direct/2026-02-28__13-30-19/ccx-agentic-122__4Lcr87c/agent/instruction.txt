# Agentic Correctness: Implement Firefox XPCOM Component

## Your Task

Write an XPCOM component header and implementation following Firefox's established patterns. Your component must: 1. Use the `NS_DECL_ISUPPORTS` and `NS_DECL_NSIOBSERVERSERVICE` macros as seen in existing components. 2. Implement `QueryInterface`, `AddRef`, `Release` following the reference counting pattern. 3. Register using `NS_GENERIC_FACTORY_CONSTRUCTOR` as found in existing component registrations under `toolkit/components/`. Write your files to `/workspace/`. Also write `/workspace/answer.json` listing the Firefox source files you referenced.

## Context

You are working on a codebase task involving repos from the org domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/firefox--871325b8.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/firefox--871325b8` (mozilla-firefox/firefox)

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
- **Keyword presence**: Are required terms present in your explanation?

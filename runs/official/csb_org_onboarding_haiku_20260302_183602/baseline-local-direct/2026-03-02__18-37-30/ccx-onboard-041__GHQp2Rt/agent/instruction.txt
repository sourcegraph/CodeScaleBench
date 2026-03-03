# Onboarding Audit: scipy.stats API Call Sites in pandas

## Your Task

Which Python source files in `pandas-dev/pandas` contain a `from scipy.stats import` statement (i.e., directly import functions or classes from `scipy.stats` at runtime)? Include files in any part of the codebase — production code and test files.

## Context

You are working on a codebase task involving repos from the onboarding domain.

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

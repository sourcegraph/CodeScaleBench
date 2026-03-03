# Architecture Map: Scientific Computing Data Flow

## Your Task

Map the data flow from raw array creation through scientific computation across these repos. Trace through all three layers: 1. Array computation layer — What function in `numpy/numpy` is the canonical entry point for array-level aggregation on raw ndarray objects? 2. Data structure layer — What class in `pandas-dev/pandas` wraps a NumPy ndarray as a pandas extension array? 3. Scientific computation layer — What function in `scipy/scipy` accepts numpy arrays (or pandas Series) as inputs for statistical analysis?

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

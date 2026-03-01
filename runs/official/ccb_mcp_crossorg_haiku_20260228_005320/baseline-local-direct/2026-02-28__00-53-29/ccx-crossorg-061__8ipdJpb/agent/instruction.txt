# Cross-Org Interface Implementation Discovery

## Your Task

Find all Go source files across the repos in this ecosystem that contain an explicit interface compliance check for `storage.Interface` using the Go pattern `var _ storage.Interface = (*StructName)(nil)`. For each match, report the repo, file path, and the struct name that implements the interface.

## Context

You are working on a codebase task involving repos from the crossorg domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
*(none — all repos available locally)*

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

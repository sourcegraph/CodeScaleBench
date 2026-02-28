# Rust ICE in Trait Method Candidate Collection

## Your Task

Users report an internal compiler error (ICE) during trait method resolution. Find the Rust source files in rust-lang/rust that (1) collect candidate trait method implementations and (2) report ambiguous trait method errors.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/rust--01f6ddf7, sg-evals/servo--be6a2f99.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/rust--01f6ddf7` (rust-lang/rust)
- `sg-evals/servo--be6a2f99` (servo/servo)

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

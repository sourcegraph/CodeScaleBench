# Vault Secret Engine Access Control Audit

## Your Task

Audit Vault secret-engine access control. Find the Go source files in hashicorp/vault that (1) register or dispatch secret-engine backends, (2) gate secret-engine operations on capabilities or path policy checks, and (3) emit the deny path when a caller crosses an auth boundary.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: hashicorp/vault.

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

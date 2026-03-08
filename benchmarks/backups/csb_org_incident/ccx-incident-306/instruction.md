# Vault Seal-Unseal Error Trace

## Your Task

Vault fails to unseal after a restart and operators see a seal-related error. Find the Go source files in hashicorp/vault that (1) coordinate seal and unseal state, (2) process recovery or unseal key shares, and (3) emit the error path when unseal initialization fails.

## Context

You are working on a codebase task involving repos from the incident domain.

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

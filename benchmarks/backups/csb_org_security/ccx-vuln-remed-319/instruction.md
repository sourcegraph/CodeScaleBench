# Vault Auth Boundary Enforcement Audit

## Your Task

Audit Vault's authentication and authorization boundary. Find the Go source files in hashicorp/vault that (1) authenticate a request into an identity or token, (2) resolve attached policies and capabilities, and (3) enforce the final authorization decision for a protected path.

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

# Vault Secret Lease Expiry Trace

## Your Task

A Vault client loses access because a dynamic secret lease expires unexpectedly. Find the Go source files in hashicorp/vault that (1) issue and renew leases, (2) revoke or expire leases in the expiration manager, and (3) surface lease-expiry errors back through the request path.

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

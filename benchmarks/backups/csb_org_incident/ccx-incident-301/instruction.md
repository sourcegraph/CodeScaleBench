# Consul Service Mesh Timeout Trace

## Your Task

Consul service mesh traffic starts timing out between sidecars. Find the Go source files in hashicorp/consul that (1) build or propagate upstream proxy configuration, (2) manage Connect sidecar or proxy timeouts, and (3) surface timeout failures during request forwarding or service resolution.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: hashicorp/consul.

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

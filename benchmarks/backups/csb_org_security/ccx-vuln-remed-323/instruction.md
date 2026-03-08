# Elasticsearch Transport TLS Audit

## Your Task

Audit Elasticsearch transport-layer TLS. Find the Java source files in elastic/elasticsearch that (1) load transport SSL/TLS settings and certificates, (2) build the transport-layer SSL context or channel handlers, and (3) enforce certificate validation for inter-node transport connections.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/elasticsearch--v8.17.0.

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.java", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

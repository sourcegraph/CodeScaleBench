# Spark Executor Secret Handling Audit

## Your Task

Audit Spark's executor secret and credential handling. Find the Java or Scala source files in apache/spark that (1) generate or distribute secrets from the driver to executors, (2) store or redact those secrets in runtime configuration, and (3) validate the secret on executor startup or RPC authentication.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: apache/spark.

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

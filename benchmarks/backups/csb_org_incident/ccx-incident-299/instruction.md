# Gin Middleware Panic Trace With Test Harness

## Your Task

A Gin service panics after a middleware is added and the regression is reproduced in a testify-backed test. Find the Go source files across gin-gonic/gin and stretchr/testify that (1) compose the Gin handler chain, (2) dispatch handlers through Gin's request pipeline, and (3) implement the testify panic assertions used by the reproducer.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: gin-gonic/gin, stretchr/testify.

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

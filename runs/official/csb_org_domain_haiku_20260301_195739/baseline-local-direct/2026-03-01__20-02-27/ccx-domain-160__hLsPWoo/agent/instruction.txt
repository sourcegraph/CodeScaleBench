# OpenJDK JVM Bytecode Interpretation Loop

## Your Task

Find all C++ source files in openjdk/jdk that implement the JVM bytecode interpreter main dispatch loop: the bytecode dispatch table, the interpreter template generation, and the method entry point setup.

## Context

You are working on a codebase task involving repos from the domain domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/jdk--742e735d.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/jdk--742e735d` (openjdk/jdk)

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

# Bazel Starlark Evaluation and BUILD File Migration Inventory

## Your Task

Find all Java source files in bazelbuild/bazel under src/main/java/com/google/devtools/build/lib/packages/ and src/main/java/net/starlark/ that implement Starlark evaluation for BUILD files. Identify: the StarlarkThread class and its environment setup, the PackageFactory that invokes Starlark evaluation, the BzlLoadFunction for .bzl file loading, the rule() and macro() builtin function implementations, and the Package.Builder that accumulates targets. Report each file path and key class.

## Context

You are working on a codebase task involving repos from the migration domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/bazel--8.0.0.

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

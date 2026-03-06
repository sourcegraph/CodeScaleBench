# TypeScript Module Resolution Migration from Classic to Node16

## Your Task

Find all TypeScript source files in microsoft/TypeScript under src/compiler/ that implement module resolution. Identify: the moduleNameResolver entry point and its strategy dispatch (Classic vs Node vs Node16 vs Bundler), the node16ModuleNameResolver and its package.json exports field resolution, the classicNameResolver, the getPackageJsonInfo helper, the pathPatternMatch for path mapping, and the tracing/diagnostic reporting for resolution failures. Report each file path and key function or class.

## Context

You are working on a codebase task involving repos from the migration domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/TypeScript--v5.7.2.

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

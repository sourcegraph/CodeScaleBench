# GCC RTL Intermediate Representation Pass Chain

## Your Task

Trace how GCC's RTL (Register Transfer Language) passes are organized and executed in gcc. Find C++ source files implementing: the RTL pass class, the pass_expand (gimple to RTL), a representative RTL optimization pass, and the final code generation pass.

## Context

You are working on a codebase task involving repos from the crossrepo domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/llvm-project--a8f3c97d, sg-evals/gcc--96dfb333.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/llvm-project--a8f3c97d` (llvm/llvm-project)
- `sg-evals/gcc--96dfb333` (gcc-mirror/gcc)

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

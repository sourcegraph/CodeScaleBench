# LLVM Legacy Pass Manager to New Pass Manager Migration Inventory

## Your Task

LLVM has been migrating from the legacy pass manager to the new pass manager. Find C++ source files in `llvm/llvm-project` under `llvm/lib/Transforms/Scalar/` and `llvm/lib/Transforms/IPO/` that still contain references to legacy pass manager infrastructure. Specifically, find files that: 1. Use `INITIALIZE_PASS` or `INITIALIZE_PASS_BEGIN`/`INITIALIZE_PASS_END` macros. 2. Inherit from `FunctionPass` or `ModulePass` (legacy base classes). 3. Define `create*Pass()` factory functions (legacy registration pattern). Report each file path and which legacy patterns it uses.

## Context

You are working on a codebase task involving repos from the migration domain.

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
    {"repo": "repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

# Agentic Correctness: Implement Minimal GCC GIMPLE Pass

## Your Task

Write C/C++ source files implementing a minimal GCC GIMPLE optimization pass that counts basic blocks per function. Your implementation must follow GCC's established patterns: 1. Define a `pass_data` struct and inherit from `gimple_opt_pass` as seen in existing passes. 2. Implement `gate()` and `execute()` virtual methods following the pattern in `gcc/tree-ssa-dce.cc`. 3. Register the pass using `make_pass_*()` factory function as defined in `gcc/tree-pass.h`. 4. Use `dump_file` for debug output following existing patterns. Write your files to `/workspace/`. Also write `/workspace/answer.json` listing the GCC source files you referenced.

## Context

You are working on a codebase task involving repos from the org domain.

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
- **Keyword presence**: Are required terms present in your explanation?

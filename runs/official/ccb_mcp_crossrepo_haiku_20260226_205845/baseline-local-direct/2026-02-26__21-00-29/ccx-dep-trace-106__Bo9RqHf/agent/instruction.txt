# GCC Optimization Pass Registration and Execution Chain

## Your Task

Trace how GCC's optimization passes are registered and executed during compilation. Find all C/C++ source files in `gcc-mirror/gcc` that: 1. Define the pass execution order (`gcc/passes.def` — the master list of all passes). 2. Implement the pass manager that orchestrates pass execution (`gcc/passes.cc`). 3. Define the `opt_pass` base class and pass manager interface (`gcc/pass_manager.h`). 4. Implement a concrete GIMPLE optimization pass — specifically dead code elimination (`gcc/tree-ssa-dce.cc`). 5. Define the tree-SSA pass header (`gcc/tree-pass.h`) that declares pass registration macros. Report the repo, file path, and key struct/function name for each file.

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

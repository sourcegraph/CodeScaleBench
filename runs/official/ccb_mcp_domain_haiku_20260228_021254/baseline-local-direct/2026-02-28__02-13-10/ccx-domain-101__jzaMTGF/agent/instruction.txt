# LLVM Optimization Pass Pipeline Propagation

## Your Task

Trace how an LLVM optimization pass is registered in the pass pipeline and executed. Find all C++ source files in `llvm/llvm-project` that participate in the optimization pipeline lifecycle: 1. The file that defines the `PassBuilder` class and its method for building the default O2 optimization pipeline (look in `llvm/lib/Passes/`). 2. The file that defines the `PassManager` template class — the core pass execution engine (look in `llvm/include/llvm/IR/`). 3. The file that implements `PassBuilderPipelines` which assembles the default module/function simplification pipelines. 4. The file that registers all standard passes via `PassRegistry.def`. 5. For a concrete example, the file implementing `DeadStoreElimination` in `llvm/lib/Transforms/Scalar/`. Report the repo, file path, and key class or function name for each.

## Context

You are working on a codebase task involving repos from the domain domain.

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

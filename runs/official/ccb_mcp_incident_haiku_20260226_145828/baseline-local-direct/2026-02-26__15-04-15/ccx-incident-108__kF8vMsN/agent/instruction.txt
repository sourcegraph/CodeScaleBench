# LLVM SelectionDAG Assertion Failure Diagnosis

## Your Task

A production build system using LLVM is crashing with the error: 'Cannot expand this type; LLVM lacks the right hooks'. Trace this assertion to its source in `llvm/llvm-project`. Find: 1. The C++ source file in `llvm/lib/CodeGen/SelectionDAG/` that contains this error message or assertion. 2. The function in that file where the assertion fires (look for type legalization expansion logic). 3. The header file that defines the `EVT` (Extended Value Type) class and its `isSimple()` method (look in `llvm/include/llvm/CodeGen/`). 4. The file that defines the `LegalizeDAG` class which orchestrates type legalization and may call the expand function. Report the repo, file path, and function or class name for each.

## Context

You are working on a codebase task involving repos from the incident domain.

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

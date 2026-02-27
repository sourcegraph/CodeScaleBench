# GCC Internal Compiler Error Diagnosis: GIMPLE Verification Failure

## Your Task

A GCC user reports an Internal Compiler Error (ICE) with the message 'verify_gimple failed'. Trace this error to its source in `gcc-mirror/gcc`. Find: 1. The C++ source file that implements `verify_gimple_in_seq` — the GIMPLE verification pass (`gcc/tree-cfg.cc`). 2. The file that defines the `verify_gimple_stmt` function which checks individual GIMPLE statements. 3. The file where the ICE handler `internal_error` is defined (`gcc/diagnostic.cc` or similar). 4. The `passes.def` file entry where GIMPLE verification is scheduled in the pass pipeline. Report the file path and key function name for each.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories may be relevant to this task:
- `sg-evals/llvm-project--a8f3c97d` (llvm/llvm-project)
- `sg-evals/gcc--96dfb333` (gcc-mirror/gcc)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

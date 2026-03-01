# Onboarding: Rust Compiler Type Inference Architecture

## Your Task

A new contributor wants to understand how the Rust compiler performs type inference. Find the key Rust source files in `rust-lang/rust` under `compiler/rustc_infer/` and `compiler/rustc_hir_typeck/` that define the core type inference engine. Specifically: 1. The file that defines the `InferCtxt` struct (the main inference context). 2. The file that implements `FnCtxt` (the function-level type checker). 3. The file that defines `TypeVariableOrigin` (how type variables are created). Report the file paths and key struct/type names.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/rust--01f6ddf7, sg-evals/servo--be6a2f99.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/rust--01f6ddf7` (rust-lang/rust)
- `sg-evals/servo--be6a2f99` (servo/servo)

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

# Rust Borrow Checker Error Origin Trace

## Your Task

A Rust user reports `error[E0505]: cannot move out of `x` because it is borrowed`. Trace how this error is generated in the Rust compiler. Find: 1. The Rust source file under `compiler/rustc_borrowck/` that implements the MIR borrow checker and detects move-while-borrowed violations. 2. The file that defines the `BorrowckErrors` or error reporting functions for borrow check diagnostics. 3. The file under `compiler/rustc_borrowck/src/diagnostics/` that formats the E0505 error message. 4. The file under `compiler/rustc_error_codes/src/error_codes/` that defines the `E0505` error code explanation. Report each file path and key function/struct.

## Context

You are working on a codebase task involving repos from the incident domain.

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

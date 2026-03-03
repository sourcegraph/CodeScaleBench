# Rust-Servo Shared Style System Discovery

## Your Task

The Rust compiler and Servo browser engine share code via common Rust crates. Find: 1. In `servo/servo`: the Cargo.toml files under `components/style/` and `components/selectors/` that define the `style` and `selectors` crates — report each crate's declared dependencies. 2. In `servo/servo`: the main entry point file for the style system (`components/style/lib.rs`). 3. In `rust-lang/rust`: find if any crate under `compiler/` or `library/` depends on or shares code with Servo's `selectors` crate (search for `selectors` in Cargo.toml files). 4. In `rust-lang/rust`: the file that defines the `proc_macro` bridge which Servo build scripts use. Report each file path and the key dependency or symbol.

## Context

You are working on a codebase task involving repos from the crossorg domain.

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

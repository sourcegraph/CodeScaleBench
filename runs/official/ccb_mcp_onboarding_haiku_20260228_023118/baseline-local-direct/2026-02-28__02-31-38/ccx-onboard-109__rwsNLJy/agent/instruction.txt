# SpiderMonkey JIT Compilation Pipeline

## Your Task

A new contributor wants to understand how Firefox's SpiderMonkey JavaScript engine compiles JS to optimized native code. Find all key C++ source files in `mozilla-firefox/firefox` that define the JIT compilation pipeline stages: 1. The file that implements the top-level `IonCompile` function which orchestrates the Ion optimizing compiler (in `js/src/jit/`). 2. The header and source files for `IonCompileTask` — the off-thread compilation task (in `js/src/jit/`). 3. The file that defines `BaselineJIT` — the first-tier JIT compiler (look for `BaselineScript` class in `js/src/jit/`). 4. The header that defines `JitRuntime` — the per-runtime JIT state (in `js/src/jit/`). 5. The file that defines `JitOptions` — JIT configuration (in `js/src/jit/`). Report the repo, file path, and key class or function name for each file.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/firefox--871325b8.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/firefox--871325b8` (mozilla-firefox/firefox)

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

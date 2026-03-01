# HotSpot JIT Compilation Pipeline Architecture

## Your Task

A new contributor wants to understand how OpenJDK's HotSpot JVM compiles Java bytecode to native machine code. Find the key C++ source files in `openjdk/jdk` under `src/hotspot/share/` that define the JIT compilation pipeline: 1. The header file for `CompileBroker` — the broker that manages all compilation requests (`compiler/compileBroker.hpp`). 2. The header file for `CompilerThread` — the thread type that runs compilation (`compiler/compilerThread.hpp`). 3. The C1 compiler header (`c1/c1_Compiler.hpp`) that defines the first-tier JIT. 4. The C2 compiler header (`opto/c2compiler.hpp`) that defines the optimizing JIT. 5. The file that defines `AbstractCompiler` — the base class for C1 and C2 (`compiler/abstractCompiler.hpp`). Report each file path and key class name.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/jdk--742e735d.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/jdk--742e735d` (openjdk/jdk)

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

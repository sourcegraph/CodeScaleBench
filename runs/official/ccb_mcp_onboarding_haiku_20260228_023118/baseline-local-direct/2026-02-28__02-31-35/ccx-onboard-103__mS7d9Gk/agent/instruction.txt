# LLVM IR-to-Machine-Code Generation Pipeline

## Your Task

A new contributor wants to understand how LLVM lowers IR to machine code. Find the key C++ source files in `llvm/llvm-project` that define the core code generation pipeline stages: 1. The file that defines the `SelectionDAGISel` class which performs instruction selection from LLVM IR to target-specific SelectionDAG nodes (in `llvm/lib/CodeGen/SelectionDAG/`). 2. The file that defines `SelectionDAGBuilder` which translates IR instructions into DAG nodes. 3. The file that implements instruction scheduling (`ScheduleDAGRRList`). 4. The file that implements register allocation (`RegAllocGreedy` in `llvm/lib/CodeGen/`). 5. The file that defines the `MachineFunction` class (the machine-level function representation). Report the repo, file path, and key class name for each.

## Context

You are working on a codebase task involving repos from the onboarding domain.

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

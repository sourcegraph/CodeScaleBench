# LibreOffice Calc Formula Evaluation Chain

## Your Task

An on-call developer is investigating incorrect formula evaluation in LibreOffice Calc. Trace how a cell formula like `=SUM(A1:A10)` is parsed and evaluated. Find the key C++ source files in `LibreOffice/core` under `sc/` that implement the formula engine: 1. The file that implements the formula tokenizer/compiler (`sc/source/core/tool/compiler.cxx` or similar). 2. The file that implements `ScInterpreter` — the formula bytecode interpreter that evaluates formulas. 3. The file that defines `ScFormulaCell` — the cell type that holds a formula and its result. 4. The file that implements `ScRecalcMode` or recalculation scheduling — how Calc determines which cells need recalculation. Report each file path and key class/function.

## Context

You are working on a codebase task involving repos from the incident domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/libreoffice-core--9c8b85f3.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/libreoffice-core--9c8b85f3` (LibreOffice/core)

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

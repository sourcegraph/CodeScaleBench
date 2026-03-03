# LibreOffice Document Model Architecture

## Your Task

A new contributor wants to understand the core document model architecture in LibreOffice. Find the key C++ source files in `LibreOffice/core` that define the document framework: 1. The header file that defines `SfxObjectShell` — the base document shell class that all document types inherit from (look under `include/sfx2/`). 2. The file that defines `SwDoc` — the Writer (word processor) document class (look under `sw/inc/` or `sw/source/core/doc/`). 3. The file that defines `ScDocument` — the Calc (spreadsheet) document class (look under `sc/inc/` or `sc/source/core/data/`). 4. The file that defines `SdDrawDocument` — the Impress/Draw document class (look under `sd/inc/` or `sd/source/core/`). 5. The file that defines `SfxApplication` — the LibreOffice application framework entry point. Report each file path and key class name.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/libreoffice-core--9c8b85f3.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/libreoffice-core--9c8b85f3` (LibreOffice/core)

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

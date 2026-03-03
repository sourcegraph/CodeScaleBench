# Node.js CommonJS to ESM Module Loader Migration Surface

## Your Task

Find all JavaScript and C++ source files in nodejs/node that implement the ESM loader and CJS-ESM interop bridge. Identify: the ModuleLoader class (lib/internal/modules/esm/loader.js), the CJS loader's ESM fallback (finalizeEsmResolution in lib/internal/modules/cjs/loader.js), the ESM translators for different formats, the ESM specifier resolver, the ModuleJob linking/evaluation pipeline, the entry point ESM detection (run_main.js), and the native ModuleWrap C++ binding.

## Context

You are working on a codebase task involving repos from the migration domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/node--v22.13.0.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/node--v22.13.0` (nodejs/node)

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

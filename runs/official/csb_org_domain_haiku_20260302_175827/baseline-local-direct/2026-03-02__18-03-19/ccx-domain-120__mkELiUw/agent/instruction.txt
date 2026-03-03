# Domain Lineage: Strata FxVanillaOption Type Family Graph

## Your Task

Trace the complete type family for `FxVanillaOption` across OpenGamma Strata's multi-module Maven project. Find: 1. The 4 core Joda-Beans domain classes: `FxVanillaOption`, `FxVanillaOptionTrade`, `ResolvedFxVanillaOption`, `ResolvedFxVanillaOptionTrade` — report each file path under `modules/product/`. 2. The 4 pricer classes (Black, Normal, Vanna-Volga, Implied-Tree variants) under `modules/pricer/` that price these types. 3. The 4 measure calculation classes under `modules/measure/` that wire pricers to the calculation engine. 4. The `FxVanillaOptionTradeCsvPlugin` loader under `modules/loader/`. 5. The `FxSingleBarrierOption` class that embeds `FxVanillaOption` as a dependency. For each file, report the module, path, and class name.

## Context

You are working on a codebase task involving repos from the domain domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/Strata--66225ca9.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/Strata--66225ca9` (OpenGamma/Strata)

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

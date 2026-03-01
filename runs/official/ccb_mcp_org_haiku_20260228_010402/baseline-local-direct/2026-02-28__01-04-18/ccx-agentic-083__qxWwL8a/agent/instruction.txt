# Agentic Correctness: Implement Envoy HTTP Filter Following Extension Patterns

## Your Task

Write a C++ header file `pass_through_filter.h` and implementation file `pass_through_filter.cc` that implement a minimal Envoy HTTP filter following the established extension patterns. Your implementation must: 1. Inherit from `Http::StreamDecoderFilter` as defined in the Envoy source. 2. Implement `decodeHeaders`, `decodeData`, and `decodeTrailers` methods following the same signature conventions as existing filters in `source/extensions/filters/http/`. 3. Register the filter using the `REGISTER_FACTORY` macro pattern. 4. Include a `config.cc` factory file following the `NamedHttpFilterConfigFactory` pattern. Write your files to `/workspace/`. Also write `/workspace/answer.json` listing the Envoy source files you referenced for the filter patterns.

## Context

You are working on a codebase task involving repos from the org domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/envoy--v1.31.2, sg-evals/data-plane-api--84e84367, sg-evals/go-control-plane--71637ad6, sg-evals/grpc--957dba5e.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/envoy--v1.31.2` (envoyproxy/envoy)
- `sg-evals/data-plane-api--84e84367` (envoyproxy/data-plane-api)
- `sg-evals/go-control-plane--71637ad6` (envoyproxy/go-control-plane)
- `sg-evals/grpc--957dba5e` (grpc/grpc)

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
- **Keyword presence**: Are required terms present in your explanation?

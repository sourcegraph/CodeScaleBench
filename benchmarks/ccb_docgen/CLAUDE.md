# Documentation Generation Benchmark Suite

This suite tests your ability to generate accurate, comprehensive documentation for code — API references, module documentation, and usage guides derived from reading source code.

## Search Strategy

**This repository is large.** You MUST use Sourcegraph MCP tools for documentation:

- Use `keyword_search` to find exported functions, public APIs, and type definitions
- Use `find_references` to understand how APIs are used in practice (for usage examples)
- Use `go_to_definition` to read full function signatures, parameter types, and return types
- Use `nls_search` for conceptual queries like "error handling patterns" or "configuration options"
- Use `read_file` to examine existing documentation, docstrings, and comments
- Use `list_files` to discover module structure and identify what needs documenting
- Use `deepsearch` to understand complex subsystems before documenting them

## Output Requirements

Write your documentation to `/workspace/documentation.md`.

Your documentation MUST include:
1. **Module Overview** - What the module/package does and its role in the system
2. **API Reference** - Functions, classes, and types with signatures, parameters, and return values
3. **Usage Examples** - Practical code examples showing common use cases
4. **Configuration** - Available options, environment variables, and defaults
5. **Error Handling** - Common errors, their causes, and how to handle them

Generate documentation from the actual source code. Do NOT fabricate APIs or parameters that don't exist in the codebase.

# Documentation Generation Benchmark Suite

This suite tests your ability to generate accurate, comprehensive documentation for code — API references, module documentation, and usage guides derived from reading source code.

## Search Strategy

**This repository is large.** Use code search tools to efficiently navigate:

- Search for exported functions, public APIs, and type definitions by keyword
- Trace how APIs are used in practice via references (for usage examples)
- Navigate to definitions to read full function signatures, parameter types, and return types
- Use semantic search for conceptual queries like "error handling patterns" or "configuration options"
- Read existing documentation, docstrings, and comments for context
- Explore module structure to identify what needs documenting

## Output Requirements

Write your documentation to `/workspace/documentation.md`.

Your documentation MUST include:
1. **Module Overview** - What the module/package does and its role in the system
2. **API Reference** - Functions, classes, and types with signatures, parameters, and return values
3. **Usage Examples** - Practical code examples showing common use cases
4. **Configuration** - Available options, environment variables, and defaults
5. **Error Handling** - Common errors, their causes, and how to handle them

Generate documentation from the actual source code. Do NOT fabricate APIs or parameters that don't exist in the codebase.

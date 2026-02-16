# NL Codebase Q&A Benchmark Suite

This suite tests your ability to answer natural-language questions about large codebases — finding specific implementations, explaining architectural decisions, and tracing data flows.

## Search Strategy

**This repository is large.** Use code search tools to efficiently navigate:

- Search for specific symbols, constants, config keys, or error messages by keyword
- Use semantic/conceptual search when you don't know exact identifiers (e.g., "authentication middleware", "rate limiting logic")
- Trace how a symbol is used across the codebase via references
- Navigate to definitions to understand type hierarchies, interfaces, and function contracts
- Read full implementations once you've located the relevant file

## Output Requirements

Write your answer to `/logs/agent/investigation.md`.

Your answer MUST include:
1. **Answer** - Direct, concise answer to the question
2. **Evidence** - Code references with file paths and line numbers supporting your answer
3. **Reasoning** - How you arrived at the answer, including search strategy used
4. **Related Components** - Other files/modules relevant to the question

Be precise — cite specific files, functions, and line numbers. Avoid vague or speculative answers.

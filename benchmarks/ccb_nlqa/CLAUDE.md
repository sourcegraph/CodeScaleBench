# NL Codebase Q&A Benchmark Suite

This suite tests your ability to answer natural-language questions about large codebases — finding specific implementations, explaining architectural decisions, and tracing data flows.

## Search Strategy

**This repository is large.** You MUST use Sourcegraph MCP tools for investigation:

- Use `keyword_search` to locate specific symbols, constants, config keys, or error messages
- Use `nls_search` for conceptual/semantic queries when you don't know exact identifiers (e.g., "authentication middleware", "rate limiting logic")
- Use `find_references` to trace how a symbol is used across the codebase
- Use `go_to_definition` to understand type hierarchies, interfaces, and function contracts
- Use `read_file` to read full implementations once you've located the relevant file
- Use `deepsearch` for broad "how does X work?" questions that require multi-file reasoning

## Output Requirements

Write your answer to `/logs/agent/investigation.md`.

Your answer MUST include:
1. **Answer** - Direct, concise answer to the question
2. **Evidence** - Code references with file paths and line numbers supporting your answer
3. **Reasoning** - How you arrived at the answer, including search strategy used
4. **Related Components** - Other files/modules relevant to the question

Be precise — cite specific files, functions, and line numbers. Avoid vague or speculative answers.

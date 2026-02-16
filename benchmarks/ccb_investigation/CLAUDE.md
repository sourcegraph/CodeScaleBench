# Investigation Benchmark Suite

This suite tests your ability to investigate code-level phenomena in large codebases.

## Search Strategy

**This repository is large.** Use code search tools to efficiently navigate:

- Search for specific symbols, configs, or patterns by keyword
- Trace symbol usage and references across the codebase
- Navigate to definitions to understand type hierarchies and function contracts
- Search commit history to find recent changes that may have caused regressions
- Search diffs to find what code was added or removed in recent changes

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md`.

Your report MUST include:
1. **Summary** - 1-2 sentence finding
2. **Root Cause** - Specific file, function, and mechanism
3. **Evidence** - Code references with file paths and line numbers
4. **Affected Components** - List of packages/modules impacted
5. **Recommendation** - Fix strategy or migration path

Do NOT write code fixes. Your job is investigation and analysis only.

# Security Vulnerability Triage Benchmark Suite

This suite tests your ability to identify, classify, and triage security vulnerabilities in codebases — analyzing attack surfaces, tracing tainted data flows, and assessing severity.

## Search Strategy

**This repository is large.** Use code search tools to efficiently navigate:

- Search for security-sensitive patterns: user input handling, SQL queries, file operations, auth checks, crypto usage
- Trace tainted data flows from input sources to sinks via references
- Navigate to definitions to understand validation functions, sanitizers, and auth middleware
- Search diffs to find recent changes that may have introduced vulnerabilities
- Search commit history for security-related fixes or patches

## Output Requirements

Write your triage report to `/logs/agent/triage.md`.

Your report MUST include:
1. **Summary** - Vulnerability classification (CWE if applicable) and severity (Critical/High/Medium/Low)
2. **Attack Vector** - How the vulnerability can be exploited, including entry points
3. **Affected Code** - Specific files, functions, and line numbers containing the vulnerability
4. **Root Cause** - Why the vulnerability exists (missing validation, broken auth, etc.)
5. **Recommendation** - Concrete fix strategy with code-level guidance

Do NOT write code fixes. Your job is triage and analysis only.

# Project Context

You are analyzing a codebase for a code understanding task. This file provides guidance on using your available tools effectively.

## Sourcegraph Deep Search MCP

You have access to the Sourcegraph Deep Search MCP server for intelligent semantic code search.

### Available MCP Tool

**mcp__deepsearch__deepsearch**
Deep semantic code search that understands relationships and context.

Use this tool for:
- Finding implementations of concepts across the codebase
- Understanding how components relate to each other
- Tracing data flow and dependencies
- Locating where specific functionality is defined

### Effective Search Strategies

1. **Start broad, then narrow**
   - First search: "authentication flow in this project"
   - Follow-up: "JWT token validation function"

2. **Search for concepts, not just keywords**
   - "functions that handle database queries"
   - "error handling in API endpoints"
   - "how does the caching layer work"

3. **Use specific patterns when helpful**
   - "validate functions in the user module"
   - "Controller classes that handle requests"

4. **Trace dependencies and relationships**
   - "what calls the processOrder function"
   - "where is UserService imported"

### CRITICAL: Always Reference the Repository

When making Deep Search queries, ALWAYS include the repository reference:
- CORRECT: "In sg-benchmarks/[repo-name], where is the authentication logic?"
- CORRECT: "Search sg-benchmarks/[repo-name] for error handling"
- WRONG: "Where is the authentication logic?" (too vague)

The repository name is provided in your task instructions.

### Example Workflow

1. **Read the task question carefully**
   - Understand what you need to find or analyze

2. **Use Deep Search to find relevant code**
   - Start with a conceptual query about the problem
   - Include the repository reference in your query
   - Example: "In sg-benchmarks/myrepo, where does the API handle user creation?"

3. **Read the files Deep Search identifies**
   - Use the Read tool to examine promising files
   - Look for the specific code sections mentioned

4. **Explore locally for additional context**
   - Check related files in /app/project/
   - Trace imports and dependencies

5. **Synthesize your findings**
   - Write your analysis to /logs/agent/solution.md
   - Include file paths and code evidence

## Task Output Requirements

Your solution.md MUST include:

1. **Key Files Identified** - List all relevant files with full paths
2. **Code Evidence** - Include code blocks showing what you found
3. **Analysis** - Explain your findings in detail
4. **Summary** - Concise answer with key technical terms

## For Code Modification Tasks

If the task requires you to modify code:

1. **IMPLEMENT changes directly in /app/project/**
   - Make the actual code modifications
   - Your changes will be evaluated

2. **Document in solution.md**
   - List files you modified
   - Show before/after code
   - Explain what you changed and why

3. **Verify your changes**
   - Run relevant tests if available
   - Check that your modifications are complete

## File Paths

- Codebase location: /app/project/
- Solution output: /logs/agent/solution.md (REQUIRED)

Always use full paths when referencing files (e.g., /app/project/src/handlers/auth.ts)

# RepoQA: Code Navigation Task

## Overview

You are searching a large codebase for a specific function based on its behavior.

**Repository**: {repository}  
**Language**: {language}  
**Commit**: {commit}

## Your Task

Find the function that matches this description:

```
{function_description}
```

## Instructions

1. **Use Sourcegraph MCP** to search for the function
   - Search by behavior, not by name
   - Use semantic search queries that describe what the function does
   - Explore call graphs and dependencies to understand context

2. **Do NOT attempt to guess** based on function naming patterns alone

3. **Provide your answer** as JSON with the exact format:

```json
{
  "function_path": "path/to/file.py",
  "function_name": "function_name",
  "justification": "Brief explanation of why this function matches the description"
}
```

## Important

- The function path should be relative to the repository root
- The function name should be the exact name as it appears in the code
- Your justification should reference the function's behavior, not just its location
- If you cannot find a matching function, return your best guess with an honest justification

## Evaluation

Your response will be scored based on:
- **Exact Match** (1.0): Correct path AND correct function name
- **Partial Match** (0.3-0.8): Close approximations
- **Justification Score**: How well your explanation matches the actual behavior

Use Sourcegraph MCP tools liberally. They are designed exactly for this task.

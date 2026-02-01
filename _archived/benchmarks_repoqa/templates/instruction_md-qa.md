# RepoQA: Multi-Hop Dependency QA (MD-QA)

## Task: Find the Call Path

You are analyzing a large codebase to understand data flow and dependency relationships.

**Repository**: {repository}  
**Language**: {language}  
**Commit**: {commit}

## Question

```
{function_description}
```

## What We're Looking For

1. The **root function** that ultimately enforces or handles the requirement
2. A **valid call path** from an entrypoint to that function

Example:
- Question: "Which function validates user credentials in the login flow?"
- Root: `auth/validators.py::validate_credentials`
- Path: `http_handlers/login.py::handle_login_post` → `auth/middleware.py::authenticate_user` → `auth/validators.py::validate_credentials`

## Search Strategy

1. **Identify the entrypoint** (typically an HTTP handler, CLI command, or main function)
2. **Trace the call chain** using Sourcegraph MCP
3. **Find the leaf function** that actually performs the work
4. **Verify the path** is valid in the codebase

### Sourcegraph MCP Tools

- **`search_codebase`**: Find handler/entrypoint functions
- **`get_call_graph`**: Trace call chains
- **`get_callers`**: Find what calls each function
- **`get_definition`**: Verify functions exist

## Output Format

```json
{
  "root_function": "path/to/file.py::function_name",
  "dependency_path": [
    "path/to/handler.py::entrypoint",
    "path/to/middleware.py::middleware_func",
    "path/to/core.py::root_function"
  ]
}
```

### Path Requirements

- Each element must be a valid function in the codebase
- Path should represent actual calls (verifiable in call graph)
- At least 2 steps (entrypoint + target)
- Last element should be the root function

## Scoring

- ✅ **Perfect** (1.0+): Correct root AND valid call path
- ✅ **Good** (0.5-0.9): Correct root OR valid prefix of path
- ⚠️ **Partial** (0.2-0.4): Plausible but incomplete
- ❌ **Incorrect** (0.0): Wrong root or invalid path

## Tips

- Use call graph queries to verify each step exists
- The path doesn't need to be the shortest path, just valid
- If multiple valid paths exist, any one is acceptable
- Focus on finding the root function first, then trace backwards

Use Sourcegraph MCP graph tools extensively for this task.

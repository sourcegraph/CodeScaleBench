# ArangoDB Authentication and Authorization Audit

## Your Task

Audit the authentication and authorization infrastructure in ArangoDB. Find all C++ source files in `arangodb/arangodb` that implement auth: 1. The file under `arangod/Auth/` or `arangod/RestHandler/` that implements user authentication (look for `AuthenticationHandler` or `UserManager`). 2. The file that implements JWT token validation for the REST API. 3. The file that defines `ExecContext` or the authorization context that checks permissions for database operations. 4. The file under `arangod/RestHandler/` that implements the `/_api/user` REST endpoint for user management. 5. The configuration file or source that defines default authentication settings (`arangosh` or `arangod` startup options). Report each file path and key class/function.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/arangodb--a5cca0b8.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/arangodb--a5cca0b8` (arangodb/arangodb)

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

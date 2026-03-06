# TiDB SQL Privilege Check and RBAC Enforcement Audit

## Your Task

Audit the privilege and RBAC enforcement in pingcap/tidb. Find all Go source files under pkg/privilege/ and pkg/planner/ that implement privilege checking for SQL statements. Identify: the PrivilegeManager interface, the MySQLPrivilege cache, the RequestVerification method and its callers, the role graph resolution logic, and any files that map SQL statement types to required privileges. For each file report the path and its role in the privilege check flow.

## Context

You are working on a codebase task involving repos from the compliance domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/tidb--v8.5.0.

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

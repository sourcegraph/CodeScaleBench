# ClickHouse Access Control and Row-Level Security Policy Audit

## Your Task

Audit the access control and row-level security implementation in ClickHouse/ClickHouse. Find all C++ source and header files under src/Access/ that implement: the AccessControl manager and its user/role resolution, the RowPolicy filter generation and attachment to queries, the ContextAccess class that checks permissions per query, the IAccessStorage interface hierarchy (UsersConfigAccessStorage, DiskAccessStorage, ReplicatedAccessStorage), and the GRANT/REVOKE statement handlers. Report each file path and key class.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/ClickHouse--v24.12.

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

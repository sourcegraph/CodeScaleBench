# Ceph OSD Authentication and Cephx Protocol Implementation

## Your Task

Find all C++ source and header files in ceph/ceph under src/auth/ and src/mon/ that implement the Cephx authentication protocol used by OSD daemons. Identify: the CephxServiceHandler and CephxClientHandler classes, the AuthAuthorizer interface, the MonClient authentication handshake methods, the key rotation and ticket generation logic, and any files defining the AUTH_CEPHX protocol message types. Report each file path and the primary class or struct it defines.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/ceph--v19.2.1.

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

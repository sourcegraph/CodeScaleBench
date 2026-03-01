# Firefox NSS TLS Implementation Audit

## Your Task

Audit the TLS/SSL implementation in Firefox's Network Security Services (NSS) library. Find all C source files in `mozilla-firefox/firefox` under `security/nss/lib/ssl/` that implement core TLS protocol handling: 1. The file that implements SSL 3.0/TLS record processing and cipher suite negotiation (`ssl3con.c`). 2. The file that implements TLS 1.3 handshake and record processing (`tls13con.c`). 3. The file that implements DTLS-specific protocol handling (`dtlscon.c`). 4. The file that implements ECC cipher suite operations (`ssl3ecc.c`). 5. The header file that declares experimental SSL APIs (`sslexp.h`). Report the repo, file path, and the primary protocol function or feature each file implements.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/firefox--871325b8.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/firefox--871325b8` (mozilla-firefox/firefox)

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

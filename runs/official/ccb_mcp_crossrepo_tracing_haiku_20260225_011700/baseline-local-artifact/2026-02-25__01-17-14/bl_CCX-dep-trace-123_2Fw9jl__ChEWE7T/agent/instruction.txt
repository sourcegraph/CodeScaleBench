# Firefox Necko Networking to NSS TLS Handshake Chain

## Your Task

Trace how Firefox initiates a TLS connection from the networking layer to the crypto layer. Find: 1. The C++ source file in `netwerk/protocol/http/` that creates an SSL transport for HTTPS connections (look for `nsHttpConnection` or `TLSFilterTransaction`). 2. The file in `netwerk/socket/` that defines the `nsSSLIOLayerHelpers` class which bridges Necko to NSS. 3. The file in `security/manager/ssl/` that implements `nsNSSIOLayer` — the NSS I/O layer integration. 4. The file in `security/nss/lib/ssl/` that performs the actual TLS handshake (`sslsecur.c` or `ssl3con.c`). Report the file path and key class/function for each hop.

## Context

You are working on a codebase task involving repos from the crossrepo tracing domain.

## Available Resources

No local repositories are pre-checked out.

**Note:** Additional repositories may be relevant to this task:
- `sg-evals/firefox--871325b8` (mozilla-firefox/firefox)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.cpp", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

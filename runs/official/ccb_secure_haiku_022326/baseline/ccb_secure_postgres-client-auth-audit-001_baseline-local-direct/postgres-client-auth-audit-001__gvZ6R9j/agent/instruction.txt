# big-code-pg-sec-001: PostgreSQL Client Authentication Pipeline Security Analysis

## Task

Trace the PostgreSQL client authentication pipeline from the point a TCP connection is accepted through HBA (Host-Based Authentication) rule matching, password/SCRAM-SHA-256 verification, and role validation to session establishment. Identify all entry points where untrusted client data enters the authentication subsystem, map the complete data flow through each verification stage, and analyze the security properties of the authentication chain.

## Context

- **Repository**: postgres/postgres (C, ~1.5M LOC)
- **Category**: Security Analysis
- **Difficulty**: hard
- **Subsystem Focus**: `src/backend/libpq/` (auth.c, auth-scram.c, auth-sasl.c, crypt.c, hba.c) and `src/backend/utils/init/` (postinit.c, miscinit.c)

## Requirements

1. Identify all entry points where untrusted data enters the authentication subsystem (startup packet, password packets, SASL tokens)
2. Trace data flow from each entry point through transformations to sensitive operations (role lookup, password comparison, session establishment)
3. Map the HBA configuration matching pipeline (`load_hba` -> `check_hba` -> `hba_getauthmethod`)
4. Trace the password verification chain through both plaintext (`CheckPasswordAuth`) and challenge-response (`CheckPWChallengeAuth`) paths
5. Trace the SCRAM-SHA-256 exchange through the SASL framework (`auth-sasl.c`) to the SCRAM implementation (`auth-scram.c`)
6. Identify all files in the attack surface and document existing mitigations

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file.ext — role in attack surface
...

## Entry Points
1. path/to/entry.ext:function_name — accepts [type of untrusted input]
...

## Data Flow
### Flow 1: [name]
1. Source: path/to/source.ext (untrusted input enters here)
2. Transform: path/to/transform.ext (data is [processed/validated/not validated])
3. Sink: path/to/sink.ext (sensitive operation: [db query/file write/exec/etc.])

## Dependency Chain
[Ordered list of files from entry to sink]

## Analysis
[Detailed security analysis including:
- Vulnerability class (injection, auth bypass, SSRF, etc.)
- Existing mitigations and their gaps
- Attack scenarios
- Recommended remediation]

## Summary
[Concise description of the vulnerability and its impact]
```

## Evaluation Criteria

- Attack surface coverage: Did you identify all files in the authentication data flow?
- Entry point identification: Did you find the correct entry points (postmaster, startup packet, auth handlers)?
- Data flow completeness: Did you trace the full path from connection to session?
- Analysis quality: Is the authentication architecture correctly described?

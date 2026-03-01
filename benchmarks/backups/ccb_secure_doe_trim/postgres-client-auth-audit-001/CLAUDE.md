# big-code-pg-sec-001: PostgreSQL Client Authentication Pipeline

This repository is large (~1.5M LOC). Use targeted search to trace data flows from entry points to sensitive operations.

## Task Type: Security Analysis

Your goal is to analyze the PostgreSQL client authentication subsystem for security properties by tracing data flow. Focus on:

1. **Entry point identification**: Find where untrusted client data enters the authentication subsystem
2. **Data flow tracing**: Follow data through HBA matching, password verification, SCRAM exchange to session establishment
3. **Mitigation assessment**: Identify existing security controls (constant-time comparison, mock auth, etc.)
4. **Vulnerability classification**: Name specific vulnerability classes (auth bypass, timing attack, username enumeration)

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the attack surface

## Entry Points
1. path/to/entry.ext:function_name — accepts [type of untrusted input]

## Data Flow
### Flow 1: [name]
1. Source: path/to/source.ext (untrusted input enters)
2. Transform: path/to/transform.ext (data processed/validated)
3. Sink: path/to/sink.ext (sensitive operation)

## Dependency Chain
[Ordered list of files from entry to sink]

## Analysis
[Vulnerability class, existing mitigations, gaps, attack scenarios, remediation]

## Summary
[Concise vulnerability description and impact]
```

## Search Strategy

- Start in `src/backend/libpq/auth.c` — the central authentication dispatcher
- Trace upward to `src/backend/postmaster/postmaster.c` for connection acceptance
- Trace downward to `src/backend/libpq/crypt.c` for password verification
- Search for SCRAM implementation in `src/backend/libpq/auth-scram.c`
- Look for HBA configuration parsing in `src/backend/libpq/hba.c`
- Check role validation in `src/backend/utils/init/miscinit.c`
- Use `find_references` to trace how `ClientAuthentication` is called

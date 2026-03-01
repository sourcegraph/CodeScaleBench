# big-code-django-sec-001: Django CSRF Protection and Session Handling Security Analysis

## Task

Trace the Django CSRF protection and session handling pipeline from HTTP request reception through CSRF token validation and session data decoding to response cookie setting. Identify all entry points where untrusted data enters the CSRF/session subsystem, map the data flow through token generation, masking, validation, and session signing, and analyze the cryptographic security properties of the pipeline.

## Context

- **Repository**: django/django (Python, ~350K LOC)
- **Category**: Security Analysis
- **Difficulty**: hard
- **Subsystem Focus**: `django/middleware/csrf.py`, `django/contrib/sessions/`, `django/core/signing.py`, `django/utils/crypto.py`

## Requirements

1. Identify all entry points where untrusted data enters the CSRF/session subsystem (HTTP cookies, POST data, headers)
2. Trace the CSRF middleware pipeline: `process_request` (read secret) -> `process_view` (validate token) -> `process_response` (set cookie)
3. Trace the session middleware pipeline: `process_request` (load session) -> `process_response` (save + set cookie)
4. Map the cryptographic chain: `crypto.py` (salted_hmac, constant_time_compare) -> `signing.py` (Signer, TimestampSigner) -> session encode/decode
5. Analyze the CSRF token masking scheme (cipher mask to prevent BREACH attacks) and its security properties
6. Document cookie security attributes (HttpOnly, Secure, SameSite) and their interaction with CSRF protection

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

- Attack surface coverage: Did you identify all files in the CSRF/session data flow?
- Entry point identification: Did you find the correct entry points (middleware hooks, cookie parsing)?
- Data flow completeness: Did you trace the full path from request to response?
- Analysis quality: Are the cryptographic properties correctly described?

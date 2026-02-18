# big-code-django-sec-001: Django CSRF Protection and Session Handling

This repository is large (~350K LOC). Use targeted search to trace data flows from entry points to sensitive operations.

## Task Type: Security Analysis

Your goal is to analyze Django's CSRF protection and session handling for security properties by tracing data flow. Focus on:

1. **Entry point identification**: Find where untrusted data enters the CSRF/session subsystem (cookies, POST data, headers)
2. **Data flow tracing**: Follow data through middleware hooks, token validation, session decode, to response cookies
3. **Mitigation assessment**: Identify existing security controls (HMAC signing, constant-time compare, SameSite cookies)
4. **Vulnerability classification**: Name specific vulnerability classes (CSRF bypass, session fixation, cookie theft)

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

- Start in `django/middleware/csrf.py` — the CSRF middleware
- Trace crypto to `django/utils/crypto.py` and `django/core/signing.py`
- Search for session handling in `django/contrib/sessions/middleware.py` and `django/contrib/sessions/backends/`
- Look for cookie handling in `django/http/response.py` (set_cookie, set_signed_cookie)
- Check cookie parsing in `django/http/cookie.py` and request handling in `django/http/request.py`
- Use `find_references` to trace how `CsrfViewMiddleware.process_view` validates tokens

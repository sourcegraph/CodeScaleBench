# Add Request Rate Limiting Middleware to Django

**Repository:** django/django
**Access Scope:** You may create/modify files in `django/middleware/`. You may read any file to understand existing patterns.

## Context

You are adding a new rate-limiting middleware to Django. The codebase has an architecture document at `docs/architecture.md` that describes how middleware should be structured. However, you should always follow the **actual code patterns** you observe in existing middleware files, not just documentation — code is the source of truth.

## Task

Create a new middleware `django/middleware/ratelimit.py` that limits the number of requests per IP address within a time window.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Create `django/middleware/ratelimit.py` with a `RateLimitMiddleware` class
2. The middleware must follow the **same pattern** as existing Django middleware. Study these files to understand the real conventions:
   - `django/middleware/csrf.py` — how it inherits, processes requests/responses
   - `django/middleware/security.py` — how settings are accessed
   - `django/middleware/common.py` — how request attributes are checked
   - `django/middleware/cache.py` — how middleware state is managed
3. The middleware should:
   - Read `settings.RATE_LIMIT_REQUESTS` (default: 100) and `settings.RATE_LIMIT_WINDOW` (default: 3600 seconds) from Django settings
   - Track requests per IP using an in-memory dictionary with timestamps
   - Return `HttpResponseForbidden` (from `django/http`) when the limit is exceeded, with a message indicating rate limit hit
   - Include the client IP in the response for debugging (use `request.META.get('REMOTE_ADDR')`)
   - Clean up expired entries periodically (every 100 requests)
4. The middleware must work with Django's standard middleware pipeline:
   - It must be callable as `middleware(request)` after initialization with `get_response`
   - Look at how `SecurityMiddleware.__init__` and `CsrfViewMiddleware.__init__` accept `get_response`
5. You need to read **at least 5 source files** to understand the real middleware pattern before implementing

### Hints

- Existing middleware like `SecurityMiddleware` in `django/middleware/security.py` shows the canonical pattern: `__init__(self, get_response)` + `__call__(self, request)` or using `MiddlewareMixin`
- `django/utils/deprecation.py` defines `MiddlewareMixin` — check if modern middleware uses it or the direct `__init__`/`__call__` pattern
- `django/conf/` contains the settings infrastructure — use `from django.conf import settings`
- `django/http/response.py` has `HttpResponseForbidden` (status 403)
- Do NOT follow the class registry pattern described in docs/architecture.md — that is an outdated proposal that was never implemented

## Success Criteria

- `django/middleware/ratelimit.py` exists and contains `RateLimitMiddleware`
- Follows the actual `__init__(get_response)` / `__call__(request)` middleware pattern (NOT a registry pattern)
- Uses `settings.RATE_LIMIT_REQUESTS` and `settings.RATE_LIMIT_WINDOW` with defaults
- Returns `HttpResponseForbidden` when rate limit exceeded
- Tracks per-IP request counts with time window
- Valid Python syntax
- Changes limited to `django/middleware/`

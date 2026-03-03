# Add Request Rate Limiting Middleware

**Repository:** django/django
**Access Scope:** You may create/modify files in `django/middleware/`. You may read any file to understand existing patterns.

## Context

You are adding a new rate-limiting middleware to Django. The codebase contains an architecture document at `docs/architecture.md` that describes how middleware should be structured. However, documentation can sometimes be outdated or describe proposals that were never adopted. **Always follow the patterns you observe in the actual source code of existing middleware** — working code is the source of truth.

## Feature Request

**From:** Security Team
**Priority:** P1

We need middleware to rate-limit incoming HTTP requests by IP address. When a client exceeds the allowed number of requests within a time window, the middleware should reject further requests with a 403 Forbidden response.

### Deliverables

Create `django/middleware/ratelimit.py` containing a `RateLimitMiddleware` class that:

1. **Follows Django's real middleware conventions** — study the existing middleware implementations already in the codebase to understand the actual patterns used. Do not rely solely on architecture documentation, as it may describe patterns that were proposed but never implemented.

2. Reads two Django settings for configuration:
   - `RATE_LIMIT_REQUESTS` — maximum requests per window (default: 100)
   - `RATE_LIMIT_WINDOW` — time window in seconds (default: 3600)

3. Tracks requests per client IP address using an in-memory dictionary with timestamps

4. Returns an HTTP 403 response when the rate limit is exceeded, including a message indicating the rate limit was hit and the client's IP address

5. Cleans up expired tracking entries periodically (every 100 requests)

6. Works correctly within Django's standard middleware pipeline

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. `RateLimitMiddleware` class in `django/middleware/ratelimit.py`
2. Must follow the **actual** middleware pattern used by existing Django middleware (read the source code of existing middleware, not just documentation)
3. Per-IP request counting with configurable limits via Django settings
4. Returns 403 when rate limit exceeded
5. Valid Python syntax
6. Changes limited to `django/middleware/`

## Success Criteria

- `django/middleware/ratelimit.py` exists with `RateLimitMiddleware`
- Follows the real Django middleware pattern (as implemented in existing middleware)
- Uses `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW` settings with defaults
- Returns 403 when rate limit exceeded
- Tracks per-IP request counts with time window
- Valid Python syntax
- Changes limited to `django/middleware/`

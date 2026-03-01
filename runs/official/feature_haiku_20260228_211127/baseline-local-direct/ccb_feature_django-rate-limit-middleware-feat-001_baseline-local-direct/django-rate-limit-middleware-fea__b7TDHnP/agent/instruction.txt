# Task: Implement RateLimitMiddleware for Django

## Objective
Create a new `RateLimitMiddleware` class in `django/middleware/ratelimit.py` that provides
configurable per-IP request rate limiting using Django's cache framework.

## Requirements

1. **Create `django/middleware/ratelimit.py`** with a `RateLimitMiddleware` class that:
   - Inherits from `MiddlewareMixin` (see `django/utils/deprecation.py`)
   - Reads configuration from `settings.RATE_LIMIT_REQUESTS` (default: 100) and `settings.RATE_LIMIT_WINDOW` (default: 3600 seconds)
   - Uses Django's cache framework (`django.core.cache.cache`) to track request counts per IP
   - Returns `HttpResponseTooManyRequests` (429) when limit is exceeded
   - Implements `process_request(self, request)` following the middleware pattern

2. **Update `django/http/__init__.py`** to export `HttpResponseTooManyRequests` if not already present

3. **Create `tests/middleware/test_ratelimit.py`** with test cases for:
   - Normal requests within limit
   - Requests exceeding limit
   - Cache key isolation per IP
   - Custom settings override

## Key Reference Files
- `django/middleware/csrf.py` — middleware pattern with `process_request`/`process_view`
- `django/middleware/common.py` — middleware using settings and returning responses
- `django/utils/deprecation.py` — `MiddlewareMixin` base class
- `django/core/cache/__init__.py` — cache framework API
- `django/http/response.py` — HTTP response classes (HttpResponseForbidden, etc.)

## Success Criteria
- RateLimitMiddleware class exists and follows Django middleware conventions
- Uses cache framework for rate tracking (not in-memory dict)
- Returns 429 status code when rate limit exceeded
- Has proper imports from django.conf, django.core.cache, django.http
- Test file exists with JUnit-style test methods

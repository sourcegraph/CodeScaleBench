# Task: Generate Unit Tests for Django Cache Middleware

**Repository:** django/django
**Output:** Write your test file to `/workspace/tests/test_cache_middleware.py`

## Objective

Generate comprehensive unit tests for Django's cache middleware (`django/middleware/cache.py`). This module implements `UpdateCacheMiddleware` and `FetchFromCacheMiddleware` which together form Django's full-page caching system.

## Scope

Read `django/middleware/cache.py` to understand the classes and their methods. Your tests must cover:

- `UpdateCacheMiddleware.process_response` — caching conditional logic (cacheable vs non-cacheable responses)
- `FetchFromCacheMiddleware.process_request` — cache hit vs cache miss behavior
- Cache-Control header handling (no-cache, max-age, private)
- Vary header interactions
- Non-GET/HEAD method passthrough (POST, PUT, DELETE should not be cached)
- Authenticated request handling

## Content Expectations

Your test file must:
- Use `django.test.TestCase` or `django.test.SimpleTestCase` as base class
- Include at least 8 test methods with `test_` prefix
- Cover at least 3 distinct failure/edge cases (e.g., non-cacheable status codes, missing Vary headers)
- Import and use Django's test client or mock request factories
- Do NOT run the tests yourself — write the test file and the evaluation system validates independently

## Output

Write your test file to:
```
/workspace/tests/test_cache_middleware.py
```

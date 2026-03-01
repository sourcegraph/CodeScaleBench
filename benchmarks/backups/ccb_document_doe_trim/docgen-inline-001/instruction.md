# Task: Generate Python Docstrings for Django Cache Middleware

**Repository:** django/django
**Output:** Write your summary to `/workspace/documentation.md`; edit the source file directly at `/workspace/django/middleware/cache.py`

## Objective

Generate comprehensive Python docstrings for Django's cache middleware module (`django/middleware/cache.py`). The module contains `UpdateCacheMiddleware` and `FetchFromCacheMiddleware` — currently undocumented — which together implement Django's full-page caching system.

## Scope

Read and document the following in `django/middleware/cache.py`:
- `UpdateCacheMiddleware` class and its `process_response` method
- `FetchFromCacheMiddleware` class and its `process_request` method
- `CacheMiddleware` combined middleware class
- Module-level docstring explaining the full-page caching system

## Content Expectations

Each docstring must include:
- **Class docstring**: purpose, typical use case, configuration (CACHE_MIDDLEWARE_* settings)
- **Method docstrings**: `Args:` section with parameter names and types, `Returns:` section, description of side effects
- **At least one usage example** in the module docstring using `.. code-block:: python`
- **Cache-Control and Vary header interactions** documented for `process_response`

## Quality Bar

- Use Google-style or NumPy-style docstrings consistently
- Reference specific Django settings by name (e.g., `CACHE_MIDDLEWARE_SECONDS`)
- Do not fabricate method behavior — read the actual implementation first
- The summary document at `/workspace/documentation.md` must list every class/method documented

## Anti-Requirements

- Do not change the implementation logic — only add docstrings
- Do not document private helper functions unless they are called from public API

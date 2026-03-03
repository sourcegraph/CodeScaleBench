# Task: Rename RequestFactory to TestRequestBuilder

## Objective
Rename the `RequestFactory` class to `TestRequestBuilder` across the Django codebase
to better reflect its purpose as a test utility that builds HTTP request objects.

## Requirements

1. **Rename the class definition** in `django/test/client.py`:
   - `class RequestFactory` → `class TestRequestBuilder`
   - Keep all methods and behavior unchanged

2. **Update all references** across the codebase:
   - Import statements: `from django.test import RequestFactory` → `TestRequestBuilder`
   - Type annotations and docstrings
   - Test files that instantiate RequestFactory
   - Expected: 25+ call sites across django/test/ and tests/

3. **Maintain backward compatibility** (optional alias):
   - Add `RequestFactory = TestRequestBuilder` alias for deprecation

## Key Reference Files
- `django/test/client.py` — class definition
- `django/test/__init__.py` — module exports
- `tests/requests/test_data_upload_settings.py` — usage example
- `tests/test_client/tests.py` — heavy usage

## Success Criteria
- Old symbol `RequestFactory` removed from class definition
- New symbol `TestRequestBuilder` used as class name
- References updated across 80%+ of call sites
- No `class RequestFactory` definition remains (alias is OK)

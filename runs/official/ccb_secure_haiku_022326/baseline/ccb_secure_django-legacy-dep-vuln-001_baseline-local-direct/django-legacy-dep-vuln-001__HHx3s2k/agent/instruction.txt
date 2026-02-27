# Add Encoding-Aware HTML Escaping for GIS Data Pipeline

**Repository:** django/django
**Access Scope:** You may modify `django/utils/html.py`. You may read any file to understand existing patterns and utilities.

## Context

Django's GIS module processes geospatial data from external C libraries (like GDAL) that may return byte strings in non-UTF-8 encodings (Latin-1, Shift-JIS, etc.). When this data needs to be rendered in HTML templates, it must first be converted from its source encoding to a Python string, and then HTML-escaped to prevent XSS.

Currently, developers must manually orchestrate two separate operations — encoding conversion and HTML escaping — in the correct order. Django has existing utility functions for both operations, but they aren't combined. The encoding conversion utilities date back to the Python 2 era and have legacy API conventions (no type hints, non-obvious parameter names, special handling for numeric types) that make them easy to misuse.

## Feature Request

**From:** GIS Team Lead
**Priority:** P2

We need a single utility function that combines encoding conversion and HTML escaping in one atomic operation. This prevents bugs where developers forget a step, apply them in the wrong order, or mishandle the legacy encoding API's special behaviors.

### Deliverables

Add an `escape_with_encoding()` function to `django/utils/html.py` that:

1. Accepts text in any encoding and produces a safe, HTML-escaped string
2. Supports the same parameters as Django's existing string-coercion utilities: encoding name, error handling mode, and the option to skip conversion for certain types
3. When the "skip non-string types" option is enabled and the input is a numeric type (int, float, Decimal, datetime, etc.), returns the value as-is without conversion or escaping — this matches the existing encoding utilities' behavior for "protected types"
4. For all other inputs, converts to a Python string using the specified encoding, then applies Django's standard conditional HTML escaping
5. Handles lazy translation objects correctly (forces evaluation before escaping)

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Function named `escape_with_encoding` in `django/utils/html.py`
2. Must reuse Django's existing encoding conversion and HTML escaping utilities internally — read their source code to understand the legacy API conventions, as these functions predate type hints and have non-obvious parameter semantics
3. Must correctly handle the "protected types" concept from Django's encoding system
4. Must integrate with Django's existing HTML escaping pipeline (including support for objects that declare themselves as already-safe HTML)
5. Valid Python syntax
6. Changes limited to `django/utils/html.py`

## Success Criteria

- `escape_with_encoding()` function exists in `django/utils/html.py`
- Correctly uses Django's existing encoding conversion with all its legacy parameters
- Handles protected types (returns without escaping when configured)
- Integrates with Django's existing conditional HTML escaping
- Valid Python syntax
- Changes limited to `django/utils/html.py`

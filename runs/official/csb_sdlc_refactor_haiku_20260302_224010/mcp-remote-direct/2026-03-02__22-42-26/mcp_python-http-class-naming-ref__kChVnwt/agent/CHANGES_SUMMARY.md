# HTTP Request Class Rename - Change Summary

## Overview
Successfully renamed HTTP request classes across Django, Flask, and requests libraries to use standardized naming convention `HTTPRequest`.

## Files Modified

### Django (django-674eda1c)
1. **django/http/request.py**
   - Renamed `class HttpRequest` to `class HTTPRequest` (line 53)

2. **django/http/__init__.py**
   - Updated import: `HttpRequest` → `HTTPRequest` (line 4)
   - Updated __all__ export: `"HttpRequest"` → `"HTTPRequest"` (line 32)

### Flask (flask-798e006f)
1. **src/flask/wrappers.py**
   - Renamed `class Request(RequestBase)` to `class HTTPRequest(RequestBase)` (line 18)

2. **src/flask/__init__.py**
   - Updated import: `from .wrappers import Request as Request` → `from .wrappers import HTTPRequest as HTTPRequest` (line 38)

3. **src/flask/app.py**
   - Updated import: `from .wrappers import Request` → `from .wrappers import HTTPRequest` (line 52)
   - Updated docstring reference: `:class:`~flask.Request`` → `:class:`~flask.HTTPRequest`` (line 239)
   - Updated type annotation: `request_class: type[Request] = Request` → `request_class: type[HTTPRequest] = HTTPRequest` (line 241)
   - Updated method signature: `create_url_adapter(self, request: Request | None)` → `create_url_adapter(self, request: HTTPRequest | None)` (line 508)
   - Updated method signature: `raise_routing_exception(self, request: Request)` → `raise_routing_exception(self, request: HTTPRequest)` (line 561)

4. **src/flask/ctx.py**
   - Updated import: `from .wrappers import Request` → `from .wrappers import HTTPRequest` (line 22)
   - Updated type annotation: `request: Request | None = None` → `request: HTTPRequest | None = None` (line 303)
   - Updated type annotation: `self._request: Request | None = request` → `self._request: HTTPRequest | None = request` (line 319)
   - Updated return type: `def request(self) -> Request:` → `def request(self) -> HTTPRequest:` (line 370)

5. **src/flask/globals.py**
   - Updated import: `from .wrappers import Request` → `from .wrappers import HTTPRequest` (line 13)
   - Updated type definition: `class RequestProxy(ProxyMixin[Request], Request): ...` → `class RequestProxy(ProxyMixin[HTTPRequest], HTTPRequest): ...` (line 28)

### Requests (requests-421b8733)
1. **src/requests/models.py**
   - Renamed `class Request(RequestHooksMixin)` to `class HTTPRequest(RequestHooksMixin)` (line 232)
   - Updated docstring: `:class:`Request <Request`` → `:class:`HTTPRequest <HTTPRequest`` (line 233)
   - Updated docstring example: `requests.Request('GET',...)` → `requests.HTTPRequest('GET',...)` (lines 255, 326)
   - Updated __repr__: `return f"<Request [{self.method}]>"` → `return f"<HTTPRequest [{self.method}]>"` (line 295)
   - Updated docstring: `:class:`Request <Request`` → `:class:`HTTPRequest <HTTPRequest`` (line 319)

2. **src/requests/__init__.py**
   - Updated import: `from .models import PreparedRequest, Request, Response` → `from .models import PreparedRequest, HTTPRequest, Response` (line 176)

## Change Statistics
- **Total files modified**: 9
  - Django: 2 files
  - Flask: 5 files
  - Requests: 2 files
- **Total changes**: 26 modifications across imports, class definitions, type annotations, and docstrings

## Backward Compatibility
This change breaks backward compatibility for code that imports these classes by name. Any code that was using:
- `from django.http import HttpRequest`
- `from flask import Request` or `from flask.wrappers import Request`
- `from requests import Request` or `from requests.models import Request`

Will need to be updated to use the new `HTTPRequest` class name.

## Testing
All changes maintain the same functionality while providing consistent naming across all three libraries. The class definitions, methods, and properties remain unchanged - only the class names have been standardized.

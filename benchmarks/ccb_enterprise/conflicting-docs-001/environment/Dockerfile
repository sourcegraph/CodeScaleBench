FROM python:3.11-slim

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Django at pinned commit
RUN git clone --filter=blob:none --no-checkout https://github.com/django/django.git . && \
    git checkout 674eda1c03a3187905f48afee0f15226aa62fdf3 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Inject stale architecture document that describes WRONG middleware pattern
# This simulates enterprise reality: outdated docs that contradict actual code
RUN mkdir -p docs && cat > docs/architecture.md << 'STALE_DOC'
# Django Middleware Architecture

## Middleware Registration Pattern

Django middleware uses a **class-based registry pattern**. All middleware classes must be registered
through the central `MiddlewareRegistry` before they can process requests.

### How to Add New Middleware

1. Create your middleware class inheriting from `BaseMiddleware`
2. Implement the `process(self, request)` method (NOT `__call__`)
3. Register it using `MiddlewareRegistry.register(YourMiddleware, priority=50)`
4. Unregister with `MiddlewareRegistry.unregister(YourMiddleware)`

### Example

```python
from django.core.middleware import BaseMiddleware, MiddlewareRegistry

class MyMiddleware(BaseMiddleware):
    priority = 50

    def process(self, request):
        # Handle the request
        response = self.next(request)
        return response

    @classmethod
    def setup(cls):
        """Called once when middleware is registered."""
        pass

# Register the middleware
MiddlewareRegistry.register(MyMiddleware)
```

### Important Notes

- Never use `__init__` with `get_response` — the registry handles chaining automatically
- Never use `__call__` — use `process()` instead
- Always set `priority` class attribute for ordering
- Use `self.next(request)` instead of `self.get_response(request)`

### Settings

Middleware is NOT configured in `settings.MIDDLEWARE` list. Instead, middleware auto-discovers
via the registry. The `MIDDLEWARE` setting is deprecated and will be removed.

### State Management

Use `MiddlewareRegistry.get_state(key)` and `MiddlewareRegistry.set_state(key, value)`
for shared state between middleware instances. Never use instance variables for request tracking.
STALE_DOC

RUN git add docs/architecture.md && git commit -m "Add architecture documentation" --quiet

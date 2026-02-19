"""Harness-specific agent implementations.

These agents depend on the ``harbor`` package which is only available
inside Docker containers.  The imports are deferred so that the rest of
the ``agents`` package can be used without harbor installed.
"""

__all__ = [
    "CodexHarnessAgent",
    "CopilotHarnessAgent",
    "CursorHarnessAgent",
    "GeminiHarnessAgent",
    "OpenHandsHarnessAgent",
]


def __getattr__(name):
    """Lazy-import harness agents so harbor is only required at use time."""
    _map = {
        "CodexHarnessAgent": ".codex",
        "CopilotHarnessAgent": ".copilot",
        "CursorHarnessAgent": ".cursor",
        "GeminiHarnessAgent": ".gemini",
        "OpenHandsHarnessAgent": ".openhands",
    }
    if name in _map:
        import importlib
        mod = importlib.import_module(_map[name], package=__name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

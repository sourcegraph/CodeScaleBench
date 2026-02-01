```python
"""
ledgerquest.engine.scripting.host
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Runtime host for executing user-authored gameplay scripts inside the
serverless LedgerQuest Engine.

The implementation strikes a balance between flexibility (full Python
syntax for power users) and safety (restricted built-ins, per-execution
timeouts, isolated global namespace).  Compiled byte-code is cached to
minimise cold-start latency in Lambda/Fargate workers, while an
Executor keeps CPU-heavy user code off the main asyncio event-loop.

The host exposes a minimal but extensible “native” API that scripts can
use to interact with the wider game-engine––e.g. dispatching events or
querying ECS state.

Usage
-----

    host = ScriptHost()
    host.expose(dispatch_event)

    await host.run_source(\"\"\"
        health = entity.get('health', 100)
        if health <= 0:
            dispatch_event('player_killed', entity_id)
    \"\"\", timeout=0.2)

A host instance can be long-lived (in a warm Lambda container) and is
thread-safe as long as exposed callables are.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import importlib.util
import inspect
import logging
import sys
import textwrap
import time
from functools import lru_cache, wraps
from pathlib import Path
from types import CodeType, MappingProxyType, ModuleType
from typing import Any, Awaitable, Callable, Dict, Optional

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

_LOG = logging.getLogger("ledgerquest.engine.scripting.host")
_LOG.addHandler(logging.NullHandler())

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class ScriptHostError(Exception):
    """Base-class for all host-side scripting errors."""


class ScriptTimeout(ScriptHostError):
    """Raised when a script exceeds its allotted runtime."""


class ScriptSecurityViolation(ScriptHostError):
    """Raised when a script attempts to access a disallowed symbol."""


class ScriptRuntimeError(ScriptHostError):
    """Wrapper around arbitrary exceptions raised by user scripts."""

    def __init__(self, original: BaseException):
        super().__init__(f"script raised {type(original).__name__}: {original}")
        self.original = original


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

_SAFE_BUILTINS = MappingProxyType(
    {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "callable": callable,
        "chr": chr,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "hash": hash,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "pow": pow,
        "print": print,  # hijacked at runtime to funnel through engine logger
        "range": range,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
    }
)

# Any import attempted inside a script will go through this synthetic module
# table.  We could whitelist certain stdlib modules here.
_ALLOWED_IMPORTS = frozenset(
    {
        "math",
        "random",
        "statistics",
        "decimal",
        "fractions",
        "itertools",
        "functools",
        "operator",
        "datetime",
        # NOTE: no file-system, sockets, multiprocessing, etc.
    }
)


def _compile(source: str, filename: str, mode: str = "exec") -> CodeType:
    """Compile source and memoise by SHA-256 hash for cold-start speed."""
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()

    @lru_cache(maxsize=128)  # pylint: disable=function-redefined
    def _inner(_digest: str) -> CodeType:  # noqa: D401
        _LOG.debug("Compiling script (%s)", filename)
        return compile(source, filename, mode)

    return _inner(digest)


def _sandbox_print_factory(execution_id: str) -> Callable[..., None]:
    """Return a print() replacement that routes to engine log."""
    prefix = f"[script:{execution_id}] "

    def _sandbox_print(*args: Any, **kwargs: Any) -> None:
        _LOG.info(prefix + " ".join(map(str, args)), **kwargs)

    return _sandbox_print


def _build_module(name: str, sandbox_globals: Dict[str, Any]) -> ModuleType:
    """Create a synthetic module holding sandbox globals (for 'import *')."""
    mod = ModuleType(name)
    mod.__dict__.update(sandbox_globals)
    return mod


# --------------------------------------------------------------------------- #
# Main Host                                                                   #
# --------------------------------------------------------------------------- #


class ScriptHost:
    """
    Executes Python snippets in a restricted environment.

    Parameters
    ----------
    max_workers:
        Size of the thread pool used to off-load blocking code.
    loop:
        AsyncIO event-loop.  Defaults to `asyncio.get_event_loop()`.
    safe_mode:
        When *True* deny access to dangerous built-ins and arbitrary imports.
    """

    def __init__(
        self,
        *,
        max_workers: int = 8,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        safe_mode: bool = True,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._executor: concurrent.futures.ThreadPoolExecutor = (
            concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        )
        self._safe_mode = safe_mode
        self._exposed_api: Dict[str, Callable[..., Any]] = {}
        self._closed = False

        _LOG.debug(
            "ScriptHost initialised (workers=%d, safe_mode=%s)",
            max_workers,
            safe_mode,
        )

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def expose(
        self, func: Optional[Callable[..., Any]] = None, *, name: Optional[str] = None
    ) -> Callable[..., Any]:
        """
        Register a native callable visible to all scripts.

        Can be used either as a decorator::

            @host.expose
            def dispatch_event(...): ...

        or directly::

            host.expose(dispatch_event, name="dispatch_event")
        """
        if func is None:

            def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
                self.expose(f, name=name)
                return f

            return decorator

        if not callable(func):
            raise TypeError("exposed object must be callable")

        key = name or func.__name__
        self._exposed_api[key] = func
        _LOG.debug("Exposed native callable '%s' to scripts", key)
        return func

    async def run_source(
        self,
        source: str,
        *,
        filename: str = "<string>",
        timeout: Optional[float] = None,
        extra_globals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute *source* in the sandbox.

        Returns the final globals dict of the executed script.
        """
        if self._closed:
            raise RuntimeError("ScriptHost is closed")

        # Normalise and compile
        source = textwrap.dedent(source)
        code = _compile(source, filename)

        # Per-execution globals
        exec_id = f"{time.time_ns():x}"
        gbls = self._build_sandbox(exec_id, extra_globals)

        # Run in executor to avoid blocking event-loop
        fut = self._loop.run_in_executor(
            self._executor, self._run_code, code, gbls, exec_id
        )

        try:
            await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            _LOG.warning("Script timed-out after %.2fs (%s)", timeout or 0.0, filename)
            raise ScriptTimeout(str(exc)) from exc
        except ScriptSecurityViolation:
            raise  # re-raise untouched
        except BaseException as exc:  # pylint: disable=broad-except
            # Wrap arbitrary user exceptions
            if isinstance(exc, ScriptRuntimeError):
                raise
            raise ScriptRuntimeError(exc) from exc

        return gbls

    async def run_file(
        self,
        path: str | Path,
        *,
        timeout: Optional[float] = None,
        extra_globals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Load a local path (**.py**) and execute it inside the sandbox.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)

        source = path.read_text(encoding="utf-8")
        return await self.run_source(
            source, filename=str(path), timeout=timeout, extra_globals=extra_globals
        )

    def close(self) -> None:
        """Shut down the host and its worker pool."""
        if not self._closed:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._closed = True
            _LOG.debug("ScriptHost closed")

    # Make host usable as an async context-manager
    async def __aenter__(self) -> "ScriptHost":
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
        self.close()

    # --------------------------------------------------------------------- #
    # Internals                                                             #
    # --------------------------------------------------------------------- #

    def _build_sandbox(
        self, exec_id: str, extra: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Create the globals dict that user code will execute in.
        """
        gbls: Dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS if self._safe_mode else __builtins__,
            "__name__": f"ledgerquest_script_{exec_id}",
            "__file__": "<sandbox>",
            "__package__": None,
            "__loader__": None,
            "__spec__": None,
            "print": _sandbox_print_factory(exec_id),
            **self._exposed_api,
        }

        if extra:
            gbls.update(extra)

        return gbls

    # This method *must* run in a dedicated thread (invoked by run_in_executor)
    def _run_code(self, code: CodeType, gbls: Dict[str, Any], exec_id: str) -> None:
        _LOG.debug("Executing script %s", exec_id)
        # monkey-patch 'import' if safe-mode
        if self._safe_mode:
            orig_import = builtins.__import__

            def _restricted_import(
                name, globals=None, locals=None, fromlist=(), level=0  # noqa: D401
            ):
                root_mod = name.split(".", 1)[0]
                if root_mod not in _ALLOWED_IMPORTS:
                    raise ScriptSecurityViolation(f"import of '{root_mod}' is blocked")
                return orig_import(name, globals, locals, fromlist, level)

            import builtins  # pylint: disable=redefined-outer-name
            builtins.__import__ = _restricted_import  # type: ignore[attr-defined]
        try:
            exec(code, gbls, gbls)  # pylint: disable=exec-used
        finally:
            if self._safe_mode:
                builtins.__import__ = orig_import  # type: ignore[attr-defined]
        _LOG.debug("Script %s finished", exec_id)


# --------------------------------------------------------------------------- #
# Convenience Singleton (optional)                                            #
# --------------------------------------------------------------------------- #

_default_host: Optional[ScriptHost] = None


def default_host() -> ScriptHost:
    """
    Lazily create a module-level shared ScriptHost.

    This is mainly for quick, frictionless usage by engine subsystems that
    don't want to manage host lifecycles explicitly.
    """
    global _default_host  # pylint: disable=global-statement
    if _default_host is None or _default_host._closed:  # type: ignore[attr-defined]
        _default_host = ScriptHost()
    return _default_host


# --------------------------------------------------------------------------- #
# Example native APIs (would normally live in other engine modules)           #
# --------------------------------------------------------------------------- #


def _demo_dispatch(event_name: str, payload: dict | None = None) -> None:
    """Placeholder for actual event bus integration."""
    _LOG.info("DISPATCH EVENT %s %s", event_name, payload or {})


# Expose demo API when module is imported
default_host().expose(_demo_dispatch, name="dispatch_event")

# --------------------------------------------------------------------------- #
# Self-test                                                                   #
# --------------------------------------------------------------------------- #
if __name__ == "__main__":  # pragma: no cover
    async def _demo() -> None:
        host = default_host()
        await host.run_source(
            """
            import math, random
            result = math.sqrt(16)
            dispatch_event("sqrt_done", {"value": result})
            print("Hello from script, result=", result)
            """,
            timeout=1.0,
        )

    asyncio.run(_demo())
```
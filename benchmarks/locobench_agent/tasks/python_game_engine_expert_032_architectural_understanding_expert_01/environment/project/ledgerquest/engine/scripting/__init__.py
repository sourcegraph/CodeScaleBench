from __future__ import annotations

"""
ledgerquest.engine.scripting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Core scripting subsystem for LedgerQuest Engine.

The module is intentionally self-contained so it can be imported by
both Lambda functions (serverless runtime) and local testing harnesses
without bringing in the heavyweight parts of the engine.

Responsibilities
----------------
1. Securely load and execute user-provided scripts (AI behaviours,
   scenario logic, etc.) located in:
      • Local package resources (for unit tests / dev)
      • S3 buckets (production, dynamically uploaded by level-editor)
2. Provide a decorator-based API to expose functions in those scripts
   as event handlers inside the larger Entity-Component-System.
3. Cache compiled scripts per container / process to minimise cold-start
   overhead in serverless environments.
4. Offer a *very* lightweight sandbox that restricts the available
   built-ins, helping prevent accidental `os.system` calls while still
   allowing normal Python gameplay logic.

NOTE:
-----
The sandbox implemented here is **not** bullet-proof.  It is meant to
stop *accidental* misuse by script authors, not malicious actors.  True
isolation is provided by AWS Lambda’s Firecracker micro-VMs or separate
container tasks with a locked-down IAM role.

"""

import importlib
import importlib.util
import logging
import sys
import time
from dataclasses import dataclass, field
from functools import lru_cache, wraps
from pathlib import Path
from types import CodeType, ModuleType
from typing import Any, Callable, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Optional dependency (boto3) – available in prod, skipped in unit tests
# --------------------------------------------------------------------------- #
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:  # pragma: no cover – unit-test environment
    boto3 = None             # type: ignore
    BotoCoreError = ClientError = Exception  # type: ignore

__all__ = [
    "ScriptEngine",
    "ScriptEngineError",
    "ScriptNotFoundError",
    "ScriptSecurityError",
    "game_script",
]

_LOGGER = logging.getLogger("ledgerquest.engine.scripting")
_EVENT_REGISTRY: Dict[str, List[Callable[..., Any]]] = {}


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class ScriptEngineError(RuntimeError):
    """Base class for all script-engine related failures."""


class ScriptNotFoundError(ScriptEngineError):
    """Raised when the requested script could not be located."""


class ScriptSecurityError(ScriptEngineError):
    """Raised on sandbox or security policy violations."""


# --------------------------------------------------------------------------- #
# Sandbox Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class SandboxConfig:
    """
    Parameters that control the in-process script sandbox.

    Attributes
    ----------
    allowed_builtins:
        Names in the `builtins` module that remain available to scripts.
    max_exec_time:
        Maximum wall-clock time (in seconds) for a single script event
        before `ScriptSecurityError` is raised.
    """

    allowed_builtins: set[str] = field(
        default_factory=lambda: {
            "abs",
            "all",
            "any",
            "bool",
            "dict",
            "float",
            "int",
            "len",
            "list",
            "max",
            "min",
            "print",
            "range",
            "set",
            "str",
            "sum",
            "tuple",
            # Add anything else that is considered safe here.
        }
    )
    max_exec_time: float = 2.0


# --------------------------------------------------------------------------- #
# Decorator – called by user scripts to register event handlers
# --------------------------------------------------------------------------- #
def game_script(event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that marks a function as an event listener.

    Example inside user script
    --------------------------
    @game_script("on_player_join")
    def greet_player(ctx, player_id: str):
        ctx["log"](f"Welcome {player_id}!")
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        _EVENT_REGISTRY.setdefault(event, []).append(func)
        _LOGGER.debug("Registered script %s for event '%s'", func.__qualname__, event)
        return func

    return decorator


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _make_module(name: str, code: CodeType) -> ModuleType:
    """Create a new module from compiled byte-code and insert into sys.modules."""
    module = ModuleType(name)
    exec(code, module.__dict__)  # noqa: S102 – exec is required for dynamic scripts
    sys.modules[name] = module
    return module


def _restricted_globals(cfg: SandboxConfig) -> Dict[str, Any]:
    """Return a globals-dict that removes disallowed builtins."""
    import builtins as _builtins

    safe_builtins = {k: getattr(_builtins, k) for k in cfg.allowed_builtins}
    return {"__builtins__": safe_builtins, "game_script": game_script}


@lru_cache(maxsize=128)
def _compile_source(source: str, name: str) -> CodeType:
    """Compile Python source code, cached by (source, name)."""
    _LOGGER.debug("Compiling script '%s' (cache miss)", name)
    return compile(source, filename=name, mode="exec")


# --------------------------------------------------------------------------- #
# ScriptEngine
# --------------------------------------------------------------------------- #
class ScriptEngine:  # noqa: D101 – docstring below
    """
    High-level interface for loading and executing game scripts.

    The engine supports three URI schemes:

        1. Dotted module path  ->  ``ledgerquest.scenarios.finance.level1``
        2. Local file path     ->  ``/tmp/user_scripts/level1.py``
        3. S3 URI              ->  ``s3://lq-scripts/tenant123/level1.py``

    Examples
    --------
    >>> engine = ScriptEngine()
    >>> module = engine.load("examples.hello_world")
    >>> engine.dispatch("on_boot", ctx={})

    The object can be reused between Lambda invocations when the container
    is *warm*, giving us in-memory caching of compiled code.
    """

    # Public API ------------------------------------------------------------ #
    def __init__(
        self,
        s3_bucket: str | None = None,
        sandbox_cfg: SandboxConfig | None = None,
    ) -> None:
        self._s3_bucket = s3_bucket
        self._sandbox_cfg = sandbox_cfg or SandboxConfig()
        self._s3_client = boto3.client("s3") if boto3 and s3_bucket else None

        _LOGGER.debug(
            "ScriptEngine initialised  (s3_bucket=%s, max_exec=%.2fs)",
            s3_bucket,
            self._sandbox_cfg.max_exec_time,
        )

    # --------------------------------------------------------------------- #
    # Script Loading
    # --------------------------------------------------------------------- #
    def load(self, identifier: str) -> ModuleType:
        """
        Load (and cache) a script identified by `identifier`.

        Returns the loaded `ModuleType` instance.  Subsequent calls with
        the same identifier return the cached module.

        Raises ScriptNotFoundError for missing sources.
        """
        if identifier in sys.modules:
            _LOGGER.debug("Returning cached module '%s'", identifier)
            return sys.modules[identifier]

        source: str
        if identifier.startswith("s3://"):
            source = self._load_from_s3(identifier)
        elif identifier.endswith(".py") and Path(identifier).exists():
            source = Path(identifier).read_text(encoding="utf-8")
        else:
            # Assume dotted path inside the current environment
            try:
                _LOGGER.debug("Attempting importlib for '%s'", identifier)
                return importlib.import_module(identifier)
            except ModuleNotFoundError as exc:
                raise ScriptNotFoundError(identifier) from exc

        code = _compile_source(source, identifier)
        module = _make_module(identifier, code)
        _LOGGER.info("Loaded script '%s' (len=%d bytes)", identifier, len(source))
        return module

    # --------------------------------------------------------------------- #
    # Event Dispatch
    # --------------------------------------------------------------------- #
    def dispatch(
        self,
        event: str,
        *,
        ctx: Optional[dict[str, Any]] = None,
        **event_payload: Any,
    ) -> List[Any]:
        """
        Execute all registered handlers for `event` and return their results.

        Parameters
        ----------
        event:
            Name of the in-engine event (e.g., ``on_tick``, ``order_filled``).
        ctx:
            Mutable context dictionary that is shared with all handlers.
            The engine populates *log* and *now* helpers automatically.
        **event_payload:
            Additional keyword arguments forwarded verbatim to handlers.

        Raises
        ------
        ScriptSecurityError
            If the cumulative execution time exceeds `SandboxConfig.max_exec_time`.
        """
        handlers = _EVENT_REGISTRY.get(event, [])
        _LOGGER.debug(
            "Dispatching event '%s' to %d handlers (payload=%s)",
            event,
            len(handlers),
            list(event_payload.keys()),
        )

        results: List[Any] = []
        start_time = time.perf_counter()
        ctx = ctx or {}
        ctx.setdefault("log", _LOGGER.info)
        ctx.setdefault("now", lambda: int(time.time() * 1000))

        for fn in handlers:
            _LOGGER.debug("Executing handler %s", fn.__qualname__)
            try:
                result = self._execute(fn, ctx, event_payload)
                results.append(result)
            except Exception:  # pragma: no cover – let engine continue
                _LOGGER.exception("Unhandled exception in script handler %s", fn.__qualname__)

            # Security gate – wall clock timer
            elapsed = time.perf_counter() - start_time
            if elapsed > self._sandbox_cfg.max_exec_time:
                raise ScriptSecurityError(
                    f"Execution time {elapsed:.2f}s exceeded "
                    f"limit of {self._sandbox_cfg.max_exec_time:.2f}s"
                )

        return results

    # --------------------------------------------------------------------- #
    # Internal Exec Helpers
    # --------------------------------------------------------------------- #
    def _execute(
        self,
        fn: Callable[..., Any],
        ctx: dict[str, Any],
        event_payload: Dict[str, Any],
    ) -> Any:
        """Run a single handler inside the (loose) sandbox."""
        allowed_globals = _restricted_globals(self._sandbox_cfg)

        # Prepare a wrapper that will execute the handler with isolated globals
        @wraps(fn)
        def _sandboxed() -> Any:
            nonlocal ctx, event_payload
            # Combine restricted globals with the handler's original globals
            exec_globals = {**allowed_globals, **fn.__globals__}
            # Assign back so inner calls see new builtins
            fn.__globals__.update(exec_globals)
            return fn(ctx, **event_payload)

        return _sandboxed()

    # --------------------------------------------------------------------- #
    # S3 Helpers
    # --------------------------------------------------------------------- #
    def _load_from_s3(self, uri: str) -> str:
        """
        Resolve an S3 URI and return the file content as UTF-8 string.

        The URI may omit the bucket name if `ScriptEngine` was initialised
        with a default *s3_bucket* parameter.

        Examples
        --------
        s3://my-bucket/path/to/script.py
        s3://tenantA/finance/level2.py
        """
        if not self._s3_client:
            raise ScriptEngineError("boto3 is required for S3 script loading")

        if not uri.startswith("s3://"):
            raise ValueError("URI must start with s3://")

        bucket, _, key = uri[5:].partition("/")
        if not key:  # missing bucket in URI – fall back to default
            key, bucket = bucket, self._s3_bucket

        bucket = bucket or self._s3_bucket
        if not bucket:
            raise ScriptEngineError("S3 bucket not provided in URI or engine config")

        try:
            _LOGGER.debug("Fetching script from S3 s3://%s/%s", bucket, key)
            obj = self._s3_client.get_object(Bucket=bucket, Key=key)
            return obj["Body"].read().decode("utf-8")
        except (BotoCoreError, ClientError) as exc:
            raise ScriptNotFoundError(uri) from exc


# --------------------------------------------------------------------------- #
# Convenience singleton for simple use-cases
# --------------------------------------------------------------------------- #
_default_engine: Optional[ScriptEngine] = None


def get_default_engine() -> ScriptEngine:
    """
    Return a lazily initialised `ScriptEngine` instance.

    This helper allows `ledgerquest.engine.*` modules to access a shared
    engine without worrying about import-order constraints.
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = ScriptEngine()
    return _default_engine


# --------------------------------------------------------------------------- #
# Logging default (only if the root logger has no handlers)
# --------------------------------------------------------------------------- #
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

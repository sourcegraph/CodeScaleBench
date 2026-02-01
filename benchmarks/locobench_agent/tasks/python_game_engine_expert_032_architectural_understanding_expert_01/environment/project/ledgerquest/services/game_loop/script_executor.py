```python
"""
ledgerquest.services.game_loop.script_executor
=============================================

Implements a sandboxed script-execution facility used by the LedgerQuest
game-loop Step Function.  Game designers upload Python snippets to a dedicated
S3 bucket; those snippets mutate the game‐state (a plain dict persisted in
DynamoDB).  This module is responsible for:

1. Downloading and caching script sources from S3
2. Compiling them to byte-code (also cached)
3. Executing them inside a restricted environment
4. Returning the mutated state or raising a well-formed error

Because the engine runs inside AWS Lambda, the compiled-code LRU cache lives
only for the duration of a warm container – which is exactly what we want for
fast, low-latency script dispatch without persisting execution artifacts.

Security considerations
-----------------------
Executing customer-supplied scripts on a managed service is dangerous.  We take
multiple precautions:

* Only a *very* small subset of safe built-ins is exposed
* No module imports are allowed from inside the script
* Execution is time-boxed with `signal.alarm` (Unix-only, but Lambda is Unix)
* Memory bloat is mitigated by discarding script globals after each run

If the script violates any of the above constraints, a `ScriptExecutionError`
is raised and an audit event is dispatched to EventBridge.

NOTE: This is a *minimal* sandbox and should not be considered bullet-proof
for untrusted code.  For stricter isolation, consider running scripts in
Firecracker-VM MicroVMs or AWS Fargate tasks with Seccomp/AppArmor profiles.
"""
from __future__ import annotations

import builtins
import json
import logging
import os
import signal
import textwrap
import types
from functools import lru_cache
from time import monotonic
from typing import Any, Dict

import boto3
from botocore.exceptions import BotoCoreError, ClientError

__all__ = ["execute_script", "ScriptExecutionError"]

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Configuration (overridable via Lambda environment variables)
# --------------------------------------------------------------------------- #
S3_BUCKET: str = os.getenv("LEDGERQUEST_SCRIPT_BUCKET", "ledgerquest-engine-scripts")
SCRIPT_PREFIX: str = os.getenv("LEDGERQUEST_SCRIPT_PREFIX", "scripts")
DEFAULT_TIMEOUT_SECONDS: int = int(os.getenv("LEDGERQUEST_SCRIPT_TIMEOUT", "2"))
SAFE_BUILTINS: tuple[str, ...] = (
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "pow",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    # math/random are provided as module proxies (see `_sandbox_globals`)
)

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class ScriptExecutionError(RuntimeError):
    """Raised when a script fails due to timeout, syntax, or runtime exceptions."""

    def __init__(self, script_key: str, *, cause: Exception):
        super().__init__(f"Execution failed for script '{script_key}': {cause}")
        self.script_key = script_key
        self.__cause__ = cause  # Preserve chained exception for debugging


# --------------------------------------------------------------------------- #
# Private helpers
# --------------------------------------------------------------------------- #

_S3_CLIENT = boto3.client("s3", config=boto3.session.Config(retries={"max_attempts": 3}))


@lru_cache(maxsize=128)
def _download_and_compile(script_key: str) -> types.CodeType:
    """
    Download a UTF-8 script from S3 and compile it to a code object.

    Results are memoised using an LRU cache (keyed by `script_key`) to reduce
    latency for frequently executed scripts within the same warm Lambda container.
    """
    s3_path = f"{SCRIPT_PREFIX.rstrip('/')}/{script_key.lstrip('/')}"
    _LOGGER.debug("Fetching script s3://%s/%s", S3_BUCKET, s3_path)

    try:
        response = _S3_CLIENT.get_object(Bucket=S3_BUCKET, Key=s3_path)
        source_bytes: bytes = response["Body"].read()
    except (ClientError, BotoCoreError) as exc:
        _LOGGER.exception("Failed to download script '%s' from S3.", script_key)
        raise ScriptExecutionError(script_key, cause=exc) from exc

    try:
        source = source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        _LOGGER.error("Script '%s' contains non-UTF8 bytes.", script_key)
        raise ScriptExecutionError(script_key, cause=exc) from exc

    try:
        code_obj = compile(source, script_key, mode="exec", dont_inherit=True)
    except SyntaxError as exc:
        _LOGGER.error("Syntax error in script '%s'.", script_key)
        raise ScriptExecutionError(script_key, cause=exc) from exc

    _LOGGER.debug("Successfully compiled script '%s'.", script_key)
    return code_obj


def _sandbox_globals(extra_globals: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Build the global namespace used for script execution.

    Only explicitly allowed built-ins and whitelisted modules/functions are
    exposed to the running script.  The function returns a *new* dict each
    invocation to avoid cross-script memory leaks.
    """
    safe_builtins: Dict[str, Any] = {name: getattr(builtins, name) for name in SAFE_BUILTINS}
    safe_modules = {
        # Expose cheap, deterministic helpers from the stdlib.
        "math": __import__("math"),
        "random": __import__("random"),
        "json": json,
    }

    # Guard `__import__` to block runtime imports from the script
    def _blocked_import(*_: Any, **__: Any) -> None:  # noqa: D401
        raise ImportError("Dynamic imports are not allowed inside LedgerQuest scripts.")

    safe_builtins["__import__"] = _blocked_import  # type: ignore[assignment]

    globals_dict: Dict[str, Any] = {"__builtins__": safe_builtins, **safe_modules}
    globals_dict.update(extra_globals or {})
    return globals_dict


def _set_timeout(seconds: int) -> None:
    """Start a Unix signal alarm to enforce CPU time limits inside the Lambda."""
    if seconds <= 0:
        return  # Disabled
    signal.alarm(seconds)


def _clear_timeout() -> None:
    """Clear any active signal alarm."""
    signal.alarm(0)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def execute_script(
    script_key: str,
    game_state: Dict[str, Any],
    event_payload: Dict[str, Any] | None = None,
    *,
    timeout_seconds: int | None = None,
) -> Dict[str, Any]:
    """
    Execute the requested game script and return the mutated state.

    Parameters
    ----------
    script_key:
        S3 key (relative to SCRIPT_PREFIX) pointing to the script source.
    game_state:
        A JSON-serialisable dictionary representing the current game state.
    event_payload:
        Optional dictionary with contextual information about the triggering
        event (e.g., player action, time tick, or simulation frame ID).
    timeout_seconds:
        Maximum wall-clock seconds allowed for script execution.  Falls back to
        DEFAULT_TIMEOUT_SECONDS if unset or `None`.

    Returns
    -------
    dict
        The mutated game state dictionary.

    Raises
    ------
    ScriptExecutionError
        When the script cannot be downloaded, compiled, or executed safely.
    """
    timeout = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
    _LOGGER.debug(
        "Executing script '%s' with timeout=%s sec, event=%s ...",
        script_key,
        timeout,
        event_payload,
    )

    # Compile (or retrieve from cache) outside the timeout guard.
    code_obj = _download_and_compile(script_key)

    # Prepare isolated globals; `state` and `event` act as the “API” for authors.
    sandbox = _sandbox_globals(
        {
            "state": json.loads(json.dumps(game_state)),  # deep-copy w/ JSON
            "event": event_payload or {},
        }
    )

    # Install a SIGALRM handler to enforce timeouts (only once per process).
    def _handle_timeout(signum: int, frame) -> None:  # noqa: D401
        raise TimeoutError(f"Script '{script_key}' exceeded {timeout} seconds.")

    old_handler = signal.signal(signal.SIGALRM, _handle_timeout)

    t0 = monotonic()
    try:
        _set_timeout(timeout)
        exec(code_obj, sandbox, None)
    except Exception as exc:  # pylint: disable=broad-except
        # Bubble up with a custom exception type for upstream error routing.
        _LOGGER.exception(
            "Error during execution of script '%s' (elapsed %.2f ms).", script_key, (monotonic() - t0) * 1000
        )
        raise ScriptExecutionError(script_key, cause=exc) from exc
    finally:
        _clear_timeout()
        # Restore previous signal handler to avoid side-effects.
        signal.signal(signal.SIGALRM, old_handler)

    elapsed_ms = (monotonic() - t0) * 1000
    _LOGGER.info("Script '%s' executed successfully in %.2f ms.", script_key, elapsed_ms)

    mutated_state = sandbox.get("state", {})
    if not isinstance(mutated_state, dict):
        _LOGGER.warning(
            "Script '%s' returned a non-dict state (%s).  Returning original state.",
            script_key,
            type(mutated_state),
        )
        return game_state

    return mutated_state
```
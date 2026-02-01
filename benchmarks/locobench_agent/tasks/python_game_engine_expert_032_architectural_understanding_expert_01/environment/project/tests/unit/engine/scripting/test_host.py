```python
"""
Unit tests for ScriptHost – the sandboxed script execution engine that powers
runtime behaviour customisation inside LedgerQuest.

These tests are intentionally comprehensive because production workloads rely
heavily on deterministic and secure execution of untrusted user‐generated
python snippets (financial models, AI behaviours, etc.).  We therefore validate
security constraints, performance expectations (compilation cache), run-time
guards (timeouts) and context propagation (tenant isolation & dependency
injection).
"""
from __future__ import annotations

import asyncio
import builtins
import inspect
import textwrap
import time
from types import MappingProxyType
from typing import Any, Dict

import pytest

# All public host API lives under game_engine.scripting.host.
# The concrete implementation is provided by the runtime package; however,
# for unit-testing we rely only on the public surface area so that refactors
# do not break callers.
from game_engine.scripting.host import (  # type: ignore
    SandboxViolationError,
    ScriptExecutionTimeout,
    ScriptHost,
)


class _DummyEventBus:
    """
    Extremely small stub that mimics game_engine.eventing.EventBus.

    ScriptHost publishes ScriptStarted / ScriptFinished events to the bus,
    which external systems may listen to for audit-logging and metrics.
    """

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish(self, event_name: str, payload: Dict[str, Any]) -> None:
        self.published.append({"event_name": event_name, "payload": payload})

    # Helper ---------------------------------------------------------------

    def filter(self, event_name: str) -> list[dict[str, Any]]:
        return [e for e in self.published if e["event_name"] == event_name]


@pytest.fixture(scope="function")
def dummy_event_bus() -> _DummyEventBus:
    return _DummyEventBus()


@pytest.fixture(scope="function")
def script_host(dummy_event_bus: _DummyEventBus) -> ScriptHost:
    """
    Return a fresh ScriptHost instance for each test, configured with tight
    execution limits so that the suite runs quickly.
    """
    return ScriptHost(
        max_execution_seconds=0.2,
        event_bus=dummy_event_bus,
        compiler_cache_size=8,
    )


# ---------------------------------------------------------------------------
# Positive execution path
# ---------------------------------------------------------------------------


def test_executes_script_and_returns_result(script_host: ScriptHost) -> None:
    code = """
    result = player_gold + 100  # simple arithmetic
    """
    code = textwrap.dedent(code)

    # Provide context visible inside the sandbox.
    context = {"player_gold": 350}

    ret = script_host.execute(code, context)

    assert ret == 450
    # Ensure that original context has not mutated (host must isolate state).
    assert context == {"player_gold": 350}


def test_publishes_start_and_finish_events(
    script_host: ScriptHost, dummy_event_bus: _DummyEventBus
) -> None:
    code = "result = 1+1"

    script_host.execute(code, {})

    start_events = dummy_event_bus.filter("ScriptStarted")
    finish_events = dummy_event_bus.filter("ScriptFinished")

    assert len(start_events) == 1
    assert len(finish_events) == 1
    # Correlate request_id
    assert (
        start_events[0]["payload"]["request_id"]
        == finish_events[0]["payload"]["request_id"]
    )
    assert finish_events[0]["payload"]["status"] == "success"


# ---------------------------------------------------------------------------
# Security guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        # Attempt (and fail) to open a file – IO is disabled.
        "open('/etc/passwd', 'r')",
        # Attempt to escape sandbox via __import__
        "__import__('os').system('echo hacked')",
    ],
)
def test_disallowed_builtins_are_blocked(payload: str, script_host: ScriptHost) -> None:
    sandbox_code = f"""
    result = {payload}
    """

    with pytest.raises(SandboxViolationError):
        script_host.execute(textwrap.dedent(sandbox_code), {})


def test_builtins_are_frozen(script_host: ScriptHost, monkeypatch: pytest.MonkeyPatch):
    """
    Ensure that user code cannot mutate builtins at run-time – we rely on
    MappingProxyType to expose an immutable view.
    """
    spy = object()

    monkeypatch.setattr(builtins, "EXTRA_ATTR_SHOULD_NOT_EXIST", spy, raising=False)

    malicious_code = """
    builtins.EXTRA_ATTR_SHOULD_NOT_EXIST = 'mutated'
    result = 123
    """

    with pytest.raises(SandboxViolationError):
        script_host.execute(textwrap.dedent(malicious_code), {})

    # The global builtins namespace must remain unchanged.
    assert getattr(builtins, "EXTRA_ATTR_SHOULD_NOT_EXIST", spy) is spy


# ---------------------------------------------------------------------------
# Runtime protections
# ---------------------------------------------------------------------------


def test_timeout_is_enforced(script_host: ScriptHost) -> None:
    runaway_code = """
    while True:
        pass
    """

    started_at = time.perf_counter()

    with pytest.raises(ScriptExecutionTimeout):
        script_host.execute(textwrap.dedent(runaway_code), {})

    duration = time.perf_counter() - started_at
    # Host should kill the script very quickly (<= configured threshold + ε).
    assert duration < 0.3


def test_cancellation_propagates_to_async_tasks(script_host: ScriptHost) -> None:
    """
    We spawn an async coroutine that sleeps forever – when the host times out,
    all nested coroutines/futures must be cancelled to prevent resource leaks.
    """

    async_code = """
    import asyncio
    async def go():
        await asyncio.sleep(9999)

    asyncio.get_event_loop().create_task(go())
    """

    with pytest.raises(ScriptExecutionTimeout):
        script_host.execute(textwrap.dedent(async_code), {})

    # The event loop must no longer have pending non-daemon tasks.
    pending = [t for t in asyncio.all_tasks() if not t.done()]
    assert not pending, "Zombie tasks survived host cancellation"


# ---------------------------------------------------------------------------
# Performance – compilation cache
# ---------------------------------------------------------------------------


def test_compilation_is_cached(script_host: ScriptHost, monkeypatch: pytest.MonkeyPatch):
    compile_spy_calls: list[str] = []

    # Patch script_host._compile_script to track how often it's invoked.
    original_compile = script_host._compile_script  # type: ignore[attr-defined]

    def _spy(source: str, tenant: str) -> Any:  # type: ignore[override]
        compile_spy_calls.append(source)
        return original_compile(source, tenant)

    monkeypatch.setattr(script_host, "_compile_script", _spy, raising=True)

    code = "result = 2 * 21"
    code = textwrap.dedent(code)

    # Two executions – compilation should only happen once.
    assert script_host.execute(code, {}) == 42
    assert script_host.execute(code, {}) == 42

    assert compile_spy_calls.count(code) == 1, "Compilation not cached"


# ---------------------------------------------------------------------------
# Multi-tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_scoped_cache(script_host: ScriptHost, monkeypatch: pytest.MonkeyPatch):
    """
    Same script string executed by different tenants must not share compiled
    byte-code because policy enforcement (IAM, feature flags, etc.) differs.
    """
    compile_spy_calls: list[tuple[str, str]] = []

    def _spy(source: str, tenant: str) -> Any:  # type: ignore[override]
        compile_spy_calls.append((source, tenant))
        return compile(source, "<sandbox>", "exec")

    monkeypatch.setattr(script_host, "_compile_script", _spy, raising=True)

    code = "result = 7"

    # Tenant A execution
    assert script_host.execute(code, {}, tenant_id="tenant_A") == 7
    # Tenant B execution
    assert script_host.execute(code, {}, tenant_id="tenant_B") == 7

    assert ("result = 7", "tenant_A") in compile_spy_calls
    assert ("result = 7", "tenant_B") in compile_spy_calls
    # Because tenant differs, compile should have been invoked twice
    assert len(compile_spy_calls) == 2


# ---------------------------------------------------------------------------
# Context immutability
# ---------------------------------------------------------------------------


def test_context_is_readonly_inside_script(script_host: ScriptHost):
    ctx = {"score": 10}

    code = """
    # Attempt to mutate upstream context
    score = 99
    result = score
    """

    result = script_host.execute(textwrap.dedent(code), ctx)

    # Local mutation should not have propagated back.
    assert ctx["score"] == 10
    assert result == 99


def test_context_access_is_mapping_proxy(script_host: ScriptHost):
    """
    The context object visible to scripts should be an immutable
    MappingProxyType to prevent accidental writes.
    """

    code = """
    assert not hasattr(context, 'update')
    result = isinstance(context, type({}.keys()).__mro__[1])  # Mapping
    """

    res = script_host.execute(textwrap.dedent(code), {"foo": "bar"})

    assert res is True
```
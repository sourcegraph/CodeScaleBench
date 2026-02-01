```python
"""
PulseStream Nexus – module_39
=============================

Resilient, rate-limited, observable HTTP client used by ingestion micro-services
to obtain data from third-party social APIs (Twitter/X, Reddit, Mastodon, etc.).
Implements:

1. Async token-bucket rate limiter
2. Circuit-breaker for downstream fault isolation
3. Prometheus metrics hooks
4. pluggable back-off strategy
5. Graceful shutdown & context-manager interface

This module purposefully contains **no domain logic**; it is an infrastructure
component that can be wired into use-case interactors without violating the
Clean Architecture boundary.

Author: PulseStream Nexus Platform Team
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional, Sequence, Tuple, Type

import aiohttp
import backoff  # type: ignore
from prometheus_client import Counter, Histogram

__all__ = [
    "AsyncRateLimiter",
    "CircuitBreaker",
    "ResilientHTTPClient",
]

_LOGGER = logging.getLogger("pulse_stream_nexus.module_39")
_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)

# -----------------------------------------------------------------------------
# Prometheus metric definitions
# -----------------------------------------------------------------------------
REQUEST_COUNTER = Counter(
    "psn_outgoing_http_requests_total",
    "Total number of outgoing HTTP requests.",
    ["endpoint", "method", "status"],
)
FAILURE_COUNTER = Counter(
    "psn_outgoing_http_failures_total",
    "Total number of failed HTTP requests.",
    ["endpoint", "method", "exception"],
)
LATENCY_HISTOGRAM = Histogram(
    "psn_outgoing_http_latency_seconds",
    "Latency of outgoing HTTP requests.",
    ["endpoint", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)

# -----------------------------------------------------------------------------
# Rate Limiter
# -----------------------------------------------------------------------------


class AsyncRateLimiter:
    """
    Simple asynchronous token-bucket rate limiter.

    Example: ``AsyncRateLimiter(rate=300, per=60)`` allows 300 tokens per
    60-second window (≈5 req/s).

    Usage:

    >>> rate_limiter = AsyncRateLimiter(10, 1)
    >>> async with rate_limiter:
    ...     await call_api()
    """

    def __init__(self, rate: int, per: float) -> None:
        if rate <= 0 or per <= 0:
            raise ValueError("rate and per must be positive numbers")
        self._capacity = rate
        self._tokens = rate
        self._per = per
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """
        Wait until a token becomes available.
        """
        async with self._lock:
            await self._refill()

            while self._tokens <= 0:
                sleep_time = self._next_refill_delta()
                _LOGGER.debug("Rate limit hit; sleeping for %.4fs", sleep_time)
                await asyncio.sleep(sleep_time)
                await self._refill()

            self._tokens -= 1
            _LOGGER.debug("Rate limiter token granted, remaining=%d", self._tokens)

    def _next_refill_delta(self) -> float:
        elapsed = time.monotonic() - self._last_refill
        return max(self._per - elapsed, 0)

    async def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed >= self._per:
            self._tokens = self._capacity
            self._last_refill = now
            _LOGGER.debug("Token bucket refilled to capacity=%d", self._capacity)

    # ------------------------------------------------------------------ magic

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # Nothing to cleanup.
        return False


# -----------------------------------------------------------------------------
# Circuit Breaker
# -----------------------------------------------------------------------------


class CircuitBreaker:
    """
    Resilient circuit breaker for async callables.

    State machine:
        CLOSED -> OPEN after `failure_threshold` consecutive failures
        OPEN   -> HALF_OPEN after `recovery_timeout` seconds pass
        HALF_OPEN -> CLOSED on first success, OPEN on failure

    Example:

    >>> breaker = CircuitBreaker()
    >>> @breaker
    ... async def fragile():
    ...     ...
    """

    _STATE_CLOSED = "closed"
    _STATE_OPEN = "open"
    _STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        expected_exceptions: Tuple[Type[BaseException], ...] = (
            aiohttp.ClientError,
            asyncio.TimeoutError,
        ),
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be a positive integer")
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._expected_exceptions = expected_exceptions

        self._state = self._STATE_CLOSED
        self._failure_count = 0
        self._opened_since: Optional[float] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ public

    def __call__(self, func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if asyncio.iscoroutinefunction(func):
            # Decorate async coroutine.
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                async with self._guard():
                    return await func(*args, **kwargs)

            return wrapper
        raise TypeError("CircuitBreaker can only decorate async functions")

    async def call(self, coro: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """
        Imperative style wrapper.
        """
        async with self._guard():
            return await coro(*args, **kwargs)

    # ------------------------------------------------------------------ internal

    @asynccontextmanager
    async def _guard(self) -> AsyncGenerator[None, None]:
        # Fail fast if circuit is OPEN and timeout not reached.
        async with self._lock:
            await self._maybe_reset_state()

            if self._state == self._STATE_OPEN:
                raise CircuitOpenError("Circuit breaker is open")

            half_open = self._state == self._STATE_HALF_OPEN

        try:
            yield
        except self._expected_exceptions as exc:
            await self._record_failure()
            raise exc
        else:
            if half_open:
                await self._close()
        # noqa: no finally needed because contextmanager takes care

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            _LOGGER.debug("CircuitBreaker failure #%d", self._failure_count)
            if self._failure_count >= self._failure_threshold:
                await self._open()

    async def _open(self) -> None:
        self._state = self._STATE_OPEN
        self._opened_since = time.monotonic()
        _LOGGER.warning("CircuitBreaker opened after %d consecutive failures", self._failure_count)

    async def _close(self) -> None:
        self._state = self._STATE_CLOSED
        self._failure_count = 0
        self._opened_since = None
        _LOGGER.info("CircuitBreaker closed; normal operation resumed")

    async def _maybe_reset_state(self) -> None:
        if self._state == self._STATE_OPEN and self._opened_since is not None:
            if (time.monotonic() - self._opened_since) >= self._recovery_timeout:
                self._state = self._STATE_HALF_OPEN
                _LOGGER.info("CircuitBreaker entering HALF_OPEN (probing) state")

    # ------------------------------------------------------------------ properties

    @property
    def state(self) -> str:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count


class CircuitOpenError(RuntimeError):
    """Raised when an operation is attempted on an open circuit breaker."""


# -----------------------------------------------------------------------------
# Backoff helpers
# -----------------------------------------------------------------------------


def _backoff_hdlr(details: dict[str, Any]) -> None:  # pragma: no cover
    _LOGGER.warning(
        "Backing off %s: tries=%d delay=%.2fs exception=%r",
        details["target"],
        details["tries"],
        details["wait"],
        details.get("value"),
    )


BACKOFF_CFG = dict(
    wait_gen=backoff.expo(base=0.5, factor=2, max_value=30),
    jitter=backoff.full_jitter,
    on_backoff=_backoff_hdlr,
    on_giveup=_backoff_hdlr,
    max_tries=5,
    giveup=lambda exc: isinstance(exc, CircuitOpenError),
)


# -----------------------------------------------------------------------------
# Resilient HTTP Client
# -----------------------------------------------------------------------------


class ResilientHTTPClient:
    """
    Lightweight wrapper around aiohttp.ClientSession that provides:

        * Rate limiting via AsyncRateLimiter
        * Circuit breaker for downstream faults
        * Observability through Prometheus metrics
        * Automatic exponential back-off via `backoff` library

    Usage:

    >>> rate_limiter = AsyncRateLimiter(300, 60)
    >>> breaker = CircuitBreaker()
    >>> client = ResilientHTTPClient(rate_limiter, breaker)
    >>> async with client:
    ...     data = await client.get_json("https://api.example.com/v1/resource")
    """

    def __init__(
        self,
        rate_limiter: AsyncRateLimiter,
        circuit_breaker: CircuitBreaker,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: aiohttp.ClientTimeout = _DEFAULT_TIMEOUT,
        user_agent: str = "PulseStream-Nexus/1.0 (+https://pulsenexus.example.com)",
    ) -> None:
        self._rate_limiter = rate_limiter
        self._breaker = circuit_breaker
        self._session_external = session  # externally managed?
        self._session: Optional[aiohttp.ClientSession] = session
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}

    # ------------------------------------------------------------------ context management

    async def __aenter__(self) -> "ResilientHTTPClient":
        if self._session is None:
            # Create private session
            self._session = aiohttp.ClientSession(timeout=self._timeout, headers=self._headers)
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # Close session only if we created it
        if self._session and not self._session_external:
            await self._session.close()
            self._session = None
        # Do not suppress exceptions
        return False

    # ------------------------------------------------------------------ HTTP verbs

    async def get_json(
        self,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        GET request returning json decoded payload.
        """
        resp = await self._request("GET", url, params=params, headers=headers, **kwargs)
        return await resp.json()

    async def post_json(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> Any:
        """
        POST request with json body; returns decoded json response.
        """
        resp = await self._request("POST", url, json=json, headers=headers, **kwargs)
        return await resp.json()

    # ------------------------------------------------------------------ core request

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[dict[str, str]] = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        if self._session is None:
            raise RuntimeError("Client session is not initialised – use 'async with'")

        @backoff.on_exception(backoff.constant,  # type: ignore[arg-type]
                              (aiohttp.ClientError, asyncio.TimeoutError, CircuitOpenError),
                              interval=0, **BACKOFF_CFG)
        async def do_request() -> aiohttp.ClientResponse:
            async with self._rate_limiter:
                start = time.monotonic()
                try:
                    async with self._breaker:
                        _LOGGER.debug("HTTP %s %s headers=%s kwargs=%s", method, url, headers, kwargs)
                        resp = await self._session.request(method, url, headers=headers, **kwargs)
                except Exception:
                    # Increment failure counter and re-raise
                    FAILURE_COUNTER.labels(url, method, "exception").inc()
                    raise

                latency = time.monotonic() - start
                LATENCY_HISTOGRAM.labels(url, method).observe(latency)
                REQUEST_COUNTER.labels(url, method, resp.status).inc()

                if 500 <= resp.status < 600:
                    FAILURE_COUNTER.labels(url, method, f"HTTP_{resp.status}").inc()
                    # Consider 5xx server errors retryable
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                        message=f"Upstream returned {resp.status}",
                        headers=resp.headers,
                    )
                return resp

        response = await do_request()
        return response

    # ------------------------------------------------------------------ high level helpers

    async def stream_lines(
        self,
        url: str,
        *,
        params: Optional[dict[str, str]] = None,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """
        Stream-parse an SSE-like HTTP endpoint line by line.
        """
        resp = await self._request("GET", url, params=params, headers={"Accept": "text/event-stream"})
        async for chunk, _ in resp.content.iter_chunks():
            if not chunk:
                continue
            for line in chunk.decode().splitlines():
                yield line

    # ------------------------------------------------------------------ properties

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Session not available outside of async context")
        return self._session


# -----------------------------------------------------------------------------
# Diagnostic entrypoint
# -----------------------------------------------------------------------------

async def _demo() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    rate_limiter = AsyncRateLimiter(rate=10, per=1)
    breaker = CircuitBreaker()
    async with ResilientHTTPClient(rate_limiter, breaker) as client:
        data = await client.get_json("https://httpbin.org/json")
        print(data)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_demo())
```
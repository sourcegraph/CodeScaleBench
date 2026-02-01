```python
"""
crowdpay_connect.libs.shared_utils.observability
================================================

Centralised, opinionated observability helpers intended to be reused across
CrowdPay-Connect micro-services.  The utilities provided in this module handle
structured logging (JSON), distributed tracing, correlation-ID propagation, and
Prometheus metrics in a *best-effort* manner (i.e. safely degrade if a backend
is not configured).

Example
-------
>>> from crowdpay_connect.libs.shared_utils.observability import (
...     ObservabilityConfig,
...     ObservabilityManager,
...     instrumented,
... )
>>>
>>> config = ObservabilityConfig(service_name="payments-api")
>>> obs = ObservabilityManager(config)
>>> obs.init()                 # Initialise loggers, tracing & metrics
>>>
>>> @instrumented()
... def pay(amount: int) -> None:
...     ...

Design notes
------------
1.  Logging is powered by `structlog` and outputs JSON to stdout.
2.  Tracing relies on `opentelemetry` (OTLP exporter by default) but falls
    back gracefully if libraries or endpoints are missing.
3.  Metrics use `prometheus_client`, exposing default process metrics plus any
    custom counters / histograms created through the helper functions.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import logging
import os
import sys
import time
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional, ParamSpec, TypeVar, Union, overload

import structlog

# Optional dependencies ------------------------------------------------------

try:
    # Tracing
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _OTEL_AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    _OTEL_AVAILABLE = False

try:
    # Metrics
    from prometheus_client import Counter, Histogram, Info, start_http_server
    _PROM_AVAILABLE = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    _PROM_AVAILABLE = False

# ---------------------------------------------------------------------------

P = ParamSpec("P")
T = TypeVar("T")


# --------------------------- Correlation-ID ---------------------------------

_CORRELATION_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def _generate_correlation_id() -> str:
    """Return a *new* RFC-4122 compliant correlation ID."""
    return str(uuid.uuid4())


def get_correlation_id() -> str:
    """Get the current correlation ID (empty string if none has been set)."""
    return _CORRELATION_ID.get()


@contextlib.contextmanager
def correlation_context(correlation_id: Optional[str] = None) -> types.GeneratorType:
    """
    Context manager to *temporarily* set a correlation-ID.

    Useful when a request header already contains an ID that needs to be
    propagated across async tasks.

    Example
    -------
    >>> with correlation_context(request.headers.get("X-Request-Id")):
    ...     call_downstream()
    """
    token = _CORRELATION_ID.set(correlation_id or _generate_correlation_id())
    try:
        yield
    finally:
        _CORRELATION_ID.reset(token)


# -------------------------- Configuration -----------------------------------

@dataclass(slots=True)
class ObservabilityConfig:
    """Configuration object that drives initialisation behaviour."""

    service_name: str
    environment: str = os.getenv("CPC_ENVIRONMENT", "development")
    log_level: str = os.getenv("CPC_LOG_LEVEL", "INFO")
    tracing_endpoint: Optional[str] = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    metrics_port: int = int(os.getenv("CPC_METRICS_PORT", "8001"))
    sentry_dsn: Optional[str] = os.getenv("SENTRY_DSN")
    # More custom knobs can be added in the future

    # Internal flags  ------------------------------
    _tracing_enabled: bool = field(init=False, default=_OTEL_AVAILABLE)
    _metrics_enabled: bool = field(init=False, default=_PROM_AVAILABLE)

    def __post_init__(self) -> None:  # noqa: D401
        """Validate log-level and sanitise config."""
        self.log_level = self.log_level.upper()
        if self.log_level not in logging._nameToLevel:  # type: ignore
            raise ValueError(f"Invalid log level: {self.log_level}")


# ------------------------- ObservabilityManager -----------------------------

class ObservabilityManager:
    """
    Bundle together logging, tracing, and metrics initialisation & helpers.

    An instance *should be* created on service start-up and kept around (module
    global or DI container) — but re-entrancy is handled, so calling `init`
    multiple times will no-op.
    """

    _initialised: bool = False

    def __init__(self, config: ObservabilityConfig) -> None:
        self.config = config
        self.logger: structlog.BoundLogger | None = None

    # ---------------------- Initialisation API -----------------------------

    def init(self) -> None:
        """Initialise all configured observability components."""
        if ObservabilityManager._initialised:  # pragma: no cover
            return
        self._setup_logging()
        self._setup_tracing()
        self._setup_metrics()
        self._maybe_setup_sentry()
        ObservabilityManager._initialised = True
        self.logger.debug("Observability stack initialised.")

    # ---------------------- Logging ----------------------------------------

    def _setup_logging(self) -> None:
        """Configure *structured* logging with structlog."""
        timestamper = structlog.processors.TimeStamper(
            fmt="iso", utc=True, key="ts"
        )
        pre_chain: list[Callable[..., Any]] = [
            timestamper,
            self._add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
        ]

        # Final renderer: JSON for production, coloured console for local/dev.
        if self.config.environment in {"production", "staging"}:
            renderer: structlog.types.ProcessorFactory = (
                structlog.processors.JSONRenderer()
            )
        else:
            renderer = structlog.dev.ConsoleRenderer()

        structlog.configure(
            processors=[
                *pre_chain,
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                logging._nameToLevel[self.config.log_level]  # type: ignore
            ),
            cache_logger_on_first_use=True,
        )

        # Also instruct stdlib to forward to structlog.
        logging.basicConfig(
            level=self.config.log_level,
            stream=sys.stdout,
            format="%(message)s",
        )

        self.logger = structlog.get_logger(self.config.service_name)

    @staticmethod
    def _add_correlation_id(
        logger: structlog.BoundLogger,
        method_name: str,
        event_dict: dict[str, Any],
    ) -> dict[str, Any]:
        """Processor that adds `corr_id` to every log line."""
        corr_id = get_correlation_id()
        if corr_id:
            event_dict["corr_id"] = corr_id
        return event_dict

    # ---------------------- Tracing ----------------------------------------

    def _setup_tracing(self) -> None:
        """Initialise OpenTelemetry tracing if available."""
        if not (self.config._tracing_enabled and _OTEL_AVAILABLE):
            return

        resource = Resource.create(
            {
                "service.name": self.config.service_name,
                "service.version": os.getenv("VERSION", "dev"),
                "deployment.environment": self.config.environment,
            }
        )

        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        span_exporter: OTLPSpanExporter = OTLPSpanExporter(
            endpoint=self.config.tracing_endpoint,
            insecure=True,  # leverage HTTPS via gateway/load-balancer
            timeout=3,
        )
        span_processor = BatchSpanProcessor(span_exporter)
        provider.add_span_processor(span_processor)

        self.tracer = trace.get_tracer(self.config.service_name)

    # ---------------------- Metrics ----------------------------------------

    def _setup_metrics(self) -> None:
        """Expose Prometheus metrics endpoint."""
        if not (self.config._metrics_enabled and _PROM_AVAILABLE):
            return
        # Start HTTP server in background thread once per process.
        start_http_server(self.config.metrics_port)
        self.logger.info(
            "Prometheus metrics exporter started.",
            port=self.config.metrics_port,
        )

        # Useful default process metadata.
        Info("service_info", "Service level metadata").info(
            {
                "service": self.config.service_name,
                "environment": self.config.environment,
            }
        )

    # ---------------------- Sentry (optional) ------------------------------

    def _maybe_setup_sentry(self) -> None:
        """Configure Sentry SDK if DSN present.  Fails silently if unavailable."""
        dsn = self.config.sentry_dsn
        if not dsn:
            return
        try:
            import sentry_sdk  # noqa: WPS433 package import

            sentry_sdk.init(
                dsn=dsn,
                traces_sample_rate=0.1,
                environment=self.config.environment,
                release=os.getenv("COMMIT_SHA"),
            )
            self.logger.info("Sentry initialised.")
        except ImportError:  # pragma: no cover
            self.logger.warning("sentry_sdk not available; skipping integration.")


# ------------------------- Decorators & Helpers -----------------------------

if _PROM_AVAILABLE:
    _REQUEST_LATENCY = Histogram(
        "cpc_function_latency_seconds",
        "Latency of decorated functions.",
        ["service", "function", "success"],
        buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 5),
    )
    _REQUEST_COUNTER = Counter(
        "cpc_function_calls_total",
        "Count of decorated function invocations.",
        ["service", "function", "success"],
    )
else:
    _REQUEST_LATENCY = None  # type: ignore
    _REQUEST_COUNTER = None  # type: ignore


def _record_metrics(
    service_name: str,
    func_name: str,
    duration: float,
    succeeded: bool,
) -> None:  # noqa: D401
    """Helper that records metrics, when Prometheus is available."""
    if not _PROM_AVAILABLE:
        return
    labels = {
        "service": service_name,
        "function": func_name,
        "success": str(succeeded).lower(),
    }
    _REQUEST_LATENCY.labels(**labels).observe(duration)
    _REQUEST_COUNTER.labels(**labels).inc()


def _get_tracer() -> Optional["trace.Tracer"]:
    if _OTEL_AVAILABLE:
        return trace.get_tracer("crowdpay-connect")
    return None


def instrumented(
    *,
    name: Optional[str] = None,
    record_args: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator that adds tracing, structured logging & metrics to a callable.

    Parameters
    ----------
    name:
        Override the *logical* operation name used in tracing & metrics.
    record_args:
        If *True*, serialises and stores arguments in logs (beware of PII).

    Works for both synchronous and asynchronous callables.
    """

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        op_name = name or func.__qualname__
        is_coro = asyncio.iscoroutinefunction(func)
        tracer = _get_tracer()

        @functools.wraps(func)
        def _sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore [override]
            start_time = time.perf_counter()
            with (
                tracer.start_as_current_span(op_name) if tracer else contextlib.nullcontext()  # type: ignore
            ) as span:
                if span and record_args:
                    span.set_attribute("args", str(args))
                    span.set_attribute("kwargs", str(kwargs))
                try:
                    result = func(*args, **kwargs)
                    succeeded = True
                    return result
                except Exception as exc:
                    succeeded = False
                    if span:
                        span.record_exception(exc)
                        span.set_status(
                            trace.status.Status(
                                trace.status.StatusCode.ERROR, str(exc)
                            )
                        )
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    _record_metrics(
                        service_name=os.getenv("CPC_SERVICE", "unknown"),
                        func_name=op_name,
                        duration=duration,
                        succeeded=succeeded,
                    )

        @functools.wraps(func)
        async def _async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:  # type: ignore [override]
            start_time = time.perf_counter()
            with (
                tracer.start_as_current_span(op_name) if tracer else contextlib.nullcontext()  # type: ignore
            ) as span:
                if span and record_args:
                    span.set_attribute("args", str(args))
                    span.set_attribute("kwargs", str(kwargs))
                try:
                    result = await func(*args, **kwargs)  # type: ignore [func-returns-value]
                    succeeded = True
                    return result
                except Exception as exc:
                    succeeded = False
                    if span:
                        span.record_exception(exc)
                        span.set_status(
                            trace.status.Status(
                                trace.status.StatusCode.ERROR, str(exc)
                            )
                        )
                    raise
                finally:
                    duration = time.perf_counter() - start_time
                    _record_metrics(
                        service_name=os.getenv("CPC_SERVICE", "unknown"),
                        func_name=op_name,
                        duration=duration,
                        succeeded=succeeded,
                    )

        return _async_wrapper if is_coro else _sync_wrapper

    return decorator


# -------------------------- Convenience API ---------------------------------

def record_custom_metric(
    name: str,
    value: Union[int, float],
    *,
    labels: Optional[dict[str, str]] = None,
) -> None:
    """
    Expose *ad-hoc* counter or gauge increment.

    Parameters
    ----------
    name:
        Metric name.  Will be created if it doesn't exist.
    value:
        Amount to increment the counter or set the gauge to.
    labels:
        Prometheus labels ‑ helps produce cardinality when used correctly.

    Notes
    -----
    Only available when `prometheus_client` is installed; otherwise, becomes
    a no-op to prevent cascading failures.
    """
    if not _PROM_AVAILABLE:
        return

    from prometheus_client import Gauge

    metric_key = (name, tuple(sorted((labels or {}).items())))
    if not hasattr(record_custom_metric, "_cache"):  # type: ignore
        setattr(record_custom_metric, "_cache", {})  # type: ignore
    cache: dict[Any, Gauge] = getattr(record_custom_metric, "_cache")  # type: ignore

    if metric_key not in cache:
        cache[metric_key] = Gauge(name, f"Custom metric {name}", (labels or {}).keys())
    gauge = cache[metric_key]
    gauge.labels(**(labels or {})).set(value)


# --------------------------- Audit helper -----------------------------------

def audit_log(
    message: str,
    *,
    actor_id: str,
    entity: str,
    entity_id: str,
    action: str,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """
    Emit an *immutable* audit record that can be persisted downstream.

    The log line is intentionally denormalised & self-contained, providing all
    contextual fields necessary for compliance review.  Downstream consumers
    (Kafka topic, Elk stack, etc.) can then parse & process as required.

    This helper only **logs**; persisting to an append-only store is handled by
    the central log shipper.
    """
    logger = structlog.get_logger("audit")
    logger.info(
        message,
        timestamp=datetime.utcnow().isoformat(),
        actor_id=actor_id,
        entity=entity,
        entity_id=entity_id,
        action=action,
        **(extra or {}),
    )
```
```python
"""
ledgerquest.services.auditing
=============================

Centralised audit-logging facilities for LedgerQuest Engine.

Why a dedicated module?
-----------------------
LedgerQuest is designed for deployment in heavily-regulated,
multi-tenant SaaS environments.  Capturing a tamper-evident,
well-structured audit trail for *every* state-mutating action is just as
important as simulating physics or rendering pixels.

This package offers:

1. A vendor-agnostic `AuditLogger` that automatically fans-out events to:
   • DynamoDB (authoritative, queryable store)  
   • CloudWatch Logs (cheap, searchable, near-realtime)  
   • EventBridge (optional—enables reactive, cross-service workflows)

2. Context propagation helpers (`AuditContext`) so that deeply-nested
   functions do not need to pass around `tenant_id`, `user_id`, etc.

3. A `@audited` decorator for effortless instrumentation of public API
   functions, Lambda handlers, Step-Function tasks, etc.

All public symbols are re-exported at package-level for convenience:

    from ledgerquest.services.auditing import (
        AuditEvent,
        AuditLogger,
        AuditContext,
        audited,
        get_audit_logger,
    )
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
import time
import uuid
from contextlib import AbstractContextManager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Generator, Optional

try:  # Optional AWS deps
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ModuleNotFoundError:  # pragma: no cover
    boto3 = None  # type: ignore
    BotoCoreError = ClientError = Exception  # type: ignore


# ---------------------------------------------------------------------------#
#                               CONFIGURATION                                #
# ---------------------------------------------------------------------------#

_DEFAULT_DDB_TABLE = os.getenv("LEDGERQUEST_AUDIT_DDB_TABLE", "ledgerquest-audit")
_DEFAULT_EVENT_BUS = os.getenv("LEDGERQUEST_AUDIT_EVENTBUS", "ledgerquest-audit-bus")
_STAGE = os.getenv("STAGE", "dev")
_MAX_DDB_BATCH_SIZE = 25  # DynamoDB's maximum for batch_write_item


# ---------------------------------------------------------------------------#
#                          CONTEXT PROPAGATION                               #
# ---------------------------------------------------------------------------#

_tenant_ctx: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)
_user_ctx: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
_corr_ctx: ContextVar[str] = ContextVar("correlation_id", default="")


def _current_timestamp() -> str:
    """Helper to get a UTC ISO-8601 timestamp."""
    return _dt.datetime.utcnow().replace(tzinfo=_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------#
#                               DATA MODEL                                   #
# ---------------------------------------------------------------------------#


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """
    Immutable value-object representing a single audit record.
    """
    tenant_id: str
    user_id: str
    correlation_id: str
    action: str
    entity: str
    timestamp: str = field(default_factory=_current_timestamp)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_ddb_item(self) -> Dict[str, Any]:
        """
        Convert the event into a shape suitable for DynamoDB put_item.
        Uses a composite primary key:  PK = tenant_id, SK = timestamp#uuid
        """
        return {
            "PK": self.tenant_id,
            "SK": f"{self.timestamp}#{self.correlation_id}",
            "UserId": self.user_id,
            "Action": self.action,
            "Entity": self.entity,
            "Details": self.details,
            "Stage": _STAGE,
        }

    def to_eventbridge_entry(self) -> Dict[str, Any]:
        """
        Format entry for EventBridge PutEvents.
        """
        return {
            "Source": "ledgerquest.audit",
            "DetailType": self.action,
            "Detail": json.dumps(asdict(self)),
            "EventBusName": _DEFAULT_EVENT_BUS,
            "Time": _dt.datetime.fromisoformat(self.timestamp),
            "Resources": [self.tenant_id],
        }


# ---------------------------------------------------------------------------#
#                           AUDIT LOGGER CORE                                #
# ---------------------------------------------------------------------------#


class AuditLogger:
    """
    Concrete implementation responsible for persisting/publishing audit
    events.  Thread-safe (per AWS SDK threads) but *not* fork-safe.
    """

    def __init__(
        self,
        ddb_table: str = _DEFAULT_DDB_TABLE,
        event_bus: str = _DEFAULT_EVENT_BUS,
        *,
        enable_cloudwatch: bool = True,
        log_level: int = logging.INFO,
    ) -> None:
        self._ddb_table_name = ddb_table
        self._event_bus_name = event_bus
        self._enable_cloudwatch = enable_cloudwatch

        self._logger = logging.getLogger("ledgerquest.audit")
        self._logger.setLevel(log_level)

        # AWS clients are expensive; create once.
        if boto3:
            self._ddb = boto3.resource("dynamodb")
            self._ddb_table = self._ddb.Table(self._ddb_table_name)
            self._eventbridge = boto3.client("events")
        else:
            self._ddb = self._ddb_table = self._eventbridge = None

        # Batching queue for DDB writes to reduce API calls under load
        self._batch: list[AuditEvent] = []
        self._batch_lock = threading.Lock()
        self._flush_thread = threading.Thread(
            target=self._flush_daemon, name="AuditFlushThread", daemon=True
        )
        self._flush_thread.start()

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def log(self, event: AuditEvent) -> None:
        """
        Accept an event and send to downstream sinks. Fast-return;
        heavy-lifting occurs in background flush thread.
        """
        if not isinstance(event, AuditEvent):
            raise TypeError("event must be an AuditEvent")

        with self._batch_lock:
            self._batch.append(event)
            if len(self._batch) >= _MAX_DDB_BATCH_SIZE:
                self._flush_batch()

        if self._enable_cloudwatch:
            # Log a brief line to CW; full data will be in DynamoDB.
            self._logger.info(
                "%s | %s | %s | %s",
                event.tenant_id,
                event.user_id,
                event.action,
                event.entity,
            )

    # --------------------------------------------------------------------- #
    #               INTERNAL BATCH/FLUSH MANAGEMENT                         #
    # --------------------------------------------------------------------- #

    def _flush_daemon(self) -> None:  # pragma: no cover
        """
        Background thread ensuring the batch queue is periodically flushed
        even during low traffic periods.
        """
        while True:
            time.sleep(2.0)
            with self._batch_lock:
                self._flush_batch()

    def _flush_batch(self) -> None:
        """
        Flush in-memory batch to DynamoDB & EventBridge.
        """
        if not self._batch:
            return

        pending = self._batch[:]
        self._batch.clear()

        if self._ddb_table:  # DynamoDB (authoritative)
            try:
                with self._ddb_table.batch_writer(overwrite_by_pkeys=("PK", "SK")) as bw:
                    for ev in pending:
                        bw.put_item(Item=ev.to_ddb_item())
            except (BotoCoreError, ClientError) as exc:  # pragma: no cover
                self._logger.error("Failed to write audit batch to DynamoDB: %s", exc, exc_info=True)

        # EventBridge (reactive flows). Don't fail overall if EB is down.
        if self._eventbridge:
            try:
                entries = [ev.to_eventbridge_entry() for ev in pending]
                # EventBridge allows max 10 entries per call
                for i in range(0, len(entries), 10):
                    slice_ = entries[i : i + 10]
                    self._eventbridge.put_events(Entries=slice_)
            except (BotoCoreError, ClientError) as exc:  # pragma: no cover
                self._logger.warning("Failed to publish audit events to EventBridge: %s", exc)

    # --------------------------------------------------------------------- #
    # Utility helpers                                                       #
    # --------------------------------------------------------------------- #

    def audit(
        self,
        action: str,
        entity: str,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditEvent:
        """
        Construct and immediately persist an `AuditEvent` built from
        supplied or context-inherited data.
        """
        ev = AuditEvent(
            tenant_id=tenant_id or _tenant_ctx.get(),
            user_id=user_id or _user_ctx.get(),
            correlation_id=correlation_id or _corr_ctx.get() or uuid.uuid4().hex,
            action=action,
            entity=entity,
            details=details or {},
        )
        self.log(ev)
        return ev


# ---------------------------------------------------------------------------#
#           CONTEXT MANAGER / DECORATOR FOR EASY INSTRUMENTATION             #
# ---------------------------------------------------------------------------#


class AuditContext(AbstractContextManager["AuditContext"]):
    """
    Context manager that temporarily sets tenant/user/correlation context
    variables—useful when entering a Lambda handler or API request.

    Example:
        with AuditContext(tenant_id="acme", user_id="u123"):
            do_work()
    """

    def __init__(
        self,
        *,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self._tokens: list[tuple[ContextVar[Any], Any]] = []
        self._values = {
            _tenant_ctx: tenant_id,
            _user_ctx: user_id,
            _corr_ctx: correlation_id or uuid.uuid4().hex,
        }

    # Contextmanager protos
    def __enter__(self) -> "AuditContext":
        for var, value in self._values.items():
            if value is not None:
                self._tokens.append((var, var.set(value)))
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: D401
        for var, token in reversed(self._tokens):
            var.reset(token)
        return False  # do NOT swallow exceptions

    # Expose read-only properties
    @property
    def tenant_id(self) -> Optional[str]:
        return _tenant_ctx.get()

    @property
    def user_id(self) -> Optional[str]:
        return _user_ctx.get()

    @property
    def correlation_id(self) -> str:
        return _corr_ctx.get()


def audited(
    *,
    action: str,
    entity: str,
    detail_fn: Optional[Callable[[Any, tuple, dict], Dict[str, Any]]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator which records an audit event *after* successful execution of
    the wrapped function.

    Parameters
    ----------
    action: str
        High-level verb (e.g. "CREATE", "DELETE", "PAY_INVOICE")
    entity: str
        Business or domain entity being acted upon (e.g. "PlayerProfile")
    detail_fn: Callable
        Optional callable `(result, args, kwargs) -> Dict[str, Any]`
        that dynamically builds the `details` payload.

    Notes
    -----
    • Exceptions raised by the wrapped function are *not* swallowed; no
      audit entry is recorded on errors (to prevent leaking invalid data).
    • The decorator captures function duration and injects it into the
      details dict under key `duration_ms`.
    """
    logger = None  # delayed global lookup to avoid early import cycles

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        nonlocal logger
        logger = get_audit_logger()

        @wraps(func)
        def wrapper(*args, **kwargs):  # type: ignore[override]
            start = time.perf_counter()
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000.0

            details: Dict[str, Any] = {"duration_ms": round(duration_ms, 3)}
            if detail_fn:
                try:
                    dynamic = detail_fn(result, args, kwargs) or {}
                    details.update(dynamic)
                except Exception as exc:  # pragma: no cover
                    logger._logger.warning(
                        "detail_fn failed for %s.%s: %s", func.__module__, func.__name__, exc
                    )

            logger.audit(action=action, entity=entity, details=details)
            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------#
#                         GLOBAL SINGLETON MANAGEMENT                        #
# ---------------------------------------------------------------------------#

_global_audit_logger: Optional[AuditLogger] = None
_global_lock = threading.Lock()


def configure_audit_logger(*, logger: Optional[AuditLogger] = None, **kwargs) -> AuditLogger:
    """
    Initialise or override the module-level `AuditLogger` instance.

    Example:
        configure_audit_logger(ddb_table="custom-table", event_bus="my-bus")
    """
    global _global_audit_logger
    with _global_lock:
        if logger is not None:
            _global_audit_logger = logger
        elif _global_audit_logger is None:
            _global_audit_logger = AuditLogger(**kwargs)
        return _global_audit_logger


def get_audit_logger() -> AuditLogger:
    """
    Retrieve the global `AuditLogger`, creating it lazily if required.
    """
    if _global_audit_logger is None:
        return configure_audit_logger()
    return _global_audit_logger


# Publish public interface
__all__ = [
    "AuditEvent",
    "AuditLogger",
    "AuditContext",
    "audited",
    "get_audit_logger",
    "configure_audit_logger",
]
```
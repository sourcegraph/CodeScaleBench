"""
ledgerquest.services
--------------------

Service layer abstractions for LedgerQuest Engine.

This package offers:

* A global service registry (`service_registry`) that provides lazily-loaded,
  thread-safe singletons for external integrations (e.g. DynamoDB, S3,
  EventBridge).
* Multi-tenant context propagation helpers (`with_tenant`, `current_tenant`)
  so that every service invocation is tenant-aware by default.
* Thin, opinionated wrappers around common AWS services that add ergonomics,
  structured logging, retry guards, and consistent error handling.

The goal is to keep business/game logic completely stateless and unaware of
infrastructure details while still making it trivial to talk to AWS services
inside Lambda, Step Functions, or local unit tests.

This file purposefully lives in ``__init__.py`` so that consumers can simply
write:

    from ledgerquest.services import get_service, with_tenant

without worrying about additional imports.
"""
from __future__ import annotations

from decimal import Decimal
import contextlib
import contextvars
import json
import logging
import os
import threading
from typing import Any, Callable, Dict, Optional

# Optional runtime dependency – code still imports even if boto3 is absent
try:
    import boto3
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None            # type: ignore
    BotoConfig = object      # type: ignore
    BotoCoreError = Exception  # type: ignore
    ClientError = Exception    # type: ignore


__all__ = [
    "get_service",
    "service_registry",
    "with_tenant",
    "current_tenant",
    "BaseService",
    "DynamoDBService",
    "S3Service",
    "EventBridgeService",
    "ServiceRegistry",
]


# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

logger = logging.getLogger("ledgerquest.services")
logger.setLevel(logging.INFO)

# Avoid duplicate handlers when the module is re-loaded (e.g. by pytest)
if not any(getattr(h, "name", None) == "LQServiceHandler" for h in logger.handlers):
    _handler = logging.StreamHandler()
    _handler.name = "LQServiceHandler"
    _handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(tenant)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    logger.addHandler(_handler)


# --------------------------------------------------------------------------- #
# Tenant context                                                              #
# --------------------------------------------------------------------------- #

_current_tenant: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ledgerquest_current_tenant", default="system"
)


def _inject_tenant(record: logging.LogRecord) -> bool:  # noqa: D401
    """Logging filter that injects the tenant id into every record."""
    record.tenant = _current_tenant.get()
    return True


logger.addFilter(_inject_tenant)


@contextlib.contextmanager
def with_tenant(tenant_id: str):
    """
    Context manager for scoping work to a particular tenant.

    Example
    -------
    >>> with with_tenant("acme-co"):
    ...     get_service("dynamodb").table("Players").put_item(Item={...})
    """
    if not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")

    token = _current_tenant.set(tenant_id)
    try:
        yield
    finally:
        # Always restore previous context (even on exception)
        _current_tenant.reset(token)


def current_tenant() -> str:
    """
    Returns the tenant bound to the current execution context.

    Defaults to ``\"system\"`` when called outside of a :func:`with_tenant`
    scope (e.g. during start-up or maintenance tasks).
    """
    return _current_tenant.get()


# --------------------------------------------------------------------------- #
# Base service class                                                          #
# --------------------------------------------------------------------------- #


class BaseService:
    """
    Abstract base-class that wraps an external service client (usually boto3).

    Sub-classes implement :meth:`_create_client` to lazily-instantiate the real
    client behind a thread-safe memoised property (:attr:`client`).

    They also get :meth:`safe_call`, a convenience wrapper that applies
    structured logging and surfaces AWS errors cleanly.
    """

    _client_lock: threading.Lock
    _client: Any

    def __init__(self, service_name: str, **boto_kwargs: Any):
        self._service_name = service_name
        self._boto_kwargs = boto_kwargs
        self._client_lock = threading.Lock()
        self._client = None

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    @property
    def client(self) -> Any:
        """Lazily create and cache the underlying client in a thread-safe way."""
        if self._client is None:
            with self._client_lock:
                if self._client is None:  # Double-checked locking
                    self._client = self._create_client()
        return self._client

    def safe_call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Run a boto3 call inside a try/except with structured logging.

        Parameters
        ----------
        fn
            The bound method on a boto3 client (e.g. ``client.put_item``).
        *args, **kwargs
            Forwarded directly to :pycode:`fn`.

        Returns
        -------
        Any
            The response from the AWS SDK.
        """
        try:
            response = fn(*args, **kwargs)
            logger.debug("AWS call %s.%s succeeded", self._service_name, fn.__name__)
            return response
        except (ClientError, BotoCoreError) as exc:  # pragma: no cover
            logger.error(
                "AWS call %s.%s failed for tenant %s: %s",
                self._service_name,
                fn.__name__,
                current_tenant(),
                exc,
            )
            raise

    # --------------------------------------------------------------------- #
    # Sub-class hooks                                                       #
    # --------------------------------------------------------------------- #

    def _create_client(self) -> Any:
        """
        Instantiate the boto3 client.

        Sub-classes can override to supply a custom resource (e.g. DynamoDB
        *resource* instead of *client*) yet still benefit from lazy init.
        """
        if boto3 is None:
            raise RuntimeError(
                "boto3 is required for cloud operations. "
                "Install it via `pip install boto3`."
            )

        logger.debug("Creating boto3 client '%s'", self._service_name)
        cfg = BotoConfig(
            retries={
                "max_attempts": int(os.getenv("LEDGERQUEST_BOTO_MAX_ATTEMPTS", "5")),
                "mode": "adaptive",
            },
            user_agent_extra=f"LQEngine/{os.getenv('LQENGINE_VERSION', 'dev')}",
        )

        return boto3.client(
            self._service_name,
            region_name=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
            config=cfg,
            **self._boto_kwargs,
        )


# --------------------------------------------------------------------------- #
# Concrete service wrappers                                                   #
# --------------------------------------------------------------------------- #


class DynamoDBService(BaseService):
    """
    DynamoDB helper that prefixes table names with ``<tenant>_`` at runtime.

    This allows a single AWS account to host fully isolated per-tenant tables
    without any dynamic IAM magic.
    """

    _table_cache: Dict[str, Any]

    def __init__(self, table_prefix: str = ""):
        super().__init__("dynamodb")
        self._table_prefix = table_prefix or os.getenv("LEDGERQUEST_DDB_PREFIX", "")
        self._table_cache = {}

    # Public helpers ------------------------------------------------------ #

    def table(self, name: str):
        """
        Return a boto3 ``Table`` resource scoped to the current tenant.

        >>> tbl = get_service("dynamodb").table("Players")
        >>> tbl.put_item(Item={"PK": "player#42", ...})
        """
        qualified_name = f"{self._table_prefix}{current_tenant()}_{name}"
        if qualified_name not in self._table_cache:
            # Resource objects are heavier than vanilla clients; cache them
            resource = boto3.resource("dynamodb")  # type: ignore
            self._table_cache[qualified_name] = resource.Table(qualified_name)
            logger.debug("Initialised DynamoDB.Table('%s')", qualified_name)
        return self._table_cache[qualified_name]


class S3Service(BaseService):
    """
    S3 helper that prefixes keys with ``<tenant>/`` to keep asset namespaces
    separated in a shared bucket.
    """

    def __init__(self, bucket: str):
        super().__init__("s3")
        if not bucket:
            raise ValueError("bucket name must not be empty")
        self._bucket = bucket

    # Public helpers ------------------------------------------------------ #

    def put_object(self, key: str, body: bytes, **kwargs: Any):
        tenant_key = self._qualify_key(key)
        logger.debug("Uploading s3://%s/%s (%s bytes)", self._bucket, tenant_key, len(body))
        return self.safe_call(
            self.client.put_object, Bucket=self._bucket, Key=tenant_key, Body=body, **kwargs
        )

    def get_object(self, key: str, **kwargs: Any):
        tenant_key = self._qualify_key(key)
        logger.debug("Fetching s3://%s/%s", self._bucket, tenant_key)
        return self.safe_call(
            self.client.get_object, Bucket=self._bucket, Key=tenant_key, **kwargs
        )

    # Internal ------------------------------------------------------------ #

    @staticmethod
    def _strip_leading_slash(s: str) -> str:
        return s[1:] if s.startswith("/") else s

    def _qualify_key(self, key: str) -> str:
        return f"{current_tenant()}/{self._strip_leading_slash(key)}"


class EventBridgeService(BaseService):
    """
    Wrapper for publishing events to an EventBridge bus.

    Events are JSON-serialised with a custom encoder that handles common
    non-serialisable types (``Decimal``, ``numpy`` dtypes, etc.).
    """

    def __init__(self, event_bus: str):
        if not event_bus:
            raise ValueError("event_bus cannot be empty")
        super().__init__("events")
        self._event_bus = event_bus

    # Public helpers ------------------------------------------------------ #

    def put_event(
        self,
        detail_type: str,
        detail: Dict[str, Any],
        source: str = "ledgerquest.engine",
    ):
        entry = {
            "EventBusName": self._event_bus,
            "Source": source,
            "DetailType": detail_type,
            "Detail": _json_dumps(detail),
        }
        logger.debug("Publishing EventBridge event: %s", entry)
        return self.safe_call(self.client.put_events, Entries=[entry])


# --------------------------------------------------------------------------- #
# JSON helper                                                                 #
# --------------------------------------------------------------------------- #


def _json_dumps(obj: Any) -> str:
    """Compact JSON dump that gracefully degrades on unknown types."""

    class _Encoder(json.JSONEncoder):
        def default(self, o):  # type: ignore[override]
            if isinstance(o, Decimal):
                return float(o)
            try:
                import numpy as _np  # noqa: WPS433 (runtime import is intentional)

                if isinstance(o, _np.integer):
                    return int(o)
                if isinstance(o, _np.floating):
                    return float(o)
                if isinstance(o, _np.ndarray):
                    return o.tolist()
            except ImportError:  # pragma: no cover
                pass
            return super().default(o)

    return json.dumps(obj, cls=_Encoder, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# Service registry                                                            #
# --------------------------------------------------------------------------- #


class ServiceRegistry:
    """
    Thread-safe singleton store for service instances.

    This behaves like a very light-weight dependency-injection container.
    """

    def __init__(self):
        self._services: Dict[str, BaseService] = {}
        self._lock = threading.Lock()

    # Public API ---------------------------------------------------------- #

    def register(self, name: str, service: BaseService) -> None:
        if not name:
            raise ValueError("service name cannot be empty")
        with self._lock:
            logger.debug("Registering service '%s' -> %s", name, service)
            self._services[name] = service

    def get(self, name: str) -> BaseService:
        with self._lock:
            if name not in self._services:
                raise KeyError(f"Service '{name}' has not been registered")
            return self._services[name]

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._services

    def clear(self) -> None:  # Useful for unit tests
        with self._lock:
            self._services.clear()


# --------------------------------------------------------------------------- #
# Global registry with opinionated defaults                                   #
# --------------------------------------------------------------------------- #

service_registry = ServiceRegistry()

# Eagerly register common services if environment variables are set.
# These env vars are typically injected by IaC stacks or the local sim harness.
if os.getenv("LEDGERQUEST_DDB_PREFIX") is not None:
    service_registry.register(
        "dynamodb",
        DynamoDBService(table_prefix=os.getenv("LEDGERQUEST_DDB_PREFIX", "")),
    )

if os.getenv("LEDGERQUEST_ASSET_BUCKET"):
    service_registry.register(
        "s3",
        S3Service(bucket=os.getenv("LEDGERQUEST_ASSET_BUCKET")),
    )

if os.getenv("LEDGERQUEST_EVENT_BUS"):
    service_registry.register(
        "eventbridge",
        EventBridgeService(event_bus=os.getenv("LEDGERQUEST_EVENT_BUS")),
    )


def get_service(name: str) -> BaseService:
    """
    Convenience alias around :meth:`ServiceRegistry.get`.

    Example
    -------
    >>> tbl = get_service("dynamodb").table("Players")
    """
    return service_registry.get(name)


# Backwards-compatibility alias (some internal modules still call `get`)
get = get_service  # type: ignore

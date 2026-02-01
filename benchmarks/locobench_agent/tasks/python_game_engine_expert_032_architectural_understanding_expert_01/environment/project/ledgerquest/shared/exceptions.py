```python
"""
ledgerquest.shared.exceptions
=============================

Centralised exception hierarchy for the LedgerQuest Engine.

This module is intended to be the single source-of-truth for *all* custom
exceptions raised by the engine—across Lambda functions, Step Functions, GPU
workers, and client-side WebSocket handlers.

The design goals are:

1.  Consistent serialisation:
    Structured errors can be pushed to CloudWatch, XRay, or returned via the
    API Gateway WebSocket channel without ad-hoc `str(exc)` calls.

2.  Minimal dependencies:
    Only the Python standard library (plus an **optional** `boto3` import for
    DynamoDB/S3 error wrapping) is used. Nothing in this file should require
    AWS credentials at import-time.

3.  Extensibility:
    Down-stream packages (e.g. `ledgerquest.physics`, `ledgerquest.ai`) may
    subclass any exception here for more granular control without reinventing
    base behaviour.

4.  Production readiness:
    - Severity levels allow central alerting (PagerDuty, Slack, etc.).
    - Error codes allow front-end clients to localise messages.
    - Built-in logging prevents the classic “raised but never logged” problem.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import Any, Mapping, MutableMapping, Optional, Type, Union, overload

__all__ = [
    "ErrorSeverity",
    "LedgerQuestError",
    "ConfigurationError",
    "ValidationError",
    "AssetNotFoundError",
    "AuthorizationError",
    "DataAccessError",
    "ConcurrencyError",
    "StepFunctionError",
    "EngineRuntimeError",
    "RateLimitExceededError",
    "unwrap_exception",
]

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #

_logger = logging.getLogger("ledgerquest.exceptions")

# Honour application-wide debug flag (can be set by AWS Lambda environment vars)
if os.getenv("LEDGERQUEST_DEBUG", "false").lower() in {"1", "true", "yes"}:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.INFO)


# --------------------------------------------------------------------------- #
# Helper Enums
# --------------------------------------------------------------------------- #


class ErrorSeverity(str, Enum):
    """
    Severity levels used throughout the engine for error classification.
    """

    DEBUG = "DEBUG"  # Used for rich information unlikely to require alerting
    INFO = "INFO"  # Benign anomalies (e.g. cache miss)
    WARNING = "WARNING"  # Non-fatal issues worth attention
    ERROR = "ERROR"  # Recoverable error; engine continues to run
    CRITICAL = "CRITICAL"  # Unrecoverable error; triggers alerts & circuit-breakers


# --------------------------------------------------------------------------- #
# Data Classes & Core Exception
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _ErrorMeta:
    """
    Immutable metadata to accompany every LedgerQuestError.

    Attributes
    ----------
    code:
        Stable error code (machine-readable, used by front-end & integration tests).
    severity:
        ErrorSeverity level.
    namespace:
        Dotted namespace of the module that raised this error.
    """
    code: str
    severity: ErrorSeverity
    namespace: str


class LedgerQuestError(Exception):
    """
    Base-class for *all* engine-defined exceptions.

    Parameters
    ----------
    message:
        Human-readable message (will be logged and made available to callers).
    code:
        Stable string identifier (e.g. ``"LQ-E00123"``).  Should follow
        ``<ProductCode>-<ServiceCode><Sequence>`` in larger organisations.
    severity:
        An :pyclass:`ErrorSeverity` hint to centralised logging / alerting.
    details:
        Optional structured metadata included in the serialised representation.
    log_immediately:
        When ``True`` (default), the error is logged at instantiation time.
    cause:
        Downstream exception that triggered this error. This is *not* the same
        as ``__cause__``; Python's native exception chaining is preserved.
    """

    __slots__ = ("_meta", "_message", "_details")

    def __init__(
        self,
        message: str,
        *,
        code: str = "LQ-E00000",
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        details: Optional[Mapping[str, Any]] = None,
        log_immediately: bool = True,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        namespace = self.__class__.__module__
        self._meta = _ErrorMeta(code=code, severity=severity, namespace=namespace)
        self._message = message
        self._details = dict(details or {})  # copy

        # Preserve exception chaining semantics
        if cause is not None:
            self.__cause__ = cause  # type: ignore[attr-defined]

        if log_immediately:
            self.log()

    # --------------------------------------------------------------------- #
    # Properties
    # --------------------------------------------------------------------- #

    @property
    def code(self) -> str:  # pragma: no cover
        return self._meta.code

    @property
    def severity(self) -> ErrorSeverity:  # pragma: no cover
        return self._meta.severity

    @property
    def namespace(self) -> str:  # pragma: no cover
        return self._meta.namespace

    @property
    def details(self) -> Mapping[str, Any]:  # pragma: no cover
        return self._details

    # --------------------------------------------------------------------- #
    # Serialisation / Representations
    # --------------------------------------------------------------------- #

    def to_dict(self, include_traceback: bool = False) -> MutableMapping[str, Any]:
        """
        Convert the exception into a JSON-serialisable mapping.

        ``traceback`` is *expensive* to compute and should be excluded in
        production unless explicitly required.
        """
        payload: MutableMapping[str, Any] = {
            "code": self.code,
            "severity": self.severity.value,
            "message": self._message,
            "namespace": self.namespace,
            "details": self._details,
        }
        if include_traceback:
            payload["traceback"] = traceback.format_exception(
                type(self), self, self.__traceback__
            )
        if self.__cause__:
            payload["cause"] = str(self.__cause__)
        return payload

    def to_json(self, **json_kwargs: Any) -> str:
        """
        JSON serialise the error using :pymod:`json`.

        All keyword args are forwarded to :pyfunc:`json.dumps`.
        """
        return json.dumps(self.to_dict(), **json_kwargs)

    # --------------------------------------------------------------------- #
    # Logging utilities
    # --------------------------------------------------------------------- #

    def log(self, *, include_traceback: bool = False) -> None:  # pragma: no cover
        """
        Log the error immediately.

        Severity maps directly onto :pymod:`logging` levels.
        """
        log_level = {
            ErrorSeverity.DEBUG: logging.DEBUG,
            ErrorSeverity.INFO: logging.INFO,
            ErrorSeverity.WARNING: logging.WARNING,
            ErrorSeverity.ERROR: logging.ERROR,
            ErrorSeverity.CRITICAL: logging.CRITICAL,
        }[self.severity]

        if include_traceback:
            _logger.log(log_level, "%s", self, exc_info=self)
        else:
            _logger.log(log_level, "%s | %s", self.code, self)

    # --------------------------------------------------------------------- #
    # Dunders
    # --------------------------------------------------------------------- #

    def __str__(self) -> str:
        return f"[{self.code}] {self._message}"

    __repr__ = __str__  # Keep it readable in REPLs


# --------------------------------------------------------------------------- #
# Concrete Exception Sub-classes
# --------------------------------------------------------------------------- #


class ConfigurationError(LedgerQuestError):
    """
    Raised when engine or game-specific configuration is invalid or missing.
    """

    def __init__(
        self,
        message: str = "Invalid or missing engine configuration.",
        *,
        details: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            message,
            code="LQ-CONFIG-001",
            severity=ErrorSeverity.CRITICAL,
            details=details,
            cause=cause,
        )


class ValidationError(LedgerQuestError):
    """
    Raised when user input or inter-service payloads fail validation.
    """

    def __init__(
        self,
        message: str = "Validation failed.",
        *,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            code="LQ-VALID-001",
            severity=ErrorSeverity.WARNING,
            details=details,
        )


class AssetNotFoundError(LedgerQuestError):
    """
    Raised when a requested asset (texture, 3D model, scene definition, etc.)
    does not exist in S3 or the Asset Catalogue.
    """

    def __init__(
        self,
        asset_id: str,
        *,
        bucket: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        msg = f"Asset '{asset_id}' not found."
        details = {"asset_id": asset_id}
        if bucket:
            details["bucket"] = bucket
        super().__init__(
            msg,
            code="LQ-ASSET-404",
            severity=ErrorSeverity.INFO,
            details=details,
            cause=cause,
        )


class AuthorizationError(LedgerQuestError):
    """
    Raised when an actor is not authorised to perform a given operation.
    """

    def __init__(
        self,
        actor_id: str,
        *,
        resource: Optional[str] = None,
        action: Optional[str] = None,
    ) -> None:
        msg = f"Actor '{actor_id}' is not authorised."
        details = {"actor_id": actor_id}
        if resource:
            details["resource"] = resource
        if action:
            details["action"] = action
        super().__init__(
            msg,
            code="LQ-AUTH-401",
            severity=ErrorSeverity.WARNING,
            details=details,
        )


class DataAccessError(LedgerQuestError):
    """
    Raised when data persistence or retrieval fails
    (DynamoDB, S3, Aurora Serverless, etc.).
    """

    def __init__(
        self,
        message: str = "Data access layer encountered an error.",
        *,
        details: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
        retryable: bool = False,
    ) -> None:
        detail_map = dict(details or {})
        detail_map["retryable"] = retryable
        super().__init__(
            message,
            code="LQ-DATA-500",
            severity=ErrorSeverity.ERROR,
            details=detail_map,
            cause=cause,
        )

    @property
    def retryable(self) -> bool:
        """
        Indicates whether the operation can be retried safely
        (based on AWS error codes, etc.).
        """
        return bool(self.details.get("retryable", False))


class ConcurrencyError(LedgerQuestError):
    """
    Raised when optimistic locking fails (e.g. `ConditionalCheckFailedException`
    in DynamoDB) or when the ECS attempts to mutate stale state.
    """

    def __init__(
        self,
        entity_id: str,
        *,
        message: str = "Concurrent modification detected.",
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            message,
            code="LQ-CONCUR-409",
            severity=ErrorSeverity.WARNING,
            details={"entity_id": entity_id},
            cause=cause,
        )


class StepFunctionError(LedgerQuestError):
    """
    Raised when the AWS Step Function orchestrating the game loop
    enters an unexpected state or fails execution.
    """

    def __init__(
        self,
        execution_arn: str,
        *,
        status: Optional[str] = None,
        message: str = "StepFunction execution failed.",
        cause: Optional[BaseException] = None,
    ) -> None:
        details = {"execution_arn": execution_arn}
        if status:
            details["status"] = status
        super().__init__(
            message,
            code="LQ-SFN-500",
            severity=ErrorSeverity.ERROR,
            details=details,
            cause=cause,
        )


class RateLimitExceededError(LedgerQuestError):
    """
    Raised when external services (e.g. DynamoDB, S3) return a throttling error.
    """

    def __init__(
        self,
        service_name: str,
        *,
        message: str = "Rate limit exceeded.",
        retry_after_seconds: Optional[int] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        details = {"service": service_name}
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(
            message,
            code="LQ-RATE-429",
            severity=ErrorSeverity.ERROR,
            details=details,
            cause=cause,
        )

    @property
    def retry_after(self) -> Optional[int]:  # pragma: no cover
        val = self.details.get("retry_after_seconds")
        return int(val) if val is not None else None


class EngineRuntimeError(LedgerQuestError):
    """
    Generic wrapper for unhandled exceptions occurring inside game logic.
    """

    def __init__(
        self,
        message: str = "An unexpected runtime error occurred in the engine.",
        *,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(
            message,
            code="LQ-RUNTIME-500",
            severity=ErrorSeverity.CRITICAL,
            cause=cause,
        )


# --------------------------------------------------------------------------- #
# Utility Functions
# --------------------------------------------------------------------------- #

@overload
def unwrap_exception(exc: LedgerQuestError) -> LedgerQuestError: ...
@overload
def unwrap_exception(exc: BaseException) -> EngineRuntimeError: ...


def unwrap_exception(exc: BaseException) -> LedgerQuestError:
    """
    Convert *any* exception into a :class:`LedgerQuestError`.

    If the exception is already a ``LedgerQuestError`` instance, it is returned
    as-is. Otherwise, it is wrapped in an :class:`EngineRuntimeError` instance,
    preserving the original exception via ``__cause__``.
    """
    if isinstance(exc, LedgerQuestError):
        return exc
    return EngineRuntimeError(cause=exc)


# --------------------------------------------------------------------------- #
# Optional AWS / boto3 Error Mapping
# --------------------------------------------------------------------------- #

try:
    from botocore.exceptions import ClientError  # type: ignore
except (ImportError, ModuleNotFoundError):
    ClientError = None  # type: ignore


def _is_retryable_boto3_error(error: "ClientError") -> bool:  # pragma: no cover
    """
    Inspect a boto3 ClientError and decide whether it can be retried.
    """
    error_code = error.response.get("Error", {}).get("Code", "")
    return error_code in {"ThrottlingException", "ProvisionedThroughputExceededException"}


def from_boto3_error(error: "ClientError") -> LedgerQuestError:  # pragma: no cover
    """
    Translate a :class:`botocore.exceptions.ClientError` into the appropriate
    LedgerQuestError subclass.
    """
    if ClientError is None or not isinstance(error, ClientError):  # noop fallback
        return EngineRuntimeError(cause=error)

    error_code: str = error.response.get("Error", {}).get("Code", "Unknown")
    message: str = error.response.get("Error", {}).get("Message", str(error))

    # Handle common throttling / retryable scenarios first
    if error_code in {
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
    }:
        retry_after: Optional[int] = None
        if "Retry-After" in error.response.get("ResponseMetadata", {}).get("HTTPHeaders", {}):
            retry_after = int(
                error.response["ResponseMetadata"]["HTTPHeaders"]["Retry-After"]
            )
        return RateLimitExceededError(
            service_name="AWS",
            message=message,
            retry_after_seconds=retry_after,
            cause=error,
        )

    # ConditionalCheckFailed == optimistic concurrency violation
    if error_code == "ConditionalCheckFailedException":
        # Extract the relevant key if possible
        entity_id = error.response.get("Error", {}).get("Item", {}).get("id", "unknown")
        return ConcurrencyError(entity_id=entity_id, cause=error)

    # Fallback to generic DataAccessError
    return DataAccessError(
        message=message,
        details={"aws_error_code": error_code},
        cause=error,
        retryable=_is_retryable_boto3_error(error),
    )
```
```python
"""
ledgerquest.services.asset_management.level_uploader
====================================================

A high-level orchestration module that validates, uploads, versions, and
announces new game-level assets produced by the LedgerQuest Level Editor.

Key Responsibilities
--------------------
1. Validation
   * Ensures both metadata and binary asset *package* conform to
     organisational rules (size, naming conventions, JSON schema, etc.).

2. Storage
   * Persists the raw artefact to S3 with strong content-addressable paths,
     enabling de-duplication and deterministic cache keys.

3. Persistence
   * Registers a manifest entry in DynamoDB to track versions, authors,
     audit fields, and integrity hashes.

4. Eventing
   * Emits a domain event to EventBridge so downstream consumers (texture
     optimisers, ECS warmers, etc.) can kick off follow-up jobs.

5. Observability / Robustness
   * Structured logs, AWS X-Ray trace injection, and best-effort retries
     with exponential back-off.

The module is purposely *stateless* so it can run within a Lambda
invocation or any other serverless container.

---------------------------------------------------------------------------
NOTE: keep external dependencies minimal. Heavier validation (e.g. full
JSON-Schema) happens in a separate validation Lambda; here we just
perform basic sanity checks.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import time
import uuid
from dataclasses import asdict, dataclass
from hashlib import blake2b
from typing import Any, Dict, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from mypy_boto3_dynamodb.service_resource import Table
from mypy_boto3_eventbridge.type_defs import PutEventsRequestEntryTypeDef
from mypy_boto3_s3.client import S3Client
from pydantic import BaseModel, Field, root_validator, validator

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.INFO)

# Environment variables injected by infrastructure-as-code
_BUCKET = os.getenv("LQ_LEVEL_BUCKET", "ledgerquest-levels")
_TABLE_NAME = os.getenv("LQ_LEVEL_TABLE", "lq-level-manifest")
_EVENT_BUS_NAME = os.getenv("LQ_EVENT_BUS", "ledgerquest-core")

# AWS client fine-tuning: low latency is preferred, but we keep some retries
# here so transient blips in Lambda networking do not break the flow.
_AWS_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    user_agent_extra="ledgerquest-level-uploader/1.0.0",
)

# -----------------------------------------------------------------------------
# Domain objects
# -----------------------------------------------------------------------------


class UploadError(Exception):
    """Raised for expected but unrecoverable validation/upload issues."""


class ExternalServiceError(Exception):
    """Raised when AWS APIs permanently fail after retries."""


class LevelUploadRequest(BaseModel):
    """Value object representing a caller's upload attempt."""

    tenant_id: str = Field(..., min_length=3, max_length=64)
    level_name: str = Field(..., min_length=3, max_length=128, regex=r"^[\w\- ]+$")
    author_id: str = Field(..., min_length=3, max_length=64)
    package_path: pathlib.Path
    version_tag: Optional[str] = Field(
        None, regex=r"^(?:v|V)?\d+\.\d+\.\d+$"
    )  # e.g. v1.2.3

    @validator("package_path")
    def _file_must_exist(cls, v: pathlib.Path) -> pathlib.Path:  # noqa: D401
        if not v.is_file():
            raise ValueError(f"Package path not found: {v}")
        return v

    @root_validator
    def _tenant_guard(cls, values: Dict[str, Any]) -> Dict[str, Any]:  # noqa: D401
        tenant_id = values.get("tenant_id")
        forbidden: set[str] = {"ledgerquest", "admin"}
        if tenant_id in forbidden:
            raise ValueError(f"Tenant id '{tenant_id}' is reserved.")
        return values


@dataclass(frozen=True)
class LevelUploadResult:
    tenant_id: str
    level_name: str
    version: str
    s3_uri: str
    manifest_id: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -----------------------------------------------------------------------------
# Uploader
# -----------------------------------------------------------------------------


class LevelUploader:
    """
    Orchestrates the full lifecycle of a level upload.

    Example
    -------
    >>> req = LevelUploadRequest(
    ...     tenant_id="acme-games",
    ...     level_name="Magma Ridge",
    ...     author_id="carol",
    ...     package_path=pathlib.Path("/tmp/magma_ridge.lqlevel"),
    ... )
    >>> result = LevelUploader().upload(req)
    """

    # S3 metadata key names
    _META_VERSION = "lq-level-version"
    _META_TENANT = "lq-tenant"
    _META_AUTHOR = "lq-author"

    def __init__(
        self,
        s3_client: Optional[S3Client] = None,
        dynamodb_table: Optional[Table] = None,
        eventbridge_client: Optional[Any] = None,
    ) -> None:
        self._s3 = s3_client or boto3.client("s3", config=_AWS_CONFIG)
        dynamodb = boto3.resource("dynamodb", config=_AWS_CONFIG)
        self._table = dynamodb_table or dynamodb.Table(_TABLE_NAME)
        self._events = eventbridge_client or boto3.client("events", config=_AWS_CONFIG)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def upload(self, request: LevelUploadRequest) -> LevelUploadResult:
        """
        Execute the upload flow.

        Steps
        -----
        1. Calculate deterministic hash of the level package
        2. Build S3 key and upload with metadata
        3. Persist manifest row in DynamoDB (conditional on new version)
        4. Emit EventBridge event for follow-up processing
        """
        _LOGGER.info(
            "Starting level upload | tenant=%s level=%s author=%s",
            request.tenant_id,
            request.level_name,
            request.author_id,
        )

        digest = self._hash_file(request.package_path)
        version = request.version_tag or f"sha-{digest[:10]}"
        s3_key = self._build_s3_key(request, digest)
        s3_uri = f"s3://{_BUCKET}/{s3_key}"

        # Step 1: upload to S3 (idempotent)
        if not self._object_exists(s3_key):
            self._put_s3_object(
                request, s3_key, extra_meta={self._META_VERSION: version}
            )
        else:
            _LOGGER.info("Object already exists in S3; skipping upload.")

        # Step 2: write manifest row
        manifest_id = self._put_manifest(request, version, s3_uri, digest)

        # Step 3: emit event
        self._emit_event(request, version, s3_uri, manifest_id)

        result = LevelUploadResult(
            tenant_id=request.tenant_id,
            level_name=request.level_name,
            version=version,
            s3_uri=s3_uri,
            manifest_id=manifest_id,
        )
        _LOGGER.info("Level upload complete | %s", result)
        return result

    # --------------------------------------------------------------------- #
    # Internals
    # --------------------------------------------------------------------- #

    @staticmethod
    def _hash_file(path: pathlib.Path, block_size: int = 1 << 20) -> str:
        """
        Generate a *blake2b* checksum. Faster than sha256 for large blobs.
        """
        hasher = blake2b(digest_size=32)
        with path.open("rb") as fp:
            while chunk := fp.read(block_size):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        _LOGGER.debug("Calculated hash: %s | path=%s", digest, path)
        return digest

    @staticmethod
    def _build_s3_key(request: LevelUploadRequest, digest: str) -> str:
        safe_name = (
            request.level_name.lower()
            .replace(" ", "-")
            .replace("/", "_")
            .replace("\\", "_")
        )
        return f"{request.tenant_id}/levels/{safe_name}/{digest}.lqlevel"

    # ---------------------------- S3 Helpers ---------------------------- #

    def _object_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=_BUCKET, Key=key)
            return True
        except self._s3.exceptions.NoSuchKey:  # type: ignore[attr-defined]
            return False
        except ClientError as exc:  # pragma: no cover
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise ExternalServiceError(
                f"Failed to check S3 object existence: {exc}"
            ) from exc

    def _put_s3_object(
        self,
        request: LevelUploadRequest,
        key: str,
        extra_meta: Optional[Dict[str, str]] = None,
    ) -> None:
        metadata = {
            **(extra_meta or {}),
            self._META_TENANT: request.tenant_id,
            self._META_AUTHOR: request.author_id,
        }
        with request.package_path.open("rb") as data:
            self._retry(
                lambda: self._s3.put_object(
                    Bucket=_BUCKET,
                    Key=key,
                    Body=data,
                    Metadata=metadata,
                    ContentType="application/x-ledgerquest-level",
                    ServerSideEncryption="AES256",
                ),
                on_exc=(ClientError, EndpointConnectionError),
                why="s3.put_object",
            )
        _LOGGER.info("Uploaded level package to %s", f"s3://{_BUCKET}/{key}")

    # ------------------------- DynamoDB Helpers ------------------------- #

    def _put_manifest(
        self,
        request: LevelUploadRequest,
        version: str,
        s3_uri: str,
        digest: str,
    ) -> str:
        """
        Create a conditional manifest row so we never clobber an existing
        version for the tenant+level pair.
        """
        pk = f"{request.tenant_id}#{request.level_name}"
        sk = version
        manifest_id = str(uuid.uuid4())
        item = {
            "pk": pk,
            "sk": sk,
            "manifest_id": manifest_id,
            "s3_uri": s3_uri,
            "content_hash": digest,
            "author_id": request.author_id,
            "created_at": int(time.time()),
        }

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
            _LOGGER.info("Wrote manifest row | pk=%s sk=%s", pk, sk)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Version already exists—safe to continue; we return the id from the existing record
                _LOGGER.warning("Manifest already exists for %s@%s", pk, sk)
                resp = self._table.get_item(Key={"pk": pk, "sk": sk})
                manifest_id = resp["Item"]["manifest_id"]
            else:  # pragma: no cover
                raise ExternalServiceError(f"DynamoDB failure: {exc}") from exc
        return manifest_id

    # --------------------------- EventBridge ---------------------------- #

    def _emit_event(
        self,
        request: LevelUploadRequest,
        version: str,
        s3_uri: str,
        manifest_id: str,
    ) -> None:
        entry: PutEventsRequestEntryTypeDef = {
            "Source": "ledgerquest.level-uploader",
            "DetailType": "level.uploaded",
            "EventBusName": _EVENT_BUS_NAME,
            "Time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Detail": json.dumps(
                {
                    "tenant_id": request.tenant_id,
                    "level_name": request.level_name,
                    "version": version,
                    "s3_uri": s3_uri,
                    "manifest_id": manifest_id,
                    "author_id": request.author_id,
                }
            ),
        }
        resp = self._events.put_events(Entries=[entry])
        if resp.get("FailedEntryCount", 0) > 0:  # pragma: no cover
            raise ExternalServiceError(
                f"Failed to put EventBridge event: {resp.get('Entries')}"
            )
        _LOGGER.info(
            "Emitted EventBridge event | id=%s",
            resp["Entries"][0].get("EventId", "unknown"),
        )

    # --------------------------------------------------------------------- #
    # Generic utilities
    # --------------------------------------------------------------------- #

    @staticmethod
    def _retry(
        func,
        *,
        on_exc: tuple[type[Exception], ...],
        why: str,
        attempts: int = 3,
        backoff: float = 0.2,
    ):
        """
        Lightweight retry with jitter. Raises `ExternalServiceError` after
        exhausting attempts.
        """
        for i in range(1, attempts + 1):
            try:
                return func()
            except on_exc as exc:  # type: ignore[misc]
                if i == attempts:
                    _LOGGER.error("%s failed after %s attempts", why, attempts)
                    raise ExternalServiceError(f"{why} ultimately failed: {exc}") from exc
                sleep_for = backoff * (2 ** (i - 1))
                _LOGGER.warning(
                    "%s failed (attempt %s/%s); retrying in %.2fs: %s",
                    why,
                    i,
                    attempts,
                    sleep_for,
                    exc,
                )
                time.sleep(sleep_for)
```
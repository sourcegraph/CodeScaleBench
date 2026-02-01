```python
"""
ledgerquest.services.asset_management
=====================================

Server-side asset management utilities for LedgerQuest Engine.

This module provides a thin façade around AWS S3 and DynamoDB for storing and
retrieving game assets (textures, audio, scene-graphs, scripts, etc.).  It hides
low-level boto3 interactions behind a concise, domain-driven API while still
surfacing enough controls for power-users (multi-part uploads, versioning,
tenant-aware queries).

Because LedgerQuest runs in a fully serverless environment, *all* functions are
stateless.  Long-lived data (metadata manifests & binary payloads) is therefore
persisted in DynamoDB and S3 respectively.

Typical usage
-------------
>>> from ledgerquest.services.asset_management import AssetManager
>>> mgr = AssetManager()
>>> asset_id, version = mgr.register_asset(
...     file_bytes=b' ... ',
...     name='orc_texture',
...     asset_type='texture',
...     tenant_id='tenant-123',
...     tags={'resolution': '1024x1024'}
... )
>>> url = mgr.get_presigned_url(asset_id, version)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

__all__ = [
    "AssetManager",
    "AssetError",
    "AssetNotFoundError",
    "AssetValidationError",
    "AssetStorageError",
    "AssetAccessError",
    "AssetMetadata",
]

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
_LOGGER = logging.getLogger("ledgerquest.asset_management")
_LOGGER.setLevel(os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO"))


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class AssetError(RuntimeError):
    """Base-class for all asset related errors."""


class AssetNotFoundError(AssetError):
    """Raised when an asset or a specific version is not found."""


class AssetValidationError(AssetError):
    """Raised when an asset fails schema or business validation."""


class AssetStorageError(AssetError):
    """Raised when we fail to persist or retrieve an asset from S3 / Dynamo."""


class AssetAccessError(AssetError):
    """Raised when a caller tries to access an asset outside of its tenant."""


# --------------------------------------------------------------------------- #
# Data models                                                                 #
# --------------------------------------------------------------------------- #
class AssetMetadata(TypedDict, total=False):
    """TypedDict representing how we store metadata in DynamoDB."""

    # Primary keys
    asset_id: str  # uuid
    version: int

    # Business fields
    name: str
    tenant_id: str
    asset_type: str
    s3_key: str
    checksum: str
    size_bytes: int
    created_at: str  # ISO 8601 UTC
    updated_at: str
    tags: Dict[str, str]


# --------------------------------------------------------------------------- #
# Helper utilities                                                            #
# --------------------------------------------------------------------------- #
def _utc_now() -> str:
    """Return an ISO-8601 timestamp in UTC with millisecond precision."""
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat(timespec="milliseconds")


def _sha256(data: bytes) -> str:
    """Compute SHA-256 checksum for *data* and return the hex digest."""
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _require(condition: bool, exc: type[AssetError], msg: str, *fmt: Any) -> None:
    """Utility that raises *exc* if *condition* is False."""
    if not condition:
        raise exc(msg.format(*fmt))


# --------------------------------------------------------------------------- #
# Asset Manager                                                               #
# --------------------------------------------------------------------------- #
class AssetManager:
    """
    Facade for S3 + DynamoDB backed asset storage.

    Parameters
    ----------
    s3_bucket:
        Name of the bucket that stores the binary payloads.  If *None*, the
        value is read from the `LEDGERQUEST_ASSET_BUCKET` environment variable.
    ddb_table:
        Name of the table that stores asset manifests.  If *None*, the value is
        read from the `LEDGERQUEST_ASSET_TABLE` environment variable.
    boto3_session:
        Optional *boto3.session.Session* instance.  If omitted, the default
        session is used (which in Lambda means role-based credentials).
    url_expiry_seconds:
        Number of seconds a presigned URL remains valid.
    """

    DEFAULT_URL_EXPIRY: int = 60 * 15  # 15 minutes

    def __init__(
        self,
        s3_bucket: Optional[str] = None,
        ddb_table: Optional[str] = None,
        boto3_session: Optional[boto3.session.Session] = None,
        url_expiry_seconds: int = DEFAULT_URL_EXPIRY,
    ) -> None:
        self._session = boto3_session or boto3.session.Session()
        self._s3: BaseClient = self._session.client("s3")
        self._ddb: BaseClient = self._session.client("dynamodb")

        self._bucket: str = s3_bucket or os.getenv("LEDGERQUEST_ASSET_BUCKET")
        self._table: str = ddb_table or os.getenv("LEDGERQUEST_ASSET_TABLE")
        self._url_expiry = url_expiry_seconds

        _require(self._bucket, AssetValidationError, "S3 bucket not configured.")
        _require(self._table, AssetValidationError, "DynamoDB table not configured.")

        _LOGGER.debug(
            "AssetManager initialised (bucket=%s table=%s expiry=%s)",
            self._bucket,
            self._table,
            self._url_expiry,
        )

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def register_asset(
        self,
        *,
        file_bytes: bytes,
        name: str,
        asset_type: str,
        tenant_id: str,
        tags: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, int]:
        """
        Upload *file_bytes* and persist metadata.

        Returns
        -------
        Tuple[str, int]
            (asset_id, version)
        """
        _require(file_bytes, AssetValidationError, "file_bytes cannot be empty.")
        _require(name, AssetValidationError, "name cannot be empty.")
        _require(asset_type, AssetValidationError, "asset_type cannot be empty.")
        _require(tenant_id, AssetValidationError, "tenant_id cannot be empty.")

        asset_id = str(uuid.uuid4())
        version = 1
        checksum = _sha256(file_bytes)
        size_bytes = len(file_bytes)
        s3_key = f"{tenant_id}/{asset_id}/v{version}/{name}"

        _LOGGER.debug(
            "Registering asset %s (v%s) for tenant %s -> s3://%s/%s",
            asset_id,
            version,
            tenant_id,
            self._bucket,
            s3_key,
        )

        # Upload to S3 (use a single PUT; larger files should call .upload_large_asset)
        self._put_object_to_s3(s3_key, file_bytes)

        # Persist manifest to DynamoDB
        now = _utc_now()
        metadata: AssetMetadata = {
            "asset_id": asset_id,
            "version": version,
            "name": name,
            "tenant_id": tenant_id,
            "asset_type": asset_type,
            "s3_key": s3_key,
            "checksum": checksum,
            "size_bytes": size_bytes,
            "created_at": now,
            "updated_at": now,
            "tags": tags or {},
        }
        self._put_metadata(metadata)
        _LOGGER.info(
            "Asset %s (v%s) registered. Size=%d Checksum=%s",
            asset_id,
            version,
            size_bytes,
            checksum,
        )
        return asset_id, version

    def upload_large_asset(
        self,
        *,
        file_path: str,
        name: str,
        asset_type: str,
        tenant_id: str,
        tags: Optional[Dict[str, str]] = None,
        chunk_size_mb: int = 8,
    ) -> Tuple[str, int]:
        """
        High-level wrapper for multipart upload of very large files without
        loading them fully into memory.
        """
        _require(os.path.isfile(file_path), AssetValidationError, "File not found: {}", file_path)

        asset_id = str(uuid.uuid4())
        version = 1
        s3_key = f"{tenant_id}/{asset_id}/v{version}/{name}"

        _LOGGER.debug("Multipart upload %s -> s3://%s/%s", file_path, self._bucket, s3_key)
        upload_id = None
        part_etags: List[Dict[str, Any]] = []
        try:
            # 1️⃣ Initiate
            resp = self._s3.create_multipart_upload(Bucket=self._bucket, Key=s3_key)
            upload_id = resp["UploadId"]

            # 2️⃣ Upload each part
            part_number = 1
            chunk_size = chunk_size_mb * 1024 * 1024
            sha256_full = hashlib.sha256()

            with open(file_path, "rb") as fh:
                while True:
                    data = fh.read(chunk_size)
                    if not data:
                        break
                    sha256_full.update(data)
                    part_resp = self._s3.upload_part(
                        Bucket=self._bucket,
                        Key=s3_key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=data,
                    )
                    part_etags.append({"PartNumber": part_number, "ETag": part_resp["ETag"]})
                    _LOGGER.debug(
                        "Uploaded part #%s for %s (etag=%s)", part_number, asset_id, part_resp["ETag"]
                    )
                    part_number += 1

            # 3️⃣ Complete
            self._s3.complete_multipart_upload(
                Bucket=self._bucket,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": part_etags},
            )
            checksum = sha256_full.hexdigest()
            size_bytes = os.path.getsize(file_path)
            now = _utc_now()
            metadata: AssetMetadata = {
                "asset_id": asset_id,
                "version": version,
                "name": name,
                "tenant_id": tenant_id,
                "asset_type": asset_type,
                "s3_key": s3_key,
                "checksum": checksum,
                "size_bytes": size_bytes,
                "created_at": now,
                "updated_at": now,
                "tags": tags or {},
            }
            self._put_metadata(metadata)
            _LOGGER.info(
                "Large asset %s (v%s) registered. Size=%d Checksum=%s",
                asset_id,
                version,
                size_bytes,
                checksum,
            )
            return asset_id, version
        except Exception as exc:  # noqa: BLE001
            # If any step fails, abort the multipart upload to avoid orphaned parts.
            if upload_id:
                self._s3.abort_multipart_upload(
                    Bucket=self._bucket, Key=s3_key, UploadId=upload_id
                )
            raise AssetStorageError(f"Multipart upload failed: {exc}") from exc

    def list_assets(
        self,
        *,
        tenant_id: str,
        asset_type: Optional[str] = None,
        limit: int = 100,
        exclusive_start_key: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[AssetMetadata], Optional[Dict[str, Any]]]:
        """
        List assets belonging to *tenant_id* (optionally filtered by *asset_type*).

        Returns
        -------
        Tuple[List[AssetMetadata], Optional[dict]]
            List of metadata items and `LastEvaluatedKey` for pagination.
        """
        _require(tenant_id, AssetValidationError, "tenant_id is required.")
        _require(limit > 0, AssetValidationError, "limit must be positive.")

        key_cond_expr = "tenant_id = :tid"
        expr_attr_vals: Dict[str, Any] = {":tid": {"S": tenant_id}}
        if asset_type:
            key_cond_expr += " AND asset_type = :typ"
            expr_attr_vals[":typ"] = {"S": asset_type}

        params = {
            "TableName": self._table,
            "IndexName": "tenant_index",  # GSI with partition key on tenant_id
            "KeyConditionExpression": key_cond_expr,
            "ExpressionAttributeValues": expr_attr_vals,
            "Limit": limit,
        }
        if exclusive_start_key:
            params["ExclusiveStartKey"] = exclusive_start_key

        try:
            resp = self._ddb.query(**params)  # type: ignore[arg-type]
            items = [self._unmarshal_item(it) for it in resp.get("Items", [])]
            lek = resp.get("LastEvaluatedKey")
            return items, lek
        except ClientError as exc:
            raise AssetStorageError(f"DynamoDB query failed: {exc}") from exc

    def get_metadata(self, asset_id: str, version: Optional[int] = None) -> AssetMetadata:
        """Return metadata for *asset_id*.  If *version* is *None*, the latest."""
        _require(asset_id, AssetValidationError, "asset_id is required.")
        try:
            if version is None:
                # Query for maximum version
                resp = self._ddb.query(
                    TableName=self._table,
                    KeyConditionExpression="asset_id = :aid",
                    ExpressionAttributeValues={":aid": {"S": asset_id}},
                    ScanIndexForward=False,  # descending
                    Limit=1,
                )
                items = resp.get("Items")
                if not items:
                    raise AssetNotFoundError(f"Asset {asset_id} not found.")
                return self._unmarshal_item(items[0])
            # GetItem for specific PK+SK
            pk = {"S": asset_id}
            sk = {"N": str(version)}
            resp = self._ddb.get_item(TableName=self._table, Key={"asset_id": pk, "version": sk})
            item = resp.get("Item")
            if not item:
                raise AssetNotFoundError(f"Asset {asset_id} v{version} not found.")
            return self._unmarshal_item(item)
        except ClientError as exc:
            raise AssetStorageError(f"DynamoDB get_item/query failed: {exc}") from exc

    def get_presigned_url(
        self, asset_id: str, version: Optional[int] = None, *, verify_tenant: Optional[str] = None
    ) -> str:
        """
        Return a presigned URL for downloading the asset binary.

        If *verify_tenant* is given, ensure the asset belongs to the tenant.
        """
        meta = self.get_metadata(asset_id, version)
        if verify_tenant and meta["tenant_id"] != verify_tenant:
            raise AssetAccessError("Tenant mismatch for asset request.")
        return self._presigned_get(meta["s3_key"])

    def update_asset(
        self,
        *,
        asset_id: str,
        file_bytes: bytes,
        user_id: str,
        message: str = "",
    ) -> int:
        """
        Create a new version of *asset_id* with *file_bytes*.

        Returns
        -------
        int
            The new version number.
        """
        meta = self.get_metadata(asset_id)  # latest version
        tenant_id = meta["tenant_id"]
        name = meta["name"]

        new_version = meta["version"] + 1
        s3_key = f"{tenant_id}/{asset_id}/v{new_version}/{name}"
        checksum = _sha256(file_bytes)
        size_bytes = len(file_bytes)

        self._put_object_to_s3(s3_key, file_bytes)

        metadata: AssetMetadata = {
            **meta,
            "version": new_version,
            "s3_key": s3_key,
            "checksum": checksum,
            "size_bytes": size_bytes,
            "updated_at": _utc_now(),
        }
        # Remove keys with potential old leftover.
        metadata.pop("created_at", None)

        self._put_metadata(metadata)
        _LOGGER.info("Asset %s updated to version %s by %s", asset_id, new_version, user_id)
        return new_version

    def delete_asset(self, asset_id: str, *, version: Optional[int] = None) -> None:
        """
        Delete *asset_id* (or a single version).  For compliance, the metadata is
        **soft-deleted** (marked as deleted) but the binary is physically removed
        from S3 to save space.
        """
        meta = self.get_metadata(asset_id, version)
        # Delete from S3
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=meta["s3_key"])
        except ClientError as exc:
            raise AssetStorageError(f"S3 delete failed: {exc}") from exc

        # Flag metadata as deleted
        try:
            self._ddb.update_item(
                TableName=self._table,
                Key={"asset_id": {"S": meta["asset_id"]}, "version": {"N": str(meta["version"])}},
                UpdateExpression="SET #d = :true, updated_at=:t",
                ExpressionAttributeNames={"#d": "deleted"},
                ExpressionAttributeValues={
                    ":true": {"BOOL": True},
                    ":t": {"S": _utc_now()},
                },
            )
            _LOGGER.warning(
                "Asset %s v%s marked deleted (binary removed from bucket).",
                asset_id,
                meta["version"],
            )
        except ClientError as exc:
            raise AssetStorageError(f"DynamoDB update failed: {exc}") from exc

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #
    def _put_object_to_s3(self, key: str, data: bytes) -> None:
        """Upload *data* to S3 with server-side encryption enabled."""
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ServerSideEncryption="AES256",
                ContentMD5=hashlib.md5(data).digest().hex(),  # noqa: S324
            )
        except ClientError as exc:
            raise AssetStorageError(f"S3 put_object failed: {exc}") from exc

    @_require  # type: ignore[misc]
    def _put_metadata(self, metadata: AssetMetadata) -> None:  # noqa: D401
        """Persist *metadata* to DynamoDB."""
        try:
            self._ddb.put_item(TableName=self._table, Item=self._marshal_item(metadata))
        except ClientError as exc:
            raise AssetStorageError(f"DynamoDB put_item failed: {exc}") from exc

    @lru_cache(maxsize=1024)
    def _presigned_get(self, key: str) -> str:  # noqa: D401
        """Return a cached presigned GET URL for *key*."""
        try:
            url = self._s3.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._url_expiry,
            )
            _LOGGER.debug("Generated presigned URL for %s", key)
            return url
        except ClientError as exc:
            raise AssetStorageError(f"Presign failed: {exc}") from exc

    # --------------------------------------------------------------------- #
    # (De)serialisation helpers                                             #
    # --------------------------------------------------------------------- #
    @staticmethod
    def _marshal_item(item: AssetMetadata) -> Dict[str, Dict[str, Any]]:
        """
        Convert a *TypedDict* into DynamoDB's AttributeValue shape.  This is
        intentionally limited to the fields we use (str, int, bool, dict).
        """
        def wrap(val: Any) -> Dict[str, Any]:
            if isinstance(val, str):
                return {"S": val}
            if isinstance(val, int):
                return {"N": str(val)}
            if isinstance(val, bool):
                return {"BOOL": val}
            if isinstance(val, dict):
                return {"M": {k: wrap(v) for k, v in val.items()}}
            raise AssetValidationError(f"Unsupported type for DynamoDB marshal: {type(val)}")

        return {k: wrap(v) for k, v in item.items()}

    @staticmethod
    def _unmarshal_item(
        wire: Dict[str, Dict[str, Any]],
    ) -> AssetMetadata:  # type: ignore[type-arg]
        """Convert DynamoDB wire format into a plain dict."""
        def unwrap(attr: Dict[str, Any]) -> Any:
            if "S" in attr:
                return attr["S"]
            if "N" in attr:
                # JSON numeric fields may be ints or floats; we only expect ints.
                return int(attr["N"])
            if "BOOL" in attr:
                return attr["BOOL"]
            if "M" in attr:
                return {k: unwrap(v) for k, v in attr["M"].items()}
            raise AssetValidationError(f"Unsupported DynamoDB type: {list(attr)}")

        return {k: unwrap(v) for k, v in wire.items()}  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Module initialisation convenience                                           #
# --------------------------------------------------------------------------- #
# Provide a default, lazily-instantiated singleton for quick scripts.
_default_manager: Optional[AssetManager] = None


def default_manager() -> AssetManager:
    """Return a module-level singleton configured via environment variables."""
    global _default_manager  # noqa: PLW0603
    if _default_manager is None:
        _default_manager = AssetManager()
    return _default_manager
```
```python
"""
LedgerQuest Engine – Resource Manager
-------------------------------------

This module provides facilities for fetching and caching binary game assets
(models, textures, scripts, scenario JSON, etc.) that are stored in Amazon S3.
The implementation is optimised for the execution environment of AWS Lambda
where a warm execution context may re-use the `/tmp` filesystem between
invocations.

Key Features
============

• Multi-tenant path isolation (each tenant gets its own directory tree)
• File-level LRU eviction to keep cache size below a configurable limit
• Thread-safe, re-entrant design for concurrent access within the same process
• Pluggable synchronous and asynchronous download back-ends
• Simple metrics emitted through the standard logging facility
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError

# --------------------------------------------------------------------------- #
# Logging configuration                                                       #
# --------------------------------------------------------------------------- #

_LOGGER = logging.getLogger("ledgerquest.engine.core.resource_manager")
if not _LOGGER.handlers:
    # Lambda defaults have no handler; add one if running locally / tests.
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s %(name)s - %(message)s")
    )
    _LOGGER.addHandler(handler)

_LOGGER.setLevel(os.getenv("LEDGERQUEST_LOG_LEVEL", "INFO").upper())

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class ResourceManagerError(Exception):
    """Base class for all resource-manager related errors."""


class AssetNotFoundError(ResourceManagerError):
    """Raised when an asset cannot be located in S3."""


class CacheFullError(ResourceManagerError):
    """Raised when the cache cannot free enough space for a new asset."""


# --------------------------------------------------------------------------- #
# Resource Manager                                                            #
# --------------------------------------------------------------------------- #


class ResourceManager:
    """
    Manages downloading and caching of tenant-specific game assets.

    Parameters
    ----------
    s3_bucket:
        Name of the S3 bucket where assets are stored.
    cache_dir:
        Root directory for local on-disk cache. Defaults to /tmp/ledgerquest_cache.
    cache_limit_mb:
        Soft upper bound (in megabytes) for the cache size.
    s3_client:
        Optional boto3 S3 client. One is created automatically if omitted.
    """

    _METADATA_FILE = "cache_meta.json"
    _LOCK = threading.RLock()  # intra-process safety (Lambda is single process)

    def __init__(
        self,
        s3_bucket: str,
        cache_dir: Optional[Path | str] = None,
        cache_limit_mb: int = 512,
        s3_client: Optional[boto3.client] = None,
    ) -> None:
        self.s3_bucket = s3_bucket
        self.cache_dir = Path(cache_dir or "/tmp/ledgerquest_cache").expanduser()
        self.cache_limit_bytes = cache_limit_mb * 1024 * 1024
        self.s3 = s3_client or boto3.client("s3", config=boto3.session.Config())
        self._cache_meta: Dict[str, Dict[str, float]] = {}  # {filepath: {"ts": ..., "size": ...}}

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_metadata()

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #

    def get_asset_path(
        self,
        asset_key: str,
        *,
        tenant_id: str = "default",
        version: str = "latest",
        force_refresh: bool = False,
    ) -> Path:
        """
        Ensure that the requested asset is available locally and return the path.

        This call is synchronous; use `get_asset_path_async` for async workflows.
        """
        path = self._asset_local_path(asset_key, tenant_id, version)

        with self._LOCK:
            if force_refresh and path.exists():
                _LOGGER.debug("Force refresh of asset: %s", path)
                self._remove_file(path)

            if path.exists():
                self._touch(path)
                _LOGGER.debug("Cache hit for asset: %s", path)
                return path

            self._evict_if_needed()

        # Download outside the lock to avoid long hold times
        _LOGGER.info("Cache miss, downloading asset %s/%s", tenant_id, asset_key)
        try:
            self._download_asset(asset_key, tenant_id, version, path)
        except (ClientError, BotoCoreError) as exc:
            raise AssetNotFoundError(f"Failed to download {asset_key}: {exc}") from exc

        with self._LOCK:
            self._track_file(path)
            self._save_metadata()

        return path

    async def get_asset_path_async(
        self,
        asset_key: str,
        *,
        tenant_id: str = "default",
        version: str = "latest",
        force_refresh: bool = False,
    ) -> Path:
        """
        Asynchronous counterpart to `get_asset_path`.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.get_asset_path,
            asset_key,
            tenant_id,
            version,
            force_refresh,
        )

    def preload_assets(
        self,
        assets: List[str],
        *,
        tenant_id: str = "default",
        version: str = "latest",
    ) -> None:
        """
        Warm the cache for a list of assets. Missing assets are downloaded in parallel.
        """
        _LOGGER.info(
            "Preloading %d asset(s) for tenant '%s'", len(assets), tenant_id
        )
        to_download: List[str] = []
        for asset_key in assets:
            if not self._asset_local_path(asset_key, tenant_id, version).exists():
                to_download.append(asset_key)

        # Use threads to parallelise blocking I/O
        threads: List[threading.Thread] = []
        for key in to_download:
            t = threading.Thread(
                target=self.get_asset_path,
                args=(key,),
                kwargs=dict(tenant_id=tenant_id, version=version),
                daemon=True,
            )
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    def _asset_local_path(self, asset_key: str, tenant_id: str, version: str) -> Path:
        safe_tenant = _sanitise_for_fs(tenant_id)
        safe_key = _sanitise_for_fs(asset_key)
        safe_version = _sanitise_for_fs(version)

        return (
            self.cache_dir
            / safe_tenant
            / safe_key
            / safe_version
            / Path(asset_key).name  # keep original filename
        )

    def _download_asset(
        self,
        asset_key: str,
        tenant_id: str,
        version: str,
        dest: Path,
    ) -> None:
        # Build S3 object key: <tenant>/assets/<key>/<version>
        s3_object_key = f"{tenant_id}/assets/{asset_key}/{version}"

        tmp_path = dest.with_suffix(".part")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)

        _LOGGER.debug(
            "Downloading s3://%s/%s to %s", self.s3_bucket, s3_object_key, tmp_path
        )

        try:
            self.s3.download_file(self.s3_bucket, s3_object_key, str(tmp_path))
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                raise AssetNotFoundError(f"Asset not found: {s3_object_key}") from exc
            raise

        tmp_path.rename(dest)
        _LOGGER.info("Downloaded asset %s (%d bytes)", dest, dest.stat().st_size)

    # ---------------- Cache bookkeeping ----------------------------------- #

    def _evict_if_needed(self) -> None:
        """Evict least recently used files until cache fits."""
        current_size = self._cache_size_bytes()
        if current_size < self.cache_limit_bytes:
            return

        _LOGGER.warning(
            "Cache size (%dMB) exceeds limit (%dMB). Evicting...",
            current_size // (1024 * 1024),
            self.cache_limit_bytes // (1024 * 1024),
        )

        # Sort by last accessed time ascending (oldest first)
        entries = sorted(
            self._cache_meta.items(),
            key=lambda item: item[1]["ts"],  # type: ignore[index]
        )

        for file_path, meta in entries:
            if current_size <= self.cache_limit_bytes:
                break
            self._remove_file(Path(file_path))
            current_size -= meta["size"]

        if current_size > self.cache_limit_bytes:
            raise CacheFullError("Unable to free sufficient cache space")

    def _cache_size_bytes(self) -> int:
        return int(
            sum(meta["size"] for meta in self._cache_meta.values())
        )

    def _load_metadata(self) -> None:
        meta_file = self.cache_dir / self._METADATA_FILE
        if not meta_file.exists():
            return
        try:
            with meta_file.open("r", encoding="utf-8") as f:
                self._cache_meta = json.load(f)
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("Failed to load cache metadata: %s", exc)
            self._cache_meta = {}

    def _save_metadata(self) -> None:
        meta_file = self.cache_dir / self._METADATA_FILE
        try:
            with meta_file.open("w", encoding="utf-8") as f:
                json.dump(self._cache_meta, f)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("Could not persist cache metadata: %s", exc)

    def _track_file(self, path: Path) -> None:
        meta = {"ts": time.time(), "size": path.stat().st_size}
        self._cache_meta[str(path)] = meta

    def _touch(self, path: Path) -> None:
        if str(path) in self._cache_meta:
            self._cache_meta[str(path)]["ts"] = time.time()

    def _remove_file(self, path: Path) -> None:
        try:
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            self._cache_meta.pop(str(path), None)
            _LOGGER.debug("Evicted %s (%d bytes)", path, size)
        except FileNotFoundError:
            pass

    # --------------------------------------------------------------------- #
    # Magic methods                                                         #
    # --------------------------------------------------------------------- #

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"{self.__class__.__name__}(bucket={self.s3_bucket!r}, "
            f"cache={str(self.cache_dir)!r}, "
            f"limit={self.cache_limit_bytes // (1024 * 1024)}MB)"
        )


# --------------------------------------------------------------------------- #
# Utility functions                                                           #
# --------------------------------------------------------------------------- #


def _sanitise_for_fs(value: str) -> str:
    """
    Replace any non-alphanumeric character so that paths stay portable,
    while still retaining enough uniqueness via SHA1 hashing.
    """
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)
    if safe != value:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        safe = f"{safe}_{digest}"
    return safe
```
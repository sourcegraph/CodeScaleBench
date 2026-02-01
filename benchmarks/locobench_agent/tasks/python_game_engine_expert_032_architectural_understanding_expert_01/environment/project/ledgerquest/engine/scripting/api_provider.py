```python
"""
ledgerquest.engine.scripting.api_provider
========================================

A dynamic, cache-aware loader for tenant/game specific Python scripts.

This module is the heart of LedgerQuest’s serverless scripting system; it is
responsible for

1. Fetching tenant/game scoped script artefacts from an object store (e.g. S3)
2. Verifying artefact integrity using a HMAC signature
3. Dynamically importing the module in an isolated namespace
4. Caching loaded APIs for warm-start performance
5. Providing a safe invocation surface that only exposes functions a script
   explicitly registered through the `register_api()` convention.

Scripts are expected to expose a top-level function called *register_api* that
returns a mapping of api_name -> callables. Example:

    def _secret_internal_impl():
        ...

    def public_business_rule(event, context):
        ...

    def register_api():
        return {"business_rule": public_business_rule}

Anything not returned by *register_api* will not be callable by game logic,
avoiding accidental exposure of helper functions or sensitive globals.

The provider is entirely stateless outside of an in-memory LRU/TTL cache, making
it perfectly suited to be executed inside ephemeral Lambda workers.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import tempfile
import textwrap
import types
from dataclasses import dataclass
from hashlib import sha256
from hmac import digest as hmac_digest
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, MutableMapping, Optional

try:
    # cachetools is a lightweight, pure-python dependency
    from cachetools import TTLCache
except ModuleNotFoundError as exc:
    raise RuntimeError(
        "cachetools package must be present. "
        "Add `cachetools>=4.0` to your requirements."
    ) from exc

try:
    import boto3  # Optional; fallback to local FS when not present.
except ModuleNotFoundError:
    boto3 = None  # type: ignore

__all__ = [
    "ScriptAPIProvider",
    "ScriptDescriptor",
    "ScriptLoadError",
    "ScriptIntegrityError",
    "UnauthorizedFunctionError",
]

_log = logging.getLogger(__name__)
DEFAULT_CACHE_TTL_SECONDS = 300  # Five minutes – balances cold-start vs. drift
DEFAULT_CACHE_MAX_SIZE = 128
API_REGISTRATION_FN = "register_api"
SCRIPT_HMAC_ENV = "LEDGERQUEST_SCRIPT_HMAC_SECRET"


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class ScriptLoadError(RuntimeError):
    """Raised when a script file cannot be fetched or imported."""


class ScriptIntegrityError(RuntimeError):
    """Raised when the downloaded script fails HMAC or checksum verification."""


class UnauthorizedFunctionError(RuntimeError):
    """Raised when invoking a function that is not part of the script's API."""


# --------------------------------------------------------------------------- #
# Data classes                                                                #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ScriptDescriptor:
    """Uniquely identifies a tenant/game scoped script bundle."""

    tenant_id: str
    game_id: str
    script_name: str
    version: str = "latest"

    @property
    def s3_key(self) -> str:
        """
        Convert the descriptor into a deterministic S3 object key.
        Customize as required for your storage layout.
        """
        return (
            f"scripts/{self.tenant_id}/{self.game_id}/"
            f"{self.script_name}@{self.version}.py"
        )

    @property
    def cache_key(self) -> str:
        """A stable identifier for in-process caching."""
        return f"{self.tenant_id}:{self.game_id}:{self.script_name}:{self.version}"


# --------------------------------------------------------------------------- #
# Provider                                                                    #
# --------------------------------------------------------------------------- #
class ScriptAPIProvider:
    """
    Loads, verifies, caches, and exposes the public API of a tenant/game script.

    The provider is intentionally *not* a Singleton. Instead, each Lambda
    execution environment gets its own provider instance (usually created at
    module import time in the handler) which contains a process-global cache.
    """

    # Class-level cache so multiple provider instances in the same process share.
    _cache: TTLCache[str, Mapping[str, Callable]] = TTLCache(
        maxsize=DEFAULT_CACHE_MAX_SIZE, ttl=DEFAULT_CACHE_TTL_SECONDS
    )

    def __init__(
        self,
        bucket: str,
        s3_session: Optional["boto3.session.Session"] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        if cache_ttl != DEFAULT_CACHE_TTL_SECONDS:
            # Allow per-instance TTL overriding
            self._cache = TTLCache(maxsize=DEFAULT_CACHE_MAX_SIZE, ttl=cache_ttl)

        self._bucket = bucket
        self._s3_client = (
            s3_session.client("s3") if s3_session and boto3 else self._lazy_s3_client()
        )

    # ------------------------ Main public interface ------------------------ #
    def get_api(self, desc: ScriptDescriptor) -> Mapping[str, Callable]:
        """
        Return the API mapping of the referenced script.

        Heavy-lifting (download, integrity, import) is performed lazily and only
        when the descriptor is not already cached.
        """
        if desc.cache_key in self._cache:
            _log.debug("Script %s resolved from cache", desc.cache_key)
            return self._cache[desc.cache_key]

        _log.info("Loading tenant script %s …", desc.cache_key)

        # 1. Download artefact
        script_path = self._download_script(desc)

        # 2. Verify integrity
        self._verify_script_integrity(script_path)

        # 3. Import module in isolated namespace
        api_mapping = self._import_and_register_api(script_path, desc)

        # 4. Populate cache
        self._cache[desc.cache_key] = api_mapping

        return api_mapping

    def invoke(
        self,
        desc: ScriptDescriptor,
        func_name: str,
        event: MutableMapping[str, Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        """
        Convenience wrapper around get_api + callable lookup.

        Raises:
            UnauthorizedFunctionError if func_name is not part of the script's
            public registry.
        """
        api = self.get_api(desc)

        if func_name not in api:
            raise UnauthorizedFunctionError(
                f"Function '{func_name}' not exported by script '{desc.script_name}'"
            )

        _log.debug(
            "Invoking %s.%s (tenant=%s, game=%s)",
            desc.script_name,
            func_name,
            desc.tenant_id,
            desc.game_id,
        )
        return api[func_name](event, context or {})

    # ----------------------- Script download helpers ----------------------- #
    def _download_script(self, desc: ScriptDescriptor) -> Path:
        """
        Download the .py artefact to a tempfile and return its path.

        Falls back to loading a local file when running integration tests
        without AWS credentials.
        """
        if not boto3:
            # Local dev / unit tests
            local_fallback = Path(__file__).resolve().parent / "fixtures" / desc.s3_key
            if not local_fallback.exists():
                raise ScriptLoadError(
                    f"Running without boto3 but script {local_fallback} not found."
                )
            return local_fallback

        try:
            with tempfile.NamedTemporaryFile(
                prefix=f"{desc.script_name}_", suffix=".py", delete=False
            ) as tmp:
                _log.debug("Downloading s3://%s/%s -> %s", self._bucket, desc.s3_key, tmp.name)
                self._s3_client.download_fileobj(self._bucket, desc.s3_key, tmp)
                return Path(tmp.name)
        except self._s3_client.exceptions.NoSuchKey as err:
            raise ScriptLoadError(f"Script not found in S3: {desc.s3_key}") from err
        except Exception as exc:  # pragma: no cover
            raise ScriptLoadError("Unhandled error during S3 download") from exc

    # ---------------------- Integrity / security checks -------------------- #
    def _verify_script_integrity(self, path: Path) -> None:
        """
        Validate artefact integrity by comparing the sha256 HMAC signature
        stored alongside the .py file.

        For each `<file>.py` we expect an additional `<file>.py.sha256` in S3.

        During local/unit testing – or when `LEDGERQUEST_SCRIPT_HMAC_SECRET`
        env-var is **not** set – verification is skipped.
        """
        secret = os.getenv(SCRIPT_HMAC_ENV)
        if not secret:
            _log.warning(
                "%s not set – skipping script integrity verification",
                SCRIPT_HMAC_ENV,
            )
            return

        sig_path = Path(f"{path}.sha256")
        if not sig_path.exists():
            raise ScriptIntegrityError(
                f"Signature file missing for script artefact {path}"
            )

        expected_sig = sig_path.read_text().strip()
        with path.open("rb") as fh:
            computed_sig = hmac_digest(secret.encode(), fh.read(), sha256).hex()

        if computed_sig != expected_sig:
            raise ScriptIntegrityError(
                f"HMAC mismatch for {path}. Expected {expected_sig}, got {computed_sig}"
            )

        _log.debug("Script integrity verified for %s", path.name)

    # --------------------------- Dynamic import ---------------------------- #
    def _import_and_register_api(
        self, script_path: Path, desc: ScriptDescriptor
    ) -> Mapping[str, Callable]:
        """
        Import the module in a unique namespace (tenant/game segregated),
        execute its register_api() hook, and freeze the resulting mapping.
        """
        # Build a unique module name to avoid cross-tenant collisions
        module_name = f"lq_script_{sha256(desc.cache_key.encode()).hexdigest()}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ScriptLoadError(f"Could not create import spec for {script_path}")

        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod  # Required for relative imports inside script
        try:
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        except Exception as exc:
            # Ensure faulty module doesn't linger in sys.modules
            sys.modules.pop(module_name, None)
            raise ScriptLoadError(f"Error importing {script_path}") from exc

        if not hasattr(mod, API_REGISTRATION_FN):
            raise ScriptLoadError(
                textwrap.dedent(
                    f"""\
                    Script {script_path.name} does not expose required function
                    '{API_REGISTRATION_FN}()'. Please implement:

                        def {API_REGISTRATION_FN}():
                            return {{"my_func": my_func}}
                    """
                )
            )

        registry = getattr(mod, API_REGISTRATION_FN)()
        if not isinstance(registry, Mapping):
            raise ScriptLoadError(
                f"{API_REGISTRATION_FN}() must return a mapping of name -> callable"
            )

        frozen_registry: Dict[str, Callable] = {}
        for name, fn in registry.items():
            if not callable(fn):
                raise ScriptLoadError(
                    f"Entry '{name}' returned by {API_REGISTRATION_FN}() is not callable"
                )
            frozen_registry[name] = fn

        _log.info(
            "Script %s registered API functions: %s",
            desc.cache_key,
            ", ".join(sorted(frozen_registry)),
        )
        return frozen_registry

    # -------------------------- Utility helpers ---------------------------- #
    @staticmethod
    def _lazy_s3_client():
        """
        Late-binding import of boto3 so that local development without AWS
        credentials does not fail at *import time*.
        """
        if boto3 is None:  # pragma: no cover
            raise RuntimeError(
                "Attempted to create S3 client but boto3 is not installed"
            )
        return boto3.client("s3")
```
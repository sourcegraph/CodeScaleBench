```python
"""
flockdesk.core.services.update_service
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A resilient, event-driven auto-update daemon responsible for keeping every
FlockDesk micro-front-end in lock-step with the latest signed release that is
compatible with the current desktop client version.

The service is designed to run inside its own lightweight asyncio TaskGroup
so that IO-bound operations do not block the UI thread.  All status changes
are propagated through the central EventBus so that other components (tray
icon, notification center, plugin host) can react in real-time.

The implementation purposefully hides download / installation complexity
behind a concise public API:

    >>> from flockdesk.core.services.update_service import UpdateService
    >>> update_service = UpdateService(event_bus, plugin_manager)
    >>> await update_service.start()

"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Type, Union

import httpx
from packaging.version import Version, InvalidVersion

# ---------------------------------------------------------------------------#
# Optional run-time imports. Where the real component exists in production
# they will be resolved, otherwise light-weight stubs are provided so the
# module can still be imported for unit testing.
# ---------------------------------------------------------------------------#
try:  # pragma: no cover – real runtime dependency.
    from flockdesk.core.events import Event, EventBus
except ModuleNotFoundError:  # Fallback when running in isolation.

    class Event:  # type: ignore
        """Generic event placeholder."""

        def __init__(self, topic: str, payload: dict | None = None) -> None:
            self.topic, self.payload = topic, payload or {}

    class EventBus:  # type: ignore
        """Very small local event bus used for tests."""

        def __init__(self) -> None:
            self._subscribers: Dict[str, List] = {}

        def publish(self, event: Event) -> None:
            for cb in self._subscribers.get(event.topic, []):
                cb(event)

        def subscribe(self, topic: str, callback) -> None:
            self._subscribers.setdefault(topic, []).append(callback)


try:
    from flockdesk.core.plugins import PluginManager, PluginInfo
except ModuleNotFoundError:  # pragma: no cover

    @dataclass
    class PluginInfo:  # type: ignore
        """Light-weight stand-in when real plugin manager is absent."""

        name: str
        version: str
        path: Path

    class PluginManager:  # type: ignore
        def get_installed_plugins(self) -> List[PluginInfo]:
            return []


# ---------------------------------------------------------------------------#
# Constants & logger
# ---------------------------------------------------------------------------#

_LOGGER = logging.getLogger(__name__)
_DEFAULT_UPDATE_ENDPOINT = "https://updates.flockdesk.io/v1/manifest.json"
_DOWNLOAD_CHUNK_SIZE = 1 << 15  # 32 KiB


# ---------------------------------------------------------------------------#
# Public data models
# ---------------------------------------------------------------------------#


@dataclass(slots=True)
class UpdateServiceConfig:
    """
    Runtime configuration holder that can be injected from the settings
    subsystem and dynamically re-loaded at runtime.
    """

    endpoint: str = _DEFAULT_UPDATE_ENDPOINT
    check_interval_s: int = 60 * 60 * 3  # 3 hours
    auto_install: bool = True
    download_dir: Path = Path.home() / ".flockdesk" / "downloads"
    verify_ssl: bool = True
    max_parallel_downloads: int = 3
    request_timeout_s: int = 30


@dataclass(slots=True)
class UpdateCandidate:
    """Information about a plugin for which an update is available."""

    name: str
    current_version: Version
    target_version: Version
    download_url: str
    sha256: str  # Hex digest
    signature: str  # Base64 signature over the SHA-256 digest

    @property
    def filename(self) -> str:
        return f"{self.name}-{self.target_version}.zip"


# ---------------------------------------------------------------------------#
# Exceptions
# ---------------------------------------------------------------------------#


class UpdateServiceError(RuntimeError):
    """Base class for all update service errors."""


class ManifestFetchError(UpdateServiceError):
    """Raised when the remote manifest cannot be retrieved."""


class VerificationError(UpdateServiceError):
    """Raised when checksum or signature verification fails."""


class InstallationError(UpdateServiceError):
    """Raised when an update could not be installed successfully."""


# ---------------------------------------------------------------------------#
# Helper functions
# ---------------------------------------------------------------------------#


def _safe_version(v: str) -> Version:
    """Return a parsed PEP 440 version, falling back to zero."""
    try:
        return Version(v)
    except InvalidVersion:
        _LOGGER.warning("Invalid version string %s, defaulting to 0.0.0", v)
        return Version("0.0.0")


def _verify_checksum(file: Path, expected_sha256_hex: str) -> None:
    """Raise VerificationError when the checksum does not match."""
    import hashlib

    sha256 = hashlib.sha256()
    with file.open("rb") as fh:
        for chunk in iter(partial(fh.read, _DOWNLOAD_CHUNK_SIZE), b""):
            sha256.update(chunk)
    digest = sha256.hexdigest()
    if digest.lower() != expected_sha256_hex.lower():
        raise VerificationError(
            f"Checksum mismatch for {file}: expected {expected_sha256_hex}, got {digest}"
        )


def _verify_signature(file: Path, signature_b64: str) -> None:
    """
    Verify the artifact signature.  In production we use Ed25519 and
    ship the public key with the application.  For unit testing this
    function is a no-op so we do not require the cryptography package.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization
        import base64

        public_key_pem = (
            Path(__file__).with_name("update_public_key.pem").read_bytes()
        )
        pubkey = serialization.load_pem_public_key(public_key_pem)
        assert isinstance(pubkey, Ed25519PublicKey)

        with file.open("rb") as fh:
            data = fh.read()

        pubkey.verify(base64.b64decode(signature_b64), data)
    except FileNotFoundError:
        # Public key not available in dev environment.
        _LOGGER.debug("Signature verification skipped – no public key present.")
    except ModuleNotFoundError:
        _LOGGER.debug("cryptography not available – skipping signature check.")
    except Exception as exc:  # pragma: no cover
        raise VerificationError(f"Signature verification failed: {exc}") from exc


# ---------------------------------------------------------------------------#
# Main UpdateService
# ---------------------------------------------------------------------------#


class UpdateService:
    """
    Auto-update daemon entry point.

    Parameters
    ----------
    event_bus:
        The central event bus used for publishing progress / state changes.
    plugin_manager:
        Provides information about currently installed plugins and is
        responsible for hot-reloading of a freshly installed plugin, if
        possible.
    config:
        Configurable runtime knobs loaded from user settings or defaults.
    """

    _task_group: Optional[asyncio.TaskGroup]

    def __init__(
        self,
        event_bus: EventBus,
        plugin_manager: PluginManager,
        config: UpdateServiceConfig | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._plugin_manager = plugin_manager
        self._config = config or UpdateServiceConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._task_group = None
        self._shutdown_event = asyncio.Event()
        self._currently_downloading: Set[str] = set()

    # ---------------------------------------------------------------------#
    # Lifecycle management
    # ---------------------------------------------------------------------#

    async def start(self) -> None:
        if self._task_group:
            return  # Already running.

        _LOGGER.info("Starting UpdateService — endpoint=%s", self._config.endpoint)
        self._client = httpx.AsyncClient(
            timeout=self._config.request_timeout_s, verify=self._config.verify_ssl
        )

        self._task_group = asyncio.TaskGroup()
        await self._task_group.__aenter__()  # type: ignore[attr-defined]
        self._task_group.create_task(self._periodic_check_loop())

    async def stop(self) -> None:
        if not self._task_group:
            return  # Not running.

        _LOGGER.info("Stopping UpdateService…")
        self._shutdown_event.set()
        await self._task_group.__aexit__(None, None, None)  # type: ignore[attr-defined]
        self._task_group = None
        if self._client:
            await self._client.aclose()

    # ---------------------------------------------------------------------#
    # Core workers
    # ---------------------------------------------------------------------#

    async def _periodic_check_loop(self) -> None:
        """
        Long-running coroutine that periodically checks for updates until the
        desktop client shuts down.
        """
        while not self._shutdown_event.is_set():
            try:
                await self._check_for_updates()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unhandled error during update check")
            await asyncio.wait(
                [self._shutdown_event.wait()],
                timeout=self._config.check_interval_s,
            )

    async def _check_for_updates(self) -> None:
        """Fetch the remote manifest and schedule downloads if newer versions exist."""
        manifest = await self._pull_manifest()
        candidates = self._detect_updates(manifest)

        if not candidates:
            _LOGGER.debug("No updates found.")
            return

        _LOGGER.info("Updates available: %s", ", ".join(c.name for c in candidates))
        for candidate in candidates:
            # Notify listeners that an update is available.
            self._event_bus.publish(
                Event(
                    "update.available",
                    {
                        "plugin": candidate.name,
                        "current": str(candidate.current_version),
                        "target": str(candidate.target_version),
                    },
                )
            )

        if self._config.auto_install:
            await self._download_and_install(candidates)

    # ---------------------------------------------------------------------#
    # Manifest handling
    # ---------------------------------------------------------------------#

    async def _pull_manifest(self) -> Dict[str, dict]:
        """
        Pull the JSON manifest from the configured endpoint.

        Returns
        -------
        The JSON body parsed into a dict mapping plugin name to manifest entry.
        """
        if not self._client:
            raise RuntimeError("UpdateService.start() must be called first")

        _LOGGER.debug("Fetching update manifest from %s", self._config.endpoint)
        try:
            resp = await self._client.get(self._config.endpoint)
            resp.raise_for_status()
            manifest = resp.json()
            _LOGGER.debug("Received manifest with %d entries", len(manifest))
            return manifest
        except (httpx.HTTPError, ValueError) as exc:
            raise ManifestFetchError(f"Failed to fetch manifest: {exc}") from exc

    def _detect_updates(self, manifest: Dict[str, dict]) -> List[UpdateCandidate]:
        """
        Compare installed versions with manifest and return a list of updates.
        """
        installed = {
            p.name: p for p in self._plugin_manager.get_installed_plugins()
        }

        candidates: List[UpdateCandidate] = []
        for name, entry in manifest.items():
            if name not in installed:
                _LOGGER.debug("Plugin %s not installed — skipping", name)
                continue

            current_v = _safe_version(installed[name].version)
            target_v = _safe_version(entry["version"])

            if target_v > current_v:
                candidates.append(
                    UpdateCandidate(
                        name=name,
                        current_version=current_v,
                        target_version=target_v,
                        download_url=entry["url"],
                        sha256=entry["sha256"],
                        signature=entry["signature"],
                    )
                )

        return candidates

    # ---------------------------------------------------------------------#
    # Download & installation
    # ---------------------------------------------------------------------#

    async def _download_and_install(self, candidates: List[UpdateCandidate]) -> None:
        """
        Download artifacts in parallel and install them one by one to ensure
        we can revert individual failures without impacting other plugins.
        """
        download_dir = self._config.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)
        sem = asyncio.Semaphore(self._config.max_parallel_downloads)

        async def _worker(candidate: UpdateCandidate) -> Tuple[UpdateCandidate, Path]:
            async with sem:
                return candidate, await self._download(candidate, download_dir)

        tasks = [asyncio.create_task(_worker(c)) for c in candidates]
        for task in asyncio.as_completed(tasks):
            candidate, artifact = await task
            try:
                await self._install(candidate, artifact)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error("Failed to install %s: %s", candidate.name, exc)
                self._event_bus.publish(
                    Event(
                        "update.failed",
                        {
                            "plugin": candidate.name,
                            "current": str(candidate.current_version),
                            "target": str(candidate.target_version),
                            "reason": str(exc),
                        },
                    )
                )
            else:
                self._event_bus.publish(
                    Event(
                        "update.installed",
                        {
                            "plugin": candidate.name,
                            "from": str(candidate.current_version),
                            "to": str(candidate.target_version),
                        },
                    )
                )

    async def _download(
        self, candidate: UpdateCandidate, download_dir: Path
    ) -> Path:
        """
        Stream the file to disk while sending progress events.
        """
        if not self._client:
            raise RuntimeError("UpdateService.start() must be called first")
        if candidate.name in self._currently_downloading:
            raise UpdateServiceError(f"{candidate.name} is already being downloaded")

        self._currently_downloading.add(candidate.name)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f"{candidate.name}-", suffix=".tmp", dir=str(download_dir)
        )
        tmp_path = Path(tmp_path_str)
        os.close(tmp_fd)  # We will reopen it with buffering.

        _LOGGER.info(
            "Downloading %s@%s — %s", candidate.name, candidate.target_version, candidate.download_url
        )
        bytes_read = 0
        start_ts = time.perf_counter()
        try:
            async with self._client.stream("GET", candidate.download_url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                with tmp_path.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(_DOWNLOAD_CHUNK_SIZE):
                        fh.write(chunk)
                        bytes_read += len(chunk)
                        self._event_bus.publish(
                            Event(
                                "update.progress",
                                {
                                    "plugin": candidate.name,
                                    "downloaded": bytes_read,
                                    "total": total,
                                },
                            )
                        )

            _LOGGER.debug(
                "Finished download of %s (%.02f MiB) in %.02fs",
                candidate.name,
                bytes_read / (1024 * 1024),
                time.perf_counter() - start_ts,
            )

            # Security checks
            _verify_checksum(tmp_path, candidate.sha256)
            _verify_signature(tmp_path, candidate.signature)

            # Move confirmed file into final location
            final_path = download_dir / candidate.filename
            tmp_path.replace(final_path)
            return final_path

        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        finally:
            self._currently_downloading.discard(candidate.name)

    async def _install(self, candidate: UpdateCandidate, artifact: Path) -> None:
        """
        Atomically replace the plugin directory with the newly downloaded
        artifact.  Installation happens in a worker thread to avoid blocking
        the event loop with ZIP extraction & IO.
        """

        async def _install_sync() -> None:
            import zipfile

            plugin_info = next(
                p
                for p in self._plugin_manager.get_installed_plugins()
                if p.name == candidate.name
            )
            target_dir = plugin_info.path.parent
            install_dir = target_dir / f"{plugin_info.name}-{candidate.target_version}"

            if install_dir.exists():
                _LOGGER.debug("Removing pre-existing dir %s", install_dir)
                shutil.rmtree(install_dir, ignore_errors=True)

            _LOGGER.debug("Extracting %s to %s", artifact, install_dir)
            with zipfile.ZipFile(artifact) as zf:
                zf.extractall(install_dir)

            # Update symlink
            current_symlink = target_dir / plugin_info.name
            temp_symlink = target_dir / f".{plugin_info.name}.tmp"

            if temp_symlink.exists():
                temp_symlink.unlink()

            temp_symlink.symlink_to(install_dir, target_is_directory=True)
            temp_symlink.replace(current_symlink)

            # Hot-reload plugin via plugin manager, fall back to app restart if fails.
            try:
                self._plugin_manager.reload_plugin(candidate.name)
            except AttributeError:  # reload_plugin not implemented
                _LOGGER.info(
                    "%s installed, but plugin hot-reload unavailable → restart required",
                    candidate.name,
                )
            except Exception as exc:
                raise InstallationError(f"Hot-reload failed: {exc}") from exc

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _install_sync)

    # ---------------------------------------------------------------------#
    # Public commands (may be used by UI / CLI)
    # ---------------------------------------------------------------------#

    async def manual_check(self) -> None:
        """Trigger a manual update cycle (ignores debounce interval)."""
        await self._check_for_updates()

    async def pause(self) -> None:
        """Pause periodic checks (downloads in progress are not interrupted)."""
        self._shutdown_event.set()
        self._shutdown_event = asyncio.Event()

    def resume(self) -> None:
        """Resume periodic checks after `pause()`."""
        if not self._task_group:
            raise RuntimeError("UpdateService is not running")
        self._task_group.create_task(self._periodic_check_loop())
```
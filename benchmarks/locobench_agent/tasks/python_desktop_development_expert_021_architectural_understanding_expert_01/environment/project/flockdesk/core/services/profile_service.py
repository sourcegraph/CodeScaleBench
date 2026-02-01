```python
"""
FlockDesk – Social Workspace Orchestrator
core.services.profile_service

This module provides the high-level “ProfileService” that manages the user’s
roaming profile, including local persistence, remote cloud sync, and in-process
publish / subscribe to profile-related events.

The service fulfils several responsibilities:

1.  Persist a *single-source-of-truth* profile document to disk so the desktop
    boots instantly – even without network connectivity.
2.  Keep the local copy in lock-step with the cloud copy via an incremental,
    fault-tolerant background synchronisation loop.
3.  Broadcast profile changes on the application-wide event-bus so that
    micro-front-ends (chat, whiteboard, etc.) can react to preference changes
    in real-time without tight coupling.
4.  Offer a simple observer interface (`register_listener`) for plug-ins that
    prefer a direct callback instead of routing through the event bus.

The implementation is deliberately *thread-safe* and *resilient* – any
unexpected exception is caught and reported without bringing down the hosting
process.

Typical usage
-------------
```python
from flockdesk.core.event_bus import EventBus
from flockdesk.core.services.profile_service import ProfileService

event_bus = EventBus()
profile_service = ProfileService(event_bus, user_id="42")
profile_service.start()          # kick-off background sync

# Retrieve the currently cached profile
profile = profile_service.profile  

# Update the profile
profile.preferences["theme"] = "dark"
profile_service.save(profile)    # persist+sync change
```
"""

from __future__ import annotations

import json
import logging
import pathlib
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, MutableMapping, Optional

import requests

# External dependencies – these modules are expected to live inside the
# FlockDesk code base.  We use `type: ignore` to keep linters quiet when this
# file is opened standalone.
from flockdesk.core.event_bus import Event, EventBus  # type: ignore

LOG = logging.getLogger(__name__)
DEFAULT_CLOUD_ENDPOINT = "https://api.flockdesk.cloud/v1/profile"

_JSON_INDENT = 2  # pretty-print profile on disk for human readability


@dataclass
class UserProfile:
    """Serializable user profile document.

    Additional keys are supported via `extra` so plug-ins can store arbitrary
    information without waiting for the core service to evolve.
    """

    user_id: str
    username: str
    preferences: Dict[str, Any] = field(default_factory=dict)
    layout: Dict[str, Any] = field(default_factory=dict)
    last_updated_ts: float = field(default_factory=lambda: time.time())
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: MutableMapping[str, Any]) -> "UserProfile":
        """Create a `UserProfile` from a JSON-decoded dict."""
        return cls(
            user_id=data["user_id"],
            username=data.get("username", ""),
            preferences=data.get("preferences", {}),
            layout=data.get("layout", {}),
            last_updated_ts=data.get("last_updated_ts", time.time()),
            extra=data.get("extra", {}),
        )

    def to_json(self) -> Dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return asdict(self)


class StorageProvider:
    """Simple JSON-file storage for the user profile."""

    def __init__(self, base_path: Optional[pathlib.Path] = None) -> None:
        self._base_path = (
            base_path if base_path is not None else pathlib.Path.home() / ".config" / "FlockDesk"
        )
        self._base_path.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------- #
    # public
    # --------------------------------------------------------------------- #

    def load(self, user_id: str) -> Optional[UserProfile]:
        path = self._file_path(user_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return UserProfile.from_json(data)
        except Exception:
            LOG.exception("Failed to load profile from disk: %s", path)
            return None

    def save(self, profile: UserProfile) -> None:
        path = self._file_path(profile.user_id)
        try:
            path.write_text(
                json.dumps(profile.to_json(), indent=_JSON_INDENT),
                encoding="utf-8",
            )
        except Exception:
            LOG.exception("Failed to save profile to disk: %s", path)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _file_path(self, user_id: str) -> pathlib.Path:
        return self._base_path / f"profile_{user_id}.json"


class ProfileService:
    """High-level facade around local/remote profile management."""

    # pylint: disable=too-many-instance-attributes
    def __init__(
        self,
        event_bus: EventBus,
        user_id: str,
        *,
        storage: Optional[StorageProvider] = None,
        remote_endpoint: str = DEFAULT_CLOUD_ENDPOINT,
        sync_interval_s: int = 120,
        max_backoff_s: int = 10 * 60,
        session: Optional[requests.Session] = None,
    ) -> None:
        self._bus = event_bus
        self._user_id = user_id
        self._storage = storage or StorageProvider()
        self._remote_endpoint = remote_endpoint.rstrip("/")
        self._sync_interval = max(15, sync_interval_s)  # sane lower bound
        self._max_backoff = max_backoff_s
        self._session = session or requests.Session()
        self._lock = threading.RLock()

        self._listeners: List[Callable[[UserProfile], None]] = []
        self._profile: UserProfile = (
            self._storage.load(user_id) or self._initialise_blank_profile()
        )

        self._sync_thread = threading.Thread(
            target=self._sync_loop,
            name="FlockDeskProfileSync",
            daemon=True,
        )
        self._stop_event = threading.Event()

        # subscribe to in-process events
        self._bus.subscribe("profile/refresh", self._on_external_refresh)

    # --------------------------------------------------------------------- #
    # lifecycle
    # --------------------------------------------------------------------- #

    def start(self) -> None:
        """Start the background sync loop."""
        if not self._sync_thread.is_alive():
            LOG.debug("Starting ProfileService sync thread for user %s", self._user_id)
            self._sync_thread.start()

    def stop(self) -> None:
        """Signal the background thread to terminate and wait for completion."""
        LOG.debug("Stopping ProfileService sync thread for user %s", self._user_id)
        self._stop_event.set()
        self._sync_thread.join(timeout=5)

    # --------------------------------------------------------------------- #
    # public – profile CRUD
    # --------------------------------------------------------------------- #

    @property
    def profile(self) -> UserProfile:
        with self._lock:
            return self._profile

    def save(self, profile: UserProfile, *, broadcast: bool = True) -> None:
        """Persist and broadcast a profile that has been modified in-memory."""
        with self._lock:
            profile.last_updated_ts = time.time()
            self._profile = profile
            self._storage.save(profile)

        if broadcast:
            self._bus.publish(Event("profile/updated", payload=profile.to_json()))
            self._notify_listeners(profile)

    def update_preferences(self, **kwargs: Any) -> None:
        """Convenience helper to modify `preferences`."""
        with self._lock:
            self._profile.preferences.update(kwargs)
            self._profile.last_updated_ts = time.time()
            self._storage.save(self._profile)

        self._bus.publish(Event("profile/updated", payload=self._profile.to_json()))
        self._notify_listeners(self._profile)

    # ------------------------------------------------------------------ #
    # observer API
    # ------------------------------------------------------------------ #

    def register_listener(self, fn: Callable[[UserProfile], None]) -> Callable[[], None]:
        """Register a callback that fires when the profile changes.

        Returns
        -------
        Callable[[], None]
            Unregister function.
        """
        if fn not in self._listeners:
            self._listeners.append(fn)

        def _unregister() -> None:
            try:
                self._listeners.remove(fn)
            except ValueError:
                pass

        return _unregister

    # ------------------------------------------------------------------ #
    # private – event bus hooks
    # ------------------------------------------------------------------ #

    def _on_external_refresh(self, event: Event) -> None:  # noqa: D401
        """Handle 'profile/refresh' emitted by external components."""
        LOG.debug("Received external profile refresh request event=%s", event.meta)
        # Force an immediate remote sync outside of the normal interval
        threading.Thread(
            target=self._pull_remote, name="FlockDeskProfileForcePull", daemon=True
        ).start()

    # ------------------------------------------------------------------ #
    # private – synchronisation loop
    # ------------------------------------------------------------------ #

    def _sync_loop(self) -> None:
        """Background loop – push/pull profile with exponential backoff."""
        backoff_s = self._sync_interval
        while not self._stop_event.is_set():
            start = time.time()
            try:
                self._push_local()    # push first so remote gets our changes
                self._pull_remote()   # then pull remote updates
                backoff_s = self._sync_interval  # reset backoff after success
            except Exception:  # noqa: BLE001 – catch-all keeps the loop alive
                LOG.exception("Profile sync failed – backing off")
                backoff_s = min(backoff_s * 2, self._max_backoff)
            finally:
                elapsed = time.time() - start
                sleep_time = max(backoff_s - elapsed, 1)
                self._stop_event.wait(timeout=sleep_time)

    def _push_local(self) -> None:
        """Push local profile to the cloud if it has diverged."""
        with self._lock:
            payload = self._profile.to_json()

        url = f"{self._remote_endpoint}/{self._user_id}"
        try:
            res = self._session.put(url, json=payload, timeout=10)
            res.raise_for_status()
            LOG.debug("Pushed profile to remote (%s)", res.status_code)
        except requests.RequestException:
            LOG.warning("Failed to push profile to cloud", exc_info=True)
            raise

    def _pull_remote(self) -> None:
        """Pull profile from cloud and merge if newer than local."""
        url = f"{self._remote_endpoint}/{self._user_id}"
        try:
            res = self._session.get(url, timeout=10)
            res.raise_for_status()
            remote_doc = res.json()
        except requests.RequestException:
            LOG.info("Profile pull skipped – network unavailable")
            raise

        remote_profile = UserProfile.from_json(remote_doc)
        with self._lock:
            if remote_profile.last_updated_ts > self._profile.last_updated_ts:
                LOG.debug("Remote profile is newer – updating local copy")
                self._profile = remote_profile
                self._storage.save(remote_profile)

        # Publish regardless – the event bus de-duplicates on payload hash
        self._bus.publish(Event("profile/updated", payload=remote_profile.to_json()))
        self._notify_listeners(remote_profile)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _notify_listeners(self, profile: UserProfile) -> None:
        """Invoke registered callbacks (best-effort, non-blocking)."""

        def _run(fn: Callable[[UserProfile], None]) -> None:
            try:
                fn(profile)
            except Exception:  # noqa: BLE001
                LOG.exception("Profile listener raised")

        for listener in list(self._listeners):  # shallow copy to avoid mutation
            threading.Thread(target=_run, args=(listener,), daemon=True).start()

    def _initialise_blank_profile(self) -> UserProfile:
        """Create a default profile document for first-time users."""
        LOG.info("Creating new blank profile for user %s", self._user_id)
        profile = UserProfile(
            user_id=self._user_id,
            username=f"user-{self._user_id}",
            preferences={
                "theme": "light",
                "language": "en",
            },
            layout={},
            extra={},
        )
        self._storage.save(profile)
        return profile
```
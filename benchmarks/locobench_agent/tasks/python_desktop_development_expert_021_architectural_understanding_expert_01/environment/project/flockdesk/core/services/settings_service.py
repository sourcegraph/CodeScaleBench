```python
"""
flockdesk.core.services.settings_service
========================================

A centralised, thread-safe settings/pref-store that is aware of plugin
namespaces and keeps the on-disk representation in sync with registered
dataclass-based schemas.  Changes are automatically propagated over the
internal event-bus.

The service embraces the following goals:

    • Multiple independent namespaces (“core”, “chat”, “whiteboard”, …)
      – usually one per micro-front-end or plugin.
    • Strongly-typed settings definitions via `@dataclass` schemas.
    • Atomic & cross-platform persistence (JSON) in the user’s roaming
      configuration directory (see `appdirs`).
    • Optional auto-save timer to persist frequent modifications without
      synchronous disk writes on every `set(..)`.
    • Event-driven notifications after a setting has been updated so that
      UI-views / view-models can react immediately.
    • Minimal, dependency-free (*) implementation – only `appdirs` is an
      external runtime requirement.

(*) `appdirs` is a de-facto standard for platform-independent config
    paths.  If it is not present an ImportError is raised at import-time,
    which is fine because FlockDesk already vendors the package.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, Generic, Optional, Protocol, Type, TypeVar

from appdirs import user_config_dir

__all__ = [
    "SettingsService",
    "SettingsServiceError",
    "register_settings_schema",
    "TransientOverride",
]

_logger = logging.getLogger(__name__)

T = TypeVar("T")


class SettingsServiceError(RuntimeError):
    """Base class for all settings-related exceptions."""


class EventBus(Protocol):
    """
    Very small subset of the internal event-bus the service cares about.
    The concrete implementation is provided by the FlockDesk runtime.
    """

    def publish(self, topic: str, payload: Dict[str, Any]) -> None: ...


class _AtomicJSONFile:
    """
    Helper for atomic JSON read/write.

    Writes are performed on `file_path.with_suffix(".tmp")` first and moved
    into place via rename, which is atomic on all modern filesystems.
    """

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._lock = threading.Lock()

    def read(self) -> Dict[str, Any]:
        if not self._file_path.exists():
            return {}
        with self._file_path.open("r", encoding="utf-8") as fp:
            try:
                return json.load(fp)
            except (json.JSONDecodeError, OSError) as exc:
                _logger.warning(
                    "Corrupted settings file '%s': %s – falling back to empty dict.",
                    self._file_path,
                    exc,
                )
                return {}

    def write(self, data: Dict[str, Any]) -> None:
        tmp_path = self._file_path.with_suffix(".tmp")
        with self._lock, tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, sort_keys=True)
            fp.flush()
            fp.close()  # Explicit close before rename for Windows.
            tmp_path.replace(self._file_path)


class _SchemaMeta(Generic[T]):
    """
    Wraps a dataclass-based schema and provides (de)serialisation helpers.
    """

    def __init__(self, schema_cls: Type[T]) -> None:
        if not dataclasses.is_dataclass(schema_cls):
            raise TypeError(f"{schema_cls!r} is not a dataclass.")
        self.cls: Type[T] = schema_cls
        # Optional versioning field
        self.version: str = getattr(schema_cls, "__version__", "1")

    # --------------------------------------------------------------------- #
    # Serialisation helpers
    # --------------------------------------------------------------------- #
    def to_dict(self, instance: T) -> Dict[str, Any]:
        return dataclasses.asdict(instance)

    def from_dict(self, raw: Dict[str, Any]) -> T:
        """
        Convert a loosely-typed dict into a concrete schema instance.
        Unknown keys are ignored; missing keys are filled with defaults.
        """
        valid_fields = {f.name for f in dataclasses.fields(self.cls)}
        kwargs = {k: v for k, v in raw.items() if k in valid_fields}
        return self.cls(**kwargs)  # type: ignore[arg-type]


class SettingsService:
    """
    The central façade used by micro-front-ends and plugins to register
    strongly-typed preference buckets and to query/update their values.
    """

    _SAVE_INTERVAL_SEC = 5

    def __init__(
        self,
        app_name: str = "FlockDesk",
        *,
        author: str = "FlockDesk",
        event_bus: Optional[EventBus] = None,
        autosave: bool = True,
    ) -> None:
        self._event_bus = event_bus
        self._autosave = autosave

        self._config_root: Path = Path(user_config_dir(app_name, author))
        self._config_root.mkdir(parents=True, exist_ok=True)

        self._schemas: Dict[str, _SchemaMeta[Any]] = {}
        self._instances: Dict[str, Any] = {}  # schema instance per namespace
        self._files: Dict[str, _AtomicJSONFile] = {}

        self._lock = threading.RLock()
        self._dirty_namespaces: set[str] = set()
        self._save_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        if autosave:
            self._save_thread = threading.Thread(
                name="SettingsAutoSaveThread",
                target=self._autosave_loop,
                daemon=True,
            )
            self._save_thread.start()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def register_schema(self, namespace: str, schema_cls: Type[T]) -> None:
        """
        Register a dataclass schema under the given namespace.
        May be invoked multiple times (usually once per plugin).

        Raises
        ------
        SettingsServiceError
            If the namespace is already in use.
        """
        with self._lock:
            if namespace in self._schemas:
                raise SettingsServiceError(
                    f"Settings namespace '{namespace}' already registered."
                )

            meta = _SchemaMeta(schema_cls)
            self._schemas[namespace] = meta
            self._files[namespace] = _AtomicJSONFile(
                self._config_root / f"{namespace}.json"
            )

            # Load persisted values OR fall back to defaults
            file_data = self._files[namespace].read()
            version = file_data.pop("__version__", None)
            if version and version != meta.version:
                _logger.info(
                    "Settings-schema version mismatch for '%s' "
                    "(file=%s, schema=%s) – applying best-effort migration.",
                    namespace,
                    version,
                    meta.version,
                )
                # TODO: call user-defined migration hook(s).
            instance = meta.from_dict(file_data)
            self._instances[namespace] = instance

    def get(self, namespace: str) -> Any:
        """
        Return the *immutable* settings dataclass for `namespace`.

        Mutating returned objects directly is not supported – use
        `edit(namespace)` or `set_value(..)` instead.
        """
        with self._lock:
            instance = self._instances.get(namespace)
            if instance is None:
                raise SettingsServiceError(f"Unknown settings namespace '{namespace}'.")
            return MappingProxyType(dataclasses.asdict(instance))

    def edit(self, namespace: str) -> "TransientOverride":
        """
        Return a context-manager that allows *temporary* modifications to
        the given namespace.  The temporary changes are discarded when the
        context exits – useful for tests or “preview” UI interactions.
        """
        return TransientOverride(self, namespace)

    def set_value(self, namespace: str, key: str, value: Any) -> None:
        """
        Update a single field in the namespace and enqueue the change for
        persistence and event-bus broadcast.

        Type mismatches raise immediately.
        """
        with self._lock:
            meta = self._schemas.get(namespace)
            instance = self._instances.get(namespace)
            if not meta or instance is None:
                raise SettingsServiceError(f"Unknown settings namespace '{namespace}'.")

            field_types = {f.name: f.type for f in dataclasses.fields(meta.cls)}
            if key not in field_types:
                raise SettingsServiceError(
                    f"Settings key '{key}' is not part of schema '{namespace}'."
                )

            expected_type = field_types[key]
            if not isinstance(value, expected_type):
                raise SettingsServiceError(
                    f"Type mismatch for '{namespace}.{key}': "
                    f"expected {expected_type}, got {type(value)}."
                )

            setattr(instance, key, value)
            self._mark_dirty(namespace)

    # ------------------------------------------------------------------ #
    # Life-cycle helpers
    # ------------------------------------------------------------------ #
    def shutdown(self) -> None:
        """
        Flush outstanding writes and stop the autosave thread.
        Must be invoked when FlockDesk shuts down.
        """
        self._stop_event.set()
        if self._save_thread and self._save_thread.is_alive():
            self._save_thread.join()
        self._flush_all()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _mark_dirty(self, namespace: str) -> None:
        self._dirty_namespaces.add(namespace)
        if self._autosave is False:
            # Persist synchronously when autosave is disabled.
            self._flush(namespace)
        else:
            _logger.debug("Marked namespace '%s' as DIRTY.", namespace)

        # Publish change notification.
        if self._event_bus:
            self._event_bus.publish(
                topic="settings.updated",
                payload={"namespace": namespace},
            )

    def _flush(self, namespace: str) -> None:
        with self._lock:
            if namespace not in self._dirty_namespaces:
                return
            meta = self._schemas[namespace]
            instance = self._instances[namespace]
            payload = meta.to_dict(instance)
            payload["__version__"] = meta.version
            self._files[namespace].write(payload)
            self._dirty_namespaces.discard(namespace)
            _logger.debug("Flushed settings for namespace '%s'.", namespace)

    def _flush_all(self) -> None:
        _logger.debug("Flushing %d dirty namespaces...", len(self._dirty_namespaces))
        for ns in list(self._dirty_namespaces):
            self._flush(ns)

    def _autosave_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self._SAVE_INTERVAL_SEC)
            if self._dirty_namespaces:
                _logger.debug(
                    "Auto-saving %d namespaces …", len(self._dirty_namespaces)
                )
            self._flush_all()


# ------------------------------------------------------------------------- #
# “Public” helper – decorator to register dataclass schemas more ergonomically
# ------------------------------------------------------------------------- #
def register_settings_schema(namespace: str) -> Callable[[Type[T]], Type[T]]:
    """
    Decorator for plugin modules:

        @register_settings_schema("chat")
        @dataclass
        class ChatSettings:
            enable_notifications: bool = True
            history_limit: int = 1000
    """

    def decorator(cls: Type[T]) -> Type[T]:
        # Postpone actual service registration until run-time – the settings
        # service is a singleton created by the application bootstrap code.
        from flockdesk.core.ioc import container  # type: ignore

        svc: SettingsService = container.resolve(SettingsService)  # pseudo-DI
        svc.register_schema(namespace, cls)
        return cls

    return decorator


# ------------------------------------------------------------------------- #
# Context-manager for temporary overrides
# ------------------------------------------------------------------------- #
class TransientOverride:
    """
    Context-manager that lets callers stack temporary changes to a namespace.

    Example:
        with settings_service.edit("core") as cfg:
            cfg["dark_mode"] = True
            # inside with-block -> dark_mode toggled.
        # outside -> previous value restored (no disk flush either)
    """

    def __init__(self, service: SettingsService, namespace: str) -> None:
        self._service = service
        self._namespace = namespace
        self._original_instance: Optional[Any] = None

    def __enter__(self) -> Dict[str, Any]:
        with self._service._lock:
            inst = self._service._instances.get(self._namespace)
            if inst is None:
                raise SettingsServiceError(
                    f"Cannot edit unknown namespace '{self._namespace}'."
                )
            # Deep-copy to preserve original
            self._original_instance = dataclasses.replace(inst)
            return dataclasses.asdict(inst)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        with self._service._lock:
            if self._original_instance is not None:
                self._service._instances[self._namespace] = self._original_instance
                self._service._dirty_namespaces.discard(self._namespace)
                _logger.debug(
                    "Transient overrides for namespace '%s' reverted.",
                    self._namespace,
                )
```
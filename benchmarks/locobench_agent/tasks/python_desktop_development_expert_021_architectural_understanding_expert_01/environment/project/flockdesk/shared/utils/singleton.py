```python
"""
flockdesk.shared.utils.singleton
================================

Thread-safe singleton helpers used across the FlockDesk desktop suite.

FlockDesk is highly modular.  Each micro-front-end (chat, presence, etc.)
runs inside its own process yet still contains *local* state that should only
have a single authoritative instance *per-process*—think global settings
caches, in-memory credential vaults, or the Qt high-level application object.

This module provides a *metaclass* and a *mixin* that turn any class into a
well-behaved singleton:

    from flockdesk.shared.utils.singleton import SingletonMeta, Singleton

    class SettingsCache(metaclass=SingletonMeta):
        ...

    # or mixin style
    class CredentialsVault(Singleton):
        ...

Features
--------
1. Thread-safe
2. Supports per-scope (a.k.a *multiton*) instances, e.g. one singleton per
   workspace or plugin id
3. Explicit reset helpers for deterministic testing or dynamic plugin unloads
4. Minimal overhead/boilerplate for adopters
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import (
    Any,
    ClassVar,
    Dict,
    Final,
    Hashable,
    MutableMapping,
    Tuple,
    Type,
    TypeVar,
)

__all__ = [
    "SingletonMeta",
    "Singleton",
    "singleton_factory",
    "release_singleton",
    "purge_singletons",
]

T = TypeVar("T")

_LOG: Final = logging.getLogger("flockdesk.utils.singleton")

###############################################################################
# Exceptions
###############################################################################


class SingletonError(RuntimeError):
    """Raised when singleton integrity cannot be guaranteed."""


###############################################################################
# Helpers
###############################################################################


def _make_instance_key(cls: Type[Any], scope: Hashable | None) -> Tuple[Type[Any], Hashable | None]:  # noqa: D401,E501
    """
    Compose a unique key for the singleton map.

    Parameters
    ----------
    cls:
        Class being instantiated.
    scope:
        Optional scope identifier.  `None` means *global* singleton for that
        class.  A hashable value (str, int, guid) enables *multi-ton* behavior
        where each scope receives its own singleton instance.
    """
    if scope is not None and not isinstance(scope, Hashable):
        raise SingletonError("Scope must be hashable")
    return cls, scope


###############################################################################
# Core metaclass
###############################################################################


class SingletonMeta(type):
    """
    Metaclass that guarantees a single instance per process **or** per scope.

    Usage::

        class Registry(metaclass=SingletonMeta):
            _scope_attr_ = "workspace_id"  # Optional – see below

            def __init__(self, workspace_id: str):
                self.workspace_id = workspace_id

    Scoping
    -------
    By default, a class using `SingletonMeta` is a *global* singleton.  To turn
    it into a *scoped* singleton (one instance per given key) either:

    1. Pass ``scope=...`` when calling the constructor:

           Registry(scope="tenant-42")

    2. Define the attribute ``_scope_attr_`` on the class.  When present, the
       value of the corresponding constructor argument will be used as the
       scope identifier automatically::

           class Registry(metaclass=SingletonMeta):
               _scope_attr_ = "workspace_id"

               def __init__(self, workspace_id: str):
                   ...

           # first instance for workspace 'alpha'
           Registry(workspace_id="alpha")

           # distinct instance
           Registry(workspace_id="beta")
    """

    #: central lookup dict that survives *across* class reloads
    _instances: MutableMapping[Tuple[Type[Any], Hashable | None], Any] = {}
    _sync_lock: ClassVar[threading.RLock] = threading.RLock()
    _async_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    # --------------------------------------------------------------------- #
    # Python synchronous construction path
    # --------------------------------------------------------------------- #
    def __call__(cls: Type[T], *args: Any, **kwargs: Any) -> T:  # type: ignore[override]  # noqa: E501
        sync = kwargs.pop("_sync_only_", False)
        scope = kwargs.pop("scope", None)

        # Automatic scope detection from _scope_attr_
        if scope is None and hasattr(cls, "_scope_attr_"):
            scope_attr = getattr(cls, "_scope_attr_")
            if scope_attr in kwargs:
                scope = kwargs[scope_attr]
            else:
                # Support positional args if the attribute matches the
                # __init__ parameter order
                init_positional_map = getattr(cls, "__init__").__code__.co_varnames[
                    1 :
                ]  # skip 'self'
                if scope_attr in init_positional_map:
                    index = init_positional_map.index(scope_attr)
                    if index < len(args):
                        scope = args[index]

        key = _make_instance_key(cls, scope)

        if sync:  # caller ensures single-threaded context – skip locks
            if key not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[key] = instance
            return cls._instances[key]

        with cls._sync_lock:
            if key not in cls._instances:
                _LOG.debug("Creating singleton %s (scope=%s)", cls.__qualname__, scope)
                instance = super().__call__(*args, **kwargs)
                cls._instances[key] = instance
            return cls._instances[key]

    # --------------------------------------------------------------------- #
    # Coroutine helper
    # --------------------------------------------------------------------- #
    async def aget(  # noqa: D401
        cls: Type[T], *args: Any, scope: Hashable | None = None, **kwargs: Any
    ) -> T:
        """
        Asynchronous version of the constructor.

        Example
        -------
            vault = await CredentialsVault.aget()
        """
        key = _make_instance_key(cls, scope)
        if key in cls._instances:
            return cls._instances[key]

        async with cls._async_lock:
            if key not in cls._instances:
                _LOG.debug(
                    "Creating *async* singleton %s (scope=%s)", cls.__qualname__, scope
                )
                instance = cls(*args, scope=scope, **kwargs, _sync_only_=True)  # type: ignore[arg-type]  # noqa: E501
                cls._instances[key] = instance
            return cls._instances[key]

    # --------------------------------------------------------------------- #
    # Introspection/maintenance helpers
    # --------------------------------------------------------------------- #
    def is_initialised(cls, scope: Hashable | None = None) -> bool:  # noqa: D401
        """Return ``True`` if the singleton instance already exists."""
        return _make_instance_key(cls, scope) in cls._instances

    def instance(cls: Type[T], scope: Hashable | None = None) -> T:
        """
        Retrieve an already created instance *without* constructing a new one.

        Raises
        ------
        SingletonError
            If the instance has not been created yet.
        """
        key = _make_instance_key(cls, scope)
        try:
            return cls._instances[key]
        except KeyError as exc:  # pragma: no cover
            raise SingletonError(
                f"{cls.__qualname__} has not been initialised for scope={scope!r}"
            ) from exc

    # --------------------------------------------------------------------- #
    # Destruction helpers – useful for testing & plugin hot reloads
    # --------------------------------------------------------------------- #
    def reset(cls, *, scope: Hashable | None = None) -> None:  # noqa: D401
        """Remove a single instance."""
        with cls._sync_lock:
            key = _make_instance_key(cls, scope)
            cls._instances.pop(key, None)

    def reset_all(cls) -> None:  # noqa: D401
        """Remove all instances of *this* class (irrespective of scope)."""
        with cls._sync_lock:
            keys = [k for k in cls._instances if k[0] is cls]
            for k in keys:
                cls._instances.pop(k, None)


###############################################################################
# Convenience mixin
###############################################################################


class Singleton(metaclass=SingletonMeta):
    """
    Mixin that makes the inheriting class a singleton.

    Example
    -------
        class TelemetryReporter(Singleton):
            def __init__(self) -> None:
                self.session_id = uuid.uuid4()
    """

    # `pass` – implementation is fully handled by the metaclass


###############################################################################
# Procedural API
###############################################################################


def singleton_factory(
    cls: Type[T],
    /,
    *,
    scope: Hashable | None = None,
    **init_kwargs: Any,
) -> T:
    """
    Procedural helper – equivalent to ``cls(scope=scope, **init_kwargs)``.

    Useful for dependency injection frameworks that prefer callables instead of
    direct class construction.
    """
    return cls(scope=scope, **init_kwargs)  # type: ignore[return-value]


def release_singleton(cls: Type[Any], /, *, scope: Hashable | None = None) -> None:
    """
    Explicitly dispose a singleton instance.

    Pattern-matching `SingletonMeta.reset` but works regardless of whether the
    class *directly* uses `SingletonMeta` or inherits from `Singleton`.
    """
    if isinstance(cls, SingletonMeta):
        cls.reset(scope=scope)  # type: ignore[attr-defined]
    else:
        raise SingletonError(f"{cls} is not managed by SingletonMeta")


def purge_singletons() -> None:  # noqa: D401
    """Remove **all** singleton instances – mostly for *test suites*."""
    with SingletonMeta._sync_lock:
        SingletonMeta._instances.clear()


###############################################################################
# Context manager for temporary overrides
###############################################################################


@contextlib.contextmanager
def _singleton_override(
    cls: Type[T], temporary: T, /, *, scope: Hashable | None = None
):  # noqa: D401,E501
    """
    Internal context manager used in tests to monkey-patch a singleton.

    Example
    -------
        real = MySingleton()

        with _singleton_override(MySingleton, Fake(), scope="alpha"):
            ...
    """
    key = _make_instance_key(cls, scope)
    with SingletonMeta._sync_lock:
        original = SingletonMeta._instances.get(key)
        SingletonMeta._instances[key] = temporary
        _LOG.debug("Temporarily overriding %s (scope=%s)", cls.__qualname__, scope)
        try:
            yield
        finally:
            # restore prior state
            if original is None:
                SingletonMeta._instances.pop(key, None)
            else:
                SingletonMeta._instances[key] = original
```

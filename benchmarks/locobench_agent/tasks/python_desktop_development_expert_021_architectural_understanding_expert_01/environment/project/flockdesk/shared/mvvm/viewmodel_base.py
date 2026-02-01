```python
"""
flockdesk.shared.mvvm.viewmodel_base
====================================

Common abstractions required by all FlockDesk view-models.  The module provides:

    • ViewModelBase –  a QObject-derived class that implements:
        – Property-change notification
        – Busy/idle state management
        – Command helpers (MVVM actions bound from the View)
        – Async/await helpers that co-exist with Qt’s event loop
        – Automatic resource clean-up on dispose()

    • Command – an invokable/observable wrapper around an arbitrary callable
      that exposes `can_execute` as a live Qt property.

The implementation purposefully avoids any UI-specific behaviour and therefore
can be reused by headless unit tests.

Author: FlockDesk engineering
License: MIT  (see repository root)
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import threading
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
)

from PySide6 import QtCore

__all__ = ["ViewModelBase", "Command"]

_log = logging.getLogger("flockdesk.viewmodel")


T = TypeVar("T")
Func = TypeVar("Func", bound=Callable[..., Any])
_SENTINEL = object()


# ----------------------------------------------------------------------------- #
#                                   COMMAND                                     #
# ----------------------------------------------------------------------------- #
class Command(QtCore.QObject):
    """
    Encapsulates an action that can be executed from the View.

    Usage
    -----
    >>> save_cmd = Command(lambda: repo.save(...))
    >>> button.clicked.connect(save_cmd)

    The `enabled` property automatically reflects the result of `can_execute`
    predicate:

    >>> save_cmd = Command(
    ...     execute=lambda: repo.save(...),
    ...     can_execute=lambda: repo.has_changes
    ... )
    """

    triggered = QtCore.Signal()
    enabledChanged = QtCore.Signal(bool)

    def __init__(
        self,
        execute: Callable[[], Any] | Callable[[], Awaitable[Any]],
        *,
        can_execute: Callable[[], bool] | None = None,
        auto_async: bool = True,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        """
        Parameters
        ----------
        execute:
            Function (sync or async) to run when the command is invoked.
        can_execute:
            Predicate that returns whether the command is currently enabled.
        auto_async:
            If *True* and `execute` returns an awaitable, it will be scheduled
            on the running asyncio loop. Errors are funnelled through the
            global exception hook.
        """
        super().__init__(parent=parent)
        self._execute = execute
        self._can_execute_fn = can_execute
        self._auto_async = auto_async

        self._enabled_cache = self._eval_can_execute()
        self.setObjectName(repr(execute))

    # --------------------------------------------------------------------- #
    #                              Qt API                                   #
    # --------------------------------------------------------------------- #
    @QtCore.Slot()
    def __call__(self) -> None:
        """Invoke the command from Python or Qt."""
        if not self.enabled:
            _log.debug("Command '%s' ignored – disabled", self.objectName())
            return

        try:
            result = self._execute()
            if self._auto_async and inspect.isawaitable(result):
                asyncio.create_task(result)
        except Exception as exc:  # pylint: disable=broad-except
            _log.exception("Unhandled exception in Command '%s'", self.objectName())
            QtCore.QCoreApplication.instance().thread().eventDispatcher().wakeUp()
            # Re-raise so the global sys.excepthook can capture it
            raise exc from None
        else:
            self.triggered.emit()

    # Qt Designer sees a method called `execute` – handy for debugging.
    execute = QtCore.Slot()(lambda self: self())

    # ------------------------------------------------------------------ #
    #                    Enabled / can_execute logic                     #
    # ------------------------------------------------------------------ #
    def _eval_can_execute(self) -> bool:
        try:
            return bool(self._can_execute_fn()) if self._can_execute_fn else True
        except Exception:  # pylint: disable=broad-except
            _log.exception("Error evaluating can_execute for '%s'", self.objectName())
            return False

    @property
    def enabled(self) -> bool:
        return self._enabled_cache

    @QtCore.Property(bool, notify=enabledChanged, fget=enabled)
    def q_enabled(self) -> bool:  # pylint: disable=invalid-name
        """Qt-exposed read-only property."""
        return self.enabled

    def reevaluate(self) -> None:
        """Force re-evaluation of the can_execute predicate."""
        current = self._enabled_cache
        next_value = self._eval_can_execute()
        if current != next_value:
            self._enabled_cache = next_value
            self.enabledChanged.emit(next_value)

    # ------------------------------------------------------------------ #
    #                      Context-manager helpers                       #
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "Command":
        self.reevaluate()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        self.reevaluate()
        return False


# ----------------------------------------------------------------------------- #
#                               VIEWMODEL BASE                                  #
# ----------------------------------------------------------------------------- #
class ViewModelBase(QtCore.QObject):
    """
    Base-class for all FlockDesk MVVM view-models.

    Highlights
    ----------
    • Property change notifications via *propertyChanged* signal  
    • Busy/idle semantics with re-entrant counters  
    • Integrated asyncio helpers that respect the Qt event loop  
    • Automatic disposal of Qt connections, asyncio tasks, and callbacks
    """

    # region Qt signals ---------------------------------------------------
    propertyChanged = QtCore.Signal(str)
    busyChanged = QtCore.Signal(bool)
    exceptionRaised = QtCore.Signal(object, str)  # exc, user-friendly message
    # endregion -----------------------------------------------------------

    def __init__(self, *, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent=parent)
        self._busy_counter = 0
        self._tasks: Set[asyncio.Task[Any]] = set()
        self._connections: List[Tuple[QtCore.QObject, Callable[..., None]]] = []

    # ------------------------------------------------------------------ #
    #                       PROPERTY NOTIFICATION                         #
    # ------------------------------------------------------------------ #
    def _set_property(
        self, field_name: str, new_value: Any, *, public_name: Optional[str] = None
    ) -> bool:
        """
        Helper for implementing observable properties.

        Example
        -------
        class UserVM(ViewModelBase):
            def __init__(...):
                self._name = ''
            @property
            def name(self):
                return self._name
            @name.setter
            def name(self, value):
                self._set_property('_name', value)
        """
        current_value = getattr(self, field_name, _SENTINEL)
        if current_value is new_value:
            return False
        if current_value == new_value:  # Handles value equivalence
            return False

        setattr(self, field_name, new_value)
        self.propertyChanged.emit(public_name or field_name.lstrip("_"))
        return True

    # ------------------------------------------------------------------ #
    #                           BUSY STATE                               #
    # ------------------------------------------------------------------ #
    @property
    def is_busy(self) -> bool:
        return self._busy_counter > 0

    @QtCore.Property(bool, notify=busyChanged, fget=is_busy)
    def q_is_busy(self) -> bool:  # pylint: disable=invalid-name
        """Read-only Qt property reflecting background activity."""
        return self.is_busy

    @contextlib.contextmanager
    def _busy(self) -> Iterable[None]:
        """Context‐manager that automatically increments/decrements busy counter."""
        self._increment_busy()
        try:
            yield
        finally:
            self._decrement_busy()

    # ------------------------------------------------------------------ #
    #                             ASYNC OPS                              #
    # ------------------------------------------------------------------ #
    def run_async(
        self,
        coro_fn: Callable[[], Awaitable[T]] | Awaitable[T],
        *,
        on_result: Callable[[T], Any] | None = None,
        on_error: Callable[[BaseException], Any] | None = None,
        name: str | None = None,
    ) -> asyncio.Task[T]:
        """
        Execute *coro_fn* and track lifecycle/busy state.

        Returns
        -------
        asyncio.Task
            The scheduled task object so the caller can await/cancel if needed.
        """

        async def _runner() -> T:
            try:
                _log.debug("Task '%s' started", task_name)
                with self._busy():
                    result = await (
                        coro_fn() if callable(coro_fn) else coro_fn  # type: ignore[arg-type]
                    )
                if on_result:
                    _invoke_in_ui_thread(on_result, result)
                return result
            except Exception as exc:  # pylint: disable=broad-except
                if on_error:
                    _invoke_in_ui_thread(on_error, exc)
                else:
                    _log.exception("Unhandled error in task '%s'", task_name)
                    self.exceptionRaised.emit(exc, str(exc))
                raise

        loop = _get_or_create_event_loop()
        task_name = name or getattr(coro_fn, "__name__", str(coro_fn))
        task: asyncio.Task[T] = loop.create_task(_runner(), name=task_name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ------------------------------------------------------------------ #
    #                             CLEAN-UP                               #
    # ------------------------------------------------------------------ #
    def add_connection(
        self,
        signal: QtCore.SignalInstance,
        slot: Callable[..., None] | QtCore.Slot,
        *,
        transient: bool = True,
    ) -> None:
        """
        Connect *signal* to *slot* and remember the connection for revival/cleanup.
        When *transient* is False, the connection survives `dispose()`.
        """
        signal.connect(slot)
        if transient:
            self._connections.append((signal, slot))  # type: ignore[arg-type]

    def dispose(self) -> None:
        """
        Releases resources and cancels pending tasks.

        Once disposed, the ViewModel is considered defunct and should not be
        re-used; create a new instance instead.
        """
        _log.debug("Disposing ViewModel '%s'", self)
        for sig, slot in self._connections:
            with contextlib.suppress(RuntimeError, ReferenceError):
                sig.disconnect(slot)

        # Cancel all remaining tasks
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        self.deleteLater()

    # ------------------------------------------------------------------ #
    #                         INTERNAL HELPERS                           #
    # ------------------------------------------------------------------ #
    def _increment_busy(self) -> None:
        was_busy = self.is_busy
        self._busy_counter += 1
        if not was_busy:
            self.busyChanged.emit(True)

    def _decrement_busy(self) -> None:
        if self._busy_counter == 0:
            _log.warning("busy_counter underflow in %s", self)
            return
        self._busy_counter -= 1
        if self._busy_counter == 0:
            self.busyChanged.emit(False)

    # Safety net in case the ViewModel is garbage-collected implicitly.
    def __del__(self) -> None:  # noqa: D401  (simple)
        try:
            self.dispose()
        except Exception:  # pylint: disable=broad-except
            # Never raise during GC
            _log.debug("Suppressed error in ViewModelBase.__del__", exc_info=True)


# ----------------------------------------------------------------------------- #
#                              UTILITY HELPERS                                  #
# ----------------------------------------------------------------------------- #
def _get_or_create_event_loop() -> asyncio.AbstractEventLoop:
    """
    Retrieve the Qt-aware asyncio loop, creating one if necessary.

    On Windows, where the main thread may be the GUI event loop, we rely on
    `asyncio.get_running_loop()` if one is already present. Otherwise we fall
    back to `asyncio.new_event_loop()` and start it in a background thread.

    The implementation intentionally avoids importing external libs like
    *qasync* to keep the shared module lean. Integrations remain free to
    override the policy by pre-installing their own loop before any VM is made.
    """
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        # No running loop – create a serviced loop in a daemon thread.
        loop = asyncio.new_event_loop()
        _log.debug("Spinning up dedicated asyncio loop")
        thread = threading.Thread(target=loop.run_forever, daemon=True, name="qt-asyncio")
        thread.start()
        return loop


def _invoke_in_ui_thread(fn: Callable[..., T], *args: Any, **kwargs: Any) -> None:
    """
    Schedule *fn* to run in the Qt GUI thread.

    If already on the GUI thread, the function executes immediately; otherwise
    a zero-length QTimer is used as a trampoline.
    """

    def _wrapper() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:  # pylint: disable=broad-except
            _log.exception("Error in UI-thread callback %s", fn)

    app = QtCore.QCoreApplication.instance()
    if app is None or QtCore.QThread.currentThread() == app.thread():
        _wrapper()
    else:
        QtCore.QTimer.singleShot(0, _wrapper)


# ----------------------------------------------------------------------------- #
#                              DECORATORS                                       #
# ----------------------------------------------------------------------------- #
def notify_change(
    *property_names: str,
) -> Callable[[Func], Func]:
    """
    Decorator that emits `propertyChanged` after the wrapped function returns.

    Example
    -------
    @notify_change('items', 'has_items')
    def add_item(self, item): ...
    """

    def decorator(func: Func) -> Func:  # type: ignore[override]
        @functools.wraps(func)
        def wrapper(self: ViewModelBase, *args: Any, **kwargs: Any):  # type: ignore[valid-type]
            result = func(self, *args, **kwargs)
            for name in property_names:
                self.propertyChanged.emit(name)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
```
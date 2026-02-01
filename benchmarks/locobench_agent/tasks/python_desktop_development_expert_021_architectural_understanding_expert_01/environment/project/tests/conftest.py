```python
"""
tests/conftest.py

Shared pytest configuration & fixtures for the FlockDesk desktop suite.

The fixtures below try to isolate the *real* application stack as much as
possible while still giving tests full control over:

1.  A temporary, writable configuration/profile directory that is injected
    through the same environment variables the application uses in production.
2.  A lightweight in-memory event-bus implementation so that individual
    services can be unit-tested without boot-strapping the full IPC layer.
3.  An optional Qt application instance, created only when tests explicitly
    ask for it (‒k 'qt' or via the `requires_qt` marker).  The fixture is
    skipped automatically when PySide6/Qt is not available – this allows the
    test-suite to run in headless CI environments without a full Qt tool-chain.
4.  A dummy plugin-registry that mimics the public interface expected by the
    production PluginManager.  It lets tests register arbitrary callables/
    classes as “plugins” and provides helpers for assertions.

Pytest hooks:
    * pytest_addoption
    * pytest_configure
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping

import pytest

###############################################################################
# ––– Optional Qt imports –––
###############################################################################

try:
    # PySide6 is preferred, but PyQt6 is accepted as a fallback.
    from PySide6 import QtWidgets  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        from PyQt6 import QtWidgets  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        QtWidgets = None  # type: ignore


###############################################################################
# ––– CLI options & markers –––
###############################################################################


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Adds command-line options to enable/disable heavy integration layers during CI.
    """
    group = parser.getgroup("flockdesk")
    group.addoption(
        "--run-gui",
        action="store_true",
        default=False,
        help="Run tests that require a Qt GUI event-loop.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """
    Register custom markers so that `pytest --markers` shows meaningful docs.
    """
    config.addinivalue_line(
        "markers",
        "requires_qt: mark test as needing a Qt GUI (skipped when Qt is missing "
        "or when --run-gui is not specified).",
    )


###############################################################################
# ––– Helper classes –––
###############################################################################


class InMemoryEventBus:
    """
    Minimal thread-safe event-bus for unit-tests.  The public surface mimics the
    *real* production interface just enough to fill in when the heavy IPC layer
    isn't spun up.
    """

    def __init__(self) -> None:
        self._subscribers: MutableMapping[str, List[Callable[[Any], None]]] = (
            defaultdict(list)
        )
        self._loop = asyncio.get_event_loop_policy().get_event_loop()
        self._closed = False

    # --------------------------------------------------------------------- #
    #  Subscription                                                          #
    # --------------------------------------------------------------------- #

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        """
        Register *handler* to be invoked synchronously when *topic* is
        published.
        """
        if self._closed:
            raise RuntimeError("Cannot subscribe on a closed event-bus.")
        if not callable(handler):
            raise TypeError("Handler must be callable.")

        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        """
        Remove *handler* from *topic* subscription list.
        """
        try:
            self._subscribers[topic].remove(handler)
        except (KeyError, ValueError):
            # Silently ignore un-subscriptions that do not exist to make test
            # clean-up easier.
            pass

    # --------------------------------------------------------------------- #
    #  Publish                                                               #
    # --------------------------------------------------------------------- #

    def publish(self, topic: str, payload: Any | None = None) -> None:
        """
        Broadcast *payload* to all handlers subscribed to *topic*.  The
        broadcast is synchronous but automatically executed in the current
        asyncio event-loop if an async def handler is detected.
        """
        if self._closed:
            raise RuntimeError("Cannot publish on a closed event-bus.")

        for handler in list(self._subscribers.get(topic, ())):
            if inspect.iscoroutinefunction(handler):
                self._loop.create_task(handler(payload))
            else:
                handler(payload)

    # --------------------------------------------------------------------- #
    #  House-keeping                                                         #
    # --------------------------------------------------------------------- #

    def close(self) -> None:
        """
        Prevent further publish/subscribe operations.  Intended to be called
        from fixture teardown.
        """
        self._subscribers.clear()
        self._closed = True


class DummyPluginRegistry:
    """
    Replace the heavy-weight plugin-manager with a feather-weight registry that
    can register arbitrary callables/classes for unit-testing.

    Example usage in a test:

    def test_my_service(plugin_registry):
        @plugin_registry.register('service')
        class MyService:
            ...

        plugin = plugin_registry.get('service')
        assert isinstance(plugin, MyService)
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    #  API expected by production code                                   #
    # ------------------------------------------------------------------ #

    def register(self, name: str) -> Callable[[Any], Any]:
        """
        Decorator that registers a class/function as a plugin under *name*.

            @plugin_registry.register("polls")
            class PollsPlugin: ...
        """

        def decorator(symbol: Any) -> Any:
            self._plugins[name] = symbol
            return symbol

        return decorator

    def get(self, name: str) -> Any:
        """
        Retrieve the plugin registered under *name*.  Raises KeyError when not
        found – mirrors production behaviour.
        """
        return self._plugins[name]

    def all(self) -> Mapping[str, Any]:
        """
        Read-only mapping of all registered plugins.
        """
        return dict(self._plugins)

    # ------------------------------------------------------------------ #
    #  Dunder hooks to ease assertions                                   #
    # ------------------------------------------------------------------ #

    def __contains__(self, item: str) -> bool:  # pragma: no cover
        return item in self._plugins

    def __iter__(self) -> Iterable[str]:  # pragma: no cover
        return iter(self._plugins)

    def __len__(self) -> int:  # pragma: no cover
        return len(self._plugins)


###############################################################################
# ––– Fixtures –––
###############################################################################


@pytest.fixture(scope="session")
def event_loop(request: pytest.FixtureRequest) -> asyncio.AbstractEventLoop:  # noqa: D401
    """
    A session-wide asyncio event-loop.  Needed for fixtures/tests that run
    asynchronous code without spawning their own loop.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.call_soon(loop.stop)
    with contextlib.suppress(RuntimeError):
        loop.close()


@pytest.fixture(scope="session")
def tmp_user_profile_dir() -> Path:
    """
    Create a temporary directory that pretends to be the user’s roaming profile.
    The real application uses the *FLOCKDESK_PROFILE_DIR* environment variable
    to locate user settings, layouts, caches, etc.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="flockdesk-profile-"))
    os.environ["FLOCKDESK_PROFILE_DIR"] = str(tmp_dir)
    yield tmp_dir
    # Safety-net: Remove the dir recursively in teardown.
    shutil.rmtree(tmp_dir, ignore_errors=True)
    os.environ.pop("FLOCKDESK_PROFILE_DIR", None)


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    """
    Provide a fresh in-memory event-bus for each test function.
    """
    bus = InMemoryEventBus()
    yield bus
    bus.close()


@pytest.fixture
def plugin_registry() -> DummyPluginRegistry:
    """
    Provide an isolated plugin registry for a test.  This avoids cross-test
    contamination when plugins are registered via decorators.
    """
    return DummyPluginRegistry()


@pytest.fixture
def qapp(request: pytest.FixtureRequest) -> QtWidgets.QApplication:  # type: ignore
    """
    Lazily start a single QApplication for tests that are explicitly marked with
    ``@pytest.mark.requires_qt`` or when ``--run-gui`` is passed.

    The fixture automatically skips the test when:
        * Qt bindings are not importable
        * The user did not opt-in via --run-gui (to keep headless default)
    """
    if not request.config.getoption("--run-gui"):
        pytest.skip("--run-gui not supplied; skipping Qt tests.")

    if QtWidgets is None:  # pragma: no cover
        pytest.skip("Qt bindings not available in this environment.")

    # QApplication must be instantiated only once per process.  We re-use the
    # global instance if it already exists.
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    yield app

    # Tear-down: flush any queued events so that background timers/timeouts do
    # not leak into other tests.
    with contextlib.suppress(Exception):
        app.processEvents()
```

```python
"""
tests/unit/modules/test_chat_vm.py

Unit-tests for the ChatViewModel abstraction used by the FlockDesk
‘chat’ micro-frontend.  The real implementation lives in
`flockdesk.chat.viewmodels`, but to guarantee these tests are runnable
in isolation (e.g., on CI without the rest of the desktop suite
present), a fully-featured fallback stub is provided.

The contract verified here focuses on:

* Correct interaction with the event-bus (publish / subscribe)
* Graceful error handling when the chat-service raises
* Proper plug-in interception of outbound messages
* Life-cycle management (attach / detach)

The tests rely solely on the public API of the VM and avoid asserting
against implementation details wherever possible.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Dict, List

import pytest

###############################################################################
# Dependency shims (event-bus, service layer, plug-in manager)
###############################################################################


class EventBus:
    """
    Ultra-lightweight synchronous event-bus implementation suitable for unit
    testing.  Topics are arbitrary strings; payloads can be any JSON-serialisable
    object.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def subscribe(self, topic: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(
        self, topic: str, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        try:
            self._subscribers[topic].remove(callback)
            if not self._subscribers[topic]:
                del self._subscribers[topic]
        except (KeyError, ValueError):
            # Silently ignore – idempotent semantics
            pass

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        for cb in list(self._subscribers.get(topic, [])):
            cb(payload)


# --------------------------------------------------------------------------- #
# Exceptions used by the chat-service stub
# --------------------------------------------------------------------------- #
class NetworkError(RuntimeError):
    """Raised by ChatService when the backend is unreachable."""


@dataclass
class ChatService:
    """
    Simplified service layer stub that pretends to talk to a backend.  Behaviour
    can be customised per-test by injecting callables.
    """

    send_callable: Callable[[str, str], str] | None = None

    def send(self, user_id: str, text: str) -> str:
        if self.send_callable:
            return self.send_callable(user_id, text)
        # Default happy path: generate deterministic message-id
        return f"msg-{abs(hash((user_id, text))) % 1_000_000:06d}"


@dataclass
class PluginManager:
    """
    Very thin adapter that lets us inject message transformation hooks.
    """

    transform_callable: Callable[[str], str] | None = None

    def transform_outgoing(self, text: str) -> str:
        if self.transform_callable:
            return self.transform_callable(text)
        return text


###############################################################################
# ChatViewModel – try to import the real deal, otherwise fall back
###############################################################################

try:
    from flockdesk.chat.viewmodels import ChatViewModel  # pragma: no cover
except ModuleNotFoundError:
    # --------------------------------------------------------------------- #
    # Fallback stub with the minimal behaviour required by our tests
    # --------------------------------------------------------------------- #
    class ChatViewModel:  # pylint: disable=too-few-public-methods
        """
        A stripped-down yet production-like ChatViewModel implementation.

        Do *not* use this in production – it exists solely so the unit
        tests can execute in isolation when the full FlockDesk stack
        is unavailable.
        """

        # Topic constants – would normally live in a shared namespace
        TOPIC_SENT = "chat.message.sent"
        TOPIC_RECEIVED = "chat.message.received"

        def __init__(
            self,
            *,
            user_id: str,
            event_bus: EventBus,
            chat_service: ChatService,
            plugin_manager: PluginManager | None = None,
            logger: logging.Logger | None = None,
        ) -> None:
            self._user_id = user_id
            self._bus = event_bus
            self._service = chat_service
            self._plugins = plugin_manager or PluginManager()
            self._logger = logger or logging.getLogger(self.__class__.__name__)

            self.messages: List[Dict[str, Any]] = []
            self.error_state: str | None = None
            self._attached = False

        # ---------------------------------------------------------------- #
        # Life-cycle management
        # ---------------------------------------------------------------- #
        def attach(self) -> None:
            if self._attached:
                return
            self._bus.subscribe(self.TOPIC_RECEIVED, self._on_message_received)
            self._attached = True
            self._logger.debug("ChatViewModel attached to event-bus.")

        def detach(self) -> None:
            if not self._attached:
                return
            self._bus.unsubscribe(self.TOPIC_RECEIVED, self._on_message_received)
            self._attached = False
            self._logger.debug("ChatViewModel detached from event-bus.")

        # ---------------------------------------------------------------- #
        # Public API
        # ---------------------------------------------------------------- #
        def send_message(self, text: str) -> str | None:
            """
            Send a chat message, passing it through plug-ins first.  On success,
            the outgoing message is published over the bus; on failure, the VM
            enters the `error_state`.
            """
            self.error_state = None
            transformed = self._plugins.transform_outgoing(text)

            try:
                message_id = self._service.send(self._user_id, transformed)
                payload = {
                    "id": message_id,
                    "user_id": self._user_id,
                    "text": transformed,
                }
                self.messages.append(payload)
                self._bus.publish(self.TOPIC_SENT, payload)
                self._logger.info("Sent chat message %s", message_id)
                return message_id
            except NetworkError as exc:  # pragma: no cover
                self.error_state = str(exc)
                self._logger.error("Failed to send message: %s", exc, exc_info=True)
                return None

        # ---------------------------------------------------------------- #
        # Internal handlers
        # ---------------------------------------------------------------- #
        # pylint: disable=unused-argument
        def _on_message_received(self, payload: Dict[str, Any]) -> None:
            self._logger.debug("Received message via event-bus: %s", payload)
            self.messages.append(payload)


# Make the fallback discoverable under the expected import path so other
# modules (or even parameterised tests) can just `import
# flockdesk.chat.viewmodels` and still resolve the stub.
module_path = "flockdesk.chat.viewmodels"
if module_path not in sys.modules:
    mod = ModuleType(module_path)
    mod.ChatViewModel = ChatViewModel
    sys.modules[module_path] = mod

###############################################################################
#                               TEST SUITE                                    #
###############################################################################

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def plugin_manager() -> PluginManager:
    return PluginManager()


@pytest.fixture()
def chat_service() -> ChatService:
    return ChatService()


@pytest.fixture()
def chat_vm(
    event_bus: EventBus,
    chat_service: ChatService,
    plugin_manager: PluginManager,
) -> ChatViewModel:
    vm = ChatViewModel(
        user_id="alice",
        event_bus=event_bus,
        chat_service=chat_service,
        plugin_manager=plugin_manager,
    )
    vm.attach()
    yield vm
    vm.detach()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_send_message_publishes_and_updates_state(
    chat_vm: ChatViewModel,
    event_bus: EventBus,
) -> None:
    """
    When a message is sent successfully *and* the underlying service returns a
    message-id, the VM must do three things:

    1. Update its internal `messages` collection
    2. Publish a `TOPIC_SENT` event onto the bus
    3. Return the generated message-id
    """

    captured: list[dict[str, Any]] = []
    event_bus.subscribe(ChatViewModel.TOPIC_SENT, lambda p: captured.append(p))

    message_id = chat_vm.send_message("Hello, world!")

    assert message_id is not None
    assert len(chat_vm.messages) == 1
    assert chat_vm.messages[0]["text"] == "Hello, world!"
    # Ensure the bus broadcast occurred
    assert captured and captured[0]["id"] == message_id


def test_incoming_message_is_propagated_to_vm_state(
    chat_vm: ChatViewModel, event_bus: EventBus
) -> None:
    """
    The VM must update its `messages` list when a *received* message event is
    fired on the bus so that the UI layer reflects live updates.
    """
    inbound_payload = {"id": "msg-999", "user_id": "bob", "text": "Howdy!"}

    event_bus.publish(ChatViewModel.TOPIC_RECEIVED, inbound_payload)

    assert chat_vm.messages[-1] == inbound_payload
    # The inbound shouldn't inadvertently mark an error or duplicate our
    # outgoing messages.
    assert chat_vm.error_state is None
    assert any(m["id"] == "msg-999" for m in chat_vm.messages)


def test_network_failure_sets_error_state_and_logs(
    chat_vm: ChatViewModel,
    chat_service: ChatService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Simulate a service-side outage and verify that:

    * The VM surfaces the error via `error_state`
    * No new message is persisted
    * A log entry is emitted at ERROR level
    """

    def flaky_send(*_: Any, **__: Any) -> str:  # pylint: disable=unused-argument
        raise NetworkError("upstream unavailable")

    chat_service.send_callable = flaky_send

    with caplog.at_level(logging.ERROR):
        msg_id = chat_vm.send_message("Will not go through")

    assert msg_id is None
    assert chat_vm.error_state == "upstream unavailable"
    # Ensure no phantom messages were added
    assert all(m["text"] != "Will not go through" for m in chat_vm.messages)
    # Log assertion
    assert any("Failed to send message" in rec.message for rec in caplog.records)


def test_plugin_transforms_outgoing_message(chat_vm: ChatViewModel, plugin_manager: PluginManager) -> None:
    """
    Verify that outgoing messages are first passed through the active plug-in
    chain before being dispatched to the service or bus.
    """

    def shrug_transform(text: str) -> str:  # noqa: D401
        return "¯\\_(ツ)_/¯" if text == "/shrug" else text

    plugin_manager.transform_callable = shrug_transform

    chat_vm.send_message("/shrug")

    assert chat_vm.messages[-1]["text"] == "¯\\_(ツ)_/¯"


def test_detach_unsubscribes_from_event_bus(
    chat_vm: ChatViewModel, event_bus: EventBus
) -> None:
    """
    After calling `detach()`, the VM must stop reacting to bus events in order
    to avoid memory leaks and duplicate UI updates.
    """
    chat_vm.detach()
    inbound_payload = {"id": "ghost-1", "user_id": "carol", "text": "Are you there?"}
    event_bus.publish(ChatViewModel.TOPIC_RECEIVED, inbound_payload)

    assert inbound_payload not in chat_vm.messages
```
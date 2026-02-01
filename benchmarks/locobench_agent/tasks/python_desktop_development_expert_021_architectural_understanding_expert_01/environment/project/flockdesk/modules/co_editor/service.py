```python
"""
flockdesk.modules.co_editor.service
==================================

Collaborative editor *domain service* responsible for orchestrating multi-user
editing sessions.  The service listens to the internal event-bus, applies edit
operations, and re-broadcasts consolidated state updates to participants.

A deliberately simplified CRDT/OT implementation is used here; production
deployments would swap this module behind the same public façade.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Protocol,
    Set,
)

LOGGER = logging.getLogger("flockdesk.co_editor")

# ---------------------------------------------------------------------------#
# Event-bus abstraction
# ---------------------------------------------------------------------------#


class EventBus(Protocol):
    """
    Very small slice of the event-bus API that we depend on.
    """

    def subscribe(
        self,
        topic: str,
        handler: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        ...

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        ...


# ---------------------------------------------------------------------------#
# Events
# ---------------------------------------------------------------------------#


class Topics:
    DOC_OPEN = "co_editor.document.open"
    DOC_CLOSE = "co_editor.document.close"
    DOC_OPERATION = "co_editor.document.operation"  # User input
    DOC_UPDATE = "co_editor.document.update"  # Broadcast to clients
    INTERNAL_ERROR = "co_editor.error"


# ---------------------------------------------------------------------------#
# Domain models
# ---------------------------------------------------------------------------#


@dataclass(slots=True)
class EditOperation:
    """
    Simplified representation of an operation the user performs.
    """

    user_id: str
    position: int
    delete_count: int
    insert_text: str
    timestamp: float = field(default_factory=lambda: time.time())


@dataclass(slots=True)
class DocumentSession:
    """
    In-memory, per-document session state.
    """

    doc_id: str
    content: str = ""
    participants: Set[str] = field(default_factory=set)
    revision: int = 0

    # Concurrency primitives (not serialised)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _queue: asyncio.Queue[EditOperation] = field(
        default_factory=asyncio.Queue, repr=False
    )


# ---------------------------------------------------------------------------#
# Plugin system
# ---------------------------------------------------------------------------#


class OperationPlugin(Protocol):
    """
    Plugins can inspect/transform operations before they are applied.
    """

    async def before_apply(
        self, session: DocumentSession, operation: EditOperation
    ) -> Optional[EditOperation]:
        """
        Optionally mutate or veto an operation.  Returning ``None`` cancels
        the operation altogether.
        """
        ...

    async def after_apply(
        self, session: DocumentSession, operation: EditOperation
    ) -> None:
        """
        Called once the operation has been applied and the document state
        has advanced.
        """
        ...


# ---------------------------------------------------------------------------#
# Helper functions
# ---------------------------------------------------------------------------#


def _apply_operation(content: str, op: EditOperation) -> str:
    """
    Extremely naïve text-patch function.  Assumes UTF-8 safe slicing.
    """
    if op.position < 0 or op.position > len(content):
        raise ValueError("Operation position outside document length")

    if op.delete_count < 0 or op.position + op.delete_count > len(content):
        raise ValueError("Delete count is invalid")

    before = content[: op.position]
    after = content[op.position + op.delete_count :]
    return before + op.insert_text + after


# ---------------------------------------------------------------------------#
# Service implementation
# ---------------------------------------------------------------------------#


class CoEditorService:
    """
    Public façade—one instance per *process*.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._sessions: Dict[str, DocumentSession] = {}
        self._plugins: List[OperationPlugin] = []
        self._tasks: Set[asyncio.Task[None]] = set()
        self._shutdown = asyncio.Event()

        self._subscribe()

    # ------------------------------- API ---------------------------------- #

    def register_plugin(self, plugin: OperationPlugin) -> None:
        """
        Dynamically extend service behaviour (spell-checker, analytics,
        operational-transform adapters...).  Can be called at runtime.
        """
        self._plugins.append(plugin)
        LOGGER.info("Plugin registered: %s", plugin.__class__.__name__)

    async def shutdown(self) -> None:
        """
        Initiate graceful shutdown; wait for all worker tasks to finish.
        """
        self._shutdown.set()
        for t in list(self._tasks):
            t.cancel("service shutdown")
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ----------------------------- Internals ------------------------------ #

    def _subscribe(self) -> None:
        """
        Hook event handlers into the event-bus.
        """
        self._bus.subscribe(Topics.DOC_OPEN, self._on_document_open)
        self._bus.subscribe(Topics.DOC_CLOSE, self._on_document_close)
        self._bus.subscribe(Topics.DOC_OPERATION, self._on_document_operation)
        LOGGER.debug("CoEditorService subscribed to event topics.")

    # ------------------------- Event Handlers ----------------------------- #

    async def _on_document_open(
        self, topic: str, payload: Dict[str, Any]
    ) -> None:
        doc_id = payload["doc_id"]
        user_id = payload["user_id"]
        session = self._sessions.setdefault(doc_id, DocumentSession(doc_id))
        session.participants.add(user_id)
        LOGGER.debug("User %s opened document %s", user_id, doc_id)

    async def _on_document_close(
        self, topic: str, payload: Dict[str, Any]
    ) -> None:
        doc_id = payload["doc_id"]
        user_id = payload["user_id"]

        session = self._sessions.get(doc_id)
        if not session:
            return

        session.participants.discard(user_id)
        LOGGER.debug("User %s closed document %s", user_id, doc_id)

        # Clean up session if empty
        if not session.participants:
            self._sessions.pop(doc_id, None)
            LOGGER.info("Session for document %s terminated.", doc_id)

    async def _on_document_operation(
        self, topic: str, payload: Dict[str, Any]
    ) -> None:
        """
        Receives raw user operations, queues them for serial processing.
        """
        try:
            op = EditOperation(
                user_id=payload["user_id"],
                position=payload["position"],
                delete_count=payload["delete_count"],
                insert_text=payload["insert_text"],
            )
        except (KeyError, TypeError) as exc:
            LOGGER.error("Invalid operation payload: %s (%s)", payload, exc)
            return

        doc_id = payload["doc_id"]
        session = self._sessions.get(doc_id)
        if not session:
            # Silently ignore edits to non-opened document
            LOGGER.warning(
                "Received operation for unknown doc %s from %s.",
                doc_id,
                op.user_id,
            )
            return

        await session._queue.put(op)

        # Spawn a worker if not already running
        if not getattr(session, "_worker_running", False):
            task = asyncio.create_task(
                self._process_queue(session), name=f"coedit-{doc_id}"
            )
            session._worker_running = True  # type: ignore[attr-defined]
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    # ----------------------- Operation Processing ------------------------- #

    async def _process_queue(self, session: DocumentSession) -> None:
        """
        Dedicated background task per document that sequentially applies queued
        operations to guarantee total ordering.
        """
        while not self._shutdown.is_set():
            try:
                op: EditOperation = await asyncio.wait_for(
                    session._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                # Periodically check if we should shut down
                continue

            try:
                await self._apply_operation(session, op)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Failed to apply op: %s", exc, exc_info=True)
                await self._bus.publish(
                    Topics.INTERNAL_ERROR,
                    {
                        "service": "co_editor",
                        "doc_id": session.doc_id,
                        "error": str(exc),
                    },
                )

    async def _apply_operation(
        self, session: DocumentSession, op: EditOperation
    ) -> None:
        """
        Serialised part—the only coroutine allowed to mutate session state.
        """
        async with session._lock:
            # Execute *before* hooks
            for plugin in self._plugins:
                try:
                    new_op = await plugin.before_apply(session, op)
                    if new_op is None:
                        LOGGER.debug("Operation vetoed by plugin: %s", plugin)
                        return  # Operation cancelled
                    op = new_op
                except Exception:  # noqa: BLE001
                    LOGGER.exception(
                        "Plugin %s failed in before_apply", plugin
                    )

            # Apply transformation
            new_content = _apply_operation(session.content, op)
            session.revision += 1
            session.content = new_content

            # Emit update
            await self._bus.publish(
                Topics.DOC_UPDATE,
                {
                    "doc_id": session.doc_id,
                    "user_id": op.user_id,
                    "revision": session.revision,
                    "content": session.content,
                    "timestamp": op.timestamp,
                },
            )
            LOGGER.debug(
                "Applied op on doc %s rev %s by user %s",
                session.doc_id,
                session.revision,
                op.user_id,
            )

            # Execute *after* hooks
            for plugin in self._plugins:
                try:
                    await plugin.after_apply(session, op)
                except Exception:  # noqa: BLE001
                    LOGGER.exception(
                        "Plugin %s failed in after_apply", plugin
                    )
```
```python
"""
ledgerquest.engine.ai.behavior_tree
==================================

A lightweight yet production-ready Behavior Tree implementation tailored for
serverless execution.  Nodes are **pure** (stateless) and therefore fully
serialisable; transient execution data (RUNNING node indices, counters, etc.)
is stored in, and restored from, the *blackboard* so that any Lambda invocation
can continue where the previous one stopped.

This design makes it possible to:

    • Run gigantic AI simulations across thousands of concurrent players.
    • Persist AI state in DynamoDB or Redis between ticks.
    • Inject domain-specific tasks at runtime without modifying the engine.

The implementation purposefully avoids performance micro-optimisations in
favour of readability and robustness—serverless invocations typically last
< 16 ms, rendering micro-benchmarks negligible compared to cold-start latency.

Author: LedgerQuest Engine Team
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from types import MappingProxyType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

# --------------------------------------------------------------------------- #
# Configuration & Logging                                                     #
# --------------------------------------------------------------------------- #

logger = logging.getLogger("ledgerquest.ai.behavior_tree")
if not logger.handlers:
    # A sane default configuration for stand-alone execution
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #


class BehaviorTreeError(Exception):
    """Base-class for Behaviour Tree errors."""


class TaskRegistrationError(BehaviorTreeError):
    """Raised when trying to register an invalid task callable."""


class TaskExecutionError(BehaviorTreeError):
    """Raised when a task callable raises unexpectedly."""


# --------------------------------------------------------------------------- #
# Node Status Enum                                                            #
# --------------------------------------------------------------------------- #


class Status(Enum):
    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()


# --------------------------------------------------------------------------- #
# Blackboard                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class Blackboard:
    """
    A *very* light dict-like container that survives between ticks.

    Developers can safely attach arbitrary JSON-serialisable data needed by
    their Behaviour Tree (BT).  Internal BT state is namespaced under the
    reserved key `_bt_internal`.
    """

    _data: Dict[str, Any] = field(default_factory=dict)

    # ---- Public helpers ---------------------------------------------------- #

    def get(self, key: str, default: Any = None) -> Any:  # noqa: A003
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:  # noqa: A003
        self._data[key] = value

    def as_read_only(self) -> MappingProxyType:
        return MappingProxyType(self._data)

    # ---- Internal (BT) helpers -------------------------------------------- #

    def _ns(self) -> Dict[str, Any]:
        # Ensure namespace exists
        return self._data.setdefault("_bt_internal", {})

    def save_node_state(self, node_uid: str, state: Any) -> None:
        self._ns()[node_uid] = state

    def load_node_state(self, node_uid: str, default: Any = None) -> Any:
        return self._ns().get(node_uid, default)


# --------------------------------------------------------------------------- #
# Behavior Node Base Class                                                    #
# --------------------------------------------------------------------------- #


@dataclass
class Node(ABC):
    """
    Base-class for all Behaviour Tree nodes.

    Each node is uniquely identified by a *stable* uid so that it can persist
    its local execution state on the blackboard even after hot-code reloads.
    """

    name: str
    uid: Optional[str] = field(default=None, init=False)

    def __post_init__(self) -> None:
        # Stable uid derived from module + class + name
        self.uid = f"{self.__class__.__module__}.{self.__class__.__qualname__}:{self.name}"

    @abstractmethod
    async def tick(self, blackboard: Blackboard) -> Status:
        """
        Runs one tick of the node.

        Returns
        -------
        Status
            SUCCESS | FAILURE | RUNNING
        """

    # Helper: convenience for synchronous tasks
    def _wrap_sync(
        self, fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Awaitable[Any]:
        loop = asyncio.get_event_loop()
        return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


# --------------------------------------------------------------------------- #
# Composite Nodes                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class Composite(Node):
    children: Sequence[Node]

    def __post_init__(self) -> None:
        if not self.children:
            raise ValueError(f"Composite node '{self.name}' must have children.")
        super().__post_init__()


class Sequence(Composite):
    """
    Executes children in order.  Fails fast.  Returns SUCCESS when all succeed.
    """

    async def tick(self, blackboard: Blackboard) -> Status:
        cursor: int = blackboard.load_node_state(self.uid, 0)
        while cursor < len(self.children):
            status = await self.children[cursor].tick(blackboard)
            if status == Status.RUNNING:
                blackboard.save_node_state(self.uid, cursor)
                return Status.RUNNING
            if status == Status.FAILURE:
                blackboard.save_node_state(self.uid, 0)
                return Status.FAILURE
            cursor += 1
        # Completed
        blackboard.save_node_state(self.uid, 0)
        return Status.SUCCESS


class Selector(Composite):
    """
    Executes children until one succeeds.  Returns FAILURE when all fail.
    """

    async def tick(self, blackboard: Blackboard) -> Status:
        cursor: int = blackboard.load_node_state(self.uid, 0)
        while cursor < len(self.children):
            status = await self.children[cursor].tick(blackboard)
            if status == Status.RUNNING:
                blackboard.save_node_state(self.uid, cursor)
                return Status.RUNNING
            if status == Status.SUCCESS:
                blackboard.save_node_state(self.uid, 0)
                return Status.SUCCESS
            cursor += 1
        blackboard.save_node_state(self.uid, 0)
        return Status.FAILURE


class Parallel(Composite):
    """
    Runs children simultaneously (Fire & Forget).

    Success policy:
        • success_threshold <= number_of_successful_children → SUCCESS
    Failure policy:
        • failures  > (len(children) - success_threshold)   → FAILURE
    Otherwise:
        • RUNNING
    """

    success_threshold: int = 1  # at least N successes for overall SUCCESS

    async def tick(self, blackboard: Blackboard) -> Status:
        tasks = [asyncio.create_task(c.tick(blackboard)) for c in self.children]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        successes = sum(1 for r in results if r == Status.SUCCESS)
        failures = sum(1 for r in results if r == Status.FAILURE)

        if successes >= self.success_threshold:
            return Status.SUCCESS

        if failures > (len(self.children) - self.success_threshold):
            return Status.FAILURE

        return Status.RUNNING


# --------------------------------------------------------------------------- #
# Decorators                                                                  #
# --------------------------------------------------------------------------- #


@dataclass
class Decorator(Node):
    child: Node


class Inverter(Decorator):
    async def tick(self, blackboard: Blackboard) -> Status:
        status = await self.child.tick(blackboard)
        if status == Status.SUCCESS:
            return Status.FAILURE
        if status == Status.FAILURE:
            return Status.SUCCESS
        return status  # RUNNING passes through


class Repeater(Decorator):
    """
    Repeats its child N times.  When `max_repetitions` is None, repeats forever.

    When the child returns RUNNING, the repeater immediately yields RUNNING.
    """

    max_repetitions: Optional[int] = None

    async def tick(self, blackboard: Blackboard) -> Status:
        counter = blackboard.load_node_state(self.uid, 0)
        while self.max_repetitions is None or counter < self.max_repetitions:
            status = await self.child.tick(blackboard)
            if status == Status.RUNNING:
                blackboard.save_node_state(self.uid, counter)
                return Status.RUNNING
            if status == Status.FAILURE:
                blackboard.save_node_state(self.uid, 0)
                return Status.FAILURE
            counter += 1
        blackboard.save_node_state(self.uid, 0)
        return Status.SUCCESS


# --------------------------------------------------------------------------- #
# Task / Leaf                                                                 #
# --------------------------------------------------------------------------- #


TaskCallable = Union[
    Callable[[Blackboard], Union[Status, Awaitable[Status]]],
    Callable[[MutableMapping[str, Any]], Union[Status, Awaitable[Status]]],
]


@dataclass
class Task(Node):
    """
    Leaf node that wraps an arbitrary callable.

    The callable must accept one positional argument: the blackboard (dict-like)
    or :class:`Blackboard` instance.  It must return a :class:`Status` or an
    *awaitable* that resolves to :class:`Status`.
    """

    fn: TaskCallable

    def __post_init__(self) -> None:
        if not callable(self.fn):
            raise TaskRegistrationError("Task callable is not callable.")
        sig = inspect.signature(self.fn)
        if len(sig.parameters) != 1:
            raise TaskRegistrationError(
                "Task callable must take exactly one positional argument (blackboard)."
            )
        super().__post_init__()

    async def tick(self, blackboard: Blackboard) -> Status:  # type: ignore[override]
        try:
            result = self.fn(blackboard)  # type: ignore[arg-type]
            if inspect.isawaitable(result):
                result = await result  # type: ignore[assignment]
            if not isinstance(result, Status):
                raise TaskExecutionError(
                    f"Task '{self.name}' returned invalid Status: {result!r}"
                )
            return result
        except Exception as exc:
            logger.exception("Unhandled exception in task '%s': %s", self.name, exc)
            return Status.FAILURE


# --------------------------------------------------------------------------- #
# Behavior Tree Container                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class BehaviorTree:
    """
    Orchestrates ticks and provides (de)serialisation helpers so that external
    systems can persist a player-specific BT between Lambda invocations.
    """

    root: Node
    blackboard: Blackboard = field(default_factory=Blackboard)
    time_budget_ms: Optional[int] = None  # Optional soft budget

    # ---- Runtime API ------------------------------------------------------- #

    async def tick(self) -> Status:
        """
        Runs one tick of the tree.

        Terminates early when `time_budget_ms` is exceeded to avoid Lambda
        timeouts.  Early termination yields Status.RUNNING.
        """
        if self.time_budget_ms is not None:
            deadline = (time.time() * 1000) + self.time_budget_ms
        else:
            deadline = None

        # We treat the *root* as a loop because we may need to exit early.
        # Most use-cases will just execute it once anyway.
        while True:
            current_status = await self.root.tick(self.blackboard)

            if current_status != Status.RUNNING:
                return current_status

            if deadline and (time.time() * 1000) > deadline:
                logger.warning(
                    "BehaviorTree exceeded time budget (%d ms).",
                    self.time_budget_ms,
                )
                return Status.RUNNING

    # ---- Persistence ------------------------------------------------------- #

    def to_json(self) -> str:
        """
        Serialises the blackboard to JSON for storage in DynamoDB / Redis.

        Note: Node *definitions* (structure) are **not** serialised; they are
        code, not data.  Only run-time state is persisted.
        """
        return json.dumps(self.blackboard._data)

    @classmethod
    def from_json(cls, root: Node, json_blob: str) -> "BehaviorTree":
        """
        Restores a BT from JSON.  The caller provides the *same* root node
        structure (usually from loaded Python code or data-driven builder).
        """
        data = json.loads(json_blob) if json_blob else {}
        return cls(root=root, blackboard=Blackboard(data))

    # ---- Convenience ------------------------------------------------------- #

    async def tick_until_done(self, max_iterations: int = 1000) -> Status:
        """
        Helper mainly intended for unit tests: keep ticking until the tree
        resolves to SUCCESS/FAILURE or iteration limit is reached.
        """
        for _ in range(max_iterations):
            status = await self.tick()
            if status != Status.RUNNING:
                return status
        raise TimeoutError(
            f"BehaviorTree did not finish within {max_iterations} iterations."
        )

    # --------------------------------------------------------------------- #
    # Sync wrapper so that synchronous flows can still use the async BT.
    # --------------------------------------------------------------------- #

    def tick_sync(self) -> Status:
        return asyncio.run(self.tick())

    def tick_until_done_sync(self, max_iterations: int = 1000) -> Status:
        return asyncio.run(self.tick_until_done(max_iterations=max_iterations))


# --------------------------------------------------------------------------- #
# Example: Built-in Tasks                                                     #
# --------------------------------------------------------------------------- #

# A minimal built-in task library can be extended by external modules
def succeed(_: Blackboard) -> Status:  # noqa: D401
    """Always returns SUCCESS."""
    return Status.SUCCESS


def fail(_: Blackboard) -> Status:
    """Always returns FAILURE."""
    return Status.FAILURE


def wait_ms(duration: int) -> TaskCallable:
    """
    Returns a task that waits for *duration* milliseconds and then succeeds.

    Demonstrates how to use the blackboard to keep track of elapsed time across
    serverless invocations.
    """

    async def _wait(bb: Blackboard) -> Status:
        start_ts = bb.load_node_state(f"_wait:{duration}", None)
        now = int(time.time() * 1000)

        if start_ts is None:
            bb.save_node_state(f"_wait:{duration}", now)
            return Status.RUNNING

        if now - start_ts >= duration:
            bb.save_node_state(f"_wait:{duration}", None)
            return Status.SUCCESS

        return Status.RUNNING

    return _wait


# --------------------------------------------------------------------------- #
# Unit Test (can be executed via `python -m ledgerquest.engine.ai.behavior_tree`)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    async def _demo() -> None:
        root = Sequence(
            name="root",
            children=[
                Task(name="say_hello", fn=lambda bb: logger.info("Hello!") or Status.SUCCESS),
                Task(name="wait", fn=wait_ms(500)),
                Selector(
                    name="foo",
                    children=[
                        Task(name="always_fail", fn=fail),
                        Task(name="always_succeed", fn=succeed),
                    ],
                ),
            ],
        )

        bt = BehaviorTree(root=root, time_budget_ms=2000)

        status = await bt.tick_until_done()
        logger.info("Behavior finished with status: %s", status)

    asyncio.run(_demo())
```
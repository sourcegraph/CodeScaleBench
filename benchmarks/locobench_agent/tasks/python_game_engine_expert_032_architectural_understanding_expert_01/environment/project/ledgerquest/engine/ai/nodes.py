```python
"""
ledgerquest.engine.ai.nodes
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Behavior–tree nodes and helpers used by LedgerQuest’s server-less AI subsystem.
The implementation is **async-first** to play nicely with AWS Lambda / Step-
Functions, but still works in traditional, synchronous game-loops by running
`asyncio.run(node.tick(...))`.

Key features
------------
* Fully typed, PEP-8 compliant code
* Safe, pluggable node-registry for dynamic loading from JSON / YAML
* Robust error handling and structured logging
* Decorator, Composite and Leaf node implementations
* Minimal but useful Blackboard abstraction
"""

from __future__ import annotations

import abc
import asyncio
import importlib
import inspect
import json
import logging
import sys
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from types import ModuleType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Type,
)

__all__ = [
    "NodeStatus",
    "Blackboard",
    "BTError",
    "Node",
    "CompositeNode",
    "SequenceNode",
    "SelectorNode",
    "DecoratorNode",
    "InverterNode",
    "RepeaterNode",
    "ConditionNode",
    "ActionNode",
    "NodeFactory",
]


logger = logging.getLogger("ledgerquest.ai")
logger.setLevel(logging.INFO)


class NodeStatus(Enum):
    """
    The result of ticking a node.

    SUCCESS  – The node completed successfully.
    FAILURE  – The node failed and will not be re-entered until the parent restarts.
    RUNNING  – The node is still active and should be ticked again on the next pass.
    """

    SUCCESS = auto()
    FAILURE = auto()
    RUNNING = auto()


class BTError(RuntimeError):
    """Generic Behaviour-Tree error."""

    def __init__(self, message: str, *, node_id: Optional[str] = None) -> None:
        super().__init__(message)
        self.node_id = node_id


class Blackboard(MutableMapping[str, Any]):
    """
    A very small blackboard implementation.

    In production we often back this with DynamoDB / Redis, but for the purpose
    of local unit-tests a dict-like object is sufficient.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Optional[Mapping[str, Any]] = None) -> None:
        self._data: Dict[str, Any] = dict(data or {})

    # --- MutableMapping protocol -------------------------------------------------

    def __getitem__(self, key: str) -> Any:  # noqa: D105
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:  # noqa: D105
        self._data[key] = value

    def __delitem__(self, key: str) -> None:  # noqa: D105
        del self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    # --------------------------------------------------------------------------- #

    def as_dict(self) -> Dict[str, Any]:
        """Return a shallow copy of the underlying data."""
        return dict(self._data)


@dataclass
class Node(abc.ABC):
    """
    Base-class for all behaviour tree nodes.

    Sub-classes should override :meth:`_tick` to implement custom logic.
    """

    name: str
    config: Dict[str, Any] = field(default_factory=dict)
    children: List["Node"] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    parent: Optional["Node"] = field(default=None, repr=False, compare=False)

    # Non-serialisable runtime fields
    _logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("ledgerquest.ai"), init=False, repr=False
    )

    # --------------------------------------------------------------------- API #

    async def tick(self, board: Blackboard) -> NodeStatus:
        """
        Entry-point used by the engine/game-loop.

        Handles logging and exception safety around the overriding `_tick`
        method. Always returns a valid NodeStatus and never raises.
        """
        try:
            self._logger.debug("Tick %s (%s)", self.name, self.id)
            result: NodeStatus = await self._tick(board)
            assert isinstance(
                result, NodeStatus
            ), f"_tick must return NodeStatus, got {result!r}"
            return result
        except Exception as exc:  # noqa: BLE001
            self._logger.error(
                "Behaviour-tree node '%s' failed: %s\n%s",
                self.name,
                exc,
                traceback.format_exc(),
            )
            # Decide here whether to surface the error. We convert to FAILURE
            # allowing the tree to continue.
            return NodeStatus.FAILURE

    # ----------------------------------------------------------------- Helpers #

    def add_child(self, child: "Node") -> "Node":
        """Attach a child node and return self for chaining."""
        child.parent = self
        self.children.append(child)
        return self

    # --------------------------------------------------------- Abstract internals #

    @abc.abstractmethod
    async def _tick(self, board: Blackboard) -> NodeStatus:
        """Actual node implementation (async)."""
        raise NotImplementedError

    # ----------------------------------------------------------------- Debugging #

    def visualise(self, depth: int = 0) -> str:
        """Return an ASCII representation of the subtree."""
        indent = "  " * depth
        lines = [f"{indent}{self.__class__.__name__}({self.name})"]
        for child in self.children:
            lines.append(child.visualise(depth + 1))
        return "\n".join(lines)

    # ------------------------------------------------------------ Serialisation #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict for storage / transport."""
        return {
            "type": f"{self.__class__.__module__}:{self.__class__.__name__}",
            "name": self.name,
            "id": self.id,
            "config": self.config,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Node":
        """Deserialise a node tree from a dict."""
        node_cls = NodeFactory.resolve(data["type"])
        node = node_cls(name=data["name"], config=data["config"])
        node.id = data["id"]
        for child_cfg in data.get("children", []):
            node.add_child(Node.from_dict(child_cfg))
        return node


# --------------------------------------------------------------------------- #
# Composite Nodes
# --------------------------------------------------------------------------- #


class CompositeNode(Node):
    """Base-class for nodes that manage multiple children."""

    def __post_init__(self) -> None:
        if not self.children:
            raise BTError(f"{self.name}: Composite node requires at least one child.")


class SequenceNode(CompositeNode):
    """
    Runs children in order until one fails or is still running.

    Equivalent to the logical **AND** of its children.
    """

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        for child in self.children:
            status = await child.tick(board)
            if status is NodeStatus.FAILURE:
                return NodeStatus.FAILURE
            if status is NodeStatus.RUNNING:
                return NodeStatus.RUNNING
        return NodeStatus.SUCCESS


class SelectorNode(CompositeNode):
    """
    Runs children in order until one succeeds or is still running.

    Equivalent to the logical **OR** of its children.
    """

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        for child in self.children:
            status = await child.tick(board)
            if status is NodeStatus.SUCCESS:
                return NodeStatus.SUCCESS
            if status is NodeStatus.RUNNING:
                return NodeStatus.RUNNING
        return NodeStatus.FAILURE


# --------------------------------------------------------------------------- #
# Decorator Nodes
# --------------------------------------------------------------------------- #


class DecoratorNode(Node):
    """Base-class that wraps exactly one child."""

    def __post_init__(self) -> None:
        if len(self.children) != 1:
            raise BTError(f"{self.name}: Decorator node requires exactly one child.")

    @property
    def child(self) -> Node:
        if not self.children:
            raise BTError(f"{self.name}: Decorator has no child attached.")
        return self.children[0]


class InverterNode(DecoratorNode):
    """Flips SUCCESS/FAILURE of the child."""

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        status = await self.child.tick(board)
        if status is NodeStatus.SUCCESS:
            return NodeStatus.FAILURE
        if status is NodeStatus.FAILURE:
            return NodeStatus.SUCCESS
        return status  # RUNNING remains unchanged


class RepeaterNode(DecoratorNode):
    """Repeats child up to `max_loops` times, or indefinitely if None."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self._max_loops: Optional[int] = self.config.get("max_loops")
        self._counter: int = 0

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        if self._max_loops is not None and self._counter >= self._max_loops:
            return NodeStatus.SUCCESS

        status = await self.child.tick(board)

        if status in (NodeStatus.SUCCESS, NodeStatus.FAILURE):
            self._counter += 1
            # Force restart if we still have loops remaining
            if self._max_loops is None or self._counter < self._max_loops:
                return NodeStatus.RUNNING
        return status


# --------------------------------------------------------------------------- #
# Leaf Nodes – Conditions & Actions
# --------------------------------------------------------------------------- #


class ConditionNode(Node):
    """
    Evaluates a configurable Python callable to decide SUCCESS / FAILURE.

    config:
        callable: dotted-path string or a direct reference
        args: list of positional args (optional)
        kwargs: dict of keyword args (optional)
    """

    def __post_init__(self) -> None:
        self._callable: Callable[..., bool] = _import_callable(self.config["callable"])
        self._args: Sequence[Any] = self.config.get("args", [])
        self._kwargs: Mapping[str, Any] = self.config.get("kwargs", {})

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        sig = self._callable  # rename for brevity
        try:
            if inspect.iscoroutinefunction(sig):
                result: bool = await sig(board, *self._args, **self._kwargs)
            else:
                # Execute potentially blocking call in threadpool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, sig, board, *self._args, **self._kwargs
                )
            return NodeStatus.SUCCESS if result else NodeStatus.FAILURE
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Condition '%s' raised: %s", self.name, exc)
            return NodeStatus.FAILURE


class ActionNode(Node):
    """
    Executes a Python callable that returns NodeStatus.

    config:
        callable: dotted-path string or direct reference
        args / kwargs: forwarded
        run_in_executor: bool – offload to threadpool even if blocking (default False)
    """

    def __post_init__(self) -> None:
        self._callable: Callable[..., Awaitable[NodeStatus] | NodeStatus] = _import_callable(
            self.config["callable"]
        )
        self._args: Sequence[Any] = self.config.get("args", [])
        self._kwargs: Mapping[str, Any] = self.config.get("kwargs", {})
        self._run_in_executor: bool = bool(self.config.get("run_in_executor", False))

    async def _tick(self, board: Blackboard) -> NodeStatus:  # noqa: D401
        cb = self._callable
        try:
            if inspect.iscoroutinefunction(cb):
                return await cb(board, *self._args, **self._kwargs)

            if self._run_in_executor:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, cb, board, *self._args, **self._kwargs
                )

            return cb(board, *self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Action '%s' raised: %s", self.name, exc)
            return NodeStatus.FAILURE


# --------------------------------------------------------------------------- #
# Node Factory / Registry
# --------------------------------------------------------------------------- #


class NodeFactory:
    """
    Dynamic loader for node classes (`module:ClassName`).

    Custom nodes can be registered using :meth:`register`.
    """

    _registry: Dict[str, Type[Node]] = {}

    @classmethod
    def register(cls, node_cls: Type[Node]) -> None:
        key = f"{node_cls.__module__}:{node_cls.__name__}"
        cls._registry[key] = node_cls
        logger.debug("Registered BT node: %s", key)

    @classmethod
    def resolve(cls, dotted: str) -> Type[Node]:
        """
        Return a node class from dotted-path.

        Looks in the registry first, otherwise imports the module on-demand.
        """
        if dotted in cls._registry:
            return cls._registry[dotted]

        try:
            mod_name, _, attr = dotted.partition(":")
            module: ModuleType = importlib.import_module(mod_name)
            node_cls = getattr(module, attr)
            if not issubclass(node_cls, Node):
                raise BTError(f"{dotted} is not a Node subclass")
            # Cache for next time
            cls.register(node_cls)
            return node_cls
        except (ImportError, AttributeError) as exc:  # noqa: BLE001
            raise BTError(f"Unable to resolve node '{dotted}': {exc}") from exc

    @classmethod
    def from_json(cls, payload: str) -> Node:
        """Build a node tree from a JSON string."""
        cfg = json.loads(payload)
        return Node.from_dict(cfg)

    @classmethod
    def to_json(cls, node: Node, *, indent: int = 2) -> str:
        """Serialise a node tree into JSON."""
        return json.dumps(node.to_dict(), indent=indent)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _import_callable(dotted_or_obj: Any) -> Callable[..., Any]:
    """
    Import a callable from dotted path or verify object is callable.
    """
    if callable(dotted_or_obj):
        return dotted_or_obj  # Already a reference
    if not isinstance(dotted_or_obj, str):
        raise BTError(f"Expected dotted path or callable, got {type(dotted_or_obj)}")

    modulename, _, attr = dotted_or_obj.partition(":")
    if not attr:
        raise BTError(f"Invalid dotted path '{dotted_or_obj}', expected 'module:attr'")

    try:
        module = importlib.import_module(modulename)
        cb = getattr(module, attr)
    except (ImportError, AttributeError) as exc:  # noqa: BLE001
        raise BTError(f"Failed to import '{dotted_or_obj}': {exc}") from exc

    if not callable(cb):
        raise BTError(f"Imported object '{dotted_or_obj}' is not callable")
    return cb


# --------------------------------------------------------------------------- #
# Auto-register built-ins
# --------------------------------------------------------------------------- #

for _cls in (
    SequenceNode,
    SelectorNode,
    InverterNode,
    RepeaterNode,
    ConditionNode,
    ActionNode,
):
    NodeFactory.register(_cls)

# --------------------------------------------------------------------------- #
# If run as a script, demonstrate simple behaviour
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    async def _demo() -> None:
        """Quick sanity check when running `python -m ledgerquest.engine.ai.nodes`"""

        # Dummy condition / action
        async def is_market_open(board: Blackboard) -> bool:
            return board.get("market_open", False)

        def place_order(board: Blackboard) -> NodeStatus:
            logger.info("Placing virtual order...")
            board["orders"] = board.get("orders", 0) + 1
            return NodeStatus.SUCCESS

        # Build tree programmatically
        root = SelectorNode(name="RootSelector")
        root.add_child(
            SequenceNode(name="TradeIfOpen")
            .add_child(ConditionNode(name="MarketOpen?", config={"callable": is_market_open}))
            .add_child(ActionNode(name="PlaceOrder", config={"callable": place_order}))
        )
        root.add_child(ActionNode(name="Idle", config={"callable": lambda *_: NodeStatus.SUCCESS}))

        print(root.visualise())

        board = Blackboard({"market_open": True})
        status = await root.tick(board)
        print("First tick:", status, board.as_dict())

        board["market_open"] = False
        status = await root.tick(board)
        print("Second tick:", status, board.as_dict())

    asyncio.run(_demo())
```
```python
"""
ledgerquest.engine.ai
~~~~~~~~~~~~~~~~~~~~~

Public façade for LedgerQuest’s AI subsystem.

This module bundles together a minimal but production-grade behaviour-tree
framework, a plugin/registry mechanism, and thin adapters for invoking
long-running or resource-intensive AI jobs through AWS Step Functions.  It is
*not* opinionated about how your game loop is executed (in LedgerQuest that
responsibility lives in a Step Functions workflow), but it does provide pure
Python primitives that can be called synchronously inside a Lambda *or* from
a local test harness.

Typical usage
-------------

>>> from ledgerquest.engine.ai import (
...     BehaviorTree, Sequence, Selector, Action, registry
... )
>>>
>>> def is_hungry(bb): ...
>>> def eat(bb): ...
>>>
>>> tree = BehaviorTree(
...     Sequence(
...         Action(is_hungry),
...         Action(eat),
...     )
... )
>>> registry.register_tree("goblin.ai.eat", tree)
>>> result = registry.run("goblin.ai.eat", {"energy": 25})
>>> print(result)
NodeStatus.SUCCESS
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import uuid
from enum import Enum
from types import ModuleType
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    MutableMapping,
    Optional,
    Union,
)

try:  # boto3 is only required for StepFunction actions.
    import boto3

    _boto3_available = True
except ModuleNotFoundError:  # pragma: no cover
    _boto3_available = False  # Still allow everything else to work.

# --------------------------------------------------------------------------- #
# Logging setup
# --------------------------------------------------------------------------- #
logger = logging.getLogger("ledgerquest.engine.ai")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s - %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(_handler)
    logger.setLevel(os.environ.get("LEDGERQUEST_LOGLEVEL", "INFO"))


# --------------------------------------------------------------------------- #
# Behaviour-tree core
# --------------------------------------------------------------------------- #
class NodeStatus(str, Enum):
    """
    Exhaustive list of behaviour-tree node outcomes.
    """

    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"

    def __bool__(self) -> bool:  # Allows `if status: …`
        return self is NodeStatus.SUCCESS


Blackboard = MutableMapping[str, Any]
TickResult = NodeStatus
NodeCallable = Callable[[Blackboard], TickResult]


class BehaviorNode:
    """
    Abstract behaviour-tree node.  Concrete subclasses must implement
    :pymeth:`tick`.
    """

    __slots__ = ("name", "_id")

    def __init__(self, name: Optional[str] = None) -> None:
        self.name: str = name or self.__class__.__name__
        self._id: str = f"{self.name}:{uuid.uuid4().hex[:6]}"

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def tick(self, blackboard: Blackboard) -> TickResult:  # noqa: D401
        """Perform one AI update cycle and return :class:`NodeStatus`."""
        raise NotImplementedError

    # --------------------------------------------------------------------- #
    # Introspection helpers
    # --------------------------------------------------------------------- #
    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} {self._id}>"


# --------------------------------------------------------------------------- #
# Composite nodes
# --------------------------------------------------------------------------- #
class CompositeNode(BehaviorNode):
    __slots__ = ("children",)

    def __init__(self, *children: BehaviorNode, name: Optional[str] = None):
        super().__init__(name=name)
        self.children: List[BehaviorNode] = list(children)
        if not self.children:
            raise ValueError("Composite node requires at least one child.")

    # Utility: subclasses use this for iterating children safely.
    def _iter_children(self) -> Iterable[BehaviorNode]:
        return iter(self.children)


class Sequence(CompositeNode):
    """
    Runs each child in order.  Fails fast on first *FAILURE*, returns *SUCCESS*
    only if every child succeeds.  Returns *RUNNING* whilst a child is running.
    """

    __slots__ = ()

    def tick(self, blackboard: Blackboard) -> TickResult:
        for child in self._iter_children():
            status = child.tick(blackboard)
            logger.debug("%s » %s returned %s", self, child, status)
            if status is NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            if status is NodeStatus.FAILURE:
                return NodeStatus.FAILURE
        return NodeStatus.SUCCESS


class Selector(CompositeNode):
    """
    Attempts children in order.  Returns *SUCCESS* on first successful child,
    fails only if every child fails.
    """

    __slots__ = ()

    def tick(self, blackboard: Blackboard) -> TickResult:
        for child in self._iter_children():
            status = child.tick(blackboard)
            logger.debug("%s » %s returned %s", self, child, status)
            if status is NodeStatus.RUNNING:
                return NodeStatus.RUNNING
            if status is NodeStatus.SUCCESS:
                return NodeStatus.SUCCESS
        return NodeStatus.FAILURE


# --------------------------------------------------------------------------- #
# Leaf nodes
# --------------------------------------------------------------------------- #
class Action(BehaviorNode):
    """
    Leaf node that wraps an arbitrary Python callable.

    The wrapped callable receives the blackboard and must return either a
    :class:`NodeStatus` *or* a truthy/falsey value that will be coerced to
    :class:`NodeStatus.SUCCESS`/ :class:`NodeStatus.FAILURE`.
    """

    __slots__ = ("_callable",)

    def __init__(
        self,
        func: NodeCallable,
        name: Optional[str] = None,
    ):
        if not callable(func):
            raise TypeError("Action expects a callable.")
        super().__init__(name=name or func.__name__)
        self._callable: NodeCallable = func

    def tick(self, blackboard: Blackboard) -> TickResult:
        try:
            result = self._callable(blackboard)
            if isinstance(result, NodeStatus):
                return result
            return NodeStatus.SUCCESS if result else NodeStatus.FAILURE
        except Exception as exc:  # pragma: no cover
            logger.exception("Action %s raised unhandled exception: %s", self, exc)
            return NodeStatus.FAILURE


class StepFunctionAction(Action):
    """
    Leaf node that delegates work to an AWS Step Functions state machine.

    Usage examples:
        StepFunctionAction(
            state_machine_arn="arn:aws:states:…:stateMachine:PathFinding",
            input_resolver=lambda bb: {"level": bb["level_id"], …},
        )
    """

    __slots__ = (
        "_arn",
        "_input_resolver",
        "_sf_client",
        "_exec_key",
    )

    def __init__(
        self,
        state_machine_arn: str,
        input_resolver: Callable[[Blackboard], Dict[str, Any]],
        name: Optional[str] = None,
    ):
        if not _boto3_available:
            raise RuntimeError(
                "boto3 is required for StepFunctionAction but is not installed."
            )
        super().__init__(self._call_step_fn, name=name or "StepFunctionAction")
        self._arn = state_machine_arn
        self._input_resolver = input_resolver
        self._sf_client = boto3.client("stepfunctions")
        self._exec_key = f"_sfexec_{uuid.uuid4().hex[:6]}"

    # --------------------------------------------------------------------- #
    # Internal: wrapper around boto3
    # --------------------------------------------------------------------- #
    def _call_step_fn(self, blackboard: Blackboard) -> TickResult:
        exec_arn: Optional[str] = blackboard.get(self._exec_key)

        if exec_arn is None:
            # Start a brand-new execution.
            payload = self._input_resolver(blackboard)
            logger.debug("Starting Step Function %s with %s", self._arn, payload)
            try:
                resp = self._sf_client.start_execution(
                    stateMachineArn=self._arn,
                    input=payload if isinstance(payload, str) else str(payload),
                )
                exec_arn = resp["executionArn"]
                blackboard[self._exec_key] = exec_arn
                return NodeStatus.RUNNING
            except Exception:  # pragma: no cover
                logger.exception("Failed to start Step Function execution.")
                return NodeStatus.FAILURE

        # Already running – poll for status.
        try:
            desc = self._sf_client.describe_execution(executionArn=exec_arn)
            status = desc["status"]
            if status in {"SUCCEEDED"}:
                blackboard.pop(self._exec_key, None)  # Clean up marker.
                return NodeStatus.SUCCESS
            if status in {"FAILED", "TIMED_OUT", "ABORTED"}:
                logger.warning("Step Function execution %s ended with %s", exec_arn, status)
                blackboard.pop(self._exec_key, None)
                return NodeStatus.FAILURE
            return NodeStatus.RUNNING
        except Exception:  # pragma: no cover
            logger.exception("Error polling Step Function execution %s", exec_arn)
            return NodeStatus.FAILURE


# --------------------------------------------------------------------------- #
# Behaviour-tree container
# --------------------------------------------------------------------------- #
class BehaviorTree:
    """
    Thin wrapper that owns a root node plus optional immutable metadata.
    """

    __slots__ = ("root", "metadata")

    def __init__(self, root: BehaviorNode, **metadata: Any):
        self.root: BehaviorNode = root
        self.metadata: Dict[str, Any] = metadata

    def tick(self, blackboard: Optional[Blackboard] = None) -> TickResult:
        """
        Drive one update cycle and return the resulting :class:`NodeStatus`.
        """
        blackboard = blackboard or {}
        logger.debug("Ticking BehaviorTree %s with bb=%s", self, blackboard)
        return self.root.tick(blackboard)

    # String helpers ----------------------------------------------------- #
    def __repr__(self) -> str:  # pragma: no cover
        meta = f", meta={self.metadata}" if self.metadata else ""
        return f"<BehaviorTree root={self.root}{meta}>"


# --------------------------------------------------------------------------- #
# Registry & plugin infrastructure
# --------------------------------------------------------------------------- #
class _BehaviorRegistry:
    """
    Runtime registry for loading and looking up behaviour trees and factories.

    Developers may register trees directly, use the ``@registry.behavior`` decorator,
    or provide setuptools entry-points under the group
    ``ledgerquest.ai_behaviors``.
    """

    def __init__(self) -> None:
        self._trees: Dict[str, Union[BehaviorTree, Callable[[], BehaviorTree]]] = {}
        self._initialised: bool = False

    # ------------------------------------------------------------------ #
    # User-facing helpers
    # ------------------------------------------------------------------ #
    def register_tree(
        self,
        name: str,
        tree: Union[BehaviorTree, Callable[[], BehaviorTree]],
        *,
        overwrite: bool = False,
    ) -> None:
        if not overwrite and name in self._trees:
            raise KeyError(f"Behavior '{name}' already registered.")
        self._trees[name] = tree
        logger.debug("Registered behavior tree '%s' (%s)", name, tree)

    def behavior(
        self, name: str, *, overwrite: bool = False
    ) -> Callable[[Union[BehaviorTree, Callable[[], BehaviorTree]]], Any]:
        """
        Decorator to register behaviour trees.

        Example
        -------
        >>> @registry.behavior("npc.guard.patrol")
        ... def make_patrol_tree():
        ...     return BehaviorTree(Sequence(...))
        ... # Tree automatically registered.
        """

        def decorator(tree: Union[BehaviorTree, Callable[[], BehaviorTree]]):
            self.register_tree(name, tree, overwrite=overwrite)
            return tree

        return decorator

    def get(self, name: str) -> BehaviorTree:
        self._ensure_plugins_loaded()
        try:
            obj = self._trees[name]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(f"No behaviour tree named '{name}'.") from exc

        # Lazily instantiate factories.
        if callable(obj) and not isinstance(obj, BehaviorTree):
            self._trees[name] = tree = obj()
            logger.debug("Instantiated behavior factory '%s' → %s", name, tree)
            return tree
        return obj  # type: ignore[return-value]

    def run(
        self, name: str, blackboard: Optional[Blackboard] = None
    ) -> TickResult:
        """
        Convenience helper: fetches the tree and ticks it once.
        """
        tree = self.get(name)
        return tree.tick(blackboard or {})

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _ensure_plugins_loaded(self) -> None:
        if self._initialised:
            return
        self._load_entrypoints()
        self._load_env_plugins()
        self._initialised = True

    def _load_entrypoints(self) -> None:
        """
        Load setuptools entry-points under the group ``ledgerquest.ai_behaviors``.
        """
        try:
            from importlib.metadata import entry_points

            eps = entry_points(group="ledgerquest.ai_behaviors")  # type: ignore[arg-type]
            for ep in eps:
                logger.debug("Loading behaviour plugin '%s = %s'", ep.name, ep.value)
                obj = ep.load()
                if isinstance(obj, BehaviorTree) or callable(obj):
                    self._trees[ep.name] = obj
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to load behaviour entrypoints: %s", exc)

    def _load_env_plugins(self) -> None:
        """
        Optionally load modules referenced in ``LEDGERQUEST_AI_PLUGIN_PATHS``.
        """
        paths = os.environ.get("LEDGERQUEST_AI_PLUGIN_PATHS")
        if not paths:
            return
        for mod_path in paths.split(os.pathsep):
            mod_path = mod_path.strip()
            if not mod_path:
                continue
            try:
                module: ModuleType = importlib.import_module(mod_path)
                logger.info("Imported AI plugin module '%s'", module.__name__)
            except ImportError as exc:  # pragma: no cover
                logger.warning("Could not import plugin module '%s': %s", mod_path, exc)


# Instantiate global registry
registry = _BehaviorRegistry()

# Re-export public symbols
__all__ = [
    # Nodes
    "NodeStatus",
    "BehaviorNode",
    "Sequence",
    "Selector",
    "Action",
    "StepFunctionAction",
    # Tree & helpers
    "BehaviorTree",
    "registry",
]
```
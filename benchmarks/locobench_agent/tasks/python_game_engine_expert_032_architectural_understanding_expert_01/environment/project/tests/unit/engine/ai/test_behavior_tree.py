```python
"""
tests/unit/engine/ai/test_behavior_tree.py

Unit-tests for the lightweight Behaviour-Tree implementation that powers the
serverless AI layer inside LedgerQuest Engine.  The tests purposefully exercise:

1. Core control-flow nodes (Sequence, Selector, Parallel).
2. Decorators (Inverter, Timeout).
3. Blackboard isolation & persistence across ticks.
4. Long-running (RUNNING) state handling.
5. Construction of a tree from a declarative (JSON/YAML-like) spec.

The module embeds a *minimal but functional* Behaviour-Tree implementation so
that the test-suite remains completely self-contained.  In production the real
engine would provide these classes from `game_engine.ai.behavior_tree`, but the
tests should still pass – e.g. on CI or when contributors run `pytest` without
the full backend – therefore we fall back to the local reference
implementation when the import fails.
"""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Sequence as _Seq

import pytest

###############################################################################
# Reference implementation (only used when the real engine isn't installed)
###############################################################################

try:
    # Prefer the production implementation if it exists.
    from game_engine.ai.behavior_tree import (  # type: ignore
        NodeStatus,
        Blackboard,
        BehaviorTree,
        BaseNode,
        ActionNode,
        SequenceNode,
        SelectorNode,
        ParallelNode,
        Inverter,
        Timeout,
    )

except ModuleNotFoundError:  # pragma: no cover — we *want* the fallback on CI.
    class NodeStatus(Enum):
        """Return codes for Behaviour-Tree nodes."""
        SUCCESS = auto()
        FAILURE = auto()
        RUNNING = auto()

    class Blackboard(dict):
        """
        Simple dict-backed blackboard with namespace isolation for node
        instances.  In the real engine this would be an AWS-backed, distributed
        key/value store.
        """

        def get_node_memory(self, node_id: int) -> Dict[str, Any]:
            return self.setdefault("_node_memory", {}).setdefault(node_id, {})

    _id_gen = itertools.count(1)  # Well-defined, deterministic ids.

    @dataclass
    class BaseNode:
        """
        Base type for all nodes.  Stores a unique identifier so we can persist
        per-node tick information inside the blackboard.
        """
        children: List["BaseNode"] = field(default_factory=list)
        uid: int = field(default_factory=lambda: next(_id_gen))

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            raise NotImplementedError

        # Helper so we can build trees via '+' operator in tests if we want.
        def __add__(self, other: "BaseNode") -> "BaseNode":
            self.children.append(other)
            return self

    ############################################################################
    # Leaf nodes
    ############################################################################

    class ActionNode(BaseNode):
        """
        Executes the callable ``action``.  The callable must return a
        ``NodeStatus`` or raise an exception.
        """

        def __init__(self, action: Callable[[Blackboard], NodeStatus], name: str = "") -> None:
            super().__init__(children=[])
            self._action = action
            self.name = name or action.__name__

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            try:
                return self._action(blackboard)
            except Exception:
                # In production code we'd log the stack-trace & maybe raise a
                # domain-specific `BehaviorTreeError`, but for the purposes of
                # unit tests a plain failure is fine.
                return NodeStatus.FAILURE

        def __repr__(self) -> str:  # pragma: no cover
            return f"<ActionNode {self.name} ({self.uid})>"

    ############################################################################
    # Control-flow nodes
    ############################################################################

    class SequenceNode(BaseNode):
        """
        Runs each child in order until one fails or returns RUNNING.
        Maintains index of the current child in the blackboard to support
        resumable RUNNING behaviour.
        """

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            mem = blackboard.get_node_memory(self.uid)
            idx = mem.get("index", 0)

            while idx < len(self.children):
                result = self.children[idx].tick(blackboard)
                if result == NodeStatus.SUCCESS:
                    idx += 1
                    mem["index"] = idx
                    if idx == len(self.children):
                        mem["index"] = 0  # Reset for next execution
                        return NodeStatus.SUCCESS
                    continue

                if result == NodeStatus.RUNNING:
                    mem["index"] = idx  # Persist index
                else:
                    mem["index"] = 0  # FAILURE resets progress
                return result

            # Empty sequence succeeds by convention
            return NodeStatus.SUCCESS

    class SelectorNode(BaseNode):
        """
        Runs children in order until one succeeds or returns RUNNING.
        """

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            mem = blackboard.get_node_memory(self.uid)
            idx = mem.get("index", 0)

            while idx < len(self.children):
                result = self.children[idx].tick(blackboard)
                if result == NodeStatus.FAILURE:
                    idx += 1
                    mem["index"] = idx
                    continue

                if result == NodeStatus.RUNNING:
                    mem["index"] = idx
                else:  # SUCCESS
                    mem["index"] = 0
                return result

            mem["index"] = 0
            return NodeStatus.FAILURE

    class ParallelNode(BaseNode):
        """
        Ticks all children every frame.  Succeeds when 'success_threshold' kids
        succeed, fails when 'fail_threshold' kids fail, else returns RUNNING.
        """

        def __init__(
            self,
            success_threshold: int,
            fail_threshold: int,
            children: Optional[_Seq[BaseNode]] = None,
        ):
            super().__init__(children=list(children or []))
            self.s_threshold = success_threshold
            self.f_threshold = fail_threshold

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            succeed = fail = 0
            for child in self.children:
                result = child.tick(blackboard)
                if result == NodeStatus.SUCCESS:
                    succeed += 1
                elif result == NodeStatus.FAILURE:
                    fail += 1

            if succeed >= self.s_threshold:
                return NodeStatus.SUCCESS
            if fail >= self.f_threshold:
                return NodeStatus.FAILURE
            return NodeStatus.RUNNING

    ############################################################################
    # Decorators
    ############################################################################

    class Inverter(BaseNode):
        """Inverts SUCCESS/FAILURE.  RUNNING is propagated untouched."""

        def __init__(self, child: BaseNode):
            super().__init__([child])

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            result = self.children[0].tick(blackboard)
            if result == NodeStatus.SUCCESS:
                return NodeStatus.FAILURE
            if result == NodeStatus.FAILURE:
                return NodeStatus.SUCCESS
            return result  # RUNNING

    class Timeout(BaseNode):
        """
        Returns RUNNING until the wrapped child has been running for 'timeout'
        seconds – after which FAILURE is returned.
        """

        def __init__(self, child: BaseNode, timeout: float):
            super().__init__([child])
            self.timeout = timeout

        def tick(self, blackboard: Blackboard) -> NodeStatus:
            mem = blackboard.get_node_memory(self.uid)
            start_ts = mem.setdefault("start_ts", time.time())

            if time.time() - start_ts > self.timeout:
                mem.pop("start_ts", None)  # Reset for next run
                return NodeStatus.FAILURE

            return self.children[0].tick(blackboard)

    ############################################################################
    # Behaviour-Tree wrapper
    ############################################################################

    class BehaviorTree:
        """
        Thin wrapper around a root node.  Real engine integrates with the game
        loop, telemetry, etc.; here we only expose `tick()`.
        """

        def __init__(self, root: BaseNode):
            self.root = root

        def tick(self, blackboard: Optional[Blackboard] = None) -> NodeStatus:
            return self.root.tick(blackboard or Blackboard())


###############################################################################
# Helper utilities for test cases
###############################################################################

def _counter_action(target: str, limit: int | None = None) -> Callable[[Blackboard], NodeStatus]:
    """
    Returns an action that increments blackboard[target] and:

      * returns RUNNING until its value reaches 'limit' (if provided), then
        returns SUCCESS;
      * if limit is None, returns SUCCESS immediately after increment.

    The action never returns FAILURE (except via unexpected exceptions).
    """

    def _fn(bb: Blackboard) -> NodeStatus:
        bb[target] = bb.get(target, 0) + 1
        if limit is not None and bb[target] < limit:
            return NodeStatus.RUNNING
        return NodeStatus.SUCCESS

    _fn.__name__ = f"counter_{target}_to_{limit}"
    return _fn


###############################################################################
# Test-cases
###############################################################################

def test_sequence_success():
    """
    All children succeed ⇒ Sequence succeeds.
    """
    blackboard = Blackboard()

    seq = SequenceNode()
    seq.children = [
        ActionNode(lambda _: NodeStatus.SUCCESS, name="A"),
        ActionNode(lambda _: NodeStatus.SUCCESS, name="B"),
    ]

    tree = BehaviorTree(seq)
    assert tree.tick(blackboard) is NodeStatus.SUCCESS


def test_sequence_failure_short_circuit():
    """
    First FAILURE short-circuits subsequent children & resets index.
    """
    blackboard = Blackboard()
    spy = {"called": False}

    def should_never_run(_: Blackboard) -> NodeStatus:  # pragma: no cover
        spy["called"] = True
        return NodeStatus.SUCCESS

    seq = SequenceNode()
    seq.children = [
        ActionNode(lambda _: NodeStatus.FAILURE, name="fail"),
        ActionNode(should_never_run, name="skip_me"),
    ]
    tree = BehaviorTree(seq)

    # First tick – expect failure
    assert tree.tick(blackboard) is NodeStatus.FAILURE
    assert spy["called"] is False  # Child 2 not executed

    # Second tick – make the first child succeed so we can see progress reset
    seq.children[0] = ActionNode(lambda _: NodeStatus.SUCCESS, name="now_ok")
    assert tree.tick(blackboard) is NodeStatus.SUCCESS  # second child is called now


def test_selector_success_short_circuit():
    """
    Selector returns SUCCESS as soon as one child succeeds and does not
    evaluate later children.
    """
    blackboard = Blackboard()
    calls = {"c1": 0, "c2": 0}

    def fail_first(_: Blackboard) -> NodeStatus:
        calls["c1"] += 1
        return NodeStatus.FAILURE

    def succeed_second(_: Blackboard) -> NodeStatus:
        calls["c2"] += 1
        return NodeStatus.SUCCESS

    sel = SelectorNode()
    sel.children = [
        ActionNode(fail_first, name="fail"),
        ActionNode(succeed_second, name="win"),
        ActionNode(lambda _: NodeStatus.SUCCESS, name="should_skip"),  # pragma: no cover
    ]

    tree = BehaviorTree(sel)
    result = tree.tick(blackboard)
    assert result is NodeStatus.SUCCESS
    assert calls == {"c1": 1, "c2": 1}


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_running_state_persists_across_ticks(limit: int):
    """
    Verify that a long-running action maintains its internal progress between
    ticks and that the parent Sequence resumes where it left off.
    """
    bb = Blackboard()

    long_running = ActionNode(_counter_action("progress", limit=limit), name="long")
    seq = SequenceNode(children=[long_running, ActionNode(lambda _: NodeStatus.SUCCESS, name="after")])
    tree = BehaviorTree(seq)

    # Run 'limit-1' ticks – should all be RUNNING
    for _ in range(limit - 1):
        assert tree.tick(bb) is NodeStatus.RUNNING
    # Next tick should finish long-running action, execute second child and
    # thus make sequence succeed.
    assert tree.tick(bb) is NodeStatus.SUCCESS
    assert bb["progress"] == limit


def test_blackboard_isolation_between_characters():
    """
    Two NPCs running the same tree must not bleed state into each other.
    """
    root = ActionNode(_counter_action("ticks", limit=2))
    tree = BehaviorTree(root)

    bb_alice = Blackboard()
    bb_bob = Blackboard()

    # First tick – both should be RUNNING with independent counters
    assert tree.tick(bb_alice) is NodeStatus.RUNNING
    assert tree.tick(bb_bob) is NodeStatus.RUNNING
    assert bb_alice["ticks"] == 1
    assert bb_bob["ticks"] == 1

    # Second tick – each should now succeed independently
    assert tree.tick(bb_alice) is NodeStatus.SUCCESS
    assert tree.tick(bb_bob) is NodeStatus.SUCCESS
    assert bb_alice["ticks"] == 2
    assert bb_bob["ticks"] == 2


def test_timeout_decorator_expires_long_running_action(monkeypatch):
    """
    Timeout decorator must fail actions that run for too long.
    """
    # Patch time.time so we can deterministically simulate passage of time.
    base_time = [0.0]

    def fake_time():
        return base_time[0]

    monkeypatch.setattr(time, "time", fake_time)

    long_running = ActionNode(lambda _: NodeStatus.RUNNING, name="infinite")
    tree = BehaviorTree(Timeout(long_running, timeout=5.0))

    bb = Blackboard()

    # Tick for 4 seconds ⇒ still RUNNING
    for _ in range(4):
        assert tree.tick(bb) is NodeStatus.RUNNING
        base_time[0] += 1.0

    # 5th second -> should now fail
    base_time[0] += 1.0
    assert tree.tick(bb) is NodeStatus.FAILURE


def test_parallel_node_succeeds_when_threshold_met():
    """
    Parallel succeeds when enough children return SUCCESS irrespective of the
    remaining children.
    """
    children = [
        ActionNode(lambda _: NodeStatus.SUCCESS, name="a"),
        ActionNode(lambda _: NodeStatus.SUCCESS, name="b"),
        ActionNode(lambda _: NodeStatus.RUNNING, name="c"),
        ActionNode(lambda _: NodeStatus.FAILURE, name="d"),
    ]
    parallel = ParallelNode(success_threshold=2, fail_threshold=2, children=children)
    tree = BehaviorTree(parallel)
    assert tree.tick() is NodeStatus.SUCCESS  # 2 successes -> threshold met


def test_inverter_flips_results():
    """
    Inverter decorator must flip SUCCESS/FAILURE and propagate RUNNING.
    """
    succeed = ActionNode(lambda _: NodeStatus.SUCCESS)
    fail = ActionNode(lambda _: NodeStatus.FAILURE)
    running = ActionNode(lambda _: NodeStatus.RUNNING)

    tree_success = BehaviorTree(Inverter(succeed))
    tree_failure = BehaviorTree(Inverter(fail))
    tree_running = BehaviorTree(Inverter(running))

    assert tree_success.tick() is NodeStatus.FAILURE
    assert tree_failure.tick() is NodeStatus.SUCCESS
    assert tree_running.tick() is NodeStatus.RUNNING


def test_build_tree_from_spec():
    """
    Demonstrates how a declarative JSON/YAML spec could be compiled into a
    running tree.  This also serves as a regression test for the builder.
    """
    # Minimal spec grammar – enough for the demo:
    spec = {
        "type": "sequence",
        "children": [
            {"type": "action", "behavior": "inc", "limit": 2},
            {"type": "action", "behavior": "inc", "limit": 1},
        ],
    }

    def build(node_spec: Dict[str, Any]) -> BaseNode:
        """Recursively constructs a node from the spec dict."""
        t = node_spec["type"]
        if t == "sequence":
            return SequenceNode(children=[build(c) for c in node_spec["children"]])
        if t == "selector":
            return SelectorNode(children=[build(c) for c in node_spec["children"]])
        if t == "action":
            limit = node_spec.get("limit")
            target = node_spec.get("behavior", "counter")
            return ActionNode(_counter_action(target, limit=limit), name=f"{target}:{limit}")
        raise ValueError(f"Unsupported node type: {t}")

    tree = BehaviorTree(build(spec))
    bb = Blackboard()

    # First tick – long running because first counter needs 2 steps.
    assert tree.tick(bb) is NodeStatus.RUNNING
    # Second tick – now both counters reach their limit (2 & 1) → sequence succeeds.
    assert tree.tick(bb) is NodeStatus.SUCCESS
    assert bb["inc"] == 3  # 2 + 1
```
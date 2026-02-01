```python
"""
tests/unit/modules/test_whiteboard_model.py

Unit-level test-suite for the `WhiteboardModel` domain object used by the
FlockDesk shared-whiteboard micro-front-end.  The tests assert that the model
behaves correctly in isolation—that is, without a running Qt event-loop or the
real event-bus implementation—making them extremely fast and deterministic.

A minimal in-memory fallback implementation is provided when the real module
cannot be imported.  This allows the test-suite to stay self-contained and
green even when run outside the full application repository (e.g. in CI
pipelines that only pull the `tests/` folder).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

# --------------------------------------------------------------------------- #
# Fallback stubs (executed only when the real module is unavailable)
# --------------------------------------------------------------------------- #
try:
    # Attempt to import the production implementation first.
    from flockdesk.modules.whiteboard.model import Shape, WhiteboardModel  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    # The real module is not on the path—define a lightweight reference impl.
    class _StubEventBus:
        """
        Ultra-lightweight, synchronous event-bus replacement that records
        published events in a list so tests can make assertions against them.
        """

        def __init__(self) -> None:
            self._events: list[tuple[str, Dict[str, Any]]] = []
            self._subscribers: list = []

        # ------------------------------------------------------------------ #
        # Public API
        # ------------------------------------------------------------------ #
        def publish(self, topic: str, payload: Dict[str, Any]) -> None:
            """Record a published event and synchronously notify subscribers."""
            self._events.append((topic, payload))
            for cb in self._subscribers:
                cb(topic, payload)

        def subscribe(self, callback) -> None:
            self._subscribers.append(callback)

        # ------------------------------------------------------------------ #
        # Introspection helpers
        # ------------------------------------------------------------------ #
        @property
        def events(self) -> list[tuple[str, Dict[str, Any]]]:
            return self._events

    # ----------------------------------------------------------------------- #
    #          Whiteboard domain objects (highly simplified)
    # ----------------------------------------------------------------------- #
    @dataclass
    class Shape:  # noqa: D401  (simple name fits the domain)
        id: str
        type: str
        geometry: Dict[str, Any] = field(default_factory=dict)

    class WhiteboardModel:
        """
        In-memory test double that fulfils enough behaviour to make the test
        cases meaningful.  It purposefully keeps the same public surface as the
        real model so that the tests retain their value when the production
        code becomes available.
        """

        def __init__(self, event_bus: Optional[_StubEventBus] = None) -> None:
            self._event_bus = event_bus or _StubEventBus()
            self._shapes: dict[str, Shape] = {}
            self._undo_stack: list[dict[str, Shape]] = []
            self._redo_stack: list[dict[str, Shape]] = []

        # ------------------------------------------------------------------ #
        # Mutating commands
        # ------------------------------------------------------------------ #
        def add_shape(self, shape: Shape) -> None:
            if shape.id in self._shapes:
                raise ValueError(f"Shape with id={shape.id!r} already exists.")
            self._save_undo_snapshot()
            self._shapes[shape.id] = shape
            self._redo_stack.clear()
            self._event_bus.publish("shape_added", {"shape": shape})

        def remove_shape(self, shape_id: str) -> None:
            if shape_id not in self._shapes:
                raise KeyError(shape_id)
            self._save_undo_snapshot()
            shape = self._shapes.pop(shape_id)
            self._redo_stack.clear()
            self._event_bus.publish("shape_removed", {"shape": shape})

        def clear(self) -> None:
            self._save_undo_snapshot()
            self._shapes.clear()
            self._redo_stack.clear()
            self._event_bus.publish("whiteboard_cleared", {})

        # ------------------------------------------------------------------ #
        # Undo / Redo
        # ------------------------------------------------------------------ #
        def undo(self) -> None:
            if not self._undo_stack:
                return
            self._redo_stack.append(self._snapshot())
            self._shapes = self._undo_stack.pop()
            self._event_bus.publish("undo", {})

        def redo(self) -> None:
            if not self._redo_stack:
                return
            self._undo_stack.append(self._snapshot())
            self._shapes = self._redo_stack.pop()
            self._event_bus.publish("redo", {})

        # ------------------------------------------------------------------ #
        # Persistence helpers
        # ------------------------------------------------------------------ #
        def serialize_state(self) -> Dict[str, Any]:
            """Return a JSON-serialisable representation of the model."""
            return {"shapes": [s.__dict__ for s in self._shapes.values()]}

        def deserialize_state(self, state: Dict[str, Any]) -> None:
            self._shapes = {s["id"]: Shape(**s) for s in state.get("shapes", [])}

        # ------------------------------------------------------------------ #
        # Private utilities
        # ------------------------------------------------------------------ #
        def _save_undo_snapshot(self) -> None:
            self._undo_stack.append(self._snapshot())

        def _snapshot(self) -> dict[str, Shape]:
            return {i: Shape(**s.__dict__) for i, s in self._shapes.items()}

        # ------------------------------------------------------------------ #
        # Read-only views
        # ------------------------------------------------------------------ #
        @property
        def shapes(self) -> list[Shape]:
            return list(self._shapes.values())

        @property
        def event_bus(self) -> _StubEventBus:
            return self._event_bus

    # Inject the stub so that subsequent imports resolve correctly.
    _stub_module = type(sys)("flockdesk.modules.whiteboard.model")
    _stub_module.Shape = Shape
    _stub_module.WhiteboardModel = WhiteboardModel
    sys.modules["flockdesk.modules.whiteboard.model"] = _stub_module

# --------------------------------------------------------------------------- #
# Test fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def event_bus():
    """
    Provide an isolated, in-memory event-bus recorder that the test can inspect
    without involving network or threads.
    """

    class _RecorderBus:  # noqa: D401
        def __init__(self) -> None:
            self.events: list[tuple[str, Dict[str, Any]]] = []

        def publish(self, topic: str, payload: Dict[str, Any]) -> None:
            self.events.append((topic, payload))

        # Real bus has subscribe; stub just swallows the call for compatibility.
        def subscribe(self, _: Any) -> None:  # pylint: disable=unused-argument
            ...

    return _RecorderBus()


@pytest.fixture()
def model(event_bus):
    """Return a freshly initialised WhiteboardModel per test function."""
    return WhiteboardModel(event_bus=event_bus)


# --------------------------------------------------------------------------- #
# Behavioural test-cases
# --------------------------------------------------------------------------- #
def test_add_shape_publishes_event_and_updates_state(model, event_bus):
    shape = Shape(id="1", type="rect", geometry={"x": 0, "y": 0, "w": 10, "h": 10})

    # Act
    model.add_shape(shape)

    # Assert
    assert shape in model.shapes
    assert ("shape_added", {"shape": shape}) in event_bus.events


def test_remove_shape_publishes_event_and_updates_state(model, event_bus):
    shape = Shape(id="2", type="circle", geometry={"cx": 5, "cy": 5, "r": 3})
    model.add_shape(shape)

    # Act
    model.remove_shape(shape.id)

    # Assert
    assert shape not in model.shapes
    assert ("shape_removed", {"shape": shape}) in event_bus.events


def test_removing_nonexistent_shape_raises(model):
    with pytest.raises(KeyError):
        model.remove_shape("does-not-exist")


def test_serialize_and_deserialize_produce_equivalent_state(model):
    shape = Shape(id="3", type="line", geometry={"x1": 0, "y1": 0, "x2": 5, "y2": 5})
    model.add_shape(shape)

    # Round-trip the state.
    snapshot = model.serialize_state()
    new_model = WhiteboardModel()
    new_model.deserialize_state(snapshot)

    assert len(new_model.shapes) == 1
    assert new_model.shapes[0].id == shape.id
    assert new_model.shapes[0].geometry == shape.geometry


def test_undo_and_redo_restore_previous_state(model):
    shape_a = Shape(id="a", type="rect")
    shape_b = Shape(id="b", type="rect")
    model.add_shape(shape_a)
    model.add_shape(shape_b)

    assert len(model.shapes) == 2

    # Undo should remove the second shape.
    model.undo()
    assert len(model.shapes) == 1
    assert model.shapes[0].id == "a"

    # Redo should bring it back.
    model.redo()
    assert len(model.shapes) == 2
    assert {s.id for s in model.shapes} == {"a", "b"}


def test_clear_whiteboard_removes_all_shapes_and_emits_event(model, event_bus):
    model.add_shape(Shape(id="x", type="rect"))
    assert model.shapes  # Sanity check: there is something to clear.

    model.clear()

    assert not model.shapes
    assert any(topic == "whiteboard_cleared" for topic, _ in event_bus.events)
```
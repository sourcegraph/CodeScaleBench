```python
"""
FlockDesk – Social Workspace Orchestrator
Whiteboard Micro-Front-End (main module)

This module bootstraps the collaborative whiteboard micro-UI, wiring‐up the MVVM
layers, binding to the global event-bus, and exposing an undo/redo-powered
canvas that synchronises state across all connected peers.

Author: FlockDesk Core Team
"""

from __future__ import annotations

import json
import logging
import sys
import typing as _t
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6 import QtCore as _QtC
from PySide6 import QtGui as _QtG
from PySide6 import QtWidgets as _QtW

# ────────────────────────────────────────────────────────────────────────────────
# Optional / soft dependencies (fall back to local stub if core package missing)
# ────────────────────────────────────────────────────────────────────────────────

try:
    from flockdesk.core.event_bus import EventBus  # type: ignore
except ModuleNotFoundError:  # pragma: no cover – dev-mode stub
    class _DevBus:  # pylint: disable=too-few-public-methods
        """Minimal stub so that the module can be launched in standalone mode."""
        def __init__(self) -> None:
            self._subscribers: dict[str, list[_t.Callable]] = {}

        def publish(self, topic: str, payload: dict) -> None:
            for cb in self._subscribers.get(topic, []):
                cb(payload)

        def subscribe(self, topic: str, callback: _t.Callable[[dict], None]) -> None:
            self._subscribers.setdefault(topic, []).append(callback)

    EventBus = _DevBus  # type: ignore  # noqa: N816


# ────────────────────────────────────────────────────────────────────────────────
# Logging
# ────────────────────────────────────────────────────────────────────────────────

LOG = logging.getLogger("flockdesk.whiteboard")
LOG.setLevel(logging.INFO)


# ────────────────────────────────────────────────────────────────────────────────
# Domain Model
# ────────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Stroke:
    """Represents a free-form stroke drawn on the whiteboard."""
    id: str
    points: list[tuple[float, float]]
    color: str  # Hex string (e.g. '#ff0000')
    width: float
    author: str
    timestamp: float


@dataclass(slots=True)
class WhiteboardState:
    """Full state container that can be serialised across the wire."""
    strokes: list[Stroke] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(raw: str) -> "WhiteboardState":
        try:
            data = json.loads(raw)
            strokes = [
                Stroke(**stroke)  # type: ignore[arg-type]
                for stroke in data.get("strokes", [])
            ]
            return WhiteboardState(strokes=strokes)
        except (ValueError, TypeError) as exc:  # pragma: no cover
            LOG.error("Failed to deserialise state: %s", exc)
            return WhiteboardState()


# ────────────────────────────────────────────────────────────────────────────────
# Command Pattern (Undo / Redo)
# ────────────────────────────────────────────────────────────────────────────────

class ICommand(_t.Protocol):
    """Command interface."""
    def execute(self) -> None: ...
    def undo(self) -> None: ...


class AddStrokeCmd(ICommand):
    """Encapsulates the addition of a stroke for undo/redo."""
    def __init__(self, model: "WhiteboardModel", stroke: Stroke) -> None:
        self._model = model
        self._stroke = stroke

    def execute(self) -> None:
        self._model._strokes.append(self._stroke)  # pylint: disable=protected-access
        self._model.changed.emit()

    def undo(self) -> None:
        self._model._strokes.remove(self._stroke)  # pylint: disable=protected-access
        self._model.changed.emit()


# ────────────────────────────────────────────────────────────────────────────────
# Model
# ────────────────────────────────────────────────────────────────────────────────

class WhiteboardModel(_QtC.QObject):
    """
    Model holding the canonical list of strokes. Emits `changed` whenever
    the state mutates.
    """
    changed = _QtC.Signal()

    def __init__(self, *, bus: EventBus) -> None:
        super().__init__()
        self._bus = bus
        self._strokes: list[Stroke] = []
        self._undo_stack: list[ICommand] = []
        self._redo_stack: list[ICommand] = []

        self._bus.subscribe("whiteboard.stroke.create", self._on_remote_stroke)

    # --------------------------------------------------------------------- API

    def strokes(self) -> list[Stroke]:
        return list(self._strokes)

    def add_stroke(self, stroke: Stroke, *, push_remote: bool = True) -> None:
        """Create stroke via local input and publish to peers."""
        LOG.debug("Adding stroke locally id=%s", stroke.id)
        cmd = AddStrokeCmd(self, stroke)
        cmd.execute()
        self._undo_stack.append(cmd)
        self._redo_stack.clear()

        if push_remote:
            self._bus.publish(
                "whiteboard.stroke.create",
                payload=asdict(stroke),
            )

    def undo(self) -> None:
        if not self._undo_stack:
            return
        cmd = self._undo_stack.pop()
        cmd.undo()
        self._redo_stack.append(cmd)

    def redo(self) -> None:
        if not self._redo_stack:
            return
        cmd = self._redo_stack.pop()
        cmd.execute()
        self._undo_stack.append(cmd)

    # ---------------------------------------------------------------- Internal

    def _on_remote_stroke(self, payload: dict) -> None:
        try:
            stroke = Stroke(**payload)  # type: ignore[arg-type]
        except TypeError as exc:  # pragma: no cover
            LOG.warning("Received malformed stroke: %s", exc)
            return

        LOG.debug("Applying remote stroke id=%s", stroke.id)
        # Don't send back to bus
        self.add_stroke(stroke, push_remote=False)


# ────────────────────────────────────────────────────────────────────────────────
# View (Qt widget performing custom painting)
# ────────────────────────────────────────────────────────────────────────────────

class CanvasWidget(_QtW.QWidget):
    """
    CanvasWidget captures pointer events, builds Stroke objects, and renders
    the entire whiteboard contents.
    """

    def __init__(self, vm: "WhiteboardViewModel") -> None:
        super().__init__()
        self.setAttribute(_QtC.Qt.WA_StaticContents)
        self.setCursor(_QtG.QCursor(_QtC.Qt.CrossCursor))
        self._vm = vm

        self._current_path: _QtG.QPainterPath | None = None
        self._current_color: str = "#000000"
        self._current_width: float = 2.0

        self._vm.model.changed.connect(self.update)

    # ---------------------------------------------------------------- Events

    def mousePressEvent(self, event: _QtG.QMouseEvent) -> None:
        if event.button() != _QtC.Qt.LeftButton:
            return
        self._current_path = _QtG.QPainterPath(event.position())
        self.grabMouse()

    def mouseMoveEvent(self, event: _QtG.QMouseEvent) -> None:
        if self._current_path is None:
            return
        self._current_path.lineTo(event.position())
        self.update()

    def mouseReleaseEvent(self, event: _QtG.QMouseEvent) -> None:
        if event.button() != _QtC.Qt.LeftButton or self._current_path is None:
            return
        self._current_path.lineTo(event.position())

        points = [
            (p.x(), p.y()) for p in _sample_path(self._current_path)
        ]
        stroke = Stroke(
            id=str(uuid.uuid4()),
            points=points,
            color=self._current_color,
            width=self._current_width,
            author=_current_user_id(),
            timestamp=_QtC.QDateTime.currentMSecsSinceEpoch(),
        )
        self._vm.create_stroke(stroke)
        self._current_path = None
        self.releaseMouse()

    def paintEvent(self, event: _QtG.QPaintEvent) -> None:
        painter = _QtG.QPainter(self)
        painter.fillRect(event.rect(), _QtG.QColor("white"))

        # Draw historic strokes
        for stroke in self._vm.model.strokes():
            _draw_stroke(painter, stroke)

        # Draw current path preview
        if self._current_path is not None:
            pen = _QtG.QPen(_QtG.QColor(self._current_color),
                            self._current_width,
                            _QtC.Qt.SolidLine, _QtC.Qt.RoundCap,
                            _QtC.Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(self._current_path)


# ────────────────────────────────────────────────────────────────────────────────
# ViewModel
# ────────────────────────────────────────────────────────────────────────────────

class WhiteboardViewModel(_QtC.QObject):
    """
    Connects the GUI (View) to the underlying Model and orchestrates commands.
    """
    def __init__(self, model: WhiteboardModel) -> None:
        super().__init__()
        self.model = model

    @_QtC.Slot(Stroke)
    def create_stroke(self, stroke: Stroke) -> None:
        self.model.add_stroke(stroke)


# ────────────────────────────────────────────────────────────────────────────────
# Main Window (shell around canvas, toolbars, status bar, etc.)
# ────────────────────────────────────────────────────────────────────────────────

class WhiteboardWindow(_QtW.QMainWindow):
    """Host window with a toolbar and the drawing canvas."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self.setWindowTitle("FlockDesk – Whiteboard")
        self.resize(900, 600)

        self._model = WhiteboardModel(bus=bus)
        self._vm = WhiteboardViewModel(self._model)
        self._canvas = CanvasWidget(self._vm)

        self.setCentralWidget(self._canvas)
        self._create_toolbar()
        self._create_shortcuts()

    # ---------------------------------------------------------------- Helpers

    def _create_toolbar(self) -> None:
        toolbar = self.addToolBar("Tools")
        toolbar.setMovable(False)

        # Undo
        undo_act = _QtG.QAction(_QtG.QIcon.fromTheme("edit-undo"), "Undo", self)
        undo_act.triggered.connect(self._model.undo)
        toolbar.addAction(undo_act)

        # Redo
        redo_act = _QtG.QAction(_QtG.QIcon.fromTheme("edit-redo"), "Redo", self)
        redo_act.triggered.connect(self._model.redo)
        toolbar.addAction(redo_act)

    def _create_shortcuts(self) -> None:
        _QtG.QShortcut(_QtG.QKeySequence.Undo, self, activated=self._model.undo)
        _QtG.QShortcut(_QtG.QKeySequence.Redo, self, activated=self._model.redo)


# ────────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ────────────────────────────────────────────────────────────────────────────────

def _draw_stroke(painter: _QtG.QPainter, stroke: Stroke) -> None:
    pen = _QtG.QPen(_QtG.QColor(stroke.color), stroke.width,
                    _QtC.Qt.SolidLine, _QtC.Qt.RoundCap, _QtC.Qt.RoundJoin)
    painter.setPen(pen)

    path = _QtG.QPainterPath()
    if not stroke.points:
        return
    path.moveTo(*stroke.points[0])
    for x, y in stroke.points[1:]:
        path.lineTo(x, y)
    painter.drawPath(path)


def _sample_path(path: _QtG.QPainterPath, *, step: float = 2.0) -> list[_QtG.QPointF]:
    """Convert QPainterPath to a list of points with a given sampling step."""
    length = int(path.length())
    return [
        path.pointAtPercent(min(1.0, i / max(length, 1)))
        for i in range(0, length + 1, int(step))
    ]


def _current_user_id() -> str:
    # In production this would query the profile service
    return "local-user"


# ────────────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────────────

def _ensure_resources() -> None:
    """Create resource directories so the app can write logs/configs."""
    res_dir = Path.home() / ".flockdesk" / "whiteboard"
    res_dir.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Entrypoint for the whiteboard micro front-end process."""
    _ensure_resources()

    _QtC.QCoreApplication.setOrganizationName("FlockDesk")
    _QtC.QCoreApplication.setOrganizationDomain("flockdesk.io")

    app = _QtW.QApplication(sys.argv)
    bus = EventBus()  # In production the core passes a singleton instance
    window = WhiteboardWindow(bus)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
```
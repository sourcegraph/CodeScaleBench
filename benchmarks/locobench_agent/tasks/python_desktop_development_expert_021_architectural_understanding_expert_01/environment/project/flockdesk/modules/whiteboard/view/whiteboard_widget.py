```python
"""
FlockDesk – Whiteboard Micro-Frontend
=====================================

View layer implementation for the collaborative whiteboard module.  The
widget exposes a canvas for free-hand drawing, basic shape tools, real-time
sync through the internal event-bus, and a drop target for whiteboard plug-in
widgets (e.g., sticky notes, timers, code snippets).

The public entry-point is `WhiteboardWidget`, a Qt/PySide6 `QWidget` that can
be embedded in a `QMainWindow` or any docking container provided by the host
shell.  It adheres to MVVM; state mutations are delegated to a
`WhiteboardViewModel` instance while the widget reacts to its *Qt signals*.

Author  :  FlockDesk Team
Created :  2024-06-01
"""

from __future__ import annotations

import importlib
import logging
import pathlib
import sys
import types
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, Optional, Tuple, Type

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QMouseEvent,
    QPainterPath,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAction,
    QFileDialog,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

# --------------------------------------------------------------------------- #
# Local FlockDesk imports.
# --------------------------------------------------------------------------- #
try:
    # Raises ImportError during isolated unit testing when the remaining
    # FlockDesk packages are not available.
    from flockdesk.common.event_bus import EventBus, SubscriptionHandle
    from flockdesk.modules.whiteboard.viewmodel import WhiteboardViewModel
except ImportError:  # pragma: no cover
    # Minimal fallbacks that keep the file importable in isolation.
    class EventBus:  # type: ignore
        def subscribe(self, *_, **__) -> "SubscriptionHandle":
            return SubscriptionHandle(lambda: None)

        def publish(self, *_: object, **__: object) -> None: ...

    class SubscriptionHandle:  # type: ignore
        def __init__(self, unsubscribe):
            self._unsubscribe = unsubscribe

        def dispose(self):
            self._unsubscribe()

    class WhiteboardViewModel:  # type: ignore
        # Dummy signals for unit tests
        remoteStrokeAdded = Signal(QPainterPath, QPen)
        canvasCleared = Signal()

        # View calls
        def add_local_stroke(self, path: QPainterPath, pen: QPen) -> None: ...
        def clear(self) -> None: ...


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Constants / Enums
# --------------------------------------------------------------------------- #
class Tool(Enum):
    PEN = auto()
    ERASER = auto()
    # Additional tools can easily be added.


# --------------------------------------------------------------------------- #
# Utility dataclass for strokes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Stroke:
    path: QPainterPath
    pen: QPen


# --------------------------------------------------------------------------- #
# Canvas
# --------------------------------------------------------------------------- #
class WhiteboardCanvas(QGraphicsView):
    """
    A zoomable & pannable canvas that captures mouse events to create strokes.
    The canvas does not modify the application state directly.  Instead, it
    emits `strokeCreated` when the user finishes drawing a free-hand path.
    """

    strokeCreated = Signal(Stroke)

    _ZOOM_FACTOR = 1.25
    _MAX_ZOOM = 3.0
    _MIN_ZOOM = 0.2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self.setAcceptDrops(True)
        self.setRenderHints(
            self.renderHints()
            | self.viewportUpdateMode()
            | self.viewport().paintEngine().type()  # type: ignore[arg-type]
        )

        # Scene large enough for typical whiteboard use.
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(QRectF(-3000, -3000, 6000, 6000))
        self.setScene(self._scene)

        # Internal state
        self._tool: Tool = Tool.PEN
        self._current_path: Optional[QPainterPath] = None
        self._current_item: Optional[QGraphicsPathItem] = None
        self._current_pen: QPen = self._create_pen(color=Qt.black)

        self._zoom: float = 1.0
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

        logger.debug("WhiteboardCanvas initialized")

    # ------------- Configuration ------------- #

    @staticmethod
    def _create_pen(
        *, color: QColor | Qt.GlobalColor, width: int = 2, cosmetic: bool = True
    ) -> QPen:
        pen = QPen(color)
        pen.setWidth(width)
        pen.setCosmetic(cosmetic)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def set_tool(self, tool: Tool) -> None:
        logger.debug("Tool changed to %s", tool)
        self._tool = tool
        if tool == Tool.ERASER:
            self._current_pen = self._create_pen(color=Qt.white, width=14)
        else:
            self._current_pen = self._create_pen(color=Qt.black)

    # ------------- Scene Interaction ------------- #

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        logger.debug("Mouse press at %s", event.position())
        self._current_path = QPainterPath(event.position())
        self._current_item = QGraphicsPathItem()
        self._current_item.setPen(self._current_pen)
        self._current_item.setPath(self._current_path)
        self._scene.addItem(self._current_item)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._current_path and self._current_item:
            self._current_path.lineTo(event.position())
            self._current_item.setPath(self._current_path)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.LeftButton
            and self._current_path
            and self._current_item
        ):
            stroke = Stroke(path=self._current_path, pen=self._current_pen)
            self.strokeCreated.emit(stroke)
            logger.debug("Stroke created with %d points", stroke.path.elementCount())
            self._current_path = None
            self._current_item = None
        else:
            super().mouseReleaseEvent(event)

    # ------------- Zoom / Pan ------------- #

    def wheelEvent(self, event: QWheelEvent) -> None:
        angleDelta = event.angleDelta().y()
        if angleDelta == 0:
            return super().wheelEvent(event)

        factor = self._ZOOM_FACTOR if angleDelta > 0 else 1 / self._ZOOM_FACTOR
        new_zoom = self._zoom * factor
        if not (self._MIN_ZOOM <= new_zoom <= self._MAX_ZOOM):
            return

        self.scale(factor, factor)
        self._zoom = new_zoom
        logger.debug("Canvas zoom set to %.2f", self._zoom)

    # ------------- Drag-&-Drop (Plug-ins) ------------- #

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        logger.debug("Drag entered with formats: %s", event.mimeData().formats())
        if event.mimeData().hasFormat("application/x-flockdesk-plugin"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat("application/x-flockdesk-plugin"):
            module_path = event.mimeData().data("application/x-flockdesk-plugin").data()
            self._load_and_spawn_plugin(bytes(module_path).decode("utf-8"), event.position())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _load_and_spawn_plugin(self, dotted_path: str, pos: QPointF) -> None:
        """Dynamically load a plug-in class given its dotted path and add
        its visual representation to the scene."""
        try:
            module_name, class_name = dotted_path.rsplit(":", 1)
            module = importlib.import_module(module_name)
            plugin_cls: Type[QGraphicsPathItem] = getattr(module, class_name)  # type: ignore[assignment]
            plugin_item = plugin_cls()  # noqa: call-plugin-constructor
            plugin_item.setPos(pos)
            self._scene.addItem(plugin_item)
            logger.info("Plug-in %s added to whiteboard at %s", dotted_path, pos)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to load plug-in %s: %s", dotted_path, exc)
            QMessageBox.critical(
                self,
                self.tr("Plug-in Load Error"),
                self.tr(f"Could not load plug-in:\n{dotted_path}\n\n{exc}"),
            )

    # ------------- Public API for ViewModel ------------- #

    def add_remote_stroke(self, stroke: Stroke) -> None:
        item = QGraphicsPathItem()
        item.setPen(stroke.pen)
        item.setPath(stroke.path)
        self._scene.addItem(item)

    def clear(self) -> None:
        self._scene.clear()


# --------------------------------------------------------------------------- #
# Toolbar
# --------------------------------------------------------------------------- #
class WhiteboardToolBar(QToolBar):
    """A thin wrapper providing actions to change tools and perform common
    tasks (save PNG, clear, etc.)."""

    toolChanged = Signal(Tool)
    clearRequested = Signal()
    saveRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent=parent)
        self._make_actions()
        self.setIconSize(self.iconSize() * 0.8)  # Slightly smaller icons.

    # -------- Private helpers ------------------------------------------------ #

    def _make_actions(self) -> None:
        self._action_pen = self._create_action(
            "Pen",
            "draw-pen",
            checkable=True,
            checked=True,
            slot=lambda: self.toolChanged.emit(Tool.PEN),
        )
        self._action_eraser = self._create_action(
            "Eraser",
            "draw-eraser",
            checkable=True,
            slot=lambda: self.toolChanged.emit(Tool.ERASER),
        )
        self.addSeparator()
        self._action_clear = self._create_action(
            "Clear",
            "edit-clear",
            slot=self.clearRequested.emit,
        )
        self._action_save = self._create_action(
            "Save as PNG",
            "document-save",
            slot=self.saveRequested.emit,
        )

        # Group exclusive checkable tools
        self._action_pen.setActionGroup(self.addActionGroup())
        self._action_eraser.setActionGroup(self.addActionGroup())

    def _create_action(
        self,
        text: str,
        icon_name: str,
        *,
        checkable: bool = False,
        checked: bool = False,
        slot: types.FunctionType | None = None,
    ) -> QAction:
        action = QAction(QIcon.fromTheme(icon_name), text, self)
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(checked)
        if slot:
            action.triggered.connect(slot)
        self.addAction(action)
        return action


# --------------------------------------------------------------------------- #
# WhiteboardWidget (public entry-point)
# --------------------------------------------------------------------------- #
class WhiteboardWidget(QWidget):
    """
    View component for the whiteboard module.

    Responsibilities:
        • Renders the canvas and controls.
        • Binds user interaction to the ViewModel.
        • Listens to ViewModel signals to update UI.
        • Subscribes to the global EventBus for remote strokes.
    """

    # Exported for shell integration (window titles, etc.)
    DISPLAY_NAME = "Whiteboard"

    def __init__(
        self,
        vm: Optional[WhiteboardViewModel] = None,
        *,
        bus: Optional[EventBus] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent=parent)
        self._vm = vm or WhiteboardViewModel()  # Fallback dummy
        self._bus = bus or EventBus()

        self._tool_bar = WhiteboardToolBar(self)
        self._canvas = WhiteboardCanvas(self)

        self._subscriptions: list[SubscriptionHandle] = []

        self._setup_layout()
        self._connect_signals()
        self._subscribe_to_events()

        # Use the same background as the current Qt palette to support
        # dynamic theme switching.
        self._apply_current_palette()

        logger.debug("WhiteboardWidget instantiated")

    # ------------- Layout ---------------------------------------------------- #

    def _setup_layout(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self._tool_bar)
        vbox.addWidget(self._canvas)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------- Signal wiring -------------------------------------------- #

    def _connect_signals(self) -> None:
        # Canvas → ViewModel
        self._canvas.strokeCreated.connect(self._on_local_stroke)

        # Toolbar → Canvas / ViewModel
        self._tool_bar.toolChanged.connect(self._canvas.set_tool)
        self._tool_bar.clearRequested.connect(self._vm.clear)
        self._tool_bar.saveRequested.connect(self._save_to_png)

        # ViewModel → Canvas
        self._vm.remoteStrokeAdded.connect(self._canvas.add_remote_stroke)
        self._vm.canvasCleared.connect(self._canvas.clear)

    # ------------- EventBus -------------------------------------------------- #

    def _subscribe_to_events(self) -> None:
        # Remote strokes over the bus.
        self._subscriptions.append(
            self._bus.subscribe("whiteboard.stroke", self._on_bus_stroke)
        )
        # Theme change.
        self._subscriptions.append(
            self._bus.subscribe("system.theme.changed", self._on_theme_change)
        )

    # ------------- Event handlers ------------------------------------------- #

    @Slot(Stroke)
    def _on_local_stroke(self, stroke: Stroke) -> None:
        logger.debug("Dispatching local stroke to ViewModel")
        self._vm.add_local_stroke(stroke.path, stroke.pen)

    def _on_bus_stroke(self, payload: dict[str, object]) -> None:
        """Handle incoming strokes from other peers."""
        try:
            pathdata = payload["path"]
            peninfo = payload["pen"]
            stroke = Stroke(
                path=QPainterPath.fromData(bytes(pathdata)),  # type: ignore[arg-type]
                pen=QPen(QColor(peninfo["color"]), int(peninfo["width"])),
            )
            logger.debug("Received remote stroke via EventBus")
            self._canvas.add_remote_stroke(stroke)
        except Exception as exc:
            logger.exception("Malformed stroke payload %s: %s", payload, exc)

    def _on_theme_change(self, theme_name: str) -> None:  # pragma: no cover
        logger.info("Applying new theme %s", theme_name)
        self._apply_current_palette()

    # ------------- Toolbar helpers ------------------------------------------ #

    def _save_to_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save Whiteboard"),
            str(pathlib.Path.home() / "whiteboard.png"),
            self.tr("PNG Images (*.png)"),
        )
        if not path:
            return

        try:
            logger.debug("Saving whiteboard to %s", path)
            image_rect = self._canvas.sceneRect()
            image = self._canvas.grab(image_rect.toRect())  # type: ignore[arg-type]
            if not image.save(path):
                raise IOError("Saving failed")

            # Notify other modules
            self._bus.publish(
                "whiteboard.export.saved",
                {"path": path, "user": self._get_current_user()},
            )
        except Exception as exc:  # pragma: no cover
            QMessageBox.critical(self, self.tr("Save Error"), str(exc))
            logger.exception("Failed to save whiteboard: %s", exc)

    # ------------- Cleanup --------------------------------------------------- #

    def closeEvent(self, event) -> None:  # noqa: D401 – Qt override
        logger.debug("WhiteboardWidget closing, disposing subscriptions")
        for handle in self._subscriptions:
            handle.dispose()
        self._subscriptions.clear()
        super().closeEvent(event)

    # ------------- Helpers --------------------------------------------------- #

    def _apply_current_palette(self) -> None:
        # Synchronize the canvas background with the QApplication palette to
        # support theme-switching at runtime.
        pal = self.palette()
        self._canvas.setBackgroundBrush(pal.window().color())

    @staticmethod
    def _get_current_user() -> str:
        # Placeholder until full auth module is plugged in
        return sys.getlogin() or "Anonymous"
```
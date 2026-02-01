```python
"""
flockdesk.shared.widgets.avatar_widget
--------------------------------------

Reusable widget that displays (and manages) a user’s avatar picture with
real-time presence indication, theme awareness, drag-and-drop support and an
extensible context-menu.

The widget is intended to be used throughout the FlockDesk desktop client:
in chat lists, white-board collaborators, community dashboards, etc.

Typical usage
~~~~~~~~~~~~~
avatar = AvatarWidget(
    user_id="42",
    event_bus=inject.instance(EventBus),          # optional
    theme_manager=inject.instance(ThemeManager),  # optional
)
"""

from __future__ import annotations

import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (QEvent, QPoint, QRunnable, QSize, Qt, QThreadPool,
                            QUrl, Signal, Slot)
from PySide6.QtGui import (QAction, QContextMenuEvent, QDragEnterEvent,
                           QDropEvent, QIcon, QImage, QMouseEvent, QPainter,
                           QPixmap)
from PySide6.QtWidgets import (QFileDialog, QMenu, QMessageBox, QWidget)

__all__ = ["AvatarWidget"]

log = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# (Optional) third-party FlockDesk services
# -----------------------------------------------------------------------------


class _DummyBus:
    """Stand-in for the real application-wide EventBus (if not imported)."""

    def subscribe(self, *_a, **_kw):
        pass

    def publish(self, *_a, **_kw):
        pass


class _DummyTheme:
    """Stand-in for the real ThemeManager (hot-swappable themes)."""

    def color(self, key: str, fallback: str = "#CCCCCC") -> str:
        return fallback


try:
    from flockdesk.core.event_bus import EventBus
except Exception:  # pragma: no cover
    EventBus = _DummyBus  # type: ignore


try:
    from flockdesk.core.theme import ThemeManager
except Exception:  # pragma: no cover
    ThemeManager = _DummyTheme  # type: ignore


# -----------------------------------------------------------------------------
# Pixmap caching helpers
# -----------------------------------------------------------------------------


class _PixmapCache:
    """
    Very small LRU cache that stores pixmaps keyed by absolute path.
    Prevents re-decoding identical images when the avatar is shown in multiple
    locations at once.
    """

    _MAX_ENTRIES = 32
    _store: OrderedDict[str, QPixmap] = OrderedDict()

    @classmethod
    def get(cls, path: str) -> Optional[QPixmap]:
        try:
            pixmap = cls._store.pop(path)
            cls._store[path] = pixmap  # move to end (most recently used)
            return pixmap
        except KeyError:
            return None

    @classmethod
    def put(cls, path: str, pixmap: QPixmap) -> None:
        cls._store[path] = pixmap
        cls._store.move_to_end(path)
        # evict least recently used
        while len(cls._store) > cls._MAX_ENTRIES:
            cls._store.popitem(last=False)


# -----------------------------------------------------------------------------
# Asynchronous loader used to decode / scale the avatar off the UI thread
# -----------------------------------------------------------------------------


class _AvatarLoader(QRunnable):
    """
    Decode and scale a QPixmap in a thread-pool to avoid UI jank when very
    large images are supplied.
    """

    def __init__(
        self,
        path: str,
        target_size: QSize,
        on_loaded: "Signal[QPixmap]",
    ) -> None:
        super().__init__()
        self._path = path
        self._target_size = target_size
        self._on_loaded = on_loaded

    def run(self) -> None:  # noqa: D401
        try:
            image = QImage(self._path)
            if image.isNull():
                raise ValueError(f"Unable to load image: {self._path}")

            # Preserve aspect ratio, crop to square, then scale
            side = min(image.width(), image.height())
            cropped = image.copy(
                (image.width() - side) // 2,
                (image.height() - side) // 2,
                side,
                side,
            )
            scaled = cropped.scaled(
                self._target_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            pixmap = QPixmap.fromImage(scaled)
            _PixmapCache.put(self._path, pixmap)
            self._on_loaded.emit(pixmap)
        except Exception:  # pragma: no cover
            log.exception("Failed to load avatar: %s", self._path)


# -----------------------------------------------------------------------------
# Avatar widget
# -----------------------------------------------------------------------------


class AvatarWidget(QWidget):
    """
    Displays a round avatar with an optional presence badge.

    Signals
    -------
    clicked: Signal[None]
        Emitted on left mouse click.
    avatarChanged: Signal[str]
        Emitted when the user changes his / her avatar locally.
    """

    clicked = Signal()
    avatarChanged = Signal(str)

    _DRAG_MIME_WHITELIST = {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }
    _DEFAULT_SIZE = 64

    def __init__(
        self,
        user_id: str,
        *,
        size: int | None = None,
        event_bus: Optional[EventBus] = None,
        theme_manager: Optional[ThemeManager] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)

        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(size or self._DEFAULT_SIZE, size or self._DEFAULT_SIZE))

        # dependencies
        self._user_id = user_id
        self._event_bus = event_bus or _DummyBus()
        self._theme = theme_manager or _DummyTheme()

        # runtime state
        self._avatar_path: Optional[str] = None
        self._pixmap: Optional[QPixmap] = None
        self._presence: str = "offline"  # offline, online, busy, away …
        self._thread_pool = QThreadPool.globalInstance()

        self._install_event_listeners()

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    def avatar(self) -> Optional[str]:
        """Return absolute path of current avatar (may be None)."""
        return self._avatar_path

    def presence(self) -> str:
        """Return the current presence key (online / busy / …)."""
        return self._presence

    @Slot(str)
    def set_avatar(self, path: str) -> None:
        """Update the avatar from the given image path."""
        path = os.path.abspath(path)
        if not os.path.exists(path):
            log.warning("Avatar path does not exist: %s", path)
            return

        self._avatar_path = path
        cached = _PixmapCache.get(path)
        if cached is not None:
            self._pixmap = cached
            self.update()
        else:
            loader = _AvatarLoader(
                path=path,
                target_size=self.size(),
                on_loaded=self._on_async_loaded,
            )
            self._thread_pool.start(loader)

    @Slot(str)
    def set_presence(self, state: str) -> None:
        """Update presence overlay, e.g. from the event-bus."""
        if state == self._presence:
            return
        self._presence = state
        self.update()

    # ---------------------------------------------------------------------
    # Event handling
    # ---------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: D401
        """Paint circular avatar with presence badge."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self._pixmap and not self._pixmap.isNull():
            painter.setBrush(Qt.NoBrush)
            path = self._rounded_rect_path()
            painter.setClipPath(path)
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            # fallback placeholder
            painter.setBrush(
                self._theme.color("avatar.background", "#8F8F8F")
            )
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(self.rect())

        self._draw_presence_indicator(painter)

    def mousePressEvent(self, event: QMouseEvent):  # noqa: D401
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: D401
        if any(fmt in event.mimeData().formats() for fmt in self._DRAG_MIME_WHITELIST):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):  # noqa: D401
        url: QUrl
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self._handle_new_avatar(Path(url.toLocalFile()))
                event.acceptProposedAction()
                return
        QMessageBox.warning(self, "Invalid file", "Please drop a local image file.")

    def contextMenuEvent(self, event: QContextMenuEvent):  # noqa: D401
        menu = QMenu(self)

        choose_action = QAction("Change avatar …", self)
        choose_action.triggered.connect(self._choose_avatar)
        menu.addAction(choose_action)

        menu.addSeparator()

        if self._avatar_path:
            reveal = QAction("Reveal in Explorer", self)
            reveal.triggered.connect(self._reveal_in_file_manager)
            menu.addAction(reveal)

        menu.exec(event.globalPos())

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _install_event_listeners(self) -> None:
        """
        Subscribe to application-wide events: theme change, presence updates
        for our user, etc.
        """
        # presence update
        if isinstance(self._event_bus, EventBus):
            self._event_bus.subscribe(
                "presence.changed",
                handler=lambda e: (
                    self.set_presence(e.payload["state"])
                    if e.payload.get("user_id") == self._user_id
                    else None
                ),
            )

        # theme hot reload
        if isinstance(self._theme, ThemeManager):
            self._theme.themeChanged.connect(lambda: self.update())  # type: ignore

    @Slot(QPixmap)
    def _on_async_loaded(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def _rounded_rect_path(self):
        """Returns a QPainterPath of a circle matching widget size."""
        from PySide6.QtGui import QPainterPath

        path = QPainterPath()
        path.addEllipse(self.rect())
        return path

    def _draw_presence_indicator(self, painter: QPainter) -> None:
        """Paint a small presence dot on bottom-right corner."""
        colors = {
            "online": "#4CAF50",
            "busy": "#F44336",
            "away": "#FFB300",
            "offline": "#9E9E9E",
        }
        radius = max(6, self.width() // 6)
        center = QPoint(self.width() - radius, self.height() - radius)

        painter.setPen(Qt.NoPen)
        painter.setBrush(colors.get(self._presence, "#9E9E9E"))
        painter.drawEllipse(center, radius, radius)

    # --------------------------------------------------------------
    # Context-menu actions
    # --------------------------------------------------------------

    def _choose_avatar(self) -> None:
        """Open file-dialog for user to pick a new avatar picture."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Avatar Picture",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if filename:
            self._handle_new_avatar(Path(filename))

    def _handle_new_avatar(self, path: Path) -> None:
        """Validate and persist the chosen avatar (drag-drop or file-dialog)."""
        if not path.exists():
            return
        if not path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            QMessageBox.warning(self, "Unsupported file", "File is not a supported image type.")
            return

        self.set_avatar(str(path))
        self.avatarChanged.emit(str(path))
        # Publish to event-bus so other processes may sync the change
        if isinstance(self._event_bus, EventBus):
            self._event_bus.publish(  # type: ignore
                "avatar.changed",
                user_id=self._user_id,
                path=str(path),
            )

    def _reveal_in_file_manager(self) -> None:
        """Platform-specific file manager reveal of the avatar file."""
        if not self._avatar_path:
            return
        try:
            if sys.platform.startswith("darwin"):
                from subprocess import call

                call(["open", "--", self._avatar_path])
            elif os.name == "nt":
                os.startfile(self._avatar_path)  # type: ignore  # pylint: disable=protected-access
            else:  # linux, etc.
                from subprocess import call

                call(["xdg-open", self._avatar_path])
        except Exception:  # pragma: no cover
            log.exception("Could not open file manager for %s", self._avatar_path)
```
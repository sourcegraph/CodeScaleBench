```python
"""
flockdesk.modules.chat.view.chat_widget
=======================================

Qt‐based *view* component for the Chat micro-frontend.  Implements the visual
layer of the MVVM triad and communicates with the associated `ChatViewModel`
via Qt signals/slots.  The widget keeps itself in sync with application state
changes delivered over the internal EventBus and exposes extension points for
runtime plugin injection.

The code does not try to provide a full chat implementation; instead it
focuses on a realistic, production-grade skeleton that can be expanded by the
larger FlockDesk host application.
"""
from __future__ import annotations

import logging
import pathlib
import typing as _t

from PySide6 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------- #
# Typing helpers / forward declarations
# --------------------------------------------------------------------------- #
if _t.TYPE_CHECKING:  # pragma: no cover – only executed by type checkers
    from flockdesk.common.event_bus import EventBus
    from flockdesk.modules.chat.viewmodel.chat_viewmodel import ChatViewModel
    from flockdesk.modules.chat.model.message import ChatMessage


_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Command objects – small helpers to keep business logic out of the view
# --------------------------------------------------------------------------- #
class SendMessageCommand(QtCore.QObject):
    """
    Encapsulates the “send message” action in a command object so that it can be
    reused by toolbars, menu entries and keyboard shortcuts without duplicating
    logic all over the place.
    """

    # Emitted after the command has been executed.  The *success* flag signals
    # whether the operation completed without an exception.
    executed = QtCore.Signal(bool)

    def __init__(self, vm: 'ChatViewModel', parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._vm = vm

    # The command pattern: a single `__call__` entry point.
    @_LOGGER.catch  # type: ignore[attr-defined]  # requires loguru or similar
    def __call__(self, text: str) -> None:  # pragma: no branch
        try:
            self._vm.post_message(text)
        except Exception as exc:  # noqa: BLE001 – broad except to flag failure
            _LOGGER.exception("Unable to post chat message")
            QtWidgets.QMessageBox.warning(
                None,  # top-level widget
                "Send failed",
                f"Could not send message:\n{exc}",
            )
            self.executed.emit(False)
        else:
            self.executed.emit(True)


# --------------------------------------------------------------------------- #
# View implementation
# --------------------------------------------------------------------------- #
class ChatWidget(QtWidgets.QWidget):
    """
    Graphical representation of the chat module.

    Parameters
    ----------
    view_model:
        Instance of :class:`~flockdesk.modules.chat.viewmodel.chat_viewmodel.ChatViewModel`
        that exposes domain data and high-level operations.
    event_bus:
        The host application’s event bus used for decoupled, intra-process
        communication.
    """

    # --------------------------------------------------------------------- #
    # Qt Designer-compatible constants
    # --------------------------------------------------------------------- #
    OBJECT_NAME: str = "FlockDesk::ChatWidget"
    MIME_TYPE_FILELIST: str = "text/uri-list"
    THEME_ROLE: QtCore.Qt.ItemDataRole = QtCore.Qt.UserRole + 1

    # --------------------------------------------------------------------- #
    # Construction
    # --------------------------------------------------------------------- #
    def __init__(
        self,
        view_model: 'ChatViewModel',
        event_bus: 'EventBus',
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(self.OBJECT_NAME)
        self.setAcceptDrops(True)

        self._vm = view_model
        self._bus = event_bus
        self._send_command = SendMessageCommand(view_model, self)

        self._setup_ui()
        self._connect_signals()
        self._subscribe_to_events()

        self._apply_theme(self._vm.current_theme)

    # ------------------------------------------------------------------ #
    # UI assembly
    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        """Builds child widgets and layouts."""
        # Message list
        self._list_view = QtWidgets.QListView(objectName="messagesView")
        self._list_view.setModel(self._vm.messages_model)
        self._list_view.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._list_view.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self._list_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._list_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        # Input area
        self._input_box = QtWidgets.QTextEdit(objectName="inputBox")
        self._input_box.setTabChangesFocus(True)
        self._input_box.setAcceptRichText(False)
        self._input_box.setPlaceholderText("Type a message…")

        self._send_btn = QtWidgets.QPushButton(
            QtGui.QIcon.fromTheme("mail-send"), "&Send", objectName="sendButton"
        )
        self._send_btn.setDefault(True)
        self._send_btn.setEnabled(False)

        # Plugin container where micro-UIs can dock at runtime
        self._plugin_container = QtWidgets.QStackedWidget(objectName="pluginContainer")
        self._plugin_container.setVisible(False)  # hidden until a plugin is added

        # Layouts
        bottom_bar = QtWidgets.QHBoxLayout()
        bottom_bar.setContentsMargins(0, 0, 0, 0)
        bottom_bar.addWidget(self._input_box, 1)
        bottom_bar.addWidget(self._send_btn)

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(self._list_view, 1)
        main_layout.addWidget(self._plugin_container, 0)
        main_layout.addLayout(bottom_bar)

    # ------------------------------------------------------------------ #
    # Signal wiring
    # ------------------------------------------------------------------ #
    def _connect_signals(self) -> None:
        """Connect GUI widgets to view-model and commands."""
        self._input_box.textChanged.connect(self._update_send_button_state)
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)

        # View-model → view updates
        self._vm.message_inserted.connect(self._scroll_to_bottom)
        self._vm.theme_changed.connect(self._apply_theme)

        # Shortcuts
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), self, activated=self._on_send_clicked)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Enter"), self, activated=self._on_send_clicked)
        QtGui.QShortcut(QtGui.QKeySequence("Esc"), self, activated=self._input_box.clear)

    # ------------------------------------------------------------------ #
    # Event-bus integration
    # ------------------------------------------------------------------ #
    def _subscribe_to_events(self) -> None:
        """
        Register event callbacks on the application’s event bus.  Unregistering
        is done in `closeEvent`.
        """

        def _on_global_theme_changed(theme: str) -> None:
            self._apply_theme(theme)

        self._bus.subscribe("ui.theme.changed", _on_global_theme_changed, owner=self)

    # ------------------------------------------------------------------ #
    # UI reactions
    # ------------------------------------------------------------------ #
    def _update_send_button_state(self) -> None:
        """Enables or disables the *Send* button depending on input content."""
        has_text = bool(self._input_box.toPlainText().strip())
        self._send_btn.setEnabled(has_text)

    @QtCore.Slot()
    def _on_send_clicked(self) -> None:
        """Trigger the *send message* command."""
        text = self._input_box.toPlainText().strip()
        if not text:
            return

        self._send_command(text)
        self._input_box.clear()

    @QtCore.Slot(QtCore.QPoint)
    def _on_context_menu(self, pos: QtCore.QPoint) -> None:
        """Context menu for message actions (copy, react, delete…)."""
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return

        message: 'ChatMessage' = index.data(QtCore.Qt.UserRole)  # type: ignore[assignment]
        menu = QtWidgets.QMenu(self)

        copy_act = menu.addAction(QtGui.QIcon.fromTheme("edit-copy"), "&Copy")
        delete_act = menu.addAction(QtGui.QIcon.fromTheme("edit-delete"), "&Delete Message")

        choice = menu.exec(self._list_view.mapToGlobal(pos))
        if choice == copy_act:
            QtGui.QGuiApplication.clipboard().setText(message.content)
        elif choice == delete_act:
            self._vm.delete_message(message)

    # ------------------------------------------------------------------ #
    # Style helpers
    # ------------------------------------------------------------------ #
    @QtCore.Slot(str)
    def _apply_theme(self, theme: str) -> None:
        """
        Applies style overrides based on the theme name.  In a real system,
        themes would probably be QSS files shipped by the branding team.
        """
        self.setProperty("theme", theme)
        self.style().polish(self)

    # ------------------------------------------------------------------ #
    # Scrolling helpers
    # ------------------------------------------------------------------ #
    def _scroll_to_bottom(self) -> None:
        """Ensures the latest message is visible."""
        # QTextListView’s default behaviour can be jerky; we enforce a smooth
        # scroll to the end of the viewport.
        scrollbar = self._list_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------ #
    # Drag & drop integration
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:  # noqa: N802
        """Accept file drops so users can attach images/documents."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            return

        paths = [pathlib.Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if paths:
            self._vm.attach_files(paths)

    # ------------------------------------------------------------------ #
    # Plugin API
    # ------------------------------------------------------------------ #
    @_t.final
    def attach_plugin(self, widget: QtWidgets.QWidget, *, plugin_id: str) -> None:
        """
        Mounts an external plugin view inside the chat window.  The plugin
        receives ownership of its widget but the life-cycle is still managed
        by ChatWidget.

        Parameters
        ----------
        widget:
            The Qt widget that represents the plugin’s UI surface.
        plugin_id:
            Unique identifier used to track and remove the plugin later.
        """
        widget.setProperty("plugin_id", plugin_id)
        self._plugin_container.addWidget(widget)
        self._plugin_container.setCurrentWidget(widget)
        self._plugin_container.setVisible(True)

        _LOGGER.info("Plugin %s attached to ChatWidget", plugin_id)

    @_t.final
    def detach_plugin(self, plugin_id: str) -> None:
        """Removes a previously attached plugin from the view."""
        for i in range(self._plugin_container.count()):
            page = self._plugin_container.widget(i)
            if page.property("plugin_id") == plugin_id:
                self._plugin_container.removeWidget(page)
                page.deleteLater()
                break

        visible = self._plugin_container.count() > 0
        self._plugin_container.setVisible(visible)

        _LOGGER.info("Plugin %s detached from ChatWidget", plugin_id)

    # ------------------------------------------------------------------ #
    # Qt life-cycle
    # ------------------------------------------------------------------ #
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        """Clean up Bus subscriptions to avoid dangling callbacks."""
        self._bus.unsubscribe_owner(self)
        super().closeEvent(event)
```
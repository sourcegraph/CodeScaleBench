```python
"""
FlockDesk – Poll Plugin
~~~~~~~~~~~~~~~~~~~~~~~

This file implements a standalone, hot-pluggable “Poll” widget that can be
dropped into any running FlockDesk workspace.  It follows the MVVM pattern:

* PollModel:   Immutable data holder (dataclass)
* PollViewModel:  Observable view-model that owns the mutable state, exposes
                  commands, and emits Qt signals when something changes
* PollWidget (View):  The QWidget that users interact with

The widget takes care of:

* Creating / updating polls
* Casting votes (single-choice)
* Live result aggregation
* Notifying the global event-bus so that other clients stay in sync

The plugin is **self-registering** by exposing two module-level attributes
that FlockDesk’s plugin-loader looks for:

* PLUGIN_METADATA – information used in the extension gallery
* create_plugin(parent, **kwargs) – factory that returns a ready-to-use widget
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Event-Bus Abstraction                                                       #
# --------------------------------------------------------------------------- #

class _EventBusProxy(QtCore.QObject):
    """
    Thin wrapper around the real FlockDesk event-bus.

    The event-bus is optional at run-time: unit tests or a stripped-down
    environment may not have the core client loaded.  In that case we silently
    fall back to a local dispatcher so that the widget keeps working.
    """
    _instance: Optional["_EventBusProxy"] = None

    # Custom inline Qt signal for local fallback
    _local_dispatch = QtCore.Signal(dict)  # payload

    def __new__(cls) -> "_EventBusProxy":  # pragma: no cover
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        super().__init__()

        try:
            # Real client ships an injectable bus singleton
            from flockdesk.runtime import event_bus  # type: ignore
            self._bus = event_bus.get_default_bus()
            logger.debug("Connected to FlockDesk global event-bus.")
        except Exception as ex:  # pylint: disable=broad-except
            self._bus = None
            logger.warning(
                "Falling back to local event dispatcher – %s", ex, exc_info=False
            )
            self._local_dispatch.connect(self._noop_listener)

    # --------------------------------------------------------------------- #
    # Low-level API                                                         #
    # --------------------------------------------------------------------- #

    def publish(self, event_type: str, payload: dict) -> None:
        """
        Post an event on the bus.  Falls back to local dispatch if the
        client-bus is unavailable.
        """
        envelope = {"type": event_type, "payload": payload}
        if self._bus is not None:
            self._bus.publish(envelope)
        else:
            self._local_dispatch.emit(envelope)

    def subscribe(self, event_type: str, slot: QtCore.Slot) -> None:
        """
        Subscribe to an event type.  Only used for demo purposes within this
        plugin so we attach to the local dispatcher when necessary.
        """
        if self._bus is not None:
            self._bus.subscribe(event_type, slot)
        else:
            self._local_dispatch.connect(
                lambda envelope: slot(envelope)
                if envelope["type"] == event_type
                else None  # noqa: E731
            )

    # Dummy slot so that the signal has at least one receiver and won’t warn
    @QtCore.Slot(dict)
    def _noop_listener(self, _message: dict) -> None:  # pragma: no cover
        pass


EVENT_BUS = _EventBusProxy()

# --------------------------------------------------------------------------- #
# Domain Model                                                                #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class PollOption:
    """Immutable representation of a choice inside a poll."""
    text: str
    votes: int = 0
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True, slots=True)
class PollModel:
    """
    Immutable poll state that can be shared across processes without
    race-conditions.  All mutations happen in `PollViewModel`.
    """
    question: str
    options: List[PollOption]
    author: str
    poll_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    closed: bool = False


# --------------------------------------------------------------------------- #
# View-Model                                                                  #
# --------------------------------------------------------------------------- #

class PollViewModel(QtCore.QObject):
    """
    Observable model that follows the Qt “signal-slot” philosophy.  Controllers
    (e.g. UI widgets) bind to its signals to stay in sync.
    """
    poll_updated = QtCore.Signal(PollModel)
    error_occurred = QtCore.Signal(str)

    def __init__(self, poll: PollModel):
        super().__init__()
        self._poll = poll

        # Subscribe to remote votes so that this VM stays in sync
        EVENT_BUS.subscribe(
            "poll.vote",
            self._on_external_vote,
        )
        EVENT_BUS.subscribe(
            "poll.close",
            self._on_external_close,
        )

    # --------------------------------------------------------------------- #
    # Properties                                                            #
    # --------------------------------------------------------------------- #

    @property
    def poll(self) -> PollModel:
        return self._poll

    # --------------------------------------------------------------------- #
    # Command API                                                           #
    # --------------------------------------------------------------------- #

    @QtCore.Slot(int)
    def cast_vote(self, option_index: int) -> None:
        """
        Register a local vote and propagate it through the event-bus.
        """
        if self._poll.closed:
            self.error_occurred.emit("This poll is already closed.")
            return

        if option_index < 0 or option_index >= len(self._poll.options):
            self.error_occurred.emit("Invalid option selected.")
            return

        logger.info(
            "Casting vote – poll=%s option_index=%d", self._poll.poll_id, option_index
        )

        # Update local state first
        self._apply_vote(option_index)

        # Broadcast to peers
        EVENT_BUS.publish(
            "poll.vote",
            {
                "poll_id": self._poll.poll_id,
                "option_index": option_index,
            },
        )

    @QtCore.Slot()
    def close(self) -> None:
        """Close the poll for further voting."""
        if self._poll.closed:
            return

        logger.info("Closing poll %s", self._poll.poll_id)
        self._poll = PollModel(
            question=self._poll.question,
            options=self._poll.options.copy(),
            author=self._poll.author,
            poll_id=self._poll.poll_id,
            closed=True,
        )
        self.poll_updated.emit(self._poll)

        # Tell everybody else
        EVENT_BUS.publish(
            "poll.close",
            {
                "poll_id": self._poll.poll_id,
            },
        )

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #

    def _apply_vote(self, option_index: int) -> None:
        updated_options = [
            PollOption(
                text=o.text,
                votes=(o.votes + 1 if idx == option_index else o.votes),
                id=o.id,
            )
            for idx, o in enumerate(self._poll.options)
        ]

        self._poll = PollModel(
            question=self._poll.question,
            options=updated_options,
            author=self._poll.author,
            poll_id=self._poll.poll_id,
            closed=self._poll.closed,
        )
        self.poll_updated.emit(self._poll)

    # --------------------------------------------------------------------- #
    # Remote event handlers                                                 #
    # --------------------------------------------------------------------- #

    @QtCore.Slot(dict)
    def _on_external_vote(self, message: dict) -> None:
        """
        Another client has voted – integrate it locally.
        Expected payload:
            {
                "poll_id": "<uuid>",
                "option_index": <int>,
            }
        """
        payload = message.get("payload", {})
        if payload.get("poll_id") != self._poll.poll_id:
            return  # Ignore; not our poll

        option_index = payload.get("option_index")
        if isinstance(option_index, int):
            logger.debug(
                "Received external vote – poll=%s option=%d",
                self._poll.poll_id,
                option_index,
            )
            # Update without re-broadcasting
            self._apply_vote(option_index)

    @QtCore.Slot(dict)
    def _on_external_close(self, message: dict) -> None:
        """
        Another client closed the poll.
        """
        payload = message.get("payload", {})
        if payload.get("poll_id") != self._poll.poll_id:
            return

        if not self._poll.closed:
            logger.debug("Received remote close for poll %s", self._poll.poll_id)
            self.close()


# --------------------------------------------------------------------------- #
# UI (View)                                                                   #
# --------------------------------------------------------------------------- #

class PollWidget(QtWidgets.QWidget):
    """
    The visual, interactive layer of the Poll plugin.
    """

    def __init__(self, poll: PollModel, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setObjectName("PollWidget")

        # View-Model
        self._vm = PollViewModel(poll)
        self._vm.poll_updated.connect(self._render)
        self._vm.error_occurred.connect(self._show_error)

        # UI
        self._question_label = QtWidgets.QLabel(poll.question)
        self._question_label.setObjectName("questionLabel")
        self._question_label.setWordWrap(True)
        self._question_label.setStyleSheet("font-weight: bold;")

        self._options_group = QtWidgets.QButtonGroup(self)
        self._options_layout = QtWidgets.QVBoxLayout()

        # Results bars (created dynamically)
        self._result_bars: List[QtWidgets.QProgressBar] = []

        # Admin controls
        self._close_button = QtWidgets.QPushButton("Close Poll")
        self._close_button.clicked.connect(self._vm.close)

        # Layout
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(self._question_label)
        root.addLayout(self._options_layout)
        root.addWidget(self._close_button)

        self._render(poll)  # Initial populate

        # Disable close button for non-authors (demo logic)
        if poll.author != QtCore.QDir.home().dirName():  # placeholder check
            self._close_button.setDisabled(True)

    # ------------------------------------------------------------------ #
    # Rendering                                                          #
    # ------------------------------------------------------------------ #

    @QtCore.Slot(PollModel)
    def _render(self, poll: PollModel) -> None:
        """
        Rebuild the option buttons *and* the live result bars each time the
        model changes.  Keeping it simple for now; large polls could be diffed.
        """
        # Guard: Remove all previous widgets in the options layout
        while self._options_layout.count():
            item = self._options_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._options_group.setExclusive(True)
        self._options_group.buttonClicked[int].disconnect() if self._options_group.receivers(  # type: ignore
            self._options_group.buttonClicked[int]
        ) else None
        self._options_group = QtWidgets.QButtonGroup(self)

        total_votes = sum(o.votes for o in poll.options) or 1  # avoid div/0
        self._result_bars.clear()

        for idx, opt in enumerate(poll.options):
            # Row container
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)

            # Radio button for voting (disabled when closed)
            radio = QtWidgets.QRadioButton(opt.text)
            radio.setEnabled(not poll.closed)
            self._options_group.addButton(radio, id=idx)

            row.addWidget(radio, stretch=3)

            # Result bar
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, total_votes)
            bar.setValue(opt.votes)
            bar.setFormat(f"{opt.votes} votes – %p%")
            bar.setTextVisible(True)
            bar.setFixedHeight(18)
            bar.setStyleSheet("QProgressBar { text-align: center; }")
            self._result_bars.append(bar)
            row.addWidget(bar, stretch=2)

            self._options_layout.addLayout(row)

        if not poll.closed:
            self._options_group.buttonClicked[int].connect(self._vm.cast_vote)

        # Close button state
        self._close_button.setDisabled(poll.closed)

    # ------------------------------------------------------------------ #
    # Error handling                                                     #
    # ------------------------------------------------------------------ #

    @QtCore.Slot(str)
    def _show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.warning(self, "Poll Error", message)


# --------------------------------------------------------------------------- #
# Plugin registration                                                         #
# --------------------------------------------------------------------------- #

PLUGIN_METADATA = {
    "id": "poll_plugin",
    "name": "Polls",
    "description": "Create real-time polls inside FlockDesk rooms.",
    "version": "1.0.0",
    "author": "FlockDesk Team",
    "entry_point": "plugins_available.poll_plugin.poll_widget",
}


def create_plugin(
    parent: Optional[QtWidgets.QWidget] = None,
    *,
    question: str | None = None,
    options: Optional[List[str]] = None,
    author: str | None = None,
) -> QtWidgets.QWidget:
    """
    Factory required by FlockDesk's plugin loader.

    Example call:
        create_plugin(parent=someDock, question="Lunch option?",
                      options=["Pizza", "Sushi"], author="alice")

    The widget is *self-contained* and can be embedded in any docking area.
    """
    if not question or not options:
        raise ValueError("A poll requires a question and at least one option.")

    poll_model = PollModel(
        question=question,
        options=[PollOption(text=o) for o in options],
        author=author or QtCore.QDir.home().dirName(),
    )
    return PollWidget(poll_model, parent=parent)


# --------------------------------------------------------------------------- #
# Local testing                                                               #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":  # pragma: no cover
    import sys

    app = QtWidgets.QApplication(sys.argv)
    widget = create_plugin(
        question="What's your favourite programming language?",
        options=["Python", "Rust", "Go", "TypeScript"],
        author="local-test",
    )
    widget.setWindowTitle("Poll Plugin – Stand-alone Test")
    widget.resize(400, 200)
    widget.show()
    sys.exit(app.exec())
```
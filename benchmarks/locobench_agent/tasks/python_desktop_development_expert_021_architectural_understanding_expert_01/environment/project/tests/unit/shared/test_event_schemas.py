```python
"""
tests/unit/shared/test_event_schemas.py

Unit-tests that exercise the Pydantic event-schema layer used by FlockDesk’s
internal event bus.  The goal is to guarantee that:

1.  Required fields are enforced.
2.  Type coercion / validation behaves as expected.
3.  Optional fields remain optional.
4.  Events can be losslessly serialised ↔ deserialised.
5.  Defensive logic (e.g., value constraints) is respected.

These tests purposefully avoid any network / IPC concerns and focus purely on
the data-model contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

# -----------------------------------------------------------------------------
# Project imports – the concrete event models live inside the shared package.
# -----------------------------------------------------------------------------
from flockdesk.shared.event_schemas import (  # type: ignore
    ChatMessageEvent,
    EventEnvelope,
    PluginInitEvent,
    PresenceUpdateEvent,
)

# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _assert_validation_error(model_cls, payload: Dict[str, Any]) -> None:
    """
    Assert that feeding *payload* into *model_cls* raises a ValidationError.
    """
    with pytest.raises(ValidationError):
        model_cls.parse_obj(payload)


def _now_utc() -> datetime:
    """Return a timezone-aware utcnow().  Wrapped for patchability."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Parametrised examples – "golden paths"                                      #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "event_cls, kwargs",
    [
        (
            ChatMessageEvent,
            dict(
                event_id=uuid4(),
                sender_id=uuid4(),
                channel_id=uuid4(),
                content="Hello world 👋",
                timestamp=_now_utc(),
            ),
        ),
        (
            PresenceUpdateEvent,
            dict(
                event_id=uuid4(),
                user_id=uuid4(),
                presence="away",
                last_seen=_now_utc() - timedelta(minutes=4),
            ),
        ),
        (
            PluginInitEvent,
            dict(
                event_id=uuid4(),
                plugin_name="flockdesk-polls",
                version="2.3.1",
                requesting_user=uuid4(),
            ),
        ),
    ],
)
def test_event_roundtrip(event_cls, kwargs):
    """
    All event models must survive a JSON round-trip without data loss.

    1.   Build the model.
    2.   Convert to JSON.
    3.   Re-inflate using `.parse_raw`.
    4.   Expect equality (== uses Pydantic’s .dict()).
    """
    original = event_cls(**kwargs)

    json_blob = original.json()
    assert isinstance(json_blob, str) and json_blob.strip().startswith("{")

    restored = event_cls.parse_raw(json_blob)
    assert restored == original
    assert restored.dict() == original.dict()


# --------------------------------------------------------------------------- #
# Negative testing                                                            #
# --------------------------------------------------------------------------- #

def test_chat_message_missing_required():
    """
    Omitting *content* should fail, because content is mandatory.
    """
    bad_payload = {
        "event_id": str(uuid4()),
        "sender_id": str(uuid4()),
        "channel_id": str(uuid4()),
        "timestamp": _now_utc().isoformat(),
    }
    _assert_validation_error(ChatMessageEvent, bad_payload)


@pytest.mark.parametrize(
    "bad_presence",
    ["", "busy-ish", None, 42],
)
def test_presence_rejects_invalid_states(bad_presence):
    """
    PresenceUpdateEvent.presence must be one of the enumerated literals.
    """
    bad_payload = {
        "event_id": str(uuid4()),
        "user_id": str(uuid4()),
        "presence": bad_presence,
        "last_seen": _now_utc().isoformat(),
    }
    _assert_validation_error(PresenceUpdateEvent, bad_payload)


def test_plugin_init_version_semver_only():
    """
    PluginInitEvent.version must follow simple semantic-versioning: #.#.#.
    """
    bad_payload = {
        "event_id": str(uuid4()),
        "plugin_name": "cool-plugin",
        "version": "2023-10-31",  # not valid semver
        "requesting_user": str(uuid4()),
    }
    _assert_validation_error(PluginInitEvent, bad_payload)


# --------------------------------------------------------------------------- #
# EventEnvelope                                                               #
# --------------------------------------------------------------------------- #

def test_envelope_assigns_defaults():
    """
    EventEnvelope should auto-populate `sent_at` if the caller leaves it out.
    """
    payload = {
        "id": str(uuid4()),
        "topic": "chat.message",
        "payload": {
            "event_id": str(uuid4()),
            "sender_id": str(uuid4()),
            "channel_id": str(uuid4()),
            "content": "auto-timestamp demo",
            "timestamp": _now_utc().isoformat(),
        },
    }

    envelope = EventEnvelope.parse_obj(payload)

    # sent_at must exist and be within ≤ 1 second of "now"
    assert envelope.sent_at is not None
    assert abs((envelope.sent_at - _now_utc()).total_seconds()) <= 1

    # The nested payload should transparently coerce into its event model
    assert isinstance(envelope.payload, ChatMessageEvent)
    assert envelope.topic == "chat.message"


# --------------------------------------------------------------------------- #
# Hypothesis property-based testing                                           #
# --------------------------------------------------------------------------- #

# Hypothesis strategy for timezone-aware UTC datetimes
aware_datetimes = st.datetimes(
    min_value=datetime(2022, 1, 1, tzinfo=timezone.utc),
    max_value=datetime(2099, 1, 1, tzinfo=timezone.utc),
    timezones=st.just(timezone.utc),
)

# Basic text limited to reasonable chat-message lengths
chat_text = st.text(
    min_size=1,
    max_size=512,
    alphabet=st.characters(blacklist_categories=("Cs",)),
)

@given(
    event_id=st.builds(uuid4),
    sender_id=st.builds(uuid4),
    channel_id=st.builds(uuid4),
    content=chat_text,
    timestamp=aware_datetimes,
)
@settings(deadline=None)  # chat_text can be large; avoid flaky timeouts
def test_chat_message_property_based(event_id, sender_id, channel_id, content, timestamp):
    """
    Property-based test: any alphabetic string should result in a valid event
    model that keeps invariants after a serialise → deserialise cycle.
    """
    event = ChatMessageEvent(
        event_id=event_id,
        sender_id=sender_id,
        channel_id=channel_id,
        content=content,
        timestamp=timestamp,
    )
    # Round-trip via dict / JSON
    reconstructed = ChatMessageEvent.parse_raw(event.json())
    assert reconstructed == event
    assert isinstance(reconstructed.event_id, UUID)
    assert reconstructed.content == content


# --------------------------------------------------------------------------- #
# Edge-cases                                                                  #
# --------------------------------------------------------------------------- #

def test_chat_message_allows_markdown():
    """
    The *content* field should allow Markdown-style characters – no sanitation
    is performed at the schema layer (left for rendering pipeline).
    """
    md_payload = {
        "event_id": uuid4(),
        "sender_id": uuid4(),
        "channel_id": uuid4(),
        "content": "**bold _italic_ ~strikethrough~** `code`",
        "timestamp": _now_utc(),
    }
    event = ChatMessageEvent(**md_payload)
    assert "**bold" in event.content
    assert event.content.startswith("**")


def test_envelope_rejects_non_uuid_id():
    """
    Envelope.id must be a UUID – strings that do not parse must fail.
    """
    bad_payload = {
        "id": "not-a-uuid",
        "topic": "presence.update",
        "payload": {
            "event_id": str(uuid4()),
            "user_id": str(uuid4()),
            "presence": "online",
            "last_seen": _now_utc().isoformat(),
        },
    }
    _assert_validation_error(EventEnvelope, bad_payload)
```
```python
"""
Unit-tests for the user-facing settings subsystem.

The real implementation (flockdesk.core.settings.service.SettingsService)
is expected to:

1. Persist user settings as JSON files in an XDG-compatible config dir.
2. Publish ‘settings.changed’ and ‘settings.saved’ events on the internal
   event-bus whenever a preference changes or is explicitly persisted.
3. Provide optimistic defaults when no disk-backing exists.
4. Be thread-safe – concurrent writes must not corrupt the on-disk file.
5. Transparently upgrade a legacy schema to the current one via a
   migration pipeline.

These tests focus on the public contract.  Internal implementation
details are stubbed/mocked so the test-suite stays backwards-compatible
to refactors, as long as the contract holds.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from threading import Event
from typing import Any, Dict, List

import json
import os
import time
from uuid import uuid4

import pytest

# --------------------------------------------------------------------------- #
# Test doubles                                                                
# --------------------------------------------------------------------------- #


class _RecorderBus:
    """
    Extremely small in-mem replacement for the production event bus.

    The real bus offers ``.publish(topic: str, payload: dict)`` and
    ``.subscribe(topic, cb)``.  For unit-testing we only need ‘publish’.
    """

    def __init__(self) -> None:
        self._messages: List[tuple[str, dict]] = []

    # Production code normally awaits/awaits – keep sync for simplicity.
    def publish(self, topic: str, payload: dict | None = None) -> None:  # noqa: D401
        self._messages.append((topic, payload or {}))

    # Helper assertion API so we have readable failure output.
    def pop(self, topic: str) -> dict:
        if not self._messages:
            pytest.fail(f"No messages on bus – expected at least “{topic}”.")
        t, payload = self._messages.pop(0)
        assert (
            t == topic
        ), f"First message was topic={t!r} not expected {topic!r}.  Payload={payload!r}"
        return payload

    def topics(self) -> list[str]:
        return [t for t, _ in self._messages]


# --------------------------------------------------------------------------- #
# Fixtures                                                                    
# --------------------------------------------------------------------------- #


@pytest.fixture()
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Ensure every test receives an isolated configuration directory.

    SettingsService relies on XDG_CONFIG_HOME for disk persistence.
    """
    path = tmp_path / ".config"
    path.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(path))
    return path


@pytest.fixture()
def event_bus() -> _RecorderBus:
    return _RecorderBus()


@pytest.fixture()
def settings_service(
    event_bus: _RecorderBus, config_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    Return a fully-wired SettingsService that writes into *config_dir* and
    publishes onto the in-memory event bus.

    We patch-inject our in-mem bus on construction.  Any breaking change
    here means the public constructor changed – the test-suite will
    fail loudly.
    """
    from flockdesk.core.settings.service import SettingsService

    svc = SettingsService(event_bus=event_bus)  # type: ignore[arg-type]
    yield svc

    # Ensure we do not leak file-descriptors across tests.
    svc.close()  # The production API guarantees idempotent `.close()`.


# --------------------------------------------------------------------------- #
# Helpers                                                                     
# --------------------------------------------------------------------------- #


def _read_raw_settings_from_disk(profile_id: str) -> Dict[str, Any]:
    """
    Bypass the service layer – inspect the physical JSON as written.

    Used to verify persistence without coupling to internal caches.
    """
    xdg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "flockdesk"
    with open(xdg_dir / f"{profile_id}.json") as fp:
        return json.load(fp)


# --------------------------------------------------------------------------- #
# Test-cases                                                                  
# --------------------------------------------------------------------------- #


def test_loads_default_settings_when_profile_missing(settings_service):
    """
    When the user starts FlockDesk for the first time no settings file
    exists.  The service must transparently supply defaults and *not*
    throw.
    """
    profile_id = str(uuid4())  # Unlikely to collide with disk.

    # Sanity – no file on disk:
    xdg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "flockdesk"
    assert not (xdg_dir / f"{profile_id}.json").exists()

    settings = settings_service.load(profile_id)

    # Common defaults – adapt depending on production default schema.
    assert settings["appearance"]["theme"] == "light"
    assert settings["notifications"]["enabled"] is True

    # A first load must broadcast – view-models will subscribe so they can
    # rebind instantly after bootstrap.
    payload = settings_service._event_bus.pop("settings.loaded")
    assert payload["profile_id"] == profile_id
    assert payload["cold_start"] is True


def test_save_settings_creates_file_and_emits_event(settings_service):
    """
    Explicitly persisting changes must write a JSON file and let other
    modules know the profile was updated.
    """
    profile_id = "work"

    updated = {
        "appearance": {"theme": "dark"},
        "hotkeys": {"toggle_command_palette": "Ctrl+P"},
    }

    settings = settings_service.load(profile_id)
    settings.update(updated)

    # Persist
    settings_service.save(profile_id)

    # Disk flush?
    raw = _read_raw_settings_from_disk(profile_id)
    for k, v in updated.items():
        assert raw[k] == v

    # Event?
    settings_service._event_bus.pop("settings.saved")


def test_change_setting_triggers_realtime_event(settings_service):
    """
    Mutating a single value should trigger an immediate ‘settings.changed’
    publish so that live components react within the same frame.
    """
    profile_id = "gaming"
    settings = settings_service.load(profile_id)

    # Toggle theme
    settings["appearance"]["theme"] = "midnight"

    # Implementation may debounce – give it a tiny bit of runtime.
    time.sleep(0.05)

    payload = settings_service._event_bus.pop("settings.changed")
    assert payload["profile_id"] == profile_id
    assert payload["path"] == ["appearance", "theme"]
    assert payload["value"] == "midnight"


def test_schema_upgrade_invoked_on_legacy_file(
    settings_service, monkeypatch: pytest.MonkeyPatch
):
    """
    If the on-disk schema is old the service must run the migrator once
    and bump the version.  We create a fake v0 file and spy on the
    migrator call.
    """
    profile_id = "legacy"
    xdg_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "flockdesk"
    xdg_dir.mkdir(exist_ok=True)

    legacy_blob = {
        "_meta": {"schema": 0},
        "theme": "old-value",
    }
    (xdg_dir / f"{profile_id}.json").write_text(json.dumps(legacy_blob))

    called = Event()

    def fake_migrate(data: dict) -> dict:  # noqa: D401
        called.set()
        # Pretend the migrator promotes to new structure.
        return {
            "_meta": {"schema": 1},
            "appearance": {"theme": data["theme"]},
        }

    monkeypatch.setattr(
        "flockdesk.core.settings.service.migrate_0_to_1",
        fake_migrate,
        raising=False,
    )

    settings = settings_service.load(profile_id)

    assert settings["appearance"]["theme"] == "old-value"
    assert called.is_set(), "Migrator was not executed."
    assert settings_service._event_bus.pop("settings.upgraded")["from"] == 0


def test_concurrent_saves_are_thread_safe(settings_service):
    """
    Spawning multiple threads that hammer ‘save()’ must not corrupt JSON.
    """
    profile_id = "stress"
    settings = settings_service.load(profile_id)

    #  Create some randomised prefs to churn through.
    variants = [
        {"appearance": {"theme": "light"}},
        {"appearance": {"theme": "dark"}},
        {"notifications": {"enabled": False}},
        {"notifications": {"enabled": True}},
    ]

    def worker(payload: dict):
        """
        Apply a set of changes and flush to disk.
        """
        settings.update(payload)
        settings_service.save(profile_id)

    with ThreadPoolExecutor(max_workers=8) as tp:
        futures = [tp.submit(worker, v) for v in variants * 25]
        wait(futures)  # noqa: S311

    # Make sure the last persisted JSON is STILL valid.
    raw = _read_raw_settings_from_disk(profile_id)
    assert isinstance(raw, dict)
    assert raw["_meta"]["schema"] >= 1, "Schema key lost during concurrent writes"


def test_invalid_json_on_disk_is_recovered(settings_service):
    """
    A power-failure may leave a half-written file.  The service must
    detect the JSON decode error, back-up the broken file and start
    afresh.
    """
    profile_id = "broken"
    xdg_file = (
        Path(os.environ["XDG_CONFIG_HOME"]) / "flockdesk" / f"{profile_id}.json"
    )
    xdg_file.parent.mkdir(exist_ok=True)
    xdg_file.write_text("{this is : not json")

    settings = settings_service.load(profile_id)

    # Should recover to defaults, and write a .bak file
    assert settings["appearance"]["theme"] == "light"
    assert xdg_file.with_suffix(".json.bak").exists()

    settings_service._event_bus.pop("settings.recovered")
```
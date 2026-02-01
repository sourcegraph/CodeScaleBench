```python
"""
flockdesk.shared.schemas.user_profile
====================================

Strongly-typed, versioned schema for persisting a user’s profile in FlockDesk.
The schema is expressed as nested Pydantic models to guarantee integrity,
provide automatic (de)serialization, and enable painless migrations when the
structure evolves.

The profile encapsulates:
    • Identity   – id, e-mail address, display name, avatar path
    • Preferences – theme, shortcuts, window layout, enabled plug-ins
    • Timestamps  – creation, last update, schema revision

The helper methods `save()` and `load()` make it trivial to persist and restore
profiles as UTF-8 JSON files.  When older documents are encountered, an
internal migration pipeline `_migrate()` upgrades them on-the-fly so the rest
of the application can rely on the latest shape.

This module has *no* external runtime dependencies outside of `pydantic`,
`uuid`, and the Python standard library.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError, root_validator, validator

__all__ = [
    "ThemeSettings",
    "ShortcutBinding",
    "KeyboardPreferences",
    "WindowGeometry",
    "WindowLayout",
    "PluginConfig",
    "UserPreferences",
    "UserProfile",
]

###############################################################################
# Low-level building blocks
###############################################################################


class ThemeSettings(BaseModel):
    """
    Visual styling preferences.

    Attributes
    ----------
    name
        Human-readable name of the theme.
    accent_color
        Hex triplet to use for accent highlights (validated).
    """

    name: str = Field("FlockDark", description="Name of the currently used theme.")
    accent_color: str = Field(
        "#1abc9c",
        regex=r"^#(?:[0-9a-fA-F]{3}){1,2}$",
        description="HEX RGB color (e.g. #RRGGBB) used for accent highlights.",
    )


class ShortcutBinding(BaseModel):
    """
    Represents one keyboard shortcut mapping.

    The `keys` field accepts multi-stroke definitions, e.g. `['Ctrl+Shift+P']`.
    """

    action: str = Field(..., description="Canonical action identifier.")
    keys: List[str] = Field(
        ...,
        min_items=1,
        description="Key sequence(s) that trigger the action.",
    )


class KeyboardPreferences(BaseModel):
    """Collection of user-defined keyboard shortcuts."""

    bindings: List[ShortcutBinding] = Field(
        default_factory=list, description="All custom keyboard bindings."
    )

    def get_binding_for_action(self, action: str) -> Optional[ShortcutBinding]:
        """
        Return the shortcut binding for a given action, if present.
        """
        return next((b for b in self.bindings if b.action == action), None)


class WindowGeometry(BaseModel):
    """
    Geometry description for a single window or dock widget.
    """

    x: int
    y: int
    width: int
    height: int
    is_maximized: bool = Field(
        False, description="Whether the window was maximised when saved."
    )

    @validator("*", pre=True)
    def _ensure_int(cls, v: Any) -> int:
        """
        Pydantic sometimes passes `None` for missing fields, we make sure the
        geometry is always an integer ≥ 0 to avoid Qt warnings later.
        """
        if not isinstance(v, int) or v < 0:
            raise ValueError("Window geometry values must be non-negative integers.")
        return v


class WindowLayout(BaseModel):
    """
    Persisted layout for main and dock windows.
    """

    main_window: WindowGeometry
    dock_widgets: Dict[str, WindowGeometry] = Field(
        default_factory=dict,
        description="Mapping dock-widget-id -> geometry.",
    )


class PluginConfig(BaseModel):
    """
    Per-plug-in runtime state (enabled, custom settings, …).
    """

    id: str = Field(..., description="Fully-qualified plug-in identifier.")
    enabled: bool = Field(True, description="Is the plug-in enabled?")
    state: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque blob saved/restored by the plug-in itself.",
    )


###############################################################################
# High-level aggregated preferences
###############################################################################


class UserPreferences(BaseModel):
    """
    Root container for everything customisable by the user.
    """

    theme: ThemeSettings = Field(default_factory=ThemeSettings)
    keyboard: KeyboardPreferences = Field(default_factory=KeyboardPreferences)
    layout: WindowLayout
    plugins: List[PluginConfig] = Field(default_factory=list)
    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when preferences changed last.",
    )

    # Convenience helpers -----------------------------------------------------

    def plugin(self, plugin_id: str) -> Optional[PluginConfig]:
        """
        Fetch a plug-in configuration by id.
        """
        return next((p for p in self.plugins if p.id == plugin_id), None)

    def enable_plugin(self, plugin_id: str) -> None:
        """
        Enable (or add) a plug-in.
        """
        cfg = self.plugin(plugin_id)
        if cfg:
            cfg.enabled = True
        else:
            self.plugins.append(PluginConfig(id=plugin_id, enabled=True))

    def disable_plugin(self, plugin_id: str) -> None:
        """
        Disable a plug-in if it exists.
        """
        cfg = self.plugin(plugin_id)
        if cfg:
            cfg.enabled = False


###############################################################################
# Top-level profile
###############################################################################


class UserProfile(BaseModel):
    """
    Complete persisted user profile.

    The model is intentionally *not* immutable – live components mutate it, and
    we rely on Pydantic’s `validate_assignment` to keep things consistent.
    """

    # --------------------------------------------------------------------- Meta
    schema_version: int = Field(
        1,
        const=True,
        description="Monotonically increasing schema revision.",
    )

    # ---------------------------------------------------------------- Identity
    user_id: UUID = Field(default_factory=uuid4)
    email: str
    display_name: str
    avatar_path: Optional[str] = Field(
        None,
        description="File path or HTTPS URL to the avatar image.",
    )

    # -------------------------------------------------------------- Preferences
    preferences: UserPreferences = Field(
        default_factory=lambda: UserPreferences(
            layout=WindowLayout(
                main_window=WindowGeometry(
                    x=50,
                    y=50,
                    width=1280,
                    height=800,
                    is_maximized=False,
                )
            )
        )
    )

    # ------------------------------------------------------------------- Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------ Config
    class Config:
        validate_assignment = True
        json_encoders = {datetime: lambda dt: dt.replace(tzinfo=None).isoformat()}

    # ----------------------------------------------------------------- Hooks
    @validator("email")
    def _email_must_be_valid(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid e-mail address.")
        return v.strip().lower()

    @root_validator
    def _touch_updated_at(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Whenever the model is (re-)validated we update the timestamp so callers
        don’t have to remember doing it themselves.
        """
        values["updated_at"] = datetime.utcnow()
        return values

    # ---------------------------------------------------------------- Public
    # Persistence helpers .....................................................

    def save(self, path: str | Path) -> None:
        """
        Flush the profile to *path* as pretty-printed UTF-8 JSON.
        """
        path = Path(path)
        try:
            path.write_text(self.json(indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            raise IOError(f"Unable to write user profile to {path}: {exc}") from exc

    @classmethod
    def load(cls, path: str | Path) -> "UserProfile":
        """
        Load a profile from *path*, migrating older versions automatically.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"User profile not found: {path}")

        raw_json = path.read_text(encoding="utf-8")
        data = json.loads(raw_json)

        current_version = cls.__fields__["schema_version"].default
        stored_version = data.get("schema_version", 0)
        if stored_version != current_version:
            data = cls._migrate(data, from_version=stored_version)

        try:
            return cls.parse_obj(data)
        except ValidationError as exc:  # pragma: no cover
            raise ValueError(
                f"Corrupted profile '{path}':\n{exc}"
            ) from exc

    # Migration pipeline ......................................................

    @staticmethod
    def _migrate(payload: Dict[str, Any], *, from_version: int) -> Dict[str, Any]:
        """
        Upgrade *payload* to the latest schema version.

        Every `if` block is responsible for migrating *from* a specific older
        revision *to* the immediate next one.
        """
        migrated = dict(payload)  # shallow copy

        if from_version < 1:
            # ––– v0 ➜ v1 ––––––––––––––––––––––––––––––––––––––––––––––––––––
            #  • Ensure `display_name` exists (fallback to local-part of e-mail)
            #
            migrated.setdefault(
                "display_name",
                migrated.get("email", "User").split("@")[0].title(),
            )
            migrated["schema_version"] = 1

        return migrated

    # Convenience API .........................................................

    def update_preferences(self, **changes: Any) -> None:
        """
        Patch top-level keys of :class:`UserPreferences`.

        Examples
        --------
        >>> user.update_preferences(theme=ThemeSettings(name="Solarized"))
        """
        for key, value in changes.items():
            if not hasattr(self.preferences, key):
                raise AttributeError(f"Unknown preference section: {key!r}")
            setattr(self.preferences, key, value)

        # Re-validate to bump `updated_at`
        self.__dict__["updated_at"] = datetime.utcnow()
        self.preferences.last_updated = self.updated_at
```
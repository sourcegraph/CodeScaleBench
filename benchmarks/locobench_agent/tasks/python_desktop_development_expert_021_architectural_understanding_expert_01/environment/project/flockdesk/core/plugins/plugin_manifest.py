```python
"""
flockdesk.core.plugins.plugin_manifest
======================================

Utility classes for reading, validating, and representing plugin manifests.

Plugins are **hot-swappable** python distributions that expose an entry point in
the form ``package.module:callable``. A minimal manifest (``fd_manifest.json``)
looks like this:

{
    "id": "polls",
    "name": "Live Polls",
    "version": "1.4.2",
    "entry_point": "fd_polls.bootstrap:start",
    "description": "Create real-time polls during meetings",
    "author": "FlockDesk Team",
    "license": "MIT",
    "flockdesk_version": ">=2.3,<3.0",
    "requires": ["pydantic>=1.10", "httpx>=0.23"],
    "capabilities": ["ui", "event-bus"]
}

The *manifest* file MUST live at the root of the plugin’s directory.  When a
user drops a plugin folder onto the running desktop client, the loader:

1. Detects the directory
2. Parses & validates ``fd_manifest.json``
3. Creates a ``PluginManifest`` object
4. Resolves dependencies and entry-point.

Only this module is concerned with steps **2** & **3**.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, MutableMapping, Optional

try:
    # `packaging` is part of the standard library starting Python 3.12.
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version, InvalidVersion
except ModuleNotFoundError:  # pragma: no cover
    raise RuntimeError(
        "FlockDesk plugins require the 'packaging' library. "
        "Install with `pip install packaging`."
    )

FD_MANIFEST_FILE = "fd_manifest.json"
FLLOCKDESK_CORE_VERSION = Version("2.5.1")  # the running version of the host app

__all__ = [
    "ManifestError",
    "ManifestValidationError",
    "CompatibilityError",
    "PluginManifest",
    "discover_plugin_manifests",
]


# --------------------------------------------------------------------------- #
# Exceptions                                                                  #
# --------------------------------------------------------------------------- #
class ManifestError(Exception):
    """Base-class for manifest-related issues."""


class ManifestValidationError(ManifestError):
    """The manifest file is syntactically invalid or missing mandatory keys."""


class CompatibilityError(ManifestError):
    """The plugin is incompatible with the running FlockDesk version."""


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #
_FIELD_SNAKE_CASE_RX = re.compile(r"^[a-z_][a-z0-9_]+$")


def _validate_entry_point(entry_point: str) -> None:
    """
    Ensure ``entry_point`` follows *dotted.module:callable* syntax.
    """
    if ":" not in entry_point:
        raise ManifestValidationError(
            "Entry-point must be of the form 'package.module:callable'"
        )
    module_part, callable_part = entry_point.split(":", 1)
    if not module_part or not callable_part:
        raise ManifestValidationError(
            "Entry-point must include both module and callable."
        )
    if callable_part.startswith("_"):
        raise ManifestValidationError("Entry-point callable cannot be private.")


def _verify_snake_case(value: str, field_name: str) -> None:
    """
    Confirm that a string value is lowercase snake_case.
    """
    if not _FIELD_SNAKE_CASE_RX.match(value):
        raise ManifestValidationError(
            f"{field_name!r} must be snake_case (got {value!r})."
        )


def _require_keys(data: Mapping[str, object], keys: Iterable[str]) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ManifestValidationError(f"Missing manifest keys: {', '.join(missing)}")


# --------------------------------------------------------------------------- #
# Dataclass                                                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class PluginManifest:
    """
    Immutable representation of a plugin manifest file.

    The dataclass is *frozen* to guarantee read-only semantics once validated.
    """

    # Primary identification & metadata
    id: str
    name: str
    version: Version
    author: str = "Unknown"
    description: str = ""
    license: str = "Proprietary"

    # Runtime fields
    entry_point: str = ""
    requires: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    flockdesk_version: SpecifierSet = field(
        default_factory=lambda: SpecifierSet(">=0")  # compatible with everything
    )

    # Raw manifest path (useful for debuggers / error messages)
    _manifest_path: Optional[Path] = field(default=None, repr=False, compare=False)

    # --------------------------------------------------------------------- #
    # Construction                                                          #
    # --------------------------------------------------------------------- #
    @classmethod
    def from_path(cls, path: Path) -> "PluginManifest":
        """
        Load and validate ``fd_manifest.json`` from *path*.

        Parameters
        ----------
        path:
            Either the directory **containing** the manifest file *or*
            the manifest file itself.

        Returns
        -------
        PluginManifest
            A validated manifest object ready for use.

        Raises
        ------
        ManifestValidationError
            The manifest is malformed or missing mandatory fields.
        """
        path = Path(path).expanduser().resolve()
        if path.is_dir():
            path = path / FD_MANIFEST_FILE
        if not path.is_file():
            raise ManifestValidationError(f"Manifest file not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf8"))
        except json.JSONDecodeError as exc:
            raise ManifestValidationError(
                f"Malformed JSON in {path.name}: {exc}"
            ) from exc

        manifest = cls._from_dict(payload, manifest_path=path)
        manifest._assert_compatible()  # type: ignore[attr-defined]
        return manifest

    # ------------------------------------------------------------------ #
    # Private helpers                                                    #
    # ------------------------------------------------------------------ #
    @classmethod
    def _from_dict(
        cls, data: MutableMapping[str, object], *, manifest_path: Optional[Path] = None
    ) -> "PluginManifest":
        """
        Validate raw dict and build the dataclass.
        """
        required = ("id", "name", "version", "entry_point")
        _require_keys(data, required)

        _verify_snake_case(str(data["id"]), "id")
        _validate_entry_point(str(data["entry_point"]))

        # Version coercion
        try:
            version = Version(str(data["version"]))
        except InvalidVersion as exc:
            raise ManifestValidationError(
                f"Invalid version string {data['version']!r}"
            ) from exc

        # Optional fields
        requires = list(map(str, data.get("requires", [])))
        capabilities = list(map(str, data.get("capabilities", [])))

        # FlockDesk compatibility specifier
        spec = SpecifierSet(str(data.get("flockdesk_version", ">=0")))

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            version=version,
            author=str(data.get("author", "Unknown")),
            description=str(data.get("description", "")),
            license=str(data.get("license", "Proprietary")),
            entry_point=str(data["entry_point"]),
            requires=requires,
            capabilities=capabilities,
            flockdesk_version=spec,
            _manifest_path=manifest_path,
        )

    # ------------------------------------------------------------------ #
    # API methods                                                        #
    # ------------------------------------------------------------------ #
    def load_entry_point(self):
        """
        Dynamically import the plugin’s entry-point and return the callable.

        Returns
        -------
        typing.Callable
            The function/class specified in *entry_point*.

        Raises
        ------
        ImportError
            If the module or attribute cannot be imported.
        """
        module_name, callable_name = self.entry_point.split(":", 1)
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            raise ImportError(
                f"Cannot find module '{module_name}' declared in '{self.entry_point}'."
            )
        module = importlib.import_module(module_name)
        try:
            target = getattr(module, callable_name)
        except AttributeError as exc:
            raise ImportError(
                f"Module '{module_name}' does not expose '{callable_name}'."
            ) from exc
        return target

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _assert_compatible(self) -> None:
        """
        Ensure the plugin declares compatibility with the running Core version.
        """
        if FLLOCKDESK_CORE_VERSION not in self.flockdesk_version:
            raise CompatibilityError(
                f"{self.id} {self.version} is not compatible with "
                f"FlockDesk {FLLOCKDESK_CORE_VERSION}. "
                f"Supported versions: {self.flockdesk_version}"
            )

    # ------------------------------------------------------------------ #
    # Dunder overloads                                                   #
    # ------------------------------------------------------------------ #
    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} v{self.version} ({self.id})"


# --------------------------------------------------------------------------- #
# Discovery utilities                                                         #
# --------------------------------------------------------------------------- #
def discover_plugin_manifests(
    search_paths: Iterable[Path], *, recursive: bool = False
) -> List[PluginManifest]:
    """
    Search *search_paths* for valid ``fd_manifest.json`` files.

    Parameters
    ----------
    search_paths:
        An iterable of directories to scan.
    recursive:
        If *True*, walk subdirectories as well.

    Returns
    -------
    list[PluginManifest]
        A list of validated manifests. Invalid manifests are skipped with
        stderr warnings so as not to interrupt discovery of other plugins.
    """
    manifests: List[PluginManifest] = []
    for root in search_paths:
        root = Path(root).expanduser().resolve()
        if not root.exists():
            print(f"[fd] discovery: path not found {root}", file=sys.stderr)
            continue

        if recursive:
            candidates = root.rglob(FD_MANIFEST_FILE)
        else:
            candidates = root.glob(f"*/{FD_MANIFEST_FILE}")

        for manifest_path in candidates:
            try:
                manifest = PluginManifest.from_path(manifest_path)
            except ManifestError as exc:
                print(f"[fd] invalid manifest {manifest_path}: {exc}", file=sys.stderr)
                continue
            manifests.append(manifest)
    return manifests
```
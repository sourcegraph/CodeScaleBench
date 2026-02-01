```python
"""
LedgerQuest Engine – Documentation build configuration for the *API* manual.

This ``conf.py`` is executed by Sphinx to create the API documentation found
under ``docs/api``.  It has been written with the following goals in mind:

1. Be *self-contained* – the docs should build from a fresh checkout without the
   package being installed system-wide.
2. Be *robust* – missing optional dependencies or a dirty git tree should not
   break the build.
3. Be *up-to-date* – version numbers and other metadata are sourced
   programmatically from the package (or git) so that the published docs always
   reflect the exact build.
4. Be *extensible* – project-specific helpers (e.g., Step-Function diagrams)
   can register themselves via the public :pyfunc:`setup` hook.

Do **not** add any heavy, runtime-only dependencies here.  Keep the import
surface minimal so that Read-the-Docs and other CI systems can execute the file
in their restricted build environments.

Author
------
LedgerQuest Engine Team <engineering@ledgerquest.io>
"""
from __future__ import annotations

import datetime as _dt
import importlib
import logging
import os
import pathlib
import subprocess
import sys
from typing import Any, Dict, List

# --------------------------------------------------------------------------- #
# Path & Import Handling                                                      #
# --------------------------------------------------------------------------- #
ROOT_DIR = pathlib.Path(__file__).resolve().parents[2]  # ‹repo_root›/docs/api/conf.py
SRC_DIR = ROOT_DIR / "game_engine"

# The docs can be built directly from source without a `pip install -e .`
# by inserting the package root into `sys.path`.  We *prepend* so that any
# *development* version in the working tree takes precedence over a possibly
# pre-installed copy.
sys.path.insert(0, str(SRC_DIR))

# --------------------------------------------------------------------------- #
# Project Metadata                                                            #
# --------------------------------------------------------------------------- #
project: str = "LedgerQuest Engine"
author: str = "LedgerQuest Engine Team"
copyright: str = f"2023–{_dt.date.today().year}, {author}"

# --------------------------------------------------------------------------- #
# Version Management                                                          #
# --------------------------------------------------------------------------- #
def _get_git_version() -> str | None:
    """
    Attempt to obtain the current version from ``git`` tags.

    Returns
    -------
    str | None
        A PEP-440 compliant version string or *None* if
        - git is not available,
        - the folder is not a git repository, or
        - no matching tag exists.
    """
    try:
        # We use `git describe` so that pre-release commits get a
        # “+<commits>.g<hash>` suffix which is PEP-440 compatible.
        completed = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            check=True,
            cwd=ROOT_DIR,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _get_pkg_version(pkg_name: str) -> str | None:
    """
    Obtain version via ``importlib.metadata`` (Python ≥3.8).

    This works once the package is installed in the build env,
    for example, when Read-the-Docs performs a ``pip install .``.
    """
    try:
        # Python 3.8+ provides importlib.metadata in stdlib;
        # on 3.7, fallback to the external importlib-metadata package.
        from importlib import metadata  # type: ignore

        return metadata.version(pkg_name)
    except Exception:  # pragma: no cover
        # a broad except is fine here – failure only changes the *source* of the
        # displayed version string.
        return None


# Prefer the installed distribution so that we do not show 'dirty' information
# for released builds.  Fallback to git, and finally to a hard-coded dev tag.
release: str = (
    _get_pkg_version("ledgerquest-engine")  # Official PyPI name (if any)
    or _get_pkg_version("game_engine")  # Local editable install
    or _get_git_version()
    or "0.0.0.dev0"
)
version: str = release.split("+")[0]  # «short» X.Y.Z part for the sidebar

# --------------------------------------------------------------------------- #
# Logging                                                                     #
# --------------------------------------------------------------------------- #
# Configure root logger so that troubleshooting messages are visible in CI.
logging.basicConfig(
    format="%(levelname)s: %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)
log.info("Building LedgerQuest Engine docs – version %s", release)

# --------------------------------------------------------------------------- #
# Sphinx Extensions                                                           #
# --------------------------------------------------------------------------- #
extensions: List[str] = [
    # Built-in
    "sphinx.ext.autodoc",
    "sphinx.ext.autodoc.typehints",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.todo",
    "sphinx.ext.intersphinx",
    "sphinx.ext.ifconfig",
    "sphinx.ext.graphviz",
    # Markdown support
    "myst_parser",
    # Clipboard button for code examples
    "sphinx_copybutton",
    # Type-hint cross-links (`list[str]` → `typing.List`)
    "sphinx_autodoc_typehints",
]

# Render type hints *both* in the signature and in the description.
autodoc_typehints: str = "both"
autodoc_typehints_description_target: str = "documented"
autodoc_default_options: Dict[str, Any] = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "inherited-members": False,
    "member-order": "bysource",
}

# Generate the autosummary stub files automatically.
autosummary_generate: bool = True

# Napoleon (Numpy/Google style docstrings) settings
napoleon_google_docstring: bool = True
napoleon_numpy_docstring: bool = True
napoleon_use_param: bool = True
napoleon_use_rtype: bool = True
napoleon_preprocess_types: bool = True

# Enable TODO entries if READTHEDOCS_BUILD=True or DOCS_TODOS=1
todo_include_todos: bool = bool(os.getenv("DOCS_TODOS") or os.getenv("READTHEDOCS"))

# --------------------------------------------------------------------------- #
# MyST (Markdown)                                                             #
# --------------------------------------------------------------------------- #
myst_enable_extensions: List[str] = [
    "attrs_inline",
    "colon_fence",
    "deflist",
    "linkify",
    "substitution",
]
myst_heading_anchors: int = 3

# --------------------------------------------------------------------------- #
# Inter-Sphinx                                                                #
# --------------------------------------------------------------------------- #
intersphinx_mapping: Dict[str, tuple[str, str | None]] = {
    "python": ("https://docs.python.org/3", None),
    "boto3": ("https://boto3.amazonaws.com/v1/documentation/api/latest", None),
    "aws_cdk": ("https://docs.aws.amazon.com/cdk/api/v2", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

# --------------------------------------------------------------------------- #
# HTML Output                                                                 #
# --------------------------------------------------------------------------- #
html_theme: str = "furo"
html_title: str = f"{project} – API Reference ({version})"
html_last_updated_fmt: str = "%b %d, %Y"
html_static_path: List[str] = ["_static"]
html_css_files: List[str] = ["custom.css"]

html_theme_options: Dict[str, Any] = {
    "sidebar_hide_name": False,
    "light_css_variables": {
        "admonition-title-font-size": "smaller",
        "code-font-size": "0.85rem",
    },
    "dark_css_variables": {
        "admonition-title-font-size": "smaller",
        "code-font-size": "0.85rem",
    },
}

# --------------------------------------------------------------------------- #
# Graphviz                                                                    #
# --------------------------------------------------------------------------- #
graphviz_output_format: str = "svg"

# --------------------------------------------------------------------------- #
# Special Handling for Serverless/Game Assets                                 #
# --------------------------------------------------------------------------- #
def _conditional_extensions() -> None:
    """
    Add optional Sphinx extensions if their dependencies are present.

    We *deliberately* do this at runtime to avoid hard dependencies when
    building on minimal CI images.
    """
    try:
        import sphinxcontrib.mermaid  # noqa: F401

        extensions.append("sphinxcontrib.mermaid")
        log.info("Enabled Mermaid diagrams")
    except ImportError:
        log.debug("Mermaid not installed – skipping")

    try:
        import sphinx.ext.imgmath  # noqa: F401

        extensions.append("sphinx.ext.imgmath")
    except ImportError:
        log.debug("imgmath not available")


_conditional_extensions()

# --------------------------------------------------------------------------- #
# Build Environment Sanity Checks                                             #
# --------------------------------------------------------------------------- #
def _sanity_checks() -> None:
    """Emit warnings for common pitfalls."""
    if not SRC_DIR.exists():
        log.warning("Source directory %s does not exist; API docs may be empty", SRC_DIR)

    if "GITHUB_ACTIONS" in os.environ and os.getenv("CI") == "true":
        log.info("Building inside GitHub Actions – Caching will be disabled")


_sanity_checks()

# --------------------------------------------------------------------------- #
# Sphinx Setup Hook                                                           #
# --------------------------------------------------------------------------- #
def setup(app: "sphinx.application.Sphinx") -> None:
    """
    Register custom hooks, directives, and events with Sphinx.

    This hook is executed *after* the config file has been imported but
    *before* the build starts.
    """
    # Example: Inject a |year| substitution into every rst/md file.
    app.add_config_value(
        name="ledgerquest_year",
        default=str(_dt.date.today().year),
        rebuild="html",
    )
    app.connect("source-read", _inject_substitutions)

    # Add further project-specific logic here.


# --------------------------------------------------------------------------- #
# Helper Functions                                                            #
# --------------------------------------------------------------------------- #
def _inject_substitutions(app: "sphinx.application.Sphinx", docname: str, source: List[str]) -> None:
    """
    Add global reST substitutions (|project|, |version|, etc.) to each document.

    Parameters
    ----------
    app
        The Sphinx application object.
    docname
        Name of the source document.
    source
        Single-element list containing the file contents; modified in-place.
    """
    text = source[0]
    substitutions = {
        "|project|": project,
        "|version|": version,
        "|release|": release,
        "|year|": app.config.ledgerquest_year,
    }
    for key, val in substitutions.items():
        # Only replace if not already defined locally to allow overrides.
        if key not in text:
            text = text + f"\n.. |{key.strip('|')}| replace:: {val}\n"
    source[0] = text


# EOF
```
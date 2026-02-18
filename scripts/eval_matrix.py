#!/usr/bin/env python3
"""Shared helpers for loading benchmark configuration matrix metadata."""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SUPPORTED = ["baseline", "sourcegraph_full", "sourcegraph_isolated"]
DEFAULT_OFFICIAL = ["baseline", "sourcegraph_full"]


def _matrix_path(project_root: Path) -> Path:
    return project_root / "configs" / "eval_matrix.json"


def load_eval_matrix(project_root: Path | None = None) -> dict:
    root = project_root or Path(__file__).resolve().parent.parent
    path = _matrix_path(root)
    if not path.is_file():
        return {
            "supported_configs": list(DEFAULT_SUPPORTED),
            "official_default_configs": list(DEFAULT_OFFICIAL),
            "config_definitions": {},
        }
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {
            "supported_configs": list(DEFAULT_SUPPORTED),
            "official_default_configs": list(DEFAULT_OFFICIAL),
            "config_definitions": {},
        }
    if not isinstance(data, dict):
        return {
            "supported_configs": list(DEFAULT_SUPPORTED),
            "official_default_configs": list(DEFAULT_OFFICIAL),
            "config_definitions": {},
        }
    return data


def supported_configs(project_root: Path | None = None) -> list[str]:
    data = load_eval_matrix(project_root)
    configs = data.get("supported_configs")
    if isinstance(configs, list) and all(isinstance(x, str) for x in configs):
        return list(configs)
    return list(DEFAULT_SUPPORTED)


def official_default_configs(project_root: Path | None = None) -> list[str]:
    data = load_eval_matrix(project_root)
    configs = data.get("official_default_configs")
    if isinstance(configs, list) and all(isinstance(x, str) for x in configs):
        return list(configs)
    return list(DEFAULT_OFFICIAL)


def mcp_enabled_configs(project_root: Path | None = None) -> set[str]:
    data = load_eval_matrix(project_root)
    defs = data.get("config_definitions") or {}
    out: set[str] = set()
    if isinstance(defs, dict):
        for name, meta in defs.items():
            if isinstance(name, str) and isinstance(meta, dict) and meta.get("mcp_enabled") is True:
                out.add(name)
    if not out:
        out = {"sourcegraph_full", "sourcegraph_isolated"}
    return out


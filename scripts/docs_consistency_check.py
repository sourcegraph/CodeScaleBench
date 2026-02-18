#!/usr/bin/env python3
"""Check that core documentation references existing files and valid config keys."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/CONFIGS.md",
    "docs/QA_PROCESS.md",
    "docs/EXTENSIBILITY.md",
    "docs/REPO_HEALTH.md",
]

REF_PATTERNS = [
    re.compile(r"(scripts/[A-Za-z0-9_./-]+\.py)"),
    re.compile(r"(configs/[A-Za-z0-9_./-]+\.sh)"),
    re.compile(r"(docs/[A-Za-z0-9_./-]+\.md)"),
]


def _load_matrix() -> dict:
    path = ROOT / "configs" / "eval_matrix.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def _extract_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for pat in REF_PATTERNS:
        refs.update(pat.findall(text))
    return refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs",
        nargs="*",
        default=DEFAULT_DOCS,
        help="Docs to scan (default: core docs)",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    for rel in args.docs:
        p = ROOT / rel
        if not p.is_file():
            errors.append(f"doc_missing:{rel}")
            continue
        refs = _extract_refs(p.read_text(errors="replace"))
        for ref in sorted(refs):
            if not (ROOT / ref).exists():
                errors.append(f"missing_ref:{rel}:{ref}")

    matrix = _load_matrix()
    if matrix:
        supported = matrix.get("supported_configs") or []
        defaults = matrix.get("official_default_configs") or []
        if not isinstance(supported, list) or not all(isinstance(x, str) for x in supported):
            errors.append("eval_matrix_invalid_supported_configs")
        if not isinstance(defaults, list) or not all(isinstance(x, str) for x in defaults):
            errors.append("eval_matrix_invalid_official_default_configs")
        if isinstance(supported, list) and isinstance(defaults, list):
            missing = [x for x in defaults if x not in supported]
            if missing:
                errors.append(f"eval_matrix_defaults_not_supported:{','.join(missing)}")
        defs = matrix.get("config_definitions") or {}
        if not isinstance(defs, dict):
            errors.append("eval_matrix_invalid_config_definitions")
        else:
            for cfg in supported:
                if cfg not in defs:
                    warnings.append(f"eval_matrix_missing_definition:{cfg}")

    if errors:
        print("Docs consistency: FAILED")
        for err in errors:
            print(f"  - {err}")
    else:
        print("Docs consistency: OK")
    if warnings:
        print("Warnings:")
        for warn in warnings:
            print(f"  - {warn}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

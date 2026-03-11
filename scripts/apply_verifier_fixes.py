#!/usr/bin/env python3
"""Apply critical verifier fixes across all benchmark test.sh files."""

import os
import re
import sys
from pathlib import Path

BENCHMARKS = Path("/home/stephanie_jarmak/CodeScaleBench/benchmarks")

# ── Fix 1: Python-level no_changes_guard ──────────────────────────────────

OLD_PYTHON = """\
    # No-changes guard: env counts are all 0.  Verify via git that the agent
    # actually modified the repo \u2014 if not, force reward to 0.0 so tests that
    # pass on the unmodified repo don't produce false-positive scores.
    import subprocess as _sp
    _verify = os.environ.get("VERIFY_REPO") or os.environ.get("TASK_REPO_ROOT") or "/workspace"
    try:
        _d = _sp.run(["git", "diff", "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
        _u = _sp.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if not _d.stdout.strip() and not _u.stdout.strip():
            reward = 0.0
            checks["no_changes_guard"] = 0.0
            details["no_changes_guard"] = "git confirmed zero agent changes"
    except Exception:
        pass"""

NEW_PYTHON = """\
    # No-changes guard: env counts are all 0.  Verify via git that the agent
    # actually modified the repo \u2014 if not, force reward to 0.0 so tests that
    # pass on the unmodified repo don't produce false-positive scores.
    # Checks origin ref too, so agents that commit their work (e.g. OpenHands
    # runtime auto-commits) are not falsely penalised.
    import subprocess as _sp
    _verify = os.environ.get("VERIFY_REPO") or os.environ.get("TASK_REPO_ROOT") or "/workspace"
    try:
        _has_changes = False
        _d = _sp.run(["git", "diff", "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if _d.stdout.strip():
            _has_changes = True
        _u = _sp.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if _u.stdout.strip():
            _has_changes = True
        if not _has_changes:
            for _ref in ["origin/HEAD", "origin/main", "origin/master"]:
                _rv = _sp.run(["git", "rev-parse", "--verify", _ref], capture_output=True, text=True, cwd=_verify, timeout=5)
                if _rv.returncode == 0:
                    _cd = _sp.run(["git", "diff", _ref, "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
                    if _cd.stdout.strip():
                        _has_changes = True
                    break
        if not _has_changes:
            reward = 0.0
            checks["no_changes_guard"] = 0.0
            details["no_changes_guard"] = "git confirmed zero agent changes"
    except Exception:
        pass"""

# ── Fix 2: Shell-level git diff guard ─────────────────────────────────────

OLD_SHELL = """\
    _nc_diff=$(git diff HEAD --stat 2>/dev/null | wc -l)
    _nc_untracked=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
    if [ "${_nc_diff:-0}" -eq 0 ] && [ "${_nc_untracked:-0}" -eq 0 ]; then"""

NEW_SHELL = """\
    _nc_diff=$(git diff HEAD --stat 2>/dev/null | wc -l)
    _nc_untracked=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
    # Also check committed changes vs origin (catches auto-commit harnesses like OpenHands)
    _nc_committed=0
    for _ref in origin/HEAD origin/main origin/master; do
        if git rev-parse --verify "$_ref" >/dev/null 2>&1; then
            _nc_committed=$(git diff "$_ref" HEAD --stat 2>/dev/null | wc -l)
            break
        fi
    done
    if [ "${_nc_diff:-0}" -eq 0 ] && [ "${_nc_untracked:-0}" -eq 0 ] && [ "${_nc_committed:-0}" -eq 0 ]; then"""

# ── Fix 3: flipt GOWORK=off ──────────────────────────────────────────────

FLIPT_OLD = "if go build ./internal/server/evaluation/..."
FLIPT_NEW = (
    "# Disable go.work to avoid version mismatches when sg_only verifier restores the\n"
    "# full repo (its go.work may require a newer Go than the container provides).\n"
    "if GOWORK=off go build ./internal/server/evaluation/..."
)

FLIPT_TARGETS = [
    BENCHMARKS / "csb_sdlc_secure/flipt-repo-scoped-access-001/tests/test.sh",
    BENCHMARKS / "csb/security/flipt-repo-scoped-access-001/tests/test.sh",
]


def apply_fix1():
    """Replace Python no_changes_guard in all test.sh files."""
    count = 0
    for path in sorted(BENCHMARKS.rglob("test.sh")):
        text = path.read_text()
        if OLD_PYTHON in text:
            new_text = text.replace(OLD_PYTHON, NEW_PYTHON)
            if new_text != text:
                path.write_text(new_text)
                count += 1
                print(f"  Fix1: {path.relative_to(BENCHMARKS)}")
    return count


def apply_fix2():
    """Replace shell-level git diff guard in csb/fix and csb_sdlc_fix."""
    count = 0
    for path in sorted(BENCHMARKS.rglob("test.sh")):
        text = path.read_text()
        if OLD_SHELL in text:
            new_text = text.replace(OLD_SHELL, NEW_SHELL)
            if new_text != text:
                path.write_text(new_text)
                count += 1
                print(f"  Fix2: {path.relative_to(BENCHMARKS)}")
    return count


def apply_fix3():
    """Add GOWORK=off to flipt test.sh files."""
    count = 0
    for path in FLIPT_TARGETS:
        if not path.exists():
            print(f"  Fix3: MISSING {path}")
            continue
        text = path.read_text()
        if FLIPT_OLD in text and "GOWORK=off" not in text:
            new_text = text.replace(FLIPT_OLD, FLIPT_NEW)
            if new_text != text:
                path.write_text(new_text)
                count += 1
                print(f"  Fix3: {path.relative_to(BENCHMARKS)}")
    return count


def main():
    print("=== Fix 1: Python no_changes_guard (origin ref check) ===")
    n1 = apply_fix1()
    print(f"  -> {n1} files updated\n")

    print("=== Fix 2: Shell git diff guard (origin ref check) ===")
    n2 = apply_fix2()
    print(f"  -> {n2} files updated\n")

    print("=== Fix 3: flipt GOWORK=off ===")
    n3 = apply_fix3()
    print(f"  -> {n3} files updated\n")

    print(f"Total: {n1 + n2 + n3} files modified across all fixes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

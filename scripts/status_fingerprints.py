#!/usr/bin/env python3
"""Error fingerprinting for benchmark task failures.

Classifies exception_info from result.json into known failure categories
with severity, advice, and matched text.

Standalone usage:
    python3 scripts/status_fingerprints.py path/to/result.json [...]
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional


# Ordered list of (fingerprint_id, regex_pattern, label, severity, advice)
# First match wins, so order matters (most specific first).
ERROR_FINGERPRINTS = [
    (
        "token_refresh_403",
        re.compile(r"403|Forbidden|token.*refresh|refresh.*token|credentials.*expired", re.IGNORECASE),
        "OAuth token refresh failure",
        "infra",
        "Check ~/.claude/.credentials.json; re-authenticate with `claude auth`.",
    ),
    (
        "verifier_parse_error",
        re.compile(r"verifier.*(?:parse|json|decode|invalid)|JSONDecodeError.*verifier|reward.*parse", re.IGNORECASE),
        "Verifier output parse error",
        "verifier",
        "Check verifier script output format; ensure reward.txt/reward.json is valid.",
    ),
    (
        "api_500",
        re.compile(r"500\s*Internal Server Error|api.*500|server.*error.*5\d{2}", re.IGNORECASE),
        "API 500 server error",
        "api",
        "Transient API issue; retry the task. If persistent, check API status page.",
    ),
    (
        "api_rate_limit",
        re.compile(r"rate.?limit|429|too many requests|throttl|overloaded", re.IGNORECASE),
        "API rate limit / overloaded",
        "api",
        "Reduce parallelism or wait before retrying. Check account quotas.",
    ),
    (
        "timeout",
        re.compile(r"timeout|timed?\s*out|deadline exceeded|SIGTERM|killed.*signal", re.IGNORECASE),
        "Task timeout",
        "task",
        "Task exceeded time limit. Consider increasing timeout_hours or simplifying the task.",
    ),
    (
        "mcp_connection",
        re.compile(r"mcp.*(?:connect|refused|unavailable|error)|sourcegraph.*(?:connect|error|fail)", re.IGNORECASE),
        "MCP server connection failure",
        "mcp",
        "Check MCP server is running and accessible. Verify MCP config in task setup.",
    ),
    (
        "import_error",
        re.compile(r"ImportError|ModuleNotFoundError|No module named|cannot import", re.IGNORECASE),
        "Python import error",
        "setup",
        "Missing dependency in Docker image. Update Dockerfile or requirements.txt.",
    ),
    (
        "docker_compose_fail",
        re.compile(r"docker.*(?:compose|build|pull).*fail|container.*(?:exit|crash|fail)|OOMKill", re.IGNORECASE),
        "Docker/container failure",
        "setup",
        "Check Docker image availability, disk space, and memory limits.",
    ),
    (
        "permission_denied",
        re.compile(r"permission denied|EACCES|Operation not permitted", re.IGNORECASE),
        "Permission denied",
        "infra",
        "Check file/directory permissions in the task workspace.",
    ),
    (
        "git_error",
        re.compile(r"fatal:.*git|git.*(?:clone|checkout|pull).*fail|repository not found", re.IGNORECASE),
        "Git operation failure",
        "setup",
        "Check repository URL and network access. Verify git credentials if private repo.",
    ),
]


def fingerprint_error(exception_info) -> Optional[dict]:
    """Classify an exception_info value into a known failure category.

    Args:
        exception_info: The exception_info field from result.json.
            Can be a dict (with 'type', 'message', 'traceback' keys),
            a string, or None.

    Returns:
        Dict with fingerprint_id, label, severity, advice, matched_text,
        or None if exception_info is None/empty.
    """
    if exception_info is None:
        return None

    # Build a single searchable string from exception_info
    if isinstance(exception_info, dict):
        # Handle both key conventions:
        #   Harbor: exception_type, exception_message, exception_traceback
        #   Generic: type, message, traceback
        parts = [
            str(exception_info.get("exception_type", exception_info.get("type", ""))),
            str(exception_info.get("exception_message", exception_info.get("message", ""))),
            str(exception_info.get("exception_traceback", exception_info.get("traceback", ""))),
        ]
        search_text = " ".join(parts)
    elif isinstance(exception_info, str):
        search_text = exception_info
    else:
        search_text = str(exception_info)

    if not search_text.strip():
        return None

    for fp_id, pattern, label, severity, advice in ERROR_FINGERPRINTS:
        match = pattern.search(search_text)
        if match:
            return {
                "fingerprint_id": fp_id,
                "label": label,
                "severity": severity,
                "advice": advice,
                "matched_text": match.group(0)[:120],
            }

    # No known pattern matched
    # Extract a short snippet for the unknown fingerprint
    snippet = search_text[:120].strip()
    return {
        "fingerprint_id": "unknown",
        "label": "Unknown error",
        "severity": "unknown",
        "advice": "Inspect result.json exception_info manually.",
        "matched_text": snippet,
    }


def main():
    """CLI: fingerprint one or more result.json files."""
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} path/to/result.json [...]", file=sys.stderr)
        sys.exit(1)

    for path_str in sys.argv[1:]:
        path = Path(path_str)
        if not path.is_file():
            print(f"SKIP (not a file): {path}")
            continue

        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"SKIP (read error): {path}: {e}")
            continue

        exception_info = data.get("exception_info")
        if exception_info is None:
            print(f"  OK (no exception): {path}")
            continue

        fp = fingerprint_error(exception_info)
        if fp is None:
            print(f"  OK (empty exception): {path}")
            continue

        sev = fp["severity"].upper()
        print(f"  [{sev}] {fp['fingerprint_id']}: {fp['label']}")
        print(f"         matched: {fp['matched_text']}")
        print(f"         advice:  {fp['advice']}")
        print(f"         file:    {path}")
        print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Shared account readiness and monitoring state for benchmark launchers.

This utility is intentionally read-only with respect to OAuth tokens. It does
not refresh credentials. Instead, it classifies accounts as ready, busy, or
unsafe based on deterministic local signals:

- OAuth token presence and time remaining
- refresh token presence
- active launcher assignments recorded by shared shell helpers

It also records recent locally observed rate-limit events for operator context,
but those observations do not create a synthetic future cooldown window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACCOUNT_NAME_RE = re.compile(r"account(\d+)$")


def default_sessions_per_account() -> int:
    value = os.environ.get("SESSIONS_PER_ACCOUNT", "6")
    try:
        return max(1, int(value))
    except ValueError:
        return 6


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_state_file() -> Path:
    return repo_root() / "runs" / "state" / "account_health.json"


def default_real_home() -> Path:
    return Path(os.environ.get("HOME", str(Path.home())))


def discover_managed_account_homes(real_home: Path) -> list[Path]:
    homes_dir = real_home / ".claude-homes"
    if not homes_dir.is_dir():
        return []

    homes: list[Path] = []
    for path in homes_dir.iterdir():
        if not path.is_dir():
            continue
        if ACCOUNT_NAME_RE.fullmatch(path.name):
            homes.append(path)

    return sorted(homes, key=lambda path: int(ACCOUNT_NAME_RE.fullmatch(path.name).group(1)))


def discover_account_homes(real_home: Path) -> list[Path]:
    homes = discover_managed_account_homes(real_home)
    if homes:
        return homes
    return [real_home]


def load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "updated_at": iso_now(), "accounts": {}}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "updated_at": iso_now(), "accounts": {}}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": iso_now(), "accounts": {}}
    data.setdefault("version", 1)
    data.setdefault("updated_at", iso_now())
    data.setdefault("accounts", {})
    if not isinstance(data["accounts"], dict):
        data["accounts"] = {}
    return data


def save_state(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = iso_now()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, sort_keys=True))
    temp_path.replace(path)


def pid_is_live(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_token_status(home: Path) -> dict[str, Any]:
    creds_file = home / ".claude" / ".credentials.json"
    result: dict[str, Any] = {
        "credentials_file": str(creds_file),
        "token_state": "missing_credentials",
        "has_refresh_token": False,
        "remaining_minutes": None,
        "expires_at": None,
    }

    if not creds_file.is_file():
        return result

    try:
        data = json.loads(creds_file.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        result["token_state"] = "corrupt_credentials"
        result["message"] = str(exc)
        return result

    oauth = data.get("claudeAiOauth", {})
    if not oauth:
        result["token_state"] = "missing_oauth"
        return result

    expires_at_ms = oauth.get("expiresAt")
    result["has_refresh_token"] = bool(oauth.get("refreshToken"))
    if not expires_at_ms:
        result["token_state"] = "missing_expiry"
        return result

    remaining_minutes = int((int(expires_at_ms) - int(time.time() * 1000)) / 60000)
    expires_at = datetime.fromtimestamp(int(expires_at_ms) / 1000, tz=timezone.utc)
    result["remaining_minutes"] = remaining_minutes
    result["expires_at"] = expires_at.isoformat()
    if remaining_minutes < 0:
        result["token_state"] = "expired"
    elif remaining_minutes == 0:
        result["token_state"] = "expiring_now"
    else:
        result["token_state"] = "valid"
    return result


def normalize_account_state(
    state: dict[str, Any],
    account_home: Path,
) -> dict[str, Any]:
    accounts = state.setdefault("accounts", {})
    account = accounts.setdefault(str(account_home), {})
    account.setdefault("active_assignments", {})

    active_assignments = account.get("active_assignments") or {}
    cleaned_assignments: dict[str, Any] = {}
    for assignment_id, payload in active_assignments.items():
        if not isinstance(payload, dict):
            continue
        pid = payload.get("pid")
        try:
            pid = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid = None
        if pid_is_live(pid):
            payload["pid"] = pid
            cleaned_assignments[assignment_id] = payload
    account["active_assignments"] = cleaned_assignments

    # Legacy fixed cooldowns are no longer used for launch gating. Clear any
    # stale values so status output reflects provider-backed signals only.
    account.pop("cooldown_until", None)

    return account


def classify_account(
    account_home: Path,
    state: dict[str, Any],
    sessions_per_account: int,
    min_token_minutes: int,
) -> dict[str, Any]:
    account = normalize_account_state(state, account_home)
    token = read_token_status(account_home)
    active_assignments = account.get("active_assignments", {})
    active_count = len(active_assignments)
    label = account_home.name if account_home.name else str(account_home)

    status = "ready"
    reasons: list[str] = []
    recommended_action = "proceed"

    if token["token_state"] in {
        "missing_credentials",
        "corrupt_credentials",
        "missing_oauth",
        "missing_expiry",
        "expired",
    }:
        status = "blocked"
        recommended_action = "login_or_refresh"
        reasons.append(token["token_state"])
    elif token["remaining_minutes"] is not None and token["remaining_minutes"] < min_token_minutes:
        status = "token_low"
        recommended_action = "refresh_or_wait"
        reasons.append(f"token<{min_token_minutes}m")

    if active_count >= sessions_per_account and status == "ready":
        status = "busy"
        recommended_action = "wait"
        reasons.append("all_slots_in_use")

    available_slots = 0
    if status == "ready":
        available_slots = max(0, sessions_per_account - active_count)

    if status == "ready" and active_count > 0:
        status = "ready_with_load"

    return {
        "label": label,
        "home": str(account_home),
        "status": status,
        "recommended_action": recommended_action,
        "available_slots": available_slots,
        "active_assignments": active_count,
        "sessions_per_account": sessions_per_account,
        "last_rate_limit_at": account.get("last_rate_limit_at"),
        "last_rate_limit_reason": account.get("last_rate_limit_reason"),
        "last_rate_limit_task_id": account.get("last_rate_limit_task_id"),
        "token": token,
        "reasons": reasons,
    }


def collect_account_status(
    *,
    home_paths: list[str] | None = None,
    real_home: str | None = None,
    state_file: str | None = None,
    sessions_per_account: int = 6,
    min_token_minutes: int = 90,
) -> dict[str, Any]:
    real_home_path = Path(real_home) if real_home else default_real_home()
    state_path = Path(state_file) if state_file else default_state_file()
    state = load_state(state_path)

    if home_paths:
        homes = [Path(p) for p in home_paths]
    else:
        homes = discover_account_homes(real_home_path)

    accounts = [
        classify_account(
            account_home=home,
            state=state,
            sessions_per_account=sessions_per_account,
            min_token_minutes=min_token_minutes,
        )
        for home in homes
    ]
    save_state(state_path, state)

    ready_accounts = [a for a in accounts if a["status"] in {"ready", "ready_with_load"}]
    total_available_slots = sum(a["available_slots"] for a in ready_accounts)
    if ready_accounts:
        action = "proceed"
        summary = (
            f"{len(ready_accounts)} account(s) ready, "
            f"{total_available_slots} total slot(s) available"
        )
    elif any(a["status"] == "busy" for a in accounts):
        action = "wait"
        summary = "All ready accounts are currently at slot capacity."
    elif any(a["status"] == "token_low" for a in accounts):
        action = "refresh_or_wait"
        summary = "No accounts meet the token safety margin."
    else:
        action = "login_or_refresh"
        summary = "No usable OAuth accounts found."

    return {
        "generated_at": iso_now(),
        "state_file": str(state_path),
        "sessions_per_account": sessions_per_account,
        "min_token_minutes": min_token_minutes,
        "accounts": accounts,
        "ready_homes": [a["home"] for a in ready_accounts],
        "blocked_homes": [
            a["home"] for a in accounts if a["status"] not in {"ready", "ready_with_load"}
        ],
        "total_available_slots": total_available_slots,
        "recommended_parallel_jobs": total_available_slots,
        "recommended_action": action,
        "summary": summary,
        "ok_to_launch": bool(ready_accounts),
    }


def print_table(report: dict[str, Any]) -> None:
    print("Account Readiness")
    print("=" * 60)
    for account in report["accounts"]:
        token = account["token"]
        token_bits = token["token_state"]
        if token["remaining_minutes"] is not None:
            token_bits += f", {token['remaining_minutes']}m left"
        if token["expires_at"]:
            token_bits += f", expires {token['expires_at']}"
        if token["has_refresh_token"]:
            token_bits += ", refresh token"
        suffix = ""
        if account["last_rate_limit_at"]:
            suffix = f" last rate-limit {account['last_rate_limit_at']}"
        print(
            f"  [{account['status']:<15}] {account['label']:<12} "
            f"slots={account['available_slots']}/{account['sessions_per_account']} "
            f"active={account['active_assignments']} token=({token_bits}){suffix}"
        )
    print("")
    print(f"Recommendation: {report['recommended_action']}")
    print(f"Summary:        {report['summary']}")


def mark_assignment(
    *,
    state_file: Path,
    home: Path,
    assignment_id: str,
    task_id: str | None,
    run_id: str | None,
    launcher: str | None,
    pid: int | None,
) -> None:
    state = load_state(state_file)
    account = normalize_account_state(state, home)
    account["active_assignments"][assignment_id] = {
        "task_id": task_id,
        "run_id": run_id,
        "launcher": launcher,
        "pid": pid,
        "started_at": iso_now(),
    }
    save_state(state_file, state)


def end_assignment(*, state_file: Path, home: Path, assignment_id: str) -> None:
    state = load_state(state_file)
    account = normalize_account_state(state, home)
    account.get("active_assignments", {}).pop(assignment_id, None)
    save_state(state_file, state)


def mark_rate_limit(
    *,
    state_file: Path,
    home: Path,
    task_id: str | None,
    reason: str | None,
) -> None:
    state = load_state(state_file)
    account = normalize_account_state(state, home)
    now = utc_now()
    account["last_rate_limit_at"] = now.isoformat()
    account["last_rate_limit_reason"] = reason or "observed runtime rate limit"
    if task_id:
        account["last_rate_limit_task_id"] = task_id
    save_state(state_file, state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Account readiness and monitoring")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("status", "preflight"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--format", choices=["table", "json"], default="table")
        sub.add_argument("--state-file", default=str(default_state_file()))
        sub.add_argument("--real-home", default=str(default_real_home()))
        sub.add_argument("--home", action="append", dest="homes")
        sub.add_argument(
            "--sessions-per-account",
            type=int,
            default=default_sessions_per_account(),
        )
        sub.add_argument("--min-token-minutes", type=int, default=90)

    begin = subparsers.add_parser("begin-assignment")
    begin.add_argument("--state-file", default=str(default_state_file()))
    begin.add_argument("--home", required=True)
    begin.add_argument("--assignment-id", required=True)
    begin.add_argument("--task-id")
    begin.add_argument("--run-id")
    begin.add_argument("--launcher")
    begin.add_argument("--pid", type=int)

    end = subparsers.add_parser("end-assignment")
    end.add_argument("--state-file", default=str(default_state_file()))
    end.add_argument("--home", required=True)
    end.add_argument("--assignment-id", required=True)

    rate_limit = subparsers.add_parser("mark-rate-limit")
    rate_limit.add_argument("--state-file", default=str(default_state_file()))
    rate_limit.add_argument("--home", required=True)
    rate_limit.add_argument("--task-id")
    rate_limit.add_argument("--reason")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in {"status", "preflight"}:
        report = collect_account_status(
            home_paths=args.homes,
            real_home=args.real_home,
            state_file=args.state_file,
            sessions_per_account=args.sessions_per_account,
            min_token_minutes=args.min_token_minutes,
        )
        if args.format == "json":
            print(json.dumps(report, indent=2))
        else:
            print_table(report)
        if args.command == "preflight" and not report["ok_to_launch"]:
            return 1
        return 0

    state_file = Path(args.state_file)
    home = Path(args.home)

    if args.command == "begin-assignment":
        mark_assignment(
            state_file=state_file,
            home=home,
            assignment_id=args.assignment_id,
            task_id=args.task_id,
            run_id=args.run_id,
            launcher=args.launcher,
            pid=args.pid,
        )
        return 0

    if args.command == "end-assignment":
        end_assignment(
            state_file=state_file,
            home=home,
            assignment_id=args.assignment_id,
        )
        return 0

    if args.command == "mark-rate-limit":
        mark_rate_limit(
            state_file=state_file,
            home=home,
            task_id=args.task_id,
            reason=args.reason,
        )
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

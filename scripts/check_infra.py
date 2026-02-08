#!/usr/bin/env python3
"""Pre-run infrastructure readiness checker.

Validates that all infrastructure prerequisites are met before launching
a benchmark run: OAuth tokens, API credentials, Docker, disk space.

Usage:
    python3 scripts/check_infra.py
    python3 scripts/check_infra.py --format json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REAL_HOME = os.environ.get("HOME", os.path.expanduser("~"))


def try_refresh_token(creds_file: Path) -> dict | None:
    """Attempt to refresh an expired OAuth token. Returns new expiry info or None."""
    try:
        data = json.loads(creds_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    oauth = data.get("claudeAiOauth", {})
    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        return None

    import urllib.request
    import urllib.error

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
    }).encode()

    req = urllib.request.Request(
        "https://console.anthropic.com/api/oauth/token",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None

    new_access = token_data.get("access_token")
    if not new_access:
        return None

    expires_in = token_data.get("expires_in", 28800)
    oauth["accessToken"] = new_access
    new_refresh = token_data.get("refresh_token")
    if new_refresh:
        oauth["refreshToken"] = new_refresh
    oauth["expiresAt"] = int(time.time() * 1000) + (expires_in * 1000)
    data["claudeAiOauth"] = oauth

    try:
        creds_file.write_text(json.dumps(data, indent=2))
    except OSError:
        pass

    return {"expires_in": expires_in, "remaining_min": expires_in // 60}


def check_oauth_token(home_dir: str | None = None) -> dict:
    """Check OAuth token validity and time remaining."""
    home = home_dir or REAL_HOME
    creds_file = Path(home) / ".claude" / ".credentials.json"

    if not creds_file.is_file():
        return {
            "check": "oauth_token",
            "status": "FAIL",
            "message": f"No credentials file at {creds_file}",
            "home": home,
        }

    try:
        data = json.loads(creds_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {
            "check": "oauth_token",
            "status": "FAIL",
            "message": f"Cannot read credentials: {e}",
            "home": home,
        }

    oauth = data.get("claudeAiOauth", {})
    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    remaining_s = (expires_at_ms - now_ms) / 1000
    remaining_min = int(remaining_s / 60)

    has_refresh = bool(oauth.get("refreshToken"))
    has_access = bool(oauth.get("accessToken"))

    if remaining_s <= 0:
        # Access token expired — try to refresh it
        if has_refresh:
            refresh_result = try_refresh_token(creds_file)
            if refresh_result:
                return {
                    "check": "oauth_token",
                    "status": "OK",
                    "message": f"Token was expired, refreshed successfully ({refresh_result['remaining_min']} min remaining)",
                    "remaining_minutes": refresh_result["remaining_min"],
                    "has_refresh_token": True,
                    "home": home,
                }
            else:
                return {
                    "check": "oauth_token",
                    "status": "WARN",
                    "message": f"Access token expired ({abs(remaining_min)} min ago). Refresh failed but agent may auto-refresh at runtime.",
                    "remaining_minutes": remaining_min,
                    "has_refresh_token": has_refresh,
                    "home": home,
                }
        return {
            "check": "oauth_token",
            "status": "FAIL",
            "message": f"Token EXPIRED ({abs(remaining_min)} min ago), no refresh token. Run: claude login",
            "remaining_minutes": remaining_min,
            "has_refresh_token": False,
            "home": home,
        }
    elif remaining_s < 1800:  # < 30 min
        return {
            "check": "oauth_token",
            "status": "WARN",
            "message": f"Token expires in {remaining_min} min (< 30 min margin). Refresh recommended.",
            "remaining_minutes": remaining_min,
            "has_refresh_token": has_refresh,
            "home": home,
        }
    else:
        return {
            "check": "oauth_token",
            "status": "OK",
            "message": f"Token valid ({remaining_min} min remaining)",
            "remaining_minutes": remaining_min,
            "has_refresh_token": has_refresh,
            "home": home,
        }


def check_multi_account_tokens() -> list[dict]:
    """Check tokens for all accounts under ~/.claude-homes/."""
    results = []
    homes_dir = Path(REAL_HOME) / ".claude-homes"

    if not homes_dir.is_dir():
        # Single account mode
        results.append(check_oauth_token())
        return results

    account_num = 1
    found_any = False
    while True:
        account_home = homes_dir / f"account{account_num}"
        creds = account_home / ".claude" / ".credentials.json"
        if creds.is_file():
            found_any = True
            results.append(check_oauth_token(str(account_home)))
            account_num += 1
        else:
            break

    if not found_any:
        results.append(check_oauth_token())

    return results


def check_env_local() -> dict:
    """Check ~/evals/.env.local for required variables (subscription-only mode)."""
    env_file = Path(REAL_HOME) / "evals" / ".env.local"

    if not env_file.is_file():
        return {
            "check": "env_local",
            "status": "FAIL",
            "message": f"No .env.local at {env_file}",
        }

    content = env_file.read_text()
    has_sg_token = "SOURCEGRAPH_ACCESS_TOKEN" in content

    if not has_sg_token:
        return {
            "check": "env_local",
            "status": "WARN",
            "message": "SOURCEGRAPH_ACCESS_TOKEN not set (MCP modes will fail)",
        }

    return {
        "check": "env_local",
        "status": "OK",
        "message": "SOURCEGRAPH_ACCESS_TOKEN found (subscription-only mode — no API key needed)",
    }


def check_docker() -> dict:
    """Check Docker daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            return {
                "check": "docker",
                "status": "OK",
                "message": "Docker daemon is running",
            }
        else:
            stderr = result.stderr.decode(errors="replace")[:200]
            return {
                "check": "docker",
                "status": "FAIL",
                "message": f"Docker not responding: {stderr}",
            }
    except FileNotFoundError:
        return {
            "check": "docker",
            "status": "FAIL",
            "message": "Docker not installed (docker command not found)",
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "docker",
            "status": "FAIL",
            "message": "Docker info timed out (daemon may be hung)",
        }


def check_disk_space() -> dict:
    """Check available disk space."""
    usage = shutil.disk_usage(REAL_HOME)
    free_gb = usage.free / (1024 ** 3)
    total_gb = usage.total / (1024 ** 3)
    pct_free = (usage.free / usage.total) * 100

    if free_gb < 5:
        return {
            "check": "disk_space",
            "status": "FAIL",
            "message": f"Only {free_gb:.1f}GB free of {total_gb:.0f}GB ({pct_free:.0f}% free). Docker images need space.",
        }
    elif free_gb < 20:
        return {
            "check": "disk_space",
            "status": "WARN",
            "message": f"{free_gb:.1f}GB free of {total_gb:.0f}GB ({pct_free:.0f}% free). May run low during large runs.",
        }
    else:
        return {
            "check": "disk_space",
            "status": "OK",
            "message": f"{free_gb:.1f}GB free of {total_gb:.0f}GB ({pct_free:.0f}% free)",
        }


def check_harbor() -> dict:
    """Check harbor CLI is available."""
    try:
        result = subprocess.run(
            ["harbor", "--help"],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            return {
                "check": "harbor",
                "status": "OK",
                "message": "harbor CLI available",
            }
        else:
            return {
                "check": "harbor",
                "status": "FAIL",
                "message": "harbor command failed",
            }
    except FileNotFoundError:
        return {
            "check": "harbor",
            "status": "FAIL",
            "message": "harbor not installed (command not found)",
        }
    except subprocess.TimeoutExpired:
        return {
            "check": "harbor",
            "status": "WARN",
            "message": "harbor --version timed out",
        }


def check_runs_dir() -> dict:
    """Check runs/official/ directory."""
    runs_dir = Path(__file__).resolve().parent.parent / "runs" / "official"
    if not runs_dir.is_dir():
        return {
            "check": "runs_dir",
            "status": "WARN",
            "message": f"runs/official/ not found at {runs_dir}. Will be created on first run.",
        }

    # Count existing run dirs
    run_count = sum(1 for d in runs_dir.iterdir() if d.is_dir())
    return {
        "check": "runs_dir",
        "status": "OK",
        "message": f"runs/official/ exists with {run_count} run directories",
    }


def format_table(results: list[dict]) -> str:
    """Format results as colored table."""
    lines = []
    lines.append("Infrastructure Readiness Check")
    lines.append("=" * 60)

    status_colors = {
        "OK": "\033[92m",    # green
        "WARN": "\033[93m",  # yellow
        "FAIL": "\033[91m",  # red
    }
    reset = "\033[0m"

    fails = 0
    warns = 0

    for r in results:
        status = r["status"]
        color = status_colors.get(status, "")
        check_name = r["check"]
        home_suffix = f" [{r['home']}]" if "home" in r else ""
        lines.append(f"  {color}[{status:4s}]{reset}  {check_name:25s}  {r['message']}{home_suffix}")
        if status == "FAIL":
            fails += 1
        elif status == "WARN":
            warns += 1

    lines.append("")
    if fails:
        lines.append(f"\033[91mBLOCKED: {fails} critical issue(s) must be fixed before running.\033[0m")
    elif warns:
        lines.append(f"\033[93mREADY with {warns} warning(s). Runs may partially fail.\033[0m")
    else:
        lines.append(f"\033[92mALL CLEAR: Infrastructure ready for benchmark runs.\033[0m")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Check infrastructure readiness before benchmark runs."
    )
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args()

    results = []

    # Token checks (handles multi-account)
    results.extend(check_multi_account_tokens())

    # Environment
    results.append(check_env_local())

    # Docker
    results.append(check_docker())

    # Disk space
    results.append(check_disk_space())

    # Harbor CLI
    results.append(check_harbor())

    # Runs directory
    results.append(check_runs_dir())

    if args.format == "json":
        output = {
            "checks": results,
            "ok": sum(1 for r in results if r["status"] == "OK"),
            "warn": sum(1 for r in results if r["status"] == "WARN"),
            "fail": sum(1 for r in results if r["status"] == "FAIL"),
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_table(results))

    # Exit code
    if any(r["status"] == "FAIL" for r in results):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

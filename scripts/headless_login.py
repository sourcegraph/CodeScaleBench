#!/usr/bin/env python3
"""Headless OAuth login for Claude Code on VMs without browsers.

Generates an authorization URL you can open in any browser (e.g., on your laptop),
then exchanges the resulting code for OAuth credentials.

Usage:
    # Login for a specific account
    python3 scripts/headless_login.py --home ~/.claude-homes/account1
    python3 scripts/headless_login.py --account 4

    # Login for all accounts interactively
    python3 scripts/headless_login.py --all-accounts

    # Login for main home
    python3 scripts/headless_login.py
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# OAuth configuration (from Claude Code binary)
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers"
ACCOUNT_NAME_RE = re.compile(r"account(\d+)$")


def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (RFC 7636)."""
    # Standard PKCE: 32 random bytes → base64url without padding
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")

    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    return code_verifier, code_challenge


def build_authorize_url(code_challenge: str, state: str) -> str:
    """Build the OAuth authorization URL with all required parameters."""
    params = [
        ("response_type", "code"),
        ("client_id", CLIENT_ID),
        ("code_challenge", code_challenge),
        ("code_challenge_method", "S256"),
        ("redirect_uri", REDIRECT_URI),
        ("state", state),
        ("scope", SCOPES),
    ]
    query = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in params)
    return f"{AUTHORIZE_URL}?{query}"


def clean_auth_code(raw_code: str) -> str:
    """Strip URL fragments and query params that may be pasted with the auth code.

    The callback page URL may look like:
      https://...callback?code=XXXX&state=UUID
    or the user may paste:
      XXXX#state-uuid
    We only want the code portion.
    """
    code = raw_code.strip()
    # Strip URL fragment (everything after #)
    if "#" in code:
        code = code.split("#", 1)[0]
    # Strip query params if user pasted a full URL
    if "?" in code:
        import urllib.parse
        parsed = urllib.parse.urlparse(code)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            code = qs["code"][0]
        else:
            # Just take what's before the ?
            code = code.split("?", 1)[0]
    return code.strip()


def exchange_code(auth_code: str, code_verifier: str, state: str) -> dict:
    """Exchange authorization code for tokens.

    Matches the exact request format used by the Claude Code binary:
    JSON body with grant_type, code, redirect_uri, client_id, code_verifier, and state.
    """
    import subprocess

    code = clean_auth_code(auth_code)
    print(f"  Auth code (cleaned): {code[:8]}...{code[-4:]}")

    payload = json.dumps({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": code_verifier,
        "state": state,
    })

    result = subprocess.run(
        [
            "curl", "-s", "-w", "\n%{http_code}",
            "-X", "POST",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: claude-code/2.1.31",
            "-H", "x-app: cli",
            "-L",  # follow redirects
            "--post301", "--post302", "--post303",  # keep POST on redirects
            "-d", payload,
            TOKEN_URL,
        ],
        capture_output=True, text=True, timeout=30,
    )

    lines = result.stdout.strip().rsplit("\n", 1)
    body = lines[0] if len(lines) > 0 else ""
    status = int(lines[1]) if len(lines) > 1 else 0

    if status == 200:
        return json.loads(body)

    print(f"  Token exchange failed (HTTP {status}): {body}", file=sys.stderr)
    sys.exit(1)


def save_credentials(home_dir: str, token_data: dict):
    """Save OAuth credentials to the Claude credentials file."""
    creds_dir = Path(home_dir) / ".claude"
    creds_dir.mkdir(parents=True, exist_ok=True)
    creds_file = creds_dir / ".credentials.json"

    # Load existing or create new
    existing = {}
    if creds_file.is_file():
        try:
            existing = json.loads(creds_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    expires_in = token_data.get("expires_in", 28800)
    existing["claudeAiOauth"] = {
        "accessToken": token_data["access_token"],
        "refreshToken": token_data.get("refresh_token", ""),
        "expiresAt": int(time.time() * 1000) + (expires_in * 1000),
        "scopes": SCOPES.split(),
        "subscriptionType": token_data.get("subscription_type", "unknown"),
        "rateLimitTier": token_data.get("rate_limit_tier", "unknown"),
    }

    creds_file.write_text(json.dumps(existing, indent=2))
    print(f"  Credentials saved to {creds_file}")
    print(f"  Token valid for {expires_in // 60} minutes")


def discover_account_homes(real_home: str) -> list[Path]:
    homes_dir = Path(real_home) / ".claude-homes"
    if not homes_dir.is_dir():
        return []

    homes = [
        path
        for path in homes_dir.iterdir()
        if path.is_dir() and ACCOUNT_NAME_RE.fullmatch(path.name)
    ]
    return sorted(homes, key=lambda path: int(ACCOUNT_NAME_RE.fullmatch(path.name).group(1)))


def ensure_account_home(real_home: str, account_num: int) -> Path:
    account_home = Path(real_home) / ".claude-homes" / f"account{account_num}"
    (account_home / ".claude").mkdir(parents=True, exist_ok=True)
    return account_home


def login_account(home_dir: str, label: str = ""):
    """Run the headless login flow for one account."""
    display = label or home_dir
    print(f"\n{'=' * 60}")
    print(f"Login: {display}")
    print(f"{'=' * 60}")

    code_verifier, code_challenge = generate_pkce()
    state = str(uuid.uuid4())
    url = build_authorize_url(code_challenge, state)

    print(f"\n1. Open this URL in your browser:\n")
    print(f"   {url}\n")
    print(f"2. Log in with the account for {display}")
    print(f"3. After authorization, you'll see a page with a code.")
    print(f"   Copy the authorization code and paste it below.")
    print(f"   (If the code contains a '#', only paste the part BEFORE the '#')\n")

    auth_code = input("Authorization code: ").strip()
    if not auth_code:
        print("ERROR: No code provided, skipping.", file=sys.stderr)
        return False

    print("  Exchanging code for tokens...")
    token_data = exchange_code(auth_code, code_verifier, state)

    save_credentials(home_dir, token_data)
    print(f"  Login successful for {display}!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Headless OAuth login for Claude Code."
    )
    parser.add_argument("--home", default=None,
                        help="Home directory for credentials (default: $HOME)")
    parser.add_argument(
        "--account",
        type=int,
        default=None,
        help="Account number under ~/.claude-homes/accountN to create/use.",
    )
    parser.add_argument("--all-accounts", action="store_true",
                        help="Login for all existing accounts under ~/.claude-homes/")
    args = parser.parse_args()

    real_home = os.environ.get("HOME", os.path.expanduser("~"))

    if args.home and args.account is not None:
        parser.error("--home and --account are mutually exclusive")
    if args.all_accounts and args.account is not None:
        parser.error("--all-accounts and --account are mutually exclusive")

    if args.all_accounts:
        account_homes = discover_account_homes(real_home)
        if not account_homes:
            homes_dir = Path(real_home) / ".claude-homes"
            print(f"No account directories found at {homes_dir}")
            sys.exit(1)

        for account_home in account_homes:
            login_account(str(account_home), account_home.name)

        print(f"\n{'=' * 60}")
        print(f"All {len(account_homes)} accounts processed.")
        print(f"{'=' * 60}")
    else:
        if args.account is not None:
            account_home = ensure_account_home(real_home, args.account)
            login_account(str(account_home), f"account{args.account}")
            return
        home = args.home or real_home
        login_account(home)


if __name__ == "__main__":
    main()

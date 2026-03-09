#!/usr/bin/env python3
"""Daytona PoC: Paired task runner for CodeScaleBench.

Runs the cgen-deps-install-001 task in both baseline and MCP configurations
using Daytona sandboxes, then collects and compares results.

Prerequisites:
  - daytona-sdk >= 0.148.0 (pip install daytona-sdk)
  - Two active Daytona sandboxes: ccb-baseline-poc, ccb-mcp-poc
  - Auth: either ANTHROPIC_API_KEY / ~/.claude/credentials.json (api-key mode)
          or ~/.claude-homes/accountN/.claude/.credentials.json (oauth mode)
  - SRC_ACCESS_TOKEN env var for Sourcegraph MCP
  - DAYTONA_API_KEY env var or ~/.config/daytona/env.sh

Usage:
  # API key auth (default)
  python3 scripts/daytona_poc_runner.py [--setup-only] [--run-only] [--verify-only]

  # OAuth with Max account
  python3 scripts/daytona_poc_runner.py --auth oauth --account 1
  python3 scripts/daytona_poc_runner.py --auth oauth --account 2 --mcp-only
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TASK_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "ccb_build" / "cgen-deps-install-001"
BASELINE_SANDBOX = "ccb-baseline-poc"
MCP_SANDBOX = "ccb-mcp-poc"
DAYTONA_API_URL = "https://app.daytona.io/api"
DAYTONA_TARGET = "us"

# Claude Code settings
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TURNS = 30
CLAUDE_TIMEOUT = 900  # 15 minutes


def load_daytona_api_key():
    """Load Daytona API key from env or config file."""
    key = os.environ.get("DAYTONA_API_KEY", "")
    if key:
        return key
    config_path = Path.home() / ".config" / "daytona" / "env.sh"
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            if line.startswith("export DAYTONA_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    # Try parsing from env.sh with different format
    for line in config_path.read_text().splitlines() if config_path.exists() else []:
        if "DAYTONA_API_KEY" in line and "=" in line:
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_anthropic_api_key():
    """Load Anthropic API key from env or credentials file."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    creds_path = Path.home() / ".claude" / "credentials.json"
    if creds_path.exists():
        creds = json.loads(creds_path.read_text())
        return creds.get("apiKey", "")
    return ""


def load_src_access_token():
    """Load Sourcegraph access token from environment."""
    return os.environ.get("SRC_ACCESS_TOKEN", "")


# ---------------------------------------------------------------------------
# OAuth credential management
# ---------------------------------------------------------------------------
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Official Claude Code CLI client ID
OAUTH_TOKEN_URL = "https://console.anthropic.com/api/oauth/token"
REFRESH_MARGIN = 1800  # 30 minutes — refresh if token expires within this window
ACCOUNT_NAME_RE = re.compile(r"account(\d+)$")


def _account_creds_path(account_num):
    """Return path to credentials.json for a given account number."""
    return Path.home() / ".claude-homes" / f"account{account_num}" / ".claude" / ".credentials.json"


def _account_home(account_num):
    """Return the home directory for a given account number."""
    return Path.home() / ".claude-homes" / f"account{account_num}"


def _discover_account_numbers():
    """Return configured account numbers under ~/.claude-homes/accountN."""
    homes_dir = Path.home() / ".claude-homes"
    if not homes_dir.is_dir():
        return []

    account_numbers = []
    for path in homes_dir.iterdir():
        if not path.is_dir():
            continue
        match = ACCOUNT_NAME_RE.fullmatch(path.name)
        if match:
            account_numbers.append(int(match.group(1)))
    return sorted(account_numbers)


def list_oauth_accounts():
    """List available OAuth accounts and their token status."""
    accounts = []
    for num in _discover_account_numbers():
        creds_path = _account_creds_path(num)
        if not creds_path.exists():
            # Also try without leading dot
            alt_path = creds_path.parent / "credentials.json"
            if alt_path.exists():
                creds_path = alt_path
            else:
                accounts.append({
                    "num": num,
                    "path": str(creds_path),
                    "error": "missing credentials",
                })
                continue
        try:
            creds = json.loads(creds_path.read_text())
            oauth = creds.get("claudeAiOauth", {})
            expires_at_ms = oauth.get("expiresAt", 0)
            now_ms = int(time.time() * 1000)
            remaining_min = int((expires_at_ms - now_ms) / 60000)
            has_refresh = bool(oauth.get("refreshToken"))
            accounts.append({
                "num": num,
                "path": str(creds_path),
                "remaining_min": remaining_min,
                "has_refresh": has_refresh,
                "valid": remaining_min > 0 or has_refresh,
            })
        except Exception as e:
            accounts.append({"num": num, "path": str(creds_path), "error": str(e)})
    return accounts


def refresh_oauth_token(account_num):
    """Refresh the OAuth token for a given account. Returns the updated credentials dict."""
    creds_path = _account_creds_path(account_num)
    if not creds_path.exists():
        alt_path = creds_path.parent / "credentials.json"
        if alt_path.exists():
            creds_path = alt_path
        else:
            raise FileNotFoundError(f"No credentials at {creds_path}")

    creds = json.loads(creds_path.read_text())
    oauth = creds.get("claudeAiOauth", {})

    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    remaining_s = (expires_at_ms - now_ms) / 1000

    if remaining_s > REFRESH_MARGIN:
        print(f"  Account {account_num}: token valid ({int(remaining_s / 60)} min remaining)")
        return creds

    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise ValueError(f"Account {account_num}: no refreshToken in credentials")

    print(f"  Account {account_num}: token expires in {int(remaining_s / 60)} min — refreshing...")

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()

    req = urllib.request.Request(
        OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ccb-daytona-runner/1.0"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"Token refresh failed: HTTP {e.code} — {body}")

    new_access = token_data.get("access_token")
    if not new_access:
        raise RuntimeError("No access_token in refresh response")

    oauth["accessToken"] = new_access
    if token_data.get("refresh_token"):
        oauth["refreshToken"] = token_data["refresh_token"]
    expires_in = token_data.get("expires_in", 28800)
    oauth["expiresAt"] = int(time.time() * 1000) + (expires_in * 1000)
    creds["claudeAiOauth"] = oauth

    # Write back
    creds_path.write_text(json.dumps(creds, indent=2))
    print(f"  Account {account_num}: refreshed (valid for {expires_in // 60} min)")
    return creds


def load_oauth_credentials(account_num):
    """Load and optionally refresh OAuth credentials for an account.

    Returns a dict with:
      - access_token: the current valid access token
      - creds_json: the full credentials.json content to upload to sandbox
    """
    creds = refresh_oauth_token(account_num)
    oauth = creds.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken", "")
    if not access_token:
        raise ValueError(f"Account {account_num}: no accessToken after refresh")
    return {
        "access_token": access_token,
        "creds_json": json.dumps(creds),
        "creds_dict": creds,
    }


def exec_cmd(sandbox, cmd, description="", timeout=120):
    """Execute a command in a Daytona sandbox and return output."""
    label = f"[{sandbox.id[:8]}]"
    if description:
        print(f"  {label} {description}")
    try:
        response = sandbox.process.exec(cmd, timeout=timeout)
        if hasattr(response, 'exit_code') and response.exit_code != 0:
            stderr = getattr(response, 'stderr', '') or ''
            stdout = getattr(response, 'result', '') or getattr(response, 'stdout', '') or ''
            print(f"  {label} WARNING: exit code {response.exit_code}")
            if stderr:
                print(f"  {label} stderr: {stderr[:500]}")
            return stdout
        result = getattr(response, 'result', '') or getattr(response, 'stdout', '') or ''
        return result
    except Exception as e:
        print(f"  {label} ERROR: {e}")
        return ""


def setup_sandbox(sandbox, sandbox_type, src_token, auth_mode="api-key",
                  anthropic_key="", oauth_creds=None):
    """Install Claude Code and configure auth in a sandbox.

    Args:
        sandbox: Daytona sandbox object
        sandbox_type: "baseline" or "mcp"
        src_token: Sourcegraph access token (only needed for mcp type)
        auth_mode: "api-key" or "oauth"
        anthropic_key: Anthropic API key (for api-key mode)
        oauth_creds: dict from load_oauth_credentials() (for oauth mode)
    """
    name = BASELINE_SANDBOX if sandbox_type == "baseline" else MCP_SANDBOX
    print(f"\n{'='*60}")
    print(f"Setting up {sandbox_type} sandbox: {name} (auth: {auth_mode})")
    print(f"{'='*60}")

    # 1. Check existing state
    exec_cmd(sandbox, "uname -a && whoami", "Checking sandbox environment")

    # 2. Install Node.js 22 (required for Claude Code)
    print(f"\n  Installing Node.js 22...")
    exec_cmd(
        sandbox,
        "curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.gz "
        "| tar -xz -C /usr/local --strip-components=1 "
        "&& node --version && npm --version",
        "Installing Node.js 22",
        timeout=120,
    )

    # 3. Install Claude Code CLI
    print(f"  Installing Claude Code CLI...")
    exec_cmd(
        sandbox,
        "npm install -g @anthropic-ai/claude-code@latest 2>&1 | tail -5 "
        "&& which claude && claude --version",
        "Installing Claude Code",
        timeout=180,
    )

    # 4. Create non-root user (Claude Code refuses --dangerously-skip-permissions as root)
    print(f"  Creating non-root user...")
    exec_cmd(
        sandbox,
        "id -u claude &>/dev/null || useradd -m -s /bin/bash claude 2>/dev/null || true",
        "Creating claude user",
    )
    exec_cmd(
        sandbox,
        "chown -R claude:claude /app /logs /tests 2>/dev/null || true",
        "Setting ownership",
    )

    # 5. Configure authentication
    print(f"  Configuring authentication ({auth_mode})...")
    if auth_mode == "oauth" and oauth_creds:
        # OAuth mode: write full credentials with claudeAiOauth token.
        # Claude Code CLI reads ~/.claude/.credentials.json (note leading dot)
        # for OAuth and ~/.claude/credentials.json (no dot) for API key.
        creds_content = oauth_creds["creds_json"]
        exec_cmd(
            sandbox,
            f"mkdir -p /home/claude/.claude "
            f"&& cat > /home/claude/.claude/.credentials.json << 'CREDEOF'\n{creds_content}\nCREDEOF",
            "Writing OAuth .credentials.json",
        )
        # Unset any stale API key so Claude Code uses OAuth
        exec_cmd(
            sandbox,
            "rm -f /home/claude/.claude/credentials.json",
            "Removing API key credentials (using OAuth instead)",
        )
    else:
        # API key mode
        creds_json = json.dumps({"apiKey": anthropic_key})
        exec_cmd(
            sandbox,
            f"mkdir -p /home/claude/.claude "
            f"&& echo '{creds_json}' > /home/claude/.claude/credentials.json",
            "Writing API key credentials.json",
        )
    exec_cmd(sandbox, "chown -R claude:claude /home/claude", "Setting home ownership")

    # 6. For MCP sandbox: configure Sourcegraph MCP server
    if sandbox_type == "mcp" and src_token:
        print(f"  Configuring Sourcegraph MCP...")
        mcp_config = {
            "mcpServers": {
                "sourcegraph": {
                    "command": "npx",
                    "args": ["-y", "@sourcegraph/mcp-server"],
                    "env": {
                        "SRC_ACCESS_TOKEN": src_token,
                        "SOURCEGRAPH_URL": "https://sourcegraph.com",
                    },
                }
            }
        }
        mcp_json = json.dumps(mcp_config)
        # Place in both locations Claude Code checks
        exec_cmd(
            sandbox,
            f"mkdir -p /home/claude/.config/claude /home/claude/.claude "
            f"&& echo '{mcp_json}' > /home/claude/.config/claude/mcp.json "
            f"&& echo '{mcp_json}' > /tmp/.mcp.json "
            f"&& chown -R claude:claude /home/claude/.config",
            "Writing MCP config",
        )

    # 7. Create required directories
    exec_cmd(sandbox, "mkdir -p /logs/agent /logs/verifier /tests", "Creating log directories")

    # 8. Verify installation
    result = exec_cmd(sandbox, "claude --version 2>&1 && echo '---' && node --version", "Verifying installation")
    print(f"  Installation result: {result[:200]}")

    return True


def upload_test_files(sandbox, sandbox_type):
    """Upload test infrastructure files to sandbox."""
    name = BASELINE_SANDBOX if sandbox_type == "baseline" else MCP_SANDBOX
    print(f"\n  Uploading test files to {name}...")

    test_files = [
        "test.sh",
        "validators.py",
        "sgonly_verifier_wrapper.sh",
        "instance.json",
        "answer_json_verifier_lib.sh",
    ]

    for filename in test_files:
        local_path = TASK_DIR / "tests" / filename
        if not local_path.exists():
            continue
        text = local_path.read_text()
        # Use heredoc to write files (avoids SDK path ambiguity)
        exec_cmd(
            sandbox,
            f"cat > /tests/{filename} << 'FILEEOF'\n{text}\nFILEEOF",
            f"Writing /tests/{filename}",
        )
        print(f"    Wrote /tests/{filename} ({len(text)} bytes)")

    # Make scripts executable
    exec_cmd(sandbox, "chmod +x /tests/test.sh /tests/sgonly_verifier_wrapper.sh 2>/dev/null || true")


def run_claude_task(sandbox, sandbox_type, src_token, auth_mode="api-key",
                    anthropic_key="", oauth_creds=None):
    """Run Claude Code with the task instruction in a sandbox.

    Returns the sandbox process output.
    """
    name = BASELINE_SANDBOX if sandbox_type == "baseline" else MCP_SANDBOX

    # Select the right instruction file
    if sandbox_type == "baseline":
        instruction_path = TASK_DIR / "instruction.md"
    else:
        instruction_path = TASK_DIR / "instruction_mcp.md"

    instruction = instruction_path.read_text()

    print(f"\n{'='*60}")
    print(f"Running Claude Code ({sandbox_type}, {auth_mode}): {name}")
    print(f"{'='*60}")
    print(f"  Instruction: {instruction_path.name} ({len(instruction)} chars)")
    print(f"  Model: {CLAUDE_MODEL}")
    print(f"  Max turns: {CLAUDE_MAX_TURNS}")

    # Build the claude command
    claude_flags = [
        "--dangerously-skip-permissions",
        f"--max-turns {CLAUDE_MAX_TURNS}",
        "--output-format json",
    ]

    # For MCP sandbox, add MCP config
    if sandbox_type == "mcp":
        claude_flags.append("--mcp-config /tmp/.mcp.json")

    flags_str = " ".join(claude_flags)

    # Write instruction to a file in the sandbox to avoid shell escaping issues
    exec_cmd(
        sandbox,
        f"cat > /tmp/task_instruction.md << 'INSTREOF'\n{instruction}\nINSTREOF",
        "Writing instruction file",
    )

    # Build wrapper script — must run as non-root 'claude' user
    # because --dangerously-skip-permissions refuses to run as root.
    # Using a wrapper script avoids quoting issues with su -c.
    script_lines = [
        "#!/bin/bash",
        "set -e",
        "export PATH=/usr/local/bin:/usr/bin:/bin:$PATH",
        "export HOME=/home/claude",
        "export CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000",
    ]
    # Auth: API key mode sets ANTHROPIC_API_KEY env var.
    # OAuth mode relies on ~/.claude/.credentials.json (written during setup).
    if auth_mode == "api-key" and anthropic_key:
        script_lines.append(f"export ANTHROPIC_API_KEY={anthropic_key}")
    # OAuth mode: Claude Code reads the token from .credentials.json automatically.
    # We also set CLAUDE_CODE_OAUTH_TOKEN as a fallback (Harbor does this too).
    if auth_mode == "oauth" and oauth_creds:
        script_lines.append(
            f"export CLAUDE_CODE_OAUTH_TOKEN={oauth_creds['access_token']}"
        )
    if sandbox_type == "mcp" and src_token:
        script_lines.append(f"export SRC_ACCESS_TOKEN={src_token}")
    script_lines.extend([
        "cd /app/repo",
        f'claude {flags_str} -p "$(cat /tmp/task_instruction.md)"',
    ])
    wrapper = "\n".join(script_lines) + "\n"

    exec_cmd(sandbox, f"cat > /tmp/run_claude.sh << 'WRAPEOF'\n{wrapper}\nWRAPEOF")
    exec_cmd(sandbox, "chmod +x /tmp/run_claude.sh")

    cmd = "su - claude -c 'bash /tmp/run_claude.sh'"

    print(f"  Starting Claude Code agent...")
    start_time = time.time()

    result = exec_cmd(sandbox, cmd, "Running agent", timeout=CLAUDE_TIMEOUT)

    elapsed = time.time() - start_time
    print(f"  Agent completed in {elapsed:.1f}s")
    print(f"  Output length: {len(result)} chars")

    # Save raw output
    exec_cmd(sandbox, f"echo '{elapsed:.1f}' > /logs/agent/elapsed_seconds.txt")

    return {
        "sandbox_type": sandbox_type,
        "elapsed_seconds": elapsed,
        "output_length": len(result),
        "raw_output": result[:5000],  # Truncate for display
    }


def run_verification(sandbox, sandbox_type):
    """Run the test.sh verifier and collect results."""
    name = BASELINE_SANDBOX if sandbox_type == "baseline" else MCP_SANDBOX
    print(f"\n  Running verification for {name}...")

    result = exec_cmd(
        sandbox,
        "cd /app/repo && bash /tests/test.sh 2>&1",
        "Running test.sh",
        timeout=300,
    )

    # Read reward file
    reward_output = exec_cmd(sandbox, "cat /logs/verifier/reward.txt 2>/dev/null || echo 'NO_REWARD'")
    reward = reward_output.strip()

    print(f"  Verification output: {result[:500]}")
    print(f"  Reward: {reward}")

    return {
        "sandbox_type": sandbox_type,
        "reward": reward,
        "verification_output": result[:2000],
    }


def print_results(baseline_run, mcp_run, baseline_verify, mcp_verify):
    """Print a comparison table of results."""
    print(f"\n{'='*70}")
    print(f"DAYTONA PoC RESULTS: cgen-deps-install-001")
    print(f"{'='*70}")
    print(f"")
    print(f"{'Metric':<30} {'Baseline':<20} {'MCP (sg_only)':<20}")
    print(f"{'-'*30} {'-'*20} {'-'*20}")
    print(f"{'Elapsed (seconds)':<30} {baseline_run['elapsed_seconds']:<20.1f} {mcp_run['elapsed_seconds']:<20.1f}")
    print(f"{'Output length (chars)':<30} {baseline_run['output_length']:<20} {mcp_run['output_length']:<20}")
    print(f"{'Reward':<30} {baseline_verify['reward']:<20} {mcp_verify['reward']:<20}")
    print(f"")

    # Determine pass/fail
    bl_pass = baseline_verify['reward'].strip() == '1.0'
    mcp_pass = mcp_verify['reward'].strip() == '1.0'
    print(f"{'Pass/Fail':<30} {'PASS' if bl_pass else 'FAIL':<20} {'PASS' if mcp_pass else 'FAIL':<20}")
    print(f"")

    # Summary
    if bl_pass and mcp_pass:
        print("Both configurations passed. MCP provides equivalent capability.")
    elif bl_pass and not mcp_pass:
        print("Baseline passed but MCP failed. MCP may need more context or turns.")
    elif not bl_pass and mcp_pass:
        print("MCP passed but baseline failed. MCP tools helped solve the task.")
    else:
        print("Both configurations failed. Task may need more turns or a stronger model.")

    print(f"\n{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Daytona PoC paired task runner")
    parser.add_argument("--setup-only", action="store_true", help="Only set up sandboxes, don't run tasks")
    parser.add_argument("--run-only", action="store_true", help="Skip setup, run tasks only")
    parser.add_argument("--verify-only", action="store_true", help="Skip setup+run, verify only")
    parser.add_argument("--baseline-only", action="store_true", help="Only run baseline")
    parser.add_argument("--mcp-only", action="store_true", help="Only run MCP")
    parser.add_argument(
        "--auth", choices=["api-key", "oauth"], default="api-key",
        help="Auth mode: api-key (default) or oauth (uses Max account credentials)",
    )
    parser.add_argument(
        "--account", type=int, default=1,
        help="OAuth account number under ~/.claude-homes/accountN. Default: 1",
    )
    parser.add_argument(
        "--list-accounts", action="store_true",
        help="List available OAuth accounts and exit",
    )
    args = parser.parse_args()

    # List accounts mode
    if args.list_accounts:
        accounts = list_oauth_accounts()
        if not accounts:
            print("No OAuth accounts found at ~/.claude-homes/accountN/.claude/.credentials.json")
            print("\nTo set up accounts, create the directory structure:")
            print("  mkdir -p ~/.claude-homes/account1/.claude")
            print("  # Or run: python3 scripts/headless_login.py --account 1")
        else:
            print(f"Found {len(accounts)} OAuth account(s):\n")
            for a in accounts:
                if "error" in a:
                    print(f"  account{a['num']}: ERROR — {a['error']}")
                else:
                    status = f"{a['remaining_min']} min remaining" if a['remaining_min'] > 0 else "EXPIRED"
                    refresh = "has refresh token" if a['has_refresh'] else "NO refresh token"
                    print(f"  account{a['num']}: {status} ({refresh})")
                    print(f"    {a['path']}")
        return

    # Load credentials
    daytona_key = load_daytona_api_key()
    src_token = load_src_access_token()
    anthropic_key = ""
    oauth_creds = None

    if not daytona_key:
        print("ERROR: No Daytona API key found. Set DAYTONA_API_KEY or check ~/.config/daytona/env.sh")
        sys.exit(1)

    if args.auth == "oauth":
        print(f"Auth mode: OAuth (account {args.account})")
        try:
            oauth_creds = load_oauth_credentials(args.account)
            print(f"  OAuth token loaded ({len(oauth_creds['access_token'])} chars)")
        except Exception as e:
            print(f"ERROR: Failed to load OAuth credentials for account {args.account}: {e}")
            print("\nTo set up OAuth accounts:")
            print(f"  mkdir -p ~/.claude-homes/account{args.account}/.claude")
            print(f"  python3 scripts/headless_login.py --account {args.account}")
            sys.exit(1)
    else:
        anthropic_key = load_anthropic_api_key()
        if not anthropic_key:
            print("ERROR: No Anthropic API key found. Set ANTHROPIC_API_KEY or check ~/.claude/credentials.json")
            sys.exit(1)
        print(f"Auth mode: API key ({anthropic_key[:10]}...)")

    if not src_token:
        print("WARNING: No SRC_ACCESS_TOKEN found. MCP sandbox will not have Sourcegraph access.")

    print(f"Daytona API key: {daytona_key[:10]}...")
    print(f"SRC_ACCESS_TOKEN: {'set' if src_token else 'NOT SET'}")

    # Connect to Daytona
    from daytona_sdk import Daytona, DaytonaConfig

    config = DaytonaConfig(
        api_key=daytona_key,
        api_url=DAYTONA_API_URL,
        target=DAYTONA_TARGET,
    )
    daytona = Daytona(config)

    run_baseline = not args.mcp_only
    run_mcp = not args.baseline_only

    # Connect to sandboxes
    baseline_sandbox = None
    mcp_sandbox = None

    if run_baseline:
        print(f"\nConnecting to baseline sandbox: {BASELINE_SANDBOX}")
        try:
            baseline_sandbox = daytona.get(BASELINE_SANDBOX)
            print(f"  Connected: {baseline_sandbox.id}")
        except Exception as e:
            print(f"  ERROR connecting to baseline: {e}")
            if not args.mcp_only:
                sys.exit(1)

    if run_mcp:
        print(f"\nConnecting to MCP sandbox: {MCP_SANDBOX}")
        try:
            mcp_sandbox = daytona.get(MCP_SANDBOX)
            print(f"  Connected: {mcp_sandbox.id}")
        except Exception as e:
            print(f"  ERROR connecting to MCP sandbox: {e}")
            if not args.baseline_only:
                sys.exit(1)

    # Common auth kwargs for setup_sandbox and run_claude_task
    auth_kwargs = {
        "auth_mode": args.auth,
        "anthropic_key": anthropic_key,
        "oauth_creds": oauth_creds,
    }

    # Phase 1: Setup
    if not args.run_only and not args.verify_only:
        if baseline_sandbox and run_baseline:
            setup_sandbox(baseline_sandbox, "baseline", src_token, **auth_kwargs)
            upload_test_files(baseline_sandbox, "baseline")
        if mcp_sandbox and run_mcp:
            setup_sandbox(mcp_sandbox, "mcp", src_token, **auth_kwargs)
            upload_test_files(mcp_sandbox, "mcp")

    if args.setup_only:
        print("\nSetup complete. Use --run-only to execute tasks.")
        return

    # Phase 2: Run Claude Code
    baseline_run = {"elapsed_seconds": 0, "output_length": 0, "raw_output": ""}
    mcp_run = {"elapsed_seconds": 0, "output_length": 0, "raw_output": ""}

    if not args.verify_only:
        if baseline_sandbox and run_baseline:
            baseline_run = run_claude_task(baseline_sandbox, "baseline", src_token, **auth_kwargs)
        if mcp_sandbox and run_mcp:
            mcp_run = run_claude_task(mcp_sandbox, "mcp", src_token, **auth_kwargs)

    if args.run_only and not args.verify_only:
        # Still run verification after task
        pass

    # Phase 3: Verify
    baseline_verify = {"reward": "N/A", "verification_output": ""}
    mcp_verify = {"reward": "N/A", "verification_output": ""}

    if baseline_sandbox and run_baseline:
        baseline_verify = run_verification(baseline_sandbox, "baseline")
    if mcp_sandbox and run_mcp:
        mcp_verify = run_verification(mcp_sandbox, "mcp")

    # Phase 4: Results
    print_results(baseline_run, mcp_run, baseline_verify, mcp_verify)

    # Save results JSON
    results = {
        "task": "cgen-deps-install-001",
        "platform": "daytona",
        "baseline": {**baseline_run, **baseline_verify},
        "mcp": {**mcp_run, **mcp_verify},
    }
    results_path = Path(__file__).parent.parent / "runs" / "daytona_poc_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults saved to: {results_path}")


if __name__ == "__main__":
    main()

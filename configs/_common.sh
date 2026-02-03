#!/bin/bash
# Shared configuration and helpers for all benchmark scripts.
# Source this at the top of every *_3config.sh and run_selected_tasks.sh.

# ============================================
# AUTHENTICATION MODE
# ============================================
# Use Claude Max subscription instead of API key.
# The agent reads ~/.claude/.credentials.json for the OAuth access token.
export USE_SUBSCRIPTION=true

# ============================================
# TOKEN REFRESH
# ============================================
# Refresh the Claude OAuth access token if it expires within REFRESH_MARGIN seconds.
# Uses the refresh_token from ~/.claude/.credentials.json.
# The OAuth endpoint returns a new access_token AND a new refresh_token (single-use).
REFRESH_MARGIN=${REFRESH_MARGIN:-1800}  # default: 30 minutes

refresh_claude_token() {
    local creds_file="$HOME/.claude/.credentials.json"
    if [ ! -f "$creds_file" ]; then
        echo "WARNING: No credentials file at $creds_file"
        return 1
    fi

    python3 - "$creds_file" "$REFRESH_MARGIN" <<'PYEOF'
import json, sys, time, urllib.request, urllib.error

creds_file = sys.argv[1]
margin = int(sys.argv[2])

with open(creds_file) as f:
    creds = json.load(f)

oauth = creds.get("claudeAiOauth", {})
expires_at_ms = oauth.get("expiresAt", 0)
now_ms = int(time.time() * 1000)
remaining_s = (expires_at_ms - now_ms) / 1000

if remaining_s > margin:
    mins = int(remaining_s / 60)
    print(f"Token still valid ({mins} min remaining, threshold {margin // 60} min). No refresh needed.")
    sys.exit(0)

refresh_token = oauth.get("refreshToken")
if not refresh_token:
    print("ERROR: No refreshToken in credentials file", file=sys.stderr)
    sys.exit(1)

print(f"Token expires in {int(remaining_s / 60)} min — refreshing...")

# Official Claude Code CLI client ID
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
except urllib.error.HTTPError as e:
    body = e.read().decode() if e.fp else ""
    print(f"ERROR: Token refresh failed: HTTP {e.code} — {body}", file=sys.stderr)
    sys.exit(1)

new_access = token_data.get("access_token")
new_refresh = token_data.get("refresh_token")
expires_in = token_data.get("expires_in", 28800)  # default 8h

if not new_access:
    print("ERROR: No access_token in refresh response", file=sys.stderr)
    sys.exit(1)

oauth["accessToken"] = new_access
if new_refresh:
    oauth["refreshToken"] = new_refresh
oauth["expiresAt"] = int(time.time() * 1000) + (expires_in * 1000)
creds["claudeAiOauth"] = oauth

with open(creds_file, "w") as f:
    json.dump(creds, f, indent=2)

new_mins = expires_in // 60
print(f"Token refreshed successfully. New token valid for {new_mins} min.")
PYEOF
}

# ============================================
# ENSURE FRESH TOKEN
# ============================================
# Call this after sourcing .env.local but before launching runs.
ensure_fresh_token() {
    if [ "$USE_SUBSCRIPTION" = "true" ]; then
        echo "Checking Claude subscription token..."
        refresh_claude_token || echo "WARNING: Token refresh failed — runs may fail if token expires"
    fi
}

# ============================================
# POST-TASK VALIDATION
# ============================================
# Accumulator for validation warnings across all batches in a run.
VALIDATION_LOG=""

validate_and_report() {
    local jobs_dir=$1
    local mode=$2
    echo "Validating task results in $jobs_dir..."
    local _val_output
    _val_output=$(python3 "$(dirname "${BASH_SOURCE[0]}")/../scripts/validate_task_run.py" \
        --jobs-dir "$jobs_dir" --config "$mode" 2>&1) || true
    echo "$_val_output"
    VALIDATION_LOG+="$_val_output"$'\n'
}

print_validation_summary() {
    local run_dir="${1:-}"
    if [ -z "$VALIDATION_LOG" ]; then
        return
    fi
    echo ""
    echo "=============================================="
    echo "Validation Summary"
    echo "=============================================="
    echo "$VALIDATION_LOG"

    # Aggregate all config-level flagged_tasks.json into a run-level file
    if [ -n "$run_dir" ] && [ -d "$run_dir" ]; then
        python3 -c "
import json, glob, os, sys
run_dir = sys.argv[1]
all_flags = []
configs_seen = []
tasks_checked = 0
for fp in sorted(glob.glob(os.path.join(run_dir, '*/flagged_tasks.json'))):
    with open(fp) as f:
        data = json.load(f)
    configs_seen.append(data.get('config', ''))
    tasks_checked += data.get('tasks_checked', 0)
    all_flags.extend(data.get('flags', []))
if not configs_seen:
    sys.exit(0)
summary = {
    'configs': configs_seen,
    'tasks_checked': tasks_checked,
    'total_flags': len(all_flags),
    'critical_count': sum(1 for f in all_flags if f['severity'] == 'CRITICAL'),
    'warning_count': sum(1 for f in all_flags if f['severity'] == 'WARNING'),
    'info_count': sum(1 for f in all_flags if f['severity'] == 'INFO'),
    'flags': all_flags,
}
out = os.path.join(run_dir, 'flagged_tasks.json')
with open(out, 'w') as f:
    json.dump(summary, f, indent=2)
print(f'Run-level summary: {out}')
" "$run_dir" 2>&1 || true
    fi
}

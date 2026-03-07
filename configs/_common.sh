#!/bin/bash
# Shared configuration and helpers for all benchmark scripts.
# Source this at the top of every *_3config.sh and run_selected_tasks.sh.

# ============================================
# AUTHENTICATION MODE — SUBSCRIPTION ONLY
# ============================================
# All runs use Claude Max subscription (OAuth tokens).
# API key mode has been removed. USE_SUBSCRIPTION is always true.
export USE_SUBSCRIPTION=true
DAYTONA_ENV_IMPORT_PATH="${DAYTONA_ENV_IMPORT_PATH:-ccb_harbor.daytona:GuardedDaytonaEnvironment}"
DAYTONA_ENFORCE_GUARD="${DAYTONA_ENFORCE_GUARD:-1}"
DAYTONA_COST_POLICY="${DAYTONA_COST_POLICY:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/configs/daytona_cost_policy.json}"

mark_daytona_cost_guard_ready() {
    export DAYTONA_COST_GUARD_PREFLIGHT_DONE=1
}

clear_daytona_cost_guard_ready() {
    unset DAYTONA_COST_GUARD_PREFLIGHT_DONE 2>/dev/null || true
}

_ccb_repo_root() {
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# Launchers and helper scripts should always have a repo root available for
# invoking repo-local utilities such as the Daytona cost guard.
export REPO_ROOT="${REPO_ROOT:-$(_ccb_repo_root)}"

_harbor_args_include_env_flag() {
    local arg
    for arg in "$@"; do
        if [ "$arg" = "--env" ] || [ "$arg" = "-e" ]; then
            return 0
        fi
    done
    return 1
}

_parse_harbor_arg_value() {
    local wanted="$1"
    shift
    local prev=""
    local arg
    for arg in "$@"; do
        if [ "$prev" = "$wanted" ]; then
            printf '%s' "$arg"
            return 0
        fi
        prev="$arg"
    done
    return 1
}

harbor_run_guarded() {
    local repo_root
    repo_root="$(_ccb_repo_root)"
    local args=("$@")
    local command=(harbor run)

    local use_daytona=false
    if [ "${HARBOR_ENV:-}" = "daytona" ]; then
        use_daytona=true
    elif _harbor_args_include_env_flag "${args[@]}" && [ "$(_parse_harbor_arg_value --env "${args[@]}")" = "daytona" ]; then
        use_daytona=true
    elif _harbor_args_include_env_flag "${args[@]}" && [ "$(_parse_harbor_arg_value -e "${args[@]}")" = "daytona" ]; then
        use_daytona=true
    fi

    if [ "$use_daytona" = true ]; then
        if [ "${DAYTONA_ENFORCE_GUARD}" = "1" ] \
            && [ "${DAYTONA_COST_GUARD_PREFLIGHT_DONE:-}" != "1" ] \
            && [ "${HARBOR_ALLOW_UNGUARDED_DAYTONA:-}" != "1" ]; then
            echo "ERROR: Daytona launch blocked. Run the Daytona cost preflight first or set HARBOR_ALLOW_UNGUARDED_DAYTONA=1."
            return 1
        fi

        if ! _harbor_args_include_env_flag "${args[@]}"; then
            command+=(--env daytona)
        fi

        command+=(--environment-import-path "$DAYTONA_ENV_IMPORT_PATH")

        local task_path jobs_dir job_name model
        task_path="$(_parse_harbor_arg_value --path "${args[@]}")"
        jobs_dir="$(_parse_harbor_arg_value --jobs-dir "${args[@]}")"
        job_name="$(_parse_harbor_arg_value --job-name "${args[@]}")"
        model="$(_parse_harbor_arg_value --model "${args[@]}")"

        local task_source_dir config_name run_id benchmark task_id category launcher mcp_type
        task_source_dir="${TASK_SOURCE_DIR:-$task_path}"
        config_name="${DAYTONA_LABEL_CONFIG:-$(basename "${jobs_dir:-unknown}")}"
        run_id="${DAYTONA_LABEL_RUN_ID:-$(basename "$(dirname "${jobs_dir:-unknown}")")}"
        benchmark="${DAYTONA_LABEL_BENCHMARK:-$(basename "$(dirname "${task_source_dir:-unknown}")")}"
        task_id="${DAYTONA_LABEL_TASK_ID:-$(basename "${task_source_dir:-unknown}")}"
        category="${DAYTONA_LABEL_CATEGORY:-$(basename "$(dirname "$(dirname "${jobs_dir:-unknown}")")")}"
        launcher="${DAYTONA_LABEL_LAUNCHER:-$(basename "$0")}"
        mcp_type="${DAYTONA_LABEL_MCP_TYPE:-${BASELINE_MCP_TYPE:-}}"

        [ -n "$launcher" ] && command+=(--ek "label_launcher=$launcher")
        [ -n "$run_id" ] && command+=(--ek "label_run_id=$run_id")
        [ -n "$benchmark" ] && command+=(--ek "label_benchmark=$benchmark")
        [ -n "$task_id" ] && command+=(--ek "label_task_id=$task_id")
        [ -n "$config_name" ] && command+=(--ek "label_config=$config_name")
        [ -n "$job_name" ] && command+=(--ek "label_job_name=$job_name")
        [ -n "$category" ] && command+=(--ek "label_category=$category")
        [ -n "$model" ] && command+=(--ek "label_model=$model")
        [ -n "$mcp_type" ] && command+=(--ek "label_mcp_type=$mcp_type")
        [ -n "$task_source_dir" ] && command+=(--ek "task_source_dir=$task_source_dir")
    fi

    command+=("${args[@]}")
    "${command[@]}"
}

# Guard function: call this in each 3config script instead of the old if/else auth block.
enforce_subscription_mode() {
    echo "Auth mode: Claude Max subscription"
    # Unset any stale API key — placeholder keys cause "Invalid API key" errors
    # when the agent tries to use API-key auth instead of OAuth subscription
    if [ "${ANTHROPIC_API_KEY:-}" = "placeholder-key" ] || [ "${ANTHROPIC_API_KEY:-}" = "" ]; then
        unset ANTHROPIC_API_KEY 2>/dev/null || true
    fi
}

# ============================================
# CREDENTIAL LOADING
# ============================================
# Loads .env.local from project root.
load_credentials() {
    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    local env_local="${repo_root}/.env.local"
    if [ -f "$env_local" ]; then
        echo "Loading credentials from $env_local..."
        source "$env_local"
    else
        echo "Warning: .env.local not found at $env_local"
    fi
}

# ============================================
# CONFIG NAME MAPPING
# ============================================
# Three-dimensional config names: {agent}-{source}-{verifier}
#   agent:    baseline (no MCP) | mcp (Sourcegraph MCP)
#   source:   local (full source) | remote (source deleted)
#   verifier: direct (git changes) | artifact (review.json)
#
# These map to internal Harbor mcp_type values via config_to_mcp_type().
# Legacy names (baseline, sourcegraph_full, artifact_full) are accepted
# for backward compatibility with existing run directories.

VERIFIER_MODE="direct"
SOURCE_ACCESS="local"

# Map composite config name → internal mcp_type for Harbor.
# Side effects: sets VERIFIER_MODE, SOURCE_ACCESS, and SOURCEGRAPH_SEARCH_BRANCH globals.
# SCIP configs set SOURCEGRAPH_SEARCH_BRANCH=scip-enabled so the agent
# targets the SCIP-indexed branch in all MCP tool calls.
config_to_mcp_type() {
    local config_name="$1"
    # Clear branch override unless it's a SCIP config
    unset SOURCEGRAPH_SEARCH_BRANCH 2>/dev/null || true
    case "$config_name" in
        baseline-local-direct)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="local"; echo "none" ;;
        mcp-remote-direct)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="remote"; echo "sourcegraph_full" ;;
        mcp-scip-remote-direct)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="remote"
            export SOURCEGRAPH_SEARCH_BRANCH="scip-enabled"
            echo "sourcegraph_full" ;;
        baseline-local-artifact)
            VERIFIER_MODE="artifact"; SOURCE_ACCESS="local"; echo "none" ;;
        mcp-remote-artifact)
            VERIFIER_MODE="artifact"; SOURCE_ACCESS="remote"; echo "artifact_full" ;;
        mcp-scip-remote-artifact)
            VERIFIER_MODE="artifact"; SOURCE_ACCESS="remote"
            export SOURCEGRAPH_SEARCH_BRANCH="scip-enabled"
            echo "artifact_full" ;;
        # Legacy names
        baseline)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="local"; echo "none" ;;
        sourcegraph_full)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="remote"; echo "sourcegraph_full" ;;
        artifact_full)
            VERIFIER_MODE="artifact"; SOURCE_ACCESS="remote"; echo "artifact_full" ;;
        none)
            VERIFIER_MODE="direct"; SOURCE_ACCESS="local"; echo "none" ;;
        *)
            echo "WARNING: Unknown config name: $config_name" >&2
            VERIFIER_MODE="direct"; SOURCE_ACCESS="local"; echo "$config_name" ;;
    esac
}

# Derive the baseline config name that pairs with a given FULL_CONFIG.
# Artifact full configs pair with artifact baselines.
baseline_config_for() {
    local full="$1"
    case "$full" in
        *-artifact|artifact_full) echo "baseline-local-artifact" ;;
        *)                        echo "baseline-local-direct" ;;
    esac
}

# Check whether a config uses SCIP precise indexing (requires branch swap).
config_uses_scip() {
    local config_name="$1"
    case "$config_name" in
        mcp-scip-*) return 0 ;;
        *)          return 1 ;;
    esac
}

# Validate a config name against the known whitelist.
# Exits 1 with error message if unknown. Call before config_to_mcp_type().
validate_config_name() {
    local config_name="$1"
    case "$config_name" in
        baseline-local-direct|mcp-remote-direct|\
        mcp-scip-remote-direct|mcp-scip-remote-artifact|\
        baseline-local-artifact|mcp-remote-artifact|\
        baseline|sourcegraph_full|artifact_full|none)
            return 0 ;;
        *)
            echo "ERROR: Unknown config name: '$config_name'" >&2
            echo "  Valid: baseline-local-direct, mcp-remote-direct, mcp-scip-remote-direct" >&2
            echo "         baseline-local-artifact, mcp-remote-artifact, mcp-scip-remote-artifact" >&2
            echo "  Legacy: baseline, sourcegraph_full, artifact_full, none" >&2
            exit 1 ;;
    esac
}

# ============================================
# PRE-FLIGHT CONFIRMATION GATE
# ============================================
# Shared pre-flight check for any script that launches harbor runs.
# Shows config, Docker status, disk, and tokens, then requires interactive
# confirmation. MUST be called before any harbor run invocation.
#
# Usage: confirm_launch "description" "config_name" [n_tasks]
#   $1 = short description (e.g., "MCP rerun: 3 SWE-Perf tasks")
#   $2 = config name (e.g., "mcp-remote-artifact")
#   $3 = number of tasks (default: 1)
#
# Exits 1 on Docker failure or low disk. Always requires Enter to proceed.
confirm_launch() {
    local description="${1:-Harbor run}"
    local config_name="${2:-unknown}"
    local n_tasks="${3:-1}"

    echo "----------------------------------------------"
    echo "PRE-FLIGHT: $description"
    echo "----------------------------------------------"
    echo "Config:       $config_name"
    echo "Tasks:        $n_tasks"

    # Docker daemon
    if timeout 10 docker info >/dev/null 2>&1; then
        echo "Docker:       OK"
    else
        echo "Docker:       FAIL — daemon not responding"
        exit 1
    fi

    # Disk space
    local _repo_root
    _repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    local _disk_free
    _disk_free=$(df -BG --output=avail "$_repo_root" 2>/dev/null | tail -1 | tr -d ' G')
    if [ -n "$_disk_free" ] && [ "$_disk_free" -lt 5 ]; then
        echo "Disk space:   FAIL — only ${_disk_free}GB free"
        exit 1
    elif [ -n "$_disk_free" ] && [ "$_disk_free" -lt 20 ]; then
        echo "Disk space:   WARN — ${_disk_free}GB free"
    else
        echo "Disk space:   OK (${_disk_free:-?}GB free)"
    fi

    # Token freshness (if multi-account is set up)
    if [ "${#CLAUDE_HOMES[@]}" -gt 0 ] 2>/dev/null; then
        echo "Accounts:     ${#CLAUDE_HOMES[@]} active"
        for _home_dir in "${CLAUDE_HOMES[@]}"; do
            local _creds="${_home_dir}/.claude/.credentials.json"
            if [ -f "$_creds" ]; then
                local _remaining
                _remaining=$(python3 -c "
import json, time, sys
try:
    d = json.load(open(sys.argv[1]))
    exp = d.get('claudeAiOauth',{}).get('expiresAt',0)
    rem = int((exp - time.time()*1000) / 60000)
    print(f'{rem} min remaining')
except: print('unknown')
" "$_creds" 2>/dev/null)
                echo "  $(basename "$_home_dir"): $_remaining"
            fi
        done
    fi

    echo "----------------------------------------------"
    read -r -p "Press Enter to proceed, Ctrl+C to abort... " _
    echo ""
}

# ============================================
# VERIFIER DEBUG MODE
# ============================================
# When DEBUG_MODE=true, verifier_lib.sh captures diagnostics to /logs/verifier/debug/
# (environment, git status, git diff, file tree). Does not affect scoring.
# Pass through to Docker containers via environment inheritance.
export DEBUG_MODE="${DEBUG_MODE:-}"

# ============================================
# DOCKER BUILD OPTIMIZATION
# ============================================
# BuildKit enables parallel layer execution, better caching, and smaller images.
export DOCKER_BUILDKIT=1

# Build CSB base images if not already cached (< 7 days old).
# These pre-clone frequently-used repos (Django, K8s, Flipt, Kafka, Flink)
# so task Dockerfiles that inherit from them skip the expensive git clone.
ensure_base_images() {
    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    local build_script="${repo_root}/base_images/build.sh"
    if [ -x "$build_script" ]; then
        echo "Ensuring CSB base images are built..."
        bash "$build_script" --parallel
    fi
}

# Pre-build all Docker images for a suite to warm the layer cache.
# Call before run_paired_configs so Harbor's docker compose build is instant.
# Args: $1 = suite name (e.g., csb_sdlc_feature), remaining args passed through
#   Example: prebuild_images "csb_sdlc_feature" --tasks "task1,task2"
prebuild_images() {
    local suite="${1:-}"
    shift || true
    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    local script="${repo_root}/scripts/prebuild_images.sh"
    if [ -x "$script" ]; then
        bash "$script" ${suite:+"$suite"} "$@"
    fi
}

# ============================================
# FAIL-FAST MODE
# ============================================
# When true, if any task errors out, kill all running tasks and abort immediately.
# Recommended for API mode to avoid wasting credits on a broken batch.
FAIL_FAST=${FAIL_FAST:-true}

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
    headers={"Content-Type": "application/json", "User-Agent": "ccb-token-refresh/1.0"},
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
        if ! refresh_claude_token; then
            echo "ERROR: Token refresh failed — aborting to prevent wasted compute."
            echo "  Fix: python3 scripts/headless_login.py --all-accounts"
            echo "  Or:  python3 scripts/check_infra.py  (to diagnose)"
            exit 1
        fi
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
    # Check trajectory.json coverage after validation
    check_trajectory_coverage "$jobs_dir"
}

# Check trajectory.json for a single task after it completes.
# Non-blocking: logs WARNING but does not fail the pipeline.
# Args: $1 = task_id (plain or composite "task_id|config|mcp_type" from paired mode)
#        $2 = jobs_dir (jobs_subdir for plain mode, or jobs_base for paired mode)
# Searches for task output directories matching the task_id pattern.
_check_task_trajectory() {
    local raw_id=$1
    local jobs_dir=$2

    [ -n "$jobs_dir" ] && [ -d "$jobs_dir" ] || return 0

    # Handle composite IDs from run_paired_configs: "task_id|config|mcp_type"
    local task_id config_subdir
    if [[ "$raw_id" == *"|"* ]]; then
        task_id="${raw_id%%|*}"
        local remainder="${raw_id#*|}"
        config_subdir="${remainder%%|*}"
        jobs_dir="${jobs_dir}/${config_subdir}"
    else
        task_id="$raw_id"
    fi

    [ -d "$jobs_dir" ] || return 0

    # Task output dirs match: {batch_timestamp}/{task_id}__{hash}/agent/
    local found=false
    for agent_dir in "$jobs_dir"/*/"${task_id}"__*/agent/; do
        [ -d "$agent_dir" ] || continue
        found=true
        if [ ! -f "$agent_dir/trajectory.json" ]; then
            echo "WARNING: trajectory.json missing for $task_id (dir: $agent_dir)"
            echo "  → TTFR/TTAR metrics will use synthesized estimates. See AGENTS.md 'Trajectory Generation'."
        fi
    done

    # If no matching task dir found yet (task may still be writing), skip silently
    if [ "$found" = false ]; then
        return 0
    fi
}

# Check for missing trajectory.json across all tasks in a jobs directory.
# Non-blocking: logs WARNING but does not fail the pipeline.
# Args: $1 = jobs_subdir (e.g., runs/official/pytorch_opus_ts/baseline)
check_trajectory_coverage() {
    local jobs_dir=$1
    local missing=0
    local checked=0

    for task_dir in "$jobs_dir"/*/*/; do
        [ -d "$task_dir" ] || continue
        local agent_dir="$task_dir/agent"
        [ -d "$agent_dir" ] || continue
        checked=$((checked + 1))
        if [ ! -f "$agent_dir/trajectory.json" ]; then
            local task_name
            task_name=$(basename "$(dirname "$agent_dir")")
            echo "WARNING: trajectory.json missing for $task_name (dir: $agent_dir)"
            missing=$((missing + 1))
        fi
    done

    if [ "$missing" -gt 0 ]; then
        echo "TRAJECTORY CHECK: $missing/$checked tasks missing trajectory.json in $jobs_dir"
        echo "  → TTFR/TTAR metrics will use synthesized estimates for these tasks."
        echo "  → See AGENTS.md 'Trajectory Generation' for troubleshooting."
    elif [ "$checked" -gt 0 ]; then
        echo "TRAJECTORY CHECK: All $checked tasks have trajectory.json"
    fi
}

# ============================================
# PARALLEL EXECUTION
# ============================================
# Number of concurrent task subshells. Set via --parallel N or PARALLEL_JOBS env var.
# Default is auto-detected after setup_multi_accounts (= SESSIONS_PER_ACCOUNT * num_accounts).
# Set to 0 here as sentinel; resolved in setup_multi_accounts.
PARALLEL_JOBS=${PARALLEL_JOBS:-0}

# Max concurrent sessions per Max-plan account before hitting rate limits.
# Based on empirical testing: ~4 concurrent Claude Code sessions per Max account.
SESSIONS_PER_ACCOUNT=${SESSIONS_PER_ACCOUNT:-4}

# ============================================
# MULTI-ACCOUNT SUPPORT
# ============================================
# Array of HOME directories for credential isolation.
# Each entry contains .claude/.credentials.json.
# Only Max-plan accounts are included (regular accounts are too rate-limited).
CLAUDE_HOMES=()
REAL_HOME="$HOME"

# List of account directory names to SKIP (e.g., non-Max-plan accounts).
# Override via SKIP_ACCOUNTS env var (space-separated).
# By default, no accounts are skipped — accounts with expired/invalid tokens
# are detected and skipped automatically in setup_multi_accounts.
SKIP_ACCOUNTS="${SKIP_ACCOUNTS:-}"

# Rate-limit preflight probe before launching runs.
# - RATE_LIMIT_PREFLIGHT=1 (default): probe each account with a tiny Claude request
# - RATE_LIMIT_PREFLIGHT=0: disable probing
# - RATE_LIMIT_PREFLIGHT_MODE=skip (default): drop rate-limited accounts from CLAUDE_HOMES
# - RATE_LIMIT_PREFLIGHT_MODE=fail: abort launch if any account is rate-limited
RATE_LIMIT_PREFLIGHT="${RATE_LIMIT_PREFLIGHT:-1}"
RATE_LIMIT_PREFLIGHT_MODE="${RATE_LIMIT_PREFLIGHT_MODE:-skip}"
RATE_LIMIT_PROBE_TIMEOUT_SEC="${RATE_LIMIT_PROBE_TIMEOUT_SEC:-20}"
RATE_LIMIT_PROBE_MODEL="${RATE_LIMIT_PROBE_MODEL:-anthropic/claude-haiku-4-5-20251001}"
RATE_LIMIT_PROBE_PROMPT="${RATE_LIMIT_PROBE_PROMPT:-Reply with exactly OK.}"

# Check whether an account's OAuth token is valid (or can be refreshed).
# Args: $1 = account home directory (e.g., ~/.claude-homes/account1)
# Returns 0 if the token is valid (or was successfully refreshed), 1 otherwise.
# Uses REFRESH_MARGIN (default 30 min) as the validity threshold.
_check_account_token() {
    local account_home=$1
    local creds_file="$account_home/.claude/.credentials.json"

    if [ ! -f "$creds_file" ]; then
        echo "    No credentials file"
        return 1
    fi

    # First check current token validity
    local token_status
    token_status=$(python3 - "$creds_file" "$REFRESH_MARGIN" <<'TOKCHK'
import json, sys, time

creds_file = sys.argv[1]
margin = int(sys.argv[2])

try:
    with open(creds_file) as f:
        creds = json.load(f)
except (json.JSONDecodeError, OSError) as e:
    print(f"corrupt:{e}")
    sys.exit(0)

oauth = creds.get("claudeAiOauth", {})
if not oauth:
    print("no_oauth")
    sys.exit(0)

expires_at_ms = oauth.get("expiresAt", 0)
now_ms = int(time.time() * 1000)
remaining_s = (expires_at_ms - now_ms) / 1000

if remaining_s > margin:
    mins = int(remaining_s / 60)
    print(f"valid:{mins}")
else:
    mins = int(remaining_s / 60)
    has_refresh = bool(oauth.get("refreshToken"))
    print(f"expiring:{mins}:{has_refresh}")
TOKCHK
    )

    local status_type="${token_status%%:*}"

    case "$status_type" in
        valid)
            local mins="${token_status#valid:}"
            echo "    Token valid (${mins} min remaining)"
            return 0
            ;;
        expiring)
            # Token is expired or expiring soon — try refresh
            echo "    Token expiring soon — attempting refresh..."
            local _refresh_out
            _refresh_out=$(HOME="$account_home" refresh_claude_token 2>&1)
            local _refresh_rc=$?
            echo "$_refresh_out" | sed 's/^/    /'
            if [ "$_refresh_rc" -eq 0 ]; then
                echo "    Token refreshed successfully"
                return 0
            else
                echo "    Token refresh FAILED"
                return 1
            fi
            ;;
        no_oauth)
            echo "    No OAuth credentials in file"
            return 1
            ;;
        corrupt*)
            echo "    Credentials file corrupt: ${token_status#corrupt:}"
            return 1
            ;;
        *)
            echo "    Unknown token status: $token_status"
            return 1
            ;;
    esac
}

# Detect all accounts under ~/.claude-homes/accountN/ (N=1,2,3,...).
# Skips accounts listed in SKIP_ACCOUNTS.
# Also skips accounts with expired/invalid tokens (after attempting refresh).
# Falls back to $HOME if no account directories are found.
# Auto-sets PARALLEL_JOBS = SESSIONS_PER_ACCOUNT * num_accounts when not explicitly set.
setup_multi_accounts() {
    CLAUDE_HOMES=()
    local skipped_accounts=()

    # Check for explicit account directories: account1, account2, ...
    local account_num=1
    while true; do
        local account_name="account$account_num"
        local account_home="$REAL_HOME/.claude-homes/$account_name"
        if [ -f "$account_home/.claude/.credentials.json" ]; then
            # Check skip list
            if [[ -n "$SKIP_ACCOUNTS" ]] && [[ " $SKIP_ACCOUNTS " == *" $account_name "* ]]; then
                echo "  Skipping $account_name (in SKIP_ACCOUNTS)"
                skipped_accounts+=("$account_name")
            else
                # Check token validity
                echo "  Checking $account_name token..."
                if _check_account_token "$account_home"; then
                    CLAUDE_HOMES+=("$account_home")
                else
                    echo "  Skipping $account_name (token expired/invalid — re-authenticate with: python3 scripts/headless_login.py --home ~/.claude-homes/$account_name)"
                    skipped_accounts+=("$account_name")
                fi
            fi
            account_num=$((account_num + 1))
        else
            break
        fi
    done

    # Restore HOME in case refresh_claude_token changed it
    export HOME="$REAL_HOME"

    # Fallback: if no account dirs found, use $HOME
    if [ ${#CLAUDE_HOMES[@]} -eq 0 ]; then
        if [ ${#skipped_accounts[@]} -gt 0 ]; then
            echo "WARNING: All accounts were skipped (${skipped_accounts[*]}). Falling back to \$HOME."
        fi
        CLAUDE_HOMES=("$HOME")
        echo "Single-account mode (using \$HOME)"
    else
        echo "Multi-account mode: ${#CLAUDE_HOMES[@]} accounts active"
        for i in "${!CLAUDE_HOMES[@]}"; do
            echo "  slot $((i+1)): ${CLAUDE_HOMES[$i]}"
        done
        if [ ${#skipped_accounts[@]} -gt 0 ]; then
            echo "  skipped: ${skipped_accounts[*]}"
        fi
    fi

    # Auto-set PARALLEL_JOBS = sessions_per_account * num_accounts
    if [ "$PARALLEL_JOBS" -eq 0 ]; then
        PARALLEL_JOBS=$(( SESSIONS_PER_ACCOUNT * ${#CLAUDE_HOMES[@]} ))
        echo "Parallel jobs auto-set to $PARALLEL_JOBS ($SESSIONS_PER_ACCOUNT sessions x ${#CLAUDE_HOMES[@]} accounts)"
    fi
}

# Backward-compatible alias
setup_dual_accounts() { setup_multi_accounts; }

# Refresh tokens for all registered accounts.
ensure_fresh_token_all() {
    # Some scripts call this before setup_multi_accounts/setup_dual_accounts.
    # Ensure account homes are discovered so refresh is never silently skipped.
    if [ ${#CLAUDE_HOMES[@]} -eq 0 ]; then
        setup_multi_accounts
    fi

    # Safety fallback in case setup_multi_accounts did not populate for any reason.
    if [ ${#CLAUDE_HOMES[@]} -eq 0 ]; then
        CLAUDE_HOMES=("${HOME}")
    fi

    for home_dir in "${CLAUDE_HOMES[@]}"; do
        echo "Refreshing token for HOME=$home_dir ..."
        HOME="$home_dir" ensure_fresh_token
    done
    # Restore real HOME
    export HOME="$REAL_HOME"
}

# Probe a single account for immediate Anthropic rate-limit status.
# Returns:
#   0 => probe succeeded and account appears usable
#   2 => account appears rate-limited
#   1 => probe failed for non-rate-limit reasons (treated as usable with warning)
_check_account_rate_limit() {
    local account_home=$1
    local output
    local rc

    # timeout returns 124 on timeout
    output=$(
        HOME="$account_home" timeout "$RATE_LIMIT_PROBE_TIMEOUT_SEC" \
            claude --print \
            --output-format text \
            --permission-mode bypassPermissions \
            --model "$RATE_LIMIT_PROBE_MODEL" \
            "$RATE_LIMIT_PROBE_PROMPT" 2>&1
    )
    rc=$?

    if echo "$output" | grep -qiE "rate[ _-]?limit|429|hit your limit|exceed your account'?s rate limit|too many requests"; then
        return 2
    fi

    if [ "$rc" -eq 124 ]; then
        echo "    Probe timed out (${RATE_LIMIT_PROBE_TIMEOUT_SEC}s); keeping account"
        return 1
    fi

    if [ "$rc" -ne 0 ]; then
        # Non-rate-limit failure should not hard-block launches by default.
        # Keep account active and let run-time retry logic handle transient errors.
        echo "    Probe command failed (exit $rc); keeping account"
        return 1
    fi

    return 0
}

# Check all active accounts for immediate rate-limit state and apply policy.
# Must be called after setup_multi_accounts/ensure_fresh_token_all.
preflight_rate_limits() {
    if [ "$RATE_LIMIT_PREFLIGHT" != "1" ]; then
        echo "Rate-limit preflight: disabled (RATE_LIMIT_PREFLIGHT=$RATE_LIMIT_PREFLIGHT)"
        return 0
    fi

    if [ ${#CLAUDE_HOMES[@]} -eq 0 ]; then
        setup_multi_accounts
    fi

    local kept_homes=()
    local limited_homes=()
    local warned=()

    echo "Rate-limit preflight: probing ${#CLAUDE_HOMES[@]} account(s)..."

    for home_dir in "${CLAUDE_HOMES[@]}"; do
        local label
        label=$(basename "$home_dir")
        echo "  Checking $label ..."
        if _check_account_rate_limit "$home_dir"; then
            echo "    OK"
            kept_homes+=("$home_dir")
        else
            local rl_rc=$?
            if [ "$rl_rc" -eq 2 ]; then
                echo "    RATE-LIMITED"
                limited_homes+=("$home_dir")
            else
                warned+=("$home_dir")
                kept_homes+=("$home_dir")
            fi
        fi
    done

    if [ ${#limited_homes[@]} -eq 0 ]; then
        echo "Rate-limit preflight: no limited accounts detected"
        return 0
    fi

    echo "Rate-limit preflight: detected ${#limited_homes[@]} limited account(s):"
    for h in "${limited_homes[@]}"; do
        echo "  - $(basename "$h")"
    done

    case "$RATE_LIMIT_PREFLIGHT_MODE" in
        skip)
            CLAUDE_HOMES=("${kept_homes[@]}")
            if [ ${#CLAUDE_HOMES[@]} -eq 0 ]; then
                echo "ERROR: all accounts are currently rate-limited; aborting launch"
                return 1
            fi
            echo "Rate-limit preflight: continuing with ${#CLAUDE_HOMES[@]} account(s)"
            if [ "$PARALLEL_JOBS" -gt 0 ]; then
                local max_jobs=$(( SESSIONS_PER_ACCOUNT * ${#CLAUDE_HOMES[@]} ))
                if [ "$PARALLEL_JOBS" -gt "$max_jobs" ]; then
                    echo "Rate-limit preflight: capping PARALLEL_JOBS from $PARALLEL_JOBS to $max_jobs"
                    PARALLEL_JOBS=$max_jobs
                fi
            fi
            ;;
        fail)
            echo "ERROR: aborting due to rate-limited accounts (RATE_LIMIT_PREFLIGHT_MODE=fail)"
            return 1
            ;;
        *)
            echo "WARNING: unknown RATE_LIMIT_PREFLIGHT_MODE=$RATE_LIMIT_PREFLIGHT_MODE; defaulting to skip"
            CLAUDE_HOMES=("${kept_homes[@]}")
            [ ${#CLAUDE_HOMES[@]} -gt 0 ] || return 1
            ;;
    esac

    return 0
}

# ============================================
# PARALLEL TASK RUNNER
# ============================================
# run_tasks_parallel: Run an array of task commands in parallel with job limiting.
#
# Usage:
#   run_tasks_parallel <task_id_array_name> <command_builder_function>
#
# The command_builder_function is called as:
#   command_builder_function <task_id> <account_home>
# and should execute the harbor run for that task (in the current shell).
#
# This function manages:
#   - Job concurrency limiting (PARALLEL_JOBS)
#   - Round-robin account distribution (CLAUDE_HOMES)
#   - PID tracking and exit code collection
#
# Returns 0 if all tasks succeeded, 1 if any failed.
# Rate-limit / account-exhaustion patterns (checked in task log output).
# If a failed task's log matches any of these, it's eligible for retry on a different account.
RATE_LIMIT_PATTERNS="rate.limit|429|too many requests|throttl|overloaded|token.*refresh.*fail|credentials.*expired|403.*Forbidden|capacity|resource_exhausted"

# Daytona-specific transient error patterns (sandbox resource contention).
# These are retried on the SAME account (not an auth issue) with backoff.
DAYTONA_TRANSIENT_PATTERNS="[Ss]andbox not found|[Ss]andbox.*missing|[Ss]andbox.*does not exist|DaytonaError"

# Maximum number of Daytona retry attempts per task (with exponential backoff).
DAYTONA_MAX_RETRIES=${DAYTONA_MAX_RETRIES:-3}

# Check if a task failure looks like a rate-limit / account-exhaustion error.
# Args: $1 = task_id, $2 = log directory (where ${task_id}.log might be)
# Returns 0 if rate-limited, 1 otherwise.
_is_rate_limited() {
    local task_id=$1
    local log_dir=$2

    # Check the task log file if it exists
    local log_file="${log_dir}/${task_id}.log"
    if [ -f "$log_file" ]; then
        if grep -qEi "$RATE_LIMIT_PATTERNS" "$log_file" 2>/dev/null; then
            return 0
        fi
    fi

    # Also check any result.json files that were recently written for this task
    local result_files
    result_files=$(find "$log_dir" -name "result.json" -newer "$log_dir" -path "*${task_id}*" 2>/dev/null || true)
    for rf in $result_files; do
        if grep -qEi "$RATE_LIMIT_PATTERNS" "$rf" 2>/dev/null; then
            return 0
        fi
    done

    return 1
}

# Check if a task failure looks like a transient Daytona sandbox error.
# These are NOT account-related — retry on the same account after a delay.
# Args: $1 = task_id, $2 = log directory
# Returns 0 if Daytona transient error, 1 otherwise.
_is_daytona_transient() {
    local task_id=$1
    local log_dir=$2

    local log_file="${log_dir}/${task_id}.log"
    if [ -f "$log_file" ]; then
        if grep -qEi "$DAYTONA_TRANSIENT_PATTERNS" "$log_file" 2>/dev/null; then
            return 0
        fi
    fi

    local result_files
    result_files=$(find "$log_dir" -name "result.json" -newer "$log_dir" -path "*${task_id}*" 2>/dev/null || true)
    for rf in $result_files; do
        if grep -qEi "$DAYTONA_TRANSIENT_PATTERNS" "$rf" 2>/dev/null; then
            return 0
        fi
    done

    return 1
}

# Pick a different account home than the one that failed.
# Args: $1 = failed account home
# Prints the alternate account home, or empty if only one account.
_pick_alternate_account() {
    local failed_home=$1
    local num_accounts=${#CLAUDE_HOMES[@]}

    if [ "$num_accounts" -le 1 ]; then
        echo ""
        return
    fi

    for home in "${CLAUDE_HOMES[@]}"; do
        if [ "$home" != "$failed_home" ]; then
            echo "$home"
            return
        fi
    done
    echo ""
}

run_tasks_parallel() {
    local -n _task_ids=$1
    local cmd_fn=$2
    local pids=()
    local task_for_pid=()
    local home_for_pid=()
    local failed=0
    local abort=false
    local account_idx=0
    local num_accounts=${#CLAUDE_HOMES[@]}

    # Retry queue: tasks to retry on a different account (rate-limit)
    local retry_tasks=()
    local retry_homes=()
    # Track which tasks already retried (prevent infinite loops)
    declare -A _retried
    # Daytona retry queue: tasks to retry on same account after backoff
    local daytona_retry_tasks=()
    local daytona_retry_homes=()
    # Track Daytona retry counts per task (up to DAYTONA_MAX_RETRIES)
    declare -A _daytona_retry_count

    # Infer log directory from the calling script's jobs_subdir variable (if set)
    local _log_dir="${jobs_subdir:-}"

    echo "Parallel execution: ${#_task_ids[@]} tasks, max $PARALLEL_JOBS concurrent, $num_accounts account(s)"

    # _kill_all: terminate all running task PIDs.
    _kill_all() {
        if [ ${#pids[@]} -eq 0 ]; then return; fi
        echo "FAIL-FAST: Killing ${#pids[@]} running task(s)..."
        for i in "${!pids[@]}"; do
            kill "${pids[$i]}" 2>/dev/null || true
            echo "  Killed ${task_for_pid[$i]} (PID ${pids[$i]})"
        done
        sleep 2
        for i in "${!pids[@]}"; do
            kill -9 "${pids[$i]}" 2>/dev/null || true
        done
        pids=()
        task_for_pid=()
        home_for_pid=()
    }

    # _reap_one: check finished PIDs, handle rate-limit retries.
    # Sets done_pid to the reaped PID, or empty if none finished.
    _reap_one() {
        done_pid=""
        for i in "${!pids[@]}"; do
            if ! kill -0 "${pids[$i]}" 2>/dev/null; then
                done_pid="${pids[$i]}"
                local _task="${task_for_pid[$i]}"
                local _home="${home_for_pid[$i]}"
                local _exit=0
                wait "$done_pid" 2>/dev/null || _exit=$?

                if [ "$_exit" -ne 0 ]; then
                    # Check if this is a rate-limit failure eligible for retry
                    if [ -n "$_log_dir" ] && \
                       [ "$num_accounts" -gt 1 ] && \
                       [ -z "${_retried[$_task]:-}" ] && \
                       _is_rate_limited "$_task" "$_log_dir"; then
                        local alt_home
                        alt_home=$(_pick_alternate_account "$_home")
                        if [ -n "$alt_home" ]; then
                            echo "RATE-LIMIT RETRY: Task $_task failed on $(basename "$_home"), will retry on $(basename "$alt_home")"
                            retry_tasks+=("$_task")
                            retry_homes+=("$alt_home")
                            _retried[$_task]=1
                        else
                            echo "WARNING: Task $_task rate-limited but no alternate account available"
                            failed=1
                        fi
                    # Check if this is a Daytona transient error (sandbox not found)
                    elif [ -n "$_log_dir" ] && \
                         _is_daytona_transient "$_task" "$_log_dir"; then
                        local _count="${_daytona_retry_count[$_task]:-0}"
                        _count=$((_count + 1))
                        if [ "$_count" -le "$DAYTONA_MAX_RETRIES" ]; then
                            local _backoff=$(( 15 * _count ))  # 15s, 30s, 45s
                            echo "DAYTONA RETRY ($_count/$DAYTONA_MAX_RETRIES): Task $_task sandbox error, retrying in ${_backoff}s on same account"
                            _daytona_retry_count[$_task]=$_count
                            daytona_retry_tasks+=("$_task")
                            daytona_retry_homes+=("$_home")
                        else
                            echo "DAYTONA EXHAUSTED: Task $_task failed after $DAYTONA_MAX_RETRIES retries"
                            failed=1
                        fi
                    else
                        echo "ERROR: Task $_task (PID $done_pid) exited with code $_exit"
                        failed=1
                        if [ "$FAIL_FAST" = "true" ]; then
                            echo "FAIL-FAST: Aborting remaining tasks due to error in $_task"
                            _kill_all
                            abort=true
                            return
                        fi
                    fi
                else
                    # Task succeeded — check trajectory.json coverage
                    _check_task_trajectory "$_task" "$_log_dir"
                fi

                unset 'pids[i]'
                unset 'task_for_pid[i]'
                unset 'home_for_pid[i]'
                # Re-index arrays
                pids=("${pids[@]}")
                task_for_pid=("${task_for_pid[@]}")
                home_for_pid=("${home_for_pid[@]}")
                break
            fi
        done
    }

    # _launch: launch a task on a given account
    _launch() {
        local task_id=$1
        local task_home=$2

        (
            export HOME="$task_home"
            $cmd_fn "$task_id" "$task_home"
        ) &
        pids+=($!)
        task_for_pid+=("$task_id")
        home_for_pid+=("$task_home")
        echo "  Launched task $task_id (PID $!, account HOME=$task_home)"
        # Stagger launches to avoid Harbor batch-directory timestamp collisions
        sleep 2
    }

    for task_id in "${_task_ids[@]}"; do
        if [ "$abort" = true ]; then break; fi

        # Wait if at PARALLEL_JOBS limit
        while [ ${#pids[@]} -ge $PARALLEL_JOBS ]; do
            _reap_one
            if [ "$abort" = true ]; then break 2; fi
            if [ -z "$done_pid" ]; then
                sleep 2
            fi
        done

        local task_home="${CLAUDE_HOMES[$account_idx]}"
        account_idx=$(( (account_idx + 1) % num_accounts ))
        _launch "$task_id" "$task_home"
    done

    # Wait for remaining tasks, then process retry queues
    while [ ${#pids[@]} -gt 0 ] || [ ${#retry_tasks[@]} -gt 0 ] || [ ${#daytona_retry_tasks[@]} -gt 0 ]; do
        if [ "$abort" = true ]; then break; fi

        # Drain running PIDs
        while [ ${#pids[@]} -gt 0 ]; do
            _reap_one
            if [ "$abort" = true ]; then break 2; fi
            if [ -z "$done_pid" ]; then
                sleep 2
            fi
        done

        # Launch any queued rate-limit retries (different account)
        if [ ${#retry_tasks[@]} -gt 0 ]; then
            echo "Processing ${#retry_tasks[@]} rate-limit retry task(s)..."
            for ri in "${!retry_tasks[@]}"; do
                if [ "$abort" = true ]; then break; fi
                while [ ${#pids[@]} -ge $PARALLEL_JOBS ]; do
                    _reap_one
                    if [ "$abort" = true ]; then break 2; fi
                    if [ -z "$done_pid" ]; then
                        sleep 2
                    fi
                done
                _launch "${retry_tasks[$ri]}" "${retry_homes[$ri]}"
            done
            retry_tasks=()
            retry_homes=()
        fi

        # Launch any queued Daytona retries (same account, with backoff)
        if [ ${#daytona_retry_tasks[@]} -gt 0 ]; then
            local _dt_count=${#daytona_retry_tasks[@]}
            echo "Processing $_dt_count Daytona retry task(s) with backoff..."
            for ri in "${!daytona_retry_tasks[@]}"; do
                if [ "$abort" = true ]; then break; fi
                local _task="${daytona_retry_tasks[$ri]}"
                local _backoff=$(( 15 * ${_daytona_retry_count[$_task]:-1} ))
                echo "  Waiting ${_backoff}s before retrying $_task..."
                sleep "$_backoff"
                while [ ${#pids[@]} -ge $PARALLEL_JOBS ]; do
                    _reap_one
                    if [ "$abort" = true ]; then break 2; fi
                    if [ -z "$done_pid" ]; then
                        sleep 2
                    fi
                done
                _launch "${daytona_retry_tasks[$ri]}" "${daytona_retry_homes[$ri]}"
            done
            daytona_retry_tasks=()
            daytona_retry_homes=()
        fi
    done

    # Restore real HOME
    export HOME="$REAL_HOME"
    return $failed
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

# ============================================
# CANARY GUARDRAILS
# ============================================
# When CANARY_ENABLED=true, run_canary_then_batch runs the first task alone,
# validates it for systemic stop signals, and only continues if it passes.
CANARY_ENABLED=${CANARY_ENABLED:-false}

# validate_canary_result: check a canary task's result.json for systemic failures.
# Args: $1 = jobs_subdir (e.g., runs/official/pytorch_opus_ts/baseline)
#        $2 = mode (baseline, sourcegraph_full)
# Writes canary_verdict.json to jobs_subdir.
# Returns 0 (pass) or 1 (stop).
validate_canary_result() {
    local jobs_subdir=$1
    local mode=$2

    python3 - "$jobs_subdir" "$mode" <<'CANARY_EOF'
import json, glob, os, sys

jobs_subdir = sys.argv[1]
mode = sys.argv[2]

# Find the most recent result.json under jobs_subdir
result_files = sorted(glob.glob(os.path.join(jobs_subdir, "**", "result.json"), recursive=True),
                      key=os.path.getmtime)

verdict = {"pass": True, "reason": "no_issues", "mode": mode, "result_file": None}

if not result_files:
    verdict = {"pass": False, "reason": "no_result_json", "mode": mode, "result_file": None,
               "message": "No result.json produced — Harbor/Docker may be broken"}
    json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
    print(f"CANARY STOP: {verdict['message']}")
    sys.exit(1)

result_file = result_files[-1]
verdict["result_file"] = result_file

try:
    data = json.load(open(result_file))
except (json.JSONDecodeError, OSError) as e:
    verdict = {"pass": False, "reason": "corrupt_result", "mode": mode,
               "result_file": result_file, "message": f"Cannot parse result.json: {e}"}
    json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
    print(f"CANARY STOP: {verdict['message']}")
    sys.exit(1)

# Check systemic stop signals
trials = data.get("trials", [])
trial = trials[0] if trials else {}

# 1. agent_result == null → agent never executed
agent_result = trial.get("agent_result")
if agent_result is None and trials:
    verdict = {"pass": False, "reason": "agent_null", "mode": mode,
               "result_file": result_file, "message": "agent_result is null — agent never executed"}
    json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
    print(f"CANARY STOP: {verdict['message']}")
    sys.exit(1)

# 2. n_output_tokens == 0 → auth failed silently
n_output = trial.get("n_output_tokens", -1)
if n_output == 0:
    verdict = {"pass": False, "reason": "zero_tokens", "mode": mode,
               "result_file": result_file, "message": "n_output_tokens=0 — auth failed silently"}
    json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
    print(f"CANARY STOP: {verdict['message']}")
    sys.exit(1)

# 3. exception_type checks
exc_info = data.get("exception_info", trial.get("exception_info", {})) or {}
exc_type = exc_info.get("exception_type", exc_info.get("type", ""))
exc_msg = exc_info.get("exception_message", exc_info.get("message", ""))
exc_combined = f"{exc_type} {exc_msg}"

# AgentSetupTimeoutError → Docker/infra broken
if "AgentSetupTimeoutError" in exc_type:
    verdict = {"pass": False, "reason": "agent_setup_timeout", "mode": mode,
               "result_file": result_file, "message": f"AgentSetupTimeoutError — Docker/infra broken"}
    json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
    print(f"CANARY STOP: {verdict['message']}")
    sys.exit(1)

# 4. Fingerprint-based checks
import re

STOP_FINGERPRINTS = [
    ("token_refresh_403",
     re.compile(r"403|Forbidden|token.*refresh|refresh.*token|credentials.*expired", re.I),
     "OAuth token refresh failure"),
    ("docker_compose_fail",
     re.compile(r"docker.compose.*fail|compose.*error|container.*fail.*start", re.I),
     "Docker/container infrastructure broken"),
]

# mcp_connection only stops MCP configs
if mode in ("sourcegraph_full",):
    STOP_FINGERPRINTS.append(
        ("mcp_connection",
         re.compile(r"mcp.*(?:connection|timeout|refused|error)|sourcegraph.*(?:fail|error|timeout)", re.I),
         "MCP server connection failure")
    )

for fp_id, pattern, label in STOP_FINGERPRINTS:
    if pattern.search(exc_combined):
        verdict = {"pass": False, "reason": fp_id, "mode": mode,
                   "result_file": result_file, "message": f"{label}: {exc_combined[:200]}"}
        json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
        print(f"CANARY STOP: {verdict['message']}")
        sys.exit(1)

# 5. All clear — task may have failed on its own merits, but no systemic issue
reward = None
vr = trial.get("verifier_result", {}) or {}
rewards_obj = vr.get("rewards", {}) or {}
reward = rewards_obj.get("reward", rewards_obj.get("score"))

verdict = {"pass": True, "reason": "no_issues", "mode": mode,
           "result_file": result_file, "reward": reward,
           "message": f"Canary passed (reward={reward})"}
json.dump(verdict, open(os.path.join(jobs_subdir, "canary_verdict.json"), "w"), indent=2)
print(f"CANARY PASS: {verdict['message']}")
sys.exit(0)
CANARY_EOF
}

# run_canary_then_batch: wraps run_tasks_parallel with canary-first logic.
# Args: $1 = task_id_array_name
#        $2 = command_builder_function
#        $3 = jobs_subdir (for canary verdict output)
#        $4 = mode (baseline, sourcegraph_full)
# Falls through to run_tasks_parallel if CANARY_ENABLED != true or only 1 task.
run_canary_then_batch() {
    local -n _canary_task_ids=$1
    local cmd_fn=$2
    local jobs_subdir=$3
    local mode=$4
    local num_tasks=${#_canary_task_ids[@]}

    # Fall through if canary disabled or only 1 task
    if [ "$CANARY_ENABLED" != "true" ] || [ "$num_tasks" -le 1 ]; then
        run_tasks_parallel "$1" "$cmd_fn" || true
        return $?
    fi

    echo ""
    echo "CANARY: Running first task as canary probe..."
    echo ""

    # Pop first task as canary
    local canary_id="${_canary_task_ids[0]}"
    local canary_arr=("$canary_id")

    # Run canary synchronously (1 task, effectively serial)
    local saved_parallel=$PARALLEL_JOBS
    PARALLEL_JOBS=1
    run_tasks_parallel canary_arr "$cmd_fn" || true
    PARALLEL_JOBS=$saved_parallel

    # Validate canary result
    if ! validate_canary_result "$jobs_subdir" "$mode"; then
        echo ""
        echo "CANARY BLOCKED: Systemic issue detected — skipping remaining ${num_tasks} tasks"
        echo "See: ${jobs_subdir}/canary_verdict.json"
        echo ""
        return 1
    fi

    # Canary passed — run remaining tasks
    local remaining_ids=("${_canary_task_ids[@]:1}")
    if [ ${#remaining_ids[@]} -gt 0 ]; then
        echo ""
        echo "CANARY CLEAR: Running remaining ${#remaining_ids[@]} tasks..."
        echo ""
        run_tasks_parallel remaining_ids "$cmd_fn" || true
    fi
}

# ============================================
# PAIRED CONFIG EXECUTION
# ============================================
# Runs baseline + SG_full for each task simultaneously (task-paired, not mode-sequential).
#
# Usage:
#   run_paired_configs TASK_IDS _my_run_fn "$JOBS_BASE"
#
# The run function must accept: $1=task_id $2=task_home $3=config_mode $4=mcp_type $5=jobs_base
# It is responsible for creating the jobs_subdir and launching harbor.
#
# This launches 2 containers per task (1 baseline + 1 MCP) simultaneously, so the total
# concurrent containers is 2x the number of tasks. PARALLEL_JOBS limits total concurrent PIDs.
run_paired_configs() {
    local -n _paired_task_ids=$1
    local run_fn=$2
    local jobs_base=$3
    local num_tasks=${#_paired_task_ids[@]}

    ensure_fresh_token_all

    echo ""
    echo "========================================"
    echo "Paired execution: $num_tasks tasks x 2 configs"
    echo "========================================"
    echo ""
    local full_config="${FULL_CONFIG:-mcp-remote-direct}"
    local bl_config
    bl_config=$(baseline_config_for "$full_config")
    echo "Each task launches ${bl_config} + ${full_config} simultaneously."
    echo "Total concurrent containers: up to $((num_tasks * 2)) (limited by PARALLEL_JOBS=$PARALLEL_JOBS)"
    echo ""

    mkdir -p "${jobs_base}/${bl_config}" "${jobs_base}/${full_config}"

    # Resolve mcp_type values once
    local bl_mcp full_mcp
    bl_mcp=$(config_to_mcp_type "$bl_config")
    full_mcp=$(config_to_mcp_type "$full_config")

    # Build paired task list: each task gets two entries
    local paired_ids=()
    for task_id in "${_paired_task_ids[@]}"; do
        paired_ids+=("${task_id}|${bl_config}|${bl_mcp}")
        paired_ids+=("${task_id}|${full_config}|${full_mcp}")
    done

    # Wrapper command function that splits the paired ID
    _paired_dispatch() {
        local composite_id=$1
        local task_home=$2
        local task_id="${composite_id%%|*}"
        local remainder="${composite_id#*|}"
        local config="${remainder%%|*}"
        local mcp_type="${remainder##*|}"

        $run_fn "$task_id" "$task_home" "$config" "$mcp_type" "$jobs_base"
    }

    run_tasks_parallel paired_ids _paired_dispatch || true
}

# ============================================
# DOCKER RESOURCE CLEANUP
# ============================================
# Clean up accumulated Docker resources after a batch completes.
# Harbor's per-trial `docker compose down --rmi local` handles individual
# containers, but BuildKit cache, dangling images, and orphan volumes
# accumulate across trials. Call this after run_paired_configs / run_task_batch.
#
# Safety: skips if any hb__* containers are still running (parallel batch).
# Only removes dangling (untagged) images — tagged base images (ccb-repo-*)
# and pre-built task images (hb__*) are preserved.
cleanup_docker_resources() {
    echo ""
    echo "========================================"
    echo "Docker resource cleanup"
    echo "========================================"

    # Safety check: abort if benchmark containers are still running
    local active_containers
    active_containers=$(docker ps --filter "name=hb__" --format '{{.Names}}' 2>/dev/null | wc -l)
    if [ "$active_containers" -gt 0 ]; then
        echo "SKIP: $active_containers hb__* containers still running. Cleanup deferred."
        return 0
    fi

    local before_df
    before_df=$(docker system df --format '{{.Type}}\t{{.Reclaimable}}' 2>/dev/null || true)
    echo "Before cleanup:"
    echo "$before_df" | sed 's/^/  /'

    # 1. Stopped containers (safe — Harbor already removed its own)
    echo "Pruning stopped containers..."
    docker container prune -f 2>/dev/null | tail -1 || true

    # 2. Orphan anonymous volumes (from compose down race conditions)
    echo "Pruning orphan volumes..."
    docker volume prune -f 2>/dev/null | tail -1 || true

    # 3. Dangling images only (untagged — won't touch ccb-repo-* or hb__*)
    echo "Pruning dangling images..."
    docker image prune -f 2>/dev/null | tail -1 || true

    # 4. Harbor trial images — Harbor names per-trial images hb__sdlc_*_<hash>
    #    and hb__rerun_*_<hash>. These are trial-specific copies of our
    #    pre-built images (hb__<task_id>, hb__sgonly_<task_id>) and are safe
    #    to remove after the trial completes. Pre-built images lack the
    #    random suffix so the pattern does not match them.
    local trial_images
    trial_images=$(docker images --format '{{.Repository}}' 2>/dev/null \
        | grep -E '^hb__(sdlc|rerun)_' || true)
    if [ -n "$trial_images" ]; then
        local count
        count=$(echo "$trial_images" | wc -l)
        echo "Removing $count Harbor trial images (hb__sdlc_*/hb__rerun_*)..."
        echo "$trial_images" | xargs -r docker rmi -f 2>/dev/null | tail -1 || true
    fi

    # 5. BuildKit cache — reserve 20 GB for hot layers, trim the rest
    # --reserved-space replaced --keep-storage in Docker 27+
    echo "Trimming BuildKit cache (reserving 20GB)..."
    docker builder prune --reserved-space=20GB -f 2>/dev/null | tail -1 \
        || docker builder prune --keep-storage=20GB -f 2>/dev/null | tail -1 \
        || true

    local after_df
    after_df=$(docker system df --format '{{.Type}}\t{{.Size}}\t{{.Reclaimable}}' 2>/dev/null || true)
    echo "After cleanup:"
    echo "$after_df" | sed 's/^/  /'
    echo ""
}

# ============================================
# TOKEN HEALTH CHECK (for overnight orchestrator)
# ============================================
# Checks and refreshes tokens for all accounts. Returns 1 if unrecoverable.
check_token_health() {
    local all_ok=true

    for home_dir in "${CLAUDE_HOMES[@]}"; do
        local creds_file="${home_dir}/.claude/.credentials.json"
        if [ ! -f "$creds_file" ]; then
            echo "TOKEN HEALTH FAIL: No credentials at $creds_file"
            all_ok=false
            continue
        fi

        # Try refresh
        if ! HOME="$home_dir" refresh_claude_token 2>/dev/null; then
            echo "TOKEN HEALTH FAIL: Cannot refresh token for HOME=$home_dir"
            all_ok=false
        fi
    done

    export HOME="$REAL_HOME"

    if [ "$all_ok" = false ]; then
        return 1
    fi
    return 0
}

#!/bin/bash
# Shared configuration and helpers for all benchmark scripts.
# Source this at the top of every *_3config.sh and run_selected_tasks.sh.

# ============================================
# AUTHENTICATION MODE — SUBSCRIPTION ONLY
# ============================================
# All runs use Claude Max subscription (OAuth tokens).
# API key mode has been removed. USE_SUBSCRIPTION is always true.
export USE_SUBSCRIPTION=true

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
            if HOME="$account_home" refresh_claude_token 2>&1 | sed 's/^/    /'; then
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
    for home_dir in "${CLAUDE_HOMES[@]}"; do
        echo "Refreshing token for HOME=$home_dir ..."
        HOME="$home_dir" ensure_fresh_token
    done
    # Restore real HOME
    export HOME="$REAL_HOME"
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

    # Retry queue: tasks to retry on a different account
    local retry_tasks=()
    local retry_homes=()
    # Track which tasks already retried (prevent infinite loops)
    declare -A _retried

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

    # Wait for remaining tasks, then process retry queue
    while [ ${#pids[@]} -gt 0 ] || [ ${#retry_tasks[@]} -gt 0 ]; do
        if [ "$abort" = true ]; then break; fi

        # Drain running PIDs
        while [ ${#pids[@]} -gt 0 ]; do
            _reap_one
            if [ "$abort" = true ]; then break 2; fi
            if [ -z "$done_pid" ]; then
                sleep 2
            fi
        done

        # Launch any queued retries
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
#        $2 = mode (baseline, sourcegraph_base, sourcegraph_full)
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
if mode in ("sourcegraph_base", "sourcegraph_full"):
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
#        $4 = mode (baseline, sourcegraph_base, sourcegraph_full)
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
# It is responsible for creating the jobs_subdir (e.g., baseline/ or sourcegraph_full/) and
# launching harbor.
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
    echo "Each task launches baseline + sourcegraph_full simultaneously."
    echo "Total concurrent containers: up to $((num_tasks * 2)) (limited by PARALLEL_JOBS=$PARALLEL_JOBS)"
    echo ""

    mkdir -p "${jobs_base}/baseline" "${jobs_base}/sourcegraph_full"

    # Build paired task list: each task gets two entries
    local paired_ids=()
    for task_id in "${_paired_task_ids[@]}"; do
        paired_ids+=("${task_id}|baseline|none")
        paired_ids+=("${task_id}|sourcegraph_full|sourcegraph_full")
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

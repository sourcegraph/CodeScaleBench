#!/usr/bin/env python3
"""
Deep Search Audit v2 for sourcegraph_full runs.
Fixes false-positive MCP connection errors and adds DS polling retry analysis.
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = "/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/runs/official"

DIR_PREFIX_TO_SUITE = {
    "swebenchpro": "ccb_swebenchpro",
    "pytorch": "ccb_pytorch",
    "locobench": "ccb_locobench",
    "repoqa": "ccb_repoqa",
    "k8s_docs": "ccb_k8s_docs",
    "crossrepo": "ccb_crossrepo",
    "largerepo": "ccb_largerepo",
    "bigcode": "ccb_largerepo",
    "tac": "ccb_tac",
    "dibench": "ccb_dibench",
    "sweperf": "ccb_sweperf",
    "codereview": "ccb_codereview",
    "linuxflbench": "ccb_linuxflbench",
}

def detect_suite(run_dir_name):
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if run_dir_name.startswith(prefix):
            return suite
    return "unknown"

def extract_task_name(task_dir_name):
    parts = task_dir_name.rsplit("__", 1)
    return parts[0] if len(parts) == 2 else task_dir_name

def is_new_ds_format(user_prompt):
    indicators = [
        "REQUIRED: Use Deep Search",
        "Step 0 (BEFORE everything else)",
        "MUST** use it as your **first action",
        "mcp__sourcegraph__sg_deepsearch_read",
        "Deep Search understands code semantically",
    ]
    return sum(1 for ind in indicators if ind in user_prompt) >= 2

def is_polling_response(content):
    """Check if a DS response is just a polling/status response (no actual results)."""
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            # Pure polling: just {link, note} with "Poll for results"
            if set(parsed.keys()) <= {"link", "note"} and "Poll for results" in parsed.get("note", ""):
                return True
            # Has actual answer content
            if "answer" in parsed and len(parsed.get("answer", "")) > 100:
                return False
            # Has code blocks
            if "blocks" in parsed:
                return False
    except json.JSONDecodeError:
        pass
    # Short content with polling indicators
    polling_phrases = ["Poll for results", "deepsearch progress", "still processing"]
    if any(p in content for p in polling_phrases) and len(content) < 500:
        return True
    return False

def has_actual_ds_results(content):
    """Check if DS response has actual code/content results."""
    if is_polling_response(content):
        return False
    if len(content) < 200:
        return False
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            answer = parsed.get("answer", "")
            if len(answer) > 100:
                return True
            if "blocks" in parsed:
                return True
    except json.JSONDecodeError:
        pass
    code_indicators = ["def ", "func ", "class ", "import ", "package ", "struct "]
    if any(ind in content for ind in code_indicators) and len(content) > 500:
        return True
    return False

def is_real_mcp_connection_error(content, fn_name):
    """
    Check if an MCP tool response is a REAL connection error
    (not just code content that happens to contain error-related words).
    """
    # Real MCP connection errors are typically short error messages, not code content
    error_patterns = [
        r"ECONNREFUSED",
        r"Connection refused",
        r"failed to connect to MCP",
        r"MCP server .* disconnected",
        r"transport error",
        r"spawn error",
        r"Could not connect to MCP",
        r"Internal error: MCP",
        r"McpError",
        r"Error: spawn",
        r'"isError"\s*:\s*true',
    ]
    for pattern in error_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False

def analyze_trajectory(trajectory_path):
    result = {
        "path": trajectory_path,
        "task_name": "",
        "suite": "",
        "run_dir": "",
        "ds_format": "unknown",
        "ds_calls": 0,
        "ds_read_calls": 0,
        "ds_polling_only_count": 0,
        "ds_success_count": 0,
        "ds_unique_searches": 0,  # number of unique DS search IDs
        "ds_max_polls_per_search": 0,  # max polls for a single search
        "mcp_calls": 0,
        "mcp_tool_breakdown": defaultdict(int),
        "mcp_connection_errors": 0,
        "total_steps": 0,
        "classification": "unknown",
        "reward": None,
        "notes": [],
    }

    try:
        with open(trajectory_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result["classification"] = "read_error"
        result["notes"].append(f"Failed to read: {e}")
        return result

    steps = data.get("steps", [])
    result["total_steps"] = len(steps)

    # Extract path info
    parts = Path(trajectory_path).parts
    try:
        sg_full_idx = parts.index("sourcegraph_full")
        result["run_dir"] = parts[sg_full_idx - 1]
        result["suite"] = detect_suite(parts[sg_full_idx - 1])
        task_dir = parts[sg_full_idx + 2]
        result["task_name"] = extract_task_name(task_dir)
        if "__archived_invalid" in trajectory_path:
            result["notes"].append("ARCHIVED (invalid)")
    except (ValueError, IndexError):
        result["notes"].append("Could not parse path structure")

    # Get reward
    result_json_path = str(Path(trajectory_path).parent.parent / "result.json")
    try:
        with open(result_json_path) as f:
            rdata = json.load(f)
        rewards = rdata.get("verifier_result", {}).get("rewards", {})
        result["reward"] = rewards.get("reward", rewards.get("score", None))
    except:
        pass

    # Check DS format
    if steps:
        user_msg = steps[0].get("message", "")
        if isinstance(user_msg, str):
            result["ds_format"] = "new" if is_new_ds_format(user_msg) else "old"

    # Track DS search IDs and their poll counts
    ds_search_ids = defaultdict(lambda: {"polls": 0, "success": False})

    for step in steps:
        tool_calls = step.get("tool_calls", [])
        obs = step.get("observation", {})
        obs_results = obs.get("results", [])

        for tc in tool_calls:
            fn = tc.get("function_name", "")
            if fn.startswith("mcp__"):
                result["mcp_calls"] += 1
                result["mcp_tool_breakdown"][fn] += 1

                # Find matching observation
                tc_id = tc.get("tool_call_id", "")
                content = ""
                for r in obs_results:
                    if r.get("source_call_id") == tc_id or len(tool_calls) == 1:
                        content = r.get("content", "")
                        break

                # Check for REAL MCP connection errors
                if is_real_mcp_connection_error(content, fn):
                    result["mcp_connection_errors"] += 1
                    result["notes"].append(f"MCP connection error in {fn}: {content[:100]}")

                # Extract DS search ID from polling responses
                ds_id = None
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and "link" in parsed:
                        link = parsed["link"]
                        if "deepsearch/" in link:
                            ds_id = link.split("deepsearch/")[-1]
                except:
                    pass

                if fn == "mcp__sourcegraph__sg_deepsearch":
                    result["ds_calls"] += 1
                    if ds_id:
                        ds_search_ids[ds_id]["polls"] += 1
                    if is_polling_response(content):
                        result["ds_polling_only_count"] += 1
                    elif has_actual_ds_results(content):
                        result["ds_success_count"] += 1
                        if ds_id:
                            ds_search_ids[ds_id]["success"] = True
                    else:
                        result["ds_polling_only_count"] += 1

                elif fn == "mcp__sourcegraph__sg_deepsearch_read":
                    result["ds_read_calls"] += 1
                    if ds_id:
                        ds_search_ids[ds_id]["polls"] += 1
                    if is_polling_response(content):
                        result["ds_polling_only_count"] += 1
                    elif has_actual_ds_results(content):
                        result["ds_success_count"] += 1
                        if ds_id:
                            ds_search_ids[ds_id]["success"] = True
                    else:
                        result["ds_polling_only_count"] += 1

    # DS search analysis
    result["ds_unique_searches"] = len(ds_search_ids)
    if ds_search_ids:
        result["ds_max_polls_per_search"] = max(v["polls"] for v in ds_search_ids.values())

    # Classify
    if result["mcp_connection_errors"] > 0 and result["mcp_calls"] == result["mcp_connection_errors"]:
        result["classification"] = "mcp_connection_error"
    elif result["mcp_calls"] == 0:
        result["classification"] = "mcp_not_used"
    elif result["ds_calls"] == 0 and result["ds_read_calls"] == 0:
        result["classification"] = "deep_search_not_used"
    elif result["ds_success_count"] > 0:
        result["classification"] = "deep_search_success"
    elif (result["ds_calls"] > 0 or result["ds_read_calls"] > 0) and result["ds_success_count"] == 0:
        result["classification"] = "deep_search_polling_only"
    else:
        result["classification"] = "unknown"

    return result


def main():
    trajectories = []
    for root, dirs, files in os.walk(BASE_DIR):
        if "/archive/" in root and "__archived_invalid" not in root:
            dirs.clear()
            continue
        if "trajectory.json" in files and "/sourcegraph_full/" in root:
            trajectories.append(os.path.join(root, "trajectory.json"))

    print(f"Scanned: found {len(trajectories)} sourcegraph_full trajectory files\n")

    results = []
    for tpath in sorted(trajectories):
        r = analyze_trajectory(tpath)
        results.append(r)

    active = [r for r in results if "ARCHIVED" not in " ".join(r["notes"])]
    archived = [r for r in results if "ARCHIVED" in " ".join(r["notes"])]

    print("=" * 130)
    print("DEEP SEARCH AUDIT REPORT v2 - sourcegraph_full runs")
    print("=" * 130)

    # ---- SUMMARY ----
    class_counts = defaultdict(int)
    for r in active:
        class_counts[r["classification"]] += 1

    print("\n## 1. CLASSIFICATION SUMMARY (active runs only)")
    print(f"  {'Classification':<30} {'Count':>6}")
    print("  " + "-" * 38)
    for cls in ["deep_search_success", "deep_search_polling_only", "deep_search_not_used", "mcp_not_used", "mcp_connection_error"]:
        if cls in class_counts:
            print(f"  {cls:<30} {class_counts[cls]:>6}")
    print(f"  {'TOTAL':<30} {len(active):>6}")
    print(f"  (+ {len(archived)} archived/invalid runs excluded)")

    # ---- DS FORMAT ----
    format_counts = defaultdict(int)
    for r in active:
        format_counts[r["ds_format"]] += 1
    print(f"\n## 2. DS INSTRUCTION FORMAT")
    print(f"  New format (explicit DS section):  {format_counts['new']}")
    print(f"  Old format (DS in tool list only): {format_counts['old']}")

    # ---- FORMAT x CLASSIFICATION ----
    print(f"\n## 3. FORMAT x CLASSIFICATION cross-tab")
    format_class = defaultdict(lambda: defaultdict(int))
    for r in active:
        format_class[r["ds_format"]][r["classification"]] += 1
    all_classes = ["deep_search_success", "deep_search_polling_only", "deep_search_not_used", "mcp_not_used"]
    header = f"  {'Format':<8}" + "".join(f" {c:>25}" for c in all_classes) + f" {'TOTAL':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for fmt in ["new", "old"]:
        total = sum(format_class[fmt].values())
        row = f"  {fmt:<8}" + "".join(f" {format_class[fmt].get(c, 0):>25}" for c in all_classes) + f" {total:>8}"
        print(row)

    # ---- BY SUITE ----
    print(f"\n## 4. BY SUITE BREAKDOWN")
    suite_data = defaultdict(lambda: defaultdict(list))
    for r in active:
        suite_data[r["suite"]][r["classification"]].append(r)

    for suite in sorted(suite_data.keys()):
        total = sum(len(v) for v in suite_data[suite].values())
        ds_success = len(suite_data[suite].get("deep_search_success", []))
        ds_poll = len(suite_data[suite].get("deep_search_polling_only", []))
        ds_unused = len(suite_data[suite].get("deep_search_not_used", []))
        mcp_unused = len(suite_data[suite].get("mcp_not_used", []))
        # Avg reward by classification
        def avg_reward(runs):
            with_r = [r["reward"] for r in runs if r["reward"] is not None]
            return f"{sum(with_r)/len(with_r):.3f}" if with_r else "n/a"
        print(f"\n  {suite} (n={total})")
        if ds_success:
            runs = suite_data[suite]["deep_search_success"]
            print(f"    DS success:      {ds_success:>3} runs  avg_reward={avg_reward(runs)}")
        if ds_poll:
            runs = suite_data[suite]["deep_search_polling_only"]
            print(f"    DS polling-only: {ds_poll:>3} runs  avg_reward={avg_reward(runs)}")
        if ds_unused:
            runs = suite_data[suite]["deep_search_not_used"]
            print(f"    DS not used:     {ds_unused:>3} runs  avg_reward={avg_reward(runs)}")
        if mcp_unused:
            runs = suite_data[suite]["mcp_not_used"]
            print(f"    MCP not used:    {mcp_unused:>3} runs  avg_reward={avg_reward(runs)}")

    # ---- POLLING RETRY ANALYSIS ----
    print(f"\n## 5. DEEP SEARCH POLLING RETRY ANALYSIS")
    print("   How many times did the agent poll for DS results before giving up?")
    polling_runs = [r for r in active if r["classification"] == "deep_search_polling_only"]
    success_runs = [r for r in active if r["classification"] == "deep_search_success"]

    print(f"\n  Polling-only runs (n={len(polling_runs)}):")
    poll_counts = defaultdict(int)
    for r in polling_runs:
        total_ds = r["ds_calls"] + r["ds_read_calls"]
        poll_counts[total_ds] += 1
        # Show per-run
    for r in sorted(polling_runs, key=lambda x: x["ds_calls"] + x["ds_read_calls"]):
        total_ds = r["ds_calls"] + r["ds_read_calls"]
        print(f"    {r['suite']:<20} {r['task_name']:<45} ds+read={total_ds} (ds={r['ds_calls']}, read={r['ds_read_calls']})")

    print(f"\n  Successful DS runs (n={len(success_runs)}):")
    for r in sorted(success_runs, key=lambda x: x["ds_calls"] + x["ds_read_calls"]):
        total_ds = r["ds_calls"] + r["ds_read_calls"]
        print(f"    {r['suite']:<20} {r['task_name']:<45} ds+read={total_ds} (ds={r['ds_calls']}, read={r['ds_read_calls']}, success={r['ds_success_count']})")

    print(f"\n  POLL COUNT DISTRIBUTION (polling-only):")
    for count in sorted(poll_counts.keys()):
        print(f"    {count} total DS calls: {poll_counts[count]} runs")

    succ_poll_counts = defaultdict(int)
    for r in success_runs:
        total_ds = r["ds_calls"] + r["ds_read_calls"]
        succ_poll_counts[total_ds] += 1
    print(f"\n  POLL COUNT DISTRIBUTION (successful):")
    for count in sorted(succ_poll_counts.keys()):
        print(f"    {count} total DS calls: {succ_poll_counts[count]} runs")

    # ---- REWARD COMPARISON ----
    print(f"\n## 6. REWARD COMPARISON BY CLASSIFICATION")
    for cls in ["deep_search_success", "deep_search_polling_only", "deep_search_not_used", "mcp_not_used"]:
        runs_with_reward = [r for r in active if r["classification"] == cls and r["reward"] is not None]
        if runs_with_reward:
            rewards = [r["reward"] for r in runs_with_reward]
            avg = sum(rewards) / len(rewards)
            passes = sum(1 for r in rewards if r > 0)
            print(f"  {cls:<30} n={len(runs_with_reward):>3}  avg_reward={avg:.3f}  pass_rate={passes}/{len(runs_with_reward)} ({100*passes/len(runs_with_reward):.0f}%)")

    # ---- SAME SUITE comparison: DS success vs polling ----
    print(f"\n## 7. WITHIN-SUITE DS SUCCESS vs POLLING COMPARISON")
    for suite in sorted(suite_data.keys()):
        success = suite_data[suite].get("deep_search_success", [])
        polling = suite_data[suite].get("deep_search_polling_only", [])
        if success and polling:
            s_rewards = [r["reward"] for r in success if r["reward"] is not None]
            p_rewards = [r["reward"] for r in polling if r["reward"] is not None]
            s_avg = sum(s_rewards)/len(s_rewards) if s_rewards else 0
            p_avg = sum(p_rewards)/len(p_rewards) if p_rewards else 0
            s_pass = sum(1 for r in s_rewards if r > 0)
            p_pass = sum(1 for r in p_rewards if r > 0)
            print(f"  {suite}:")
            print(f"    DS success:      n={len(s_rewards):>2}  avg={s_avg:.3f}  pass={s_pass}/{len(s_rewards)}")
            print(f"    DS polling-only: n={len(p_rewards):>2}  avg={p_avg:.3f}  pass={p_pass}/{len(p_rewards)}")
            delta = s_avg - p_avg
            print(f"    Delta (success - polling): {delta:+.3f}")

    # ---- DETAILED LISTINGS ----
    # Polling-only detail
    print(f"\n{'=' * 130}")
    print(f"## 8. DETAILED: DEEP SEARCH POLLING-ONLY RUNS")
    print(f"{'=' * 130}")
    print(f"These {len(polling_runs)} runs called DS but never received actual results.")
    for r in sorted(polling_runs, key=lambda x: (x["suite"], x["task_name"])):
        reward_str = f"reward={r['reward']:.4f}" if r['reward'] is not None else "no reward"
        print(f"  {r['suite']:<20} {r['task_name']:<45} {reward_str:<18} ds={r['ds_calls']} read={r['ds_read_calls']} format={r['ds_format']}")

    # DS not used detail
    ds_not_used = [r for r in active if r["classification"] == "deep_search_not_used"]
    print(f"\n{'=' * 130}")
    print(f"## 9. DETAILED: DS NOT USED (but MCP tools used)")
    print(f"{'=' * 130}")
    for r in sorted(ds_not_used, key=lambda x: (x["suite"], x["task_name"])):
        reward_str = f"reward={r['reward']:.4f}" if r['reward'] is not None else "no reward"
        tools_used = ", ".join(f"{k}={v}" for k, v in sorted(r["mcp_tool_breakdown"].items()))
        print(f"  {r['suite']:<20} {r['task_name']:<45} {reward_str:<18} format={r['ds_format']} mcp={r['mcp_calls']} [{tools_used}]")

    # Old format
    old_format = [r for r in active if r["ds_format"] == "old"]
    print(f"\n{'=' * 130}")
    print(f"## 10. OLD DS FORMAT RUNS (need rerun)")
    print(f"{'=' * 130}")
    print(f"{len(old_format)} runs with old instruction format:")
    by_suite = defaultdict(list)
    for r in old_format:
        by_suite[r["suite"]].append(r)
    for suite in sorted(by_suite.keys()):
        print(f"  {suite}: {len(by_suite[suite])} tasks")
        for r in by_suite[suite]:
            print(f"    {r['task_name']:<50} cls={r['classification']:<28} reward={r['reward']}")

    # MCP connection errors
    mcp_errs = [r for r in active if r["mcp_connection_errors"] > 0]
    print(f"\n{'=' * 130}")
    print(f"## 11. MCP CONNECTION ERRORS")
    print(f"{'=' * 130}")
    if mcp_errs:
        for r in mcp_errs:
            print(f"  {r['suite']:<20} {r['task_name']:<45} errors={r['mcp_connection_errors']} notes={r['notes']}")
    else:
        print("  No real MCP connection errors found in any active sourcegraph_full run.")

    # ---- EXECUTIVE SUMMARY ----
    print(f"\n{'=' * 130}")
    print(f"## EXECUTIVE SUMMARY")
    print(f"{'=' * 130}")
    print(f"""
Active sourcegraph_full runs analyzed: {len(active)}
  - DS success (got results):    {class_counts.get('deep_search_success', 0):>3} ({100*class_counts.get('deep_search_success',0)/len(active):.0f}%)
  - DS polling-only (no results): {class_counts.get('deep_search_polling_only', 0):>3} ({100*class_counts.get('deep_search_polling_only',0)/len(active):.0f}%)
  - DS not used (other MCP only): {class_counts.get('deep_search_not_used', 0):>3} ({100*class_counts.get('deep_search_not_used',0)/len(active):.0f}%)
  - MCP not used at all:          {class_counts.get('mcp_not_used', 0):>3} ({100*class_counts.get('mcp_not_used',0)/len(active):.0f}%)
  - MCP connection errors:         {class_counts.get('mcp_connection_error', 0):>3}

DS instruction format:
  - New format: {format_counts['new']} runs (DS call rate: {sum(1 for r in active if r['ds_format']=='new' and r['ds_calls']>0)}/{format_counts['new']} = {100*sum(1 for r in active if r['ds_format']=='new' and r['ds_calls']>0)/max(1,format_counts['new']):.0f}%)
  - Old format: {format_counts['old']} runs (DS call rate: {sum(1 for r in active if r['ds_format']=='old' and r['ds_calls']>0)}/{format_counts['old']} = {100*sum(1 for r in active if r['ds_format']=='old' and r['ds_calls']>0)/max(1,format_counts['old']):.0f}%)

Of runs that called DS (n={class_counts.get('deep_search_success',0)+class_counts.get('deep_search_polling_only',0)}):
  - Got actual results: {class_counts.get('deep_search_success', 0)} ({100*class_counts.get('deep_search_success',0)/max(1,class_counts.get('deep_search_success',0)+class_counts.get('deep_search_polling_only',0)):.0f}%)
  - Only got polling:   {class_counts.get('deep_search_polling_only', 0)} ({100*class_counts.get('deep_search_polling_only',0)/max(1,class_counts.get('deep_search_success',0)+class_counts.get('deep_search_polling_only',0)):.0f}%)

Key issue: {class_counts.get('deep_search_polling_only',0)} runs ({100*class_counts.get('deep_search_polling_only',0)/len(active):.0f}% of all SG_full runs)
called Deep Search but the agent gave up polling before results arrived.
Typical pattern: 1 DS call + 0-2 read polls, then agent moves on to other tools.
""")

if __name__ == "__main__":
    main()

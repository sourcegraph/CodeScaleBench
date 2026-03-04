#!/usr/bin/env python3
"""Scan SDLC task results in runs/official/ for anomalies.

Walks all result.json files, extracts task_id, config type (baseline vs MCP),
and reward scores. Groups by task, computes means, and flags anomalies:
  - Any run with reward == 0.0
  - |mean_baseline - mean_MCP| > 0.4
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

OFFICIAL_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"

# The 9 SDLC suites
SDLC_SUITES = {
    "csb_sdlc_feature", "csb_sdlc_refactor", "csb_sdlc_debug", "csb_sdlc_fix",
    "csb_sdlc_test", "csb_sdlc_design", "csb_sdlc_document", "csb_sdlc_secure", "csb_sdlc_understand",
    # Legacy names for backward compatibility
    "ccb_feature", "ccb_refactor", "ccb_debug", "ccb_fix",
    "ccb_test", "ccb_design", "ccb_document", "ccb_secure", "ccb_understand",
}

# Also match old "ccb_build" which was split into ccb_feature + ccb_refactor
# We'll map tasks from ccb_build to the appropriate suite based on task_id path if available


def classify_config(path_str: str) -> str | None:
    """Determine if a result.json path is from a baseline or MCP config."""
    path_lower = path_str.lower()
    # Check path components for config type
    parts = path_lower.split(os.sep)
    for part in parts:
        if part in ("baseline", "baseline-local-direct", "baseline-local-artifact"):
            return "baseline"
        if part in ("mcp", "mcp-remote-direct", "sourcegraph_full"):
            return "mcp"
    return None


def extract_suite_from_task_id_path(task_id_path: str) -> str | None:
    """Extract suite name from task_id path like .../benchmarks/ccb_feature/task-name."""
    if not task_id_path:
        return None
    for suite in SDLC_SUITES:
        if f"/{suite}/" in task_id_path or f"/{suite}\\" in task_id_path:
            return suite
    # Check for old ccb_build (split into feature/refactor)
    if "/ccb_build/" in task_id_path:
        return "ccb_build"
    return None


def extract_suite_from_batch_dir(result_path: str) -> str | None:
    """Extract suite from the batch directory name in the path."""
    # Batch dirs are like: ccb_fix_haiku_20260228_185835 or fix_haiku_20260301_190026
    rel = os.path.relpath(result_path, OFFICIAL_DIR)
    batch_dir = rel.split(os.sep)[0]

    # Direct prefix matching for SDLC suites
    sdlc_names = ["feature", "refactor", "debug", "fix", "test", "design", "document", "secure", "understand"]
    for name in sdlc_names:
        # Match csb_sdlc_{name}_ or ccb_{name}_ or {name}_ at start of batch dir
        if batch_dir.startswith(f"csb_sdlc_{name}_"):
            return f"csb_sdlc_{name}"
        if batch_dir.startswith(f"ccb_{name}_") or batch_dir.startswith(f"{name}_"):
            return f"ccb_{name}"
    # Legacy build
    if batch_dir.startswith("ccb_build_") or batch_dir.startswith("build_"):
        return "ccb_build"
    return None


def normalize_task_name(task_name: str) -> str:
    """Strip prefixes and normalize to lowercase."""
    name = task_name.lower().strip()
    had_mcp_prefix = False
    # Strip sgonly_ prefix
    if name.startswith("sgonly_"):
        name = name[len("sgonly_"):]
    # Strip mcp_ prefix (some MCP runs prefix with mcp_)
    if name.startswith("mcp_"):
        name = name[len("mcp_"):]
        had_mcp_prefix = True
    # Strip trailing _XXXXX random suffixes (from mcp_ prefixed names)
    # Pattern: old mcp task names are like mcp_task-name-001_Random6
    # After stripping mcp_, we get task-name-001_random6
    # The random suffix is 6 alphanumeric chars after last underscore
    # Only strip if we had an mcp_ prefix to avoid stripping valid task name parts
    if had_mcp_prefix:
        m = re.match(r"^(.+-\d{3})_[a-z0-9]{4,8}$", name)
        if m:
            name = m.group(1)
    return name


def extract_reward(data: dict) -> float | None:
    """Extract reward score from result.json data."""
    vr = data.get("verifier_result")
    if not vr:
        return None
    rewards = vr.get("rewards")
    if not rewards:
        return None
    reward = rewards.get("reward")
    if reward is not None:
        return float(reward)
    return None


def extract_error_info(data: dict) -> dict:
    """Extract error/exception info from result.json."""
    info = {}
    exc = data.get("exception_info")
    if exc:
        info["exception_info"] = exc if isinstance(exc, str) else json.dumps(exc)[:300]

    agent_result = data.get("agent_result", {}) or {}
    info["n_output_tokens"] = agent_result.get("n_output_tokens")

    # Check for error in verifier
    vr = data.get("verifier_result", {}) or {}
    if isinstance(vr, dict):
        for key in ("error", "stderr", "message"):
            if key in vr:
                info[f"verifier_{key}"] = str(vr[key])[:200]

    return info


def main():
    # Collect all task-level result.json files
    # Structure: {task_id: {"baseline": [(reward, error_info, path)], "mcp": [...]}}
    task_data = defaultdict(lambda: {"baseline": [], "mcp": [], "suite": None})

    result_count = 0
    skipped_batch = 0
    skipped_no_suite = 0
    skipped_no_config = 0

    for root, dirs, files in os.walk(OFFICIAL_DIR):
        # Skip archive directory
        if "archive" in root.split(os.sep):
            continue
        if "result.json" not in files:
            continue

        fpath = os.path.join(root, "result.json")
        try:
            with open(fpath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # Skip batch-level result.json
        if "stats" in data and "task_name" not in data:
            skipped_batch += 1
            continue
        if "stats" in data:
            skipped_batch += 1
            continue
        if "task_name" not in data:
            continue

        task_name = data["task_name"]
        normalized = normalize_task_name(task_name)

        # Determine suite
        task_id_obj = data.get("task_id", "")
        task_id_path = ""
        if isinstance(task_id_obj, dict):
            task_id_path = task_id_obj.get("path", "")
        elif isinstance(task_id_obj, str):
            task_id_path = task_id_obj

        suite = extract_suite_from_task_id_path(task_id_path)
        if not suite:
            suite = extract_suite_from_batch_dir(fpath)

        # Filter to SDLC suites only (including old ccb_build)
        if suite not in SDLC_SUITES and suite != "ccb_build":
            skipped_no_suite += 1
            continue

        # Map ccb_build to feature or refactor based on task name heuristics
        if suite == "ccb_build":
            # Skip old build tasks; they were split into feature/refactor
            # Include them under a generic "ccb_build_legacy" label
            suite = "ccb_build(legacy)"

        # Determine config
        config = classify_config(fpath)
        if config is None:
            skipped_no_config += 1
            continue

        # Extract reward
        reward = extract_reward(data)

        # Extract error info
        error_info = extract_error_info(data)
        error_info["path"] = fpath

        result_count += 1

        task_data[normalized]["suite"] = suite
        task_data[normalized][config].append({
            "reward": reward,
            "error_info": error_info,
            "path": fpath,
        })

    print(f"=== SDLC Anomaly Scan ===")
    print(f"Total task-level results parsed: {result_count}")
    print(f"Skipped batch-level: {skipped_batch}")
    print(f"Skipped non-SDLC: {skipped_no_suite}")
    print(f"Skipped no config: {skipped_no_config}")
    print(f"Unique tasks found: {len(task_data)}")
    print()

    # Compute stats and flag anomalies
    flagged = []
    for task_id, info in sorted(task_data.items()):
        suite = info["suite"]
        bl_rewards = [r["reward"] for r in info["baseline"] if r["reward"] is not None]
        mcp_rewards = [r["reward"] for r in info["mcp"] if r["reward"] is not None]

        # Also track None rewards (errors)
        bl_nulls = sum(1 for r in info["baseline"] if r["reward"] is None)
        mcp_nulls = sum(1 for r in info["mcp"] if r["reward"] is None)

        mean_bl = sum(bl_rewards) / len(bl_rewards) if bl_rewards else None
        mean_mcp = sum(mcp_rewards) / len(mcp_rewards) if mcp_rewards else None

        flags = []

        # Flag a: any run scoring exactly 0.0
        if any(r == 0.0 for r in bl_rewards):
            flags.append("baseline_has_zero")
        if any(r == 0.0 for r in mcp_rewards):
            flags.append("mcp_has_zero")

        # Flag: any run with None reward (exception/error)
        if bl_nulls > 0:
            flags.append(f"baseline_null_reward(x{bl_nulls})")
        if mcp_nulls > 0:
            flags.append(f"mcp_null_reward(x{mcp_nulls})")

        # Flag b: large delta
        delta = None
        if mean_bl is not None and mean_mcp is not None:
            delta = mean_mcp - mean_bl
            if abs(delta) > 0.4:
                direction = "mcp_better" if delta > 0 else "baseline_better"
                flags.append(f"large_delta({direction})")

        if flags:
            # Collect error details for flagged runs
            bl_errors = []
            mcp_errors = []
            for r in info["baseline"]:
                if r["reward"] is None or r["reward"] == 0.0:
                    bl_errors.append(r["error_info"])
            for r in info["mcp"]:
                if r["reward"] is None or r["reward"] == 0.0:
                    mcp_errors.append(r["error_info"])

            flagged.append({
                "task_id": task_id,
                "suite": suite,
                "bl_rewards": bl_rewards,
                "mcp_rewards": mcp_rewards,
                "bl_nulls": bl_nulls,
                "mcp_nulls": mcp_nulls,
                "mean_bl": mean_bl,
                "mean_mcp": mean_mcp,
                "delta": delta,
                "flags": flags,
                "bl_errors": bl_errors,
                "mcp_errors": mcp_errors,
            })

    # Sort by suite, then task_id
    flagged.sort(key=lambda x: (x["suite"], x["task_id"]))

    # Print report
    print(f"{'='*120}")
    print(f"FLAGGED TASKS: {len(flagged)}")
    print(f"{'='*120}")
    print()

    current_suite = None
    for item in flagged:
        if item["suite"] != current_suite:
            current_suite = item["suite"]
            print(f"\n{'─'*120}")
            print(f"  SUITE: {current_suite}")
            print(f"{'─'*120}")

        print(f"\n  Task: {item['task_id']}")
        print(f"  Baseline scores: {item['bl_rewards']} (n={len(item['bl_rewards'])}, nulls={item['bl_nulls']})")
        print(f"  MCP scores:      {item['mcp_rewards']} (n={len(item['mcp_rewards'])}, nulls={item['mcp_nulls']})")
        mean_bl_str = f"{item['mean_bl']:.4f}" if item['mean_bl'] is not None else "N/A"
        mean_mcp_str = f"{item['mean_mcp']:.4f}" if item['mean_mcp'] is not None else "N/A"
        delta_str = f"{item['delta']:+.4f}" if item['delta'] is not None else "N/A"
        print(f"  Mean BL: {mean_bl_str}  |  Mean MCP: {mean_mcp_str}  |  Delta: {delta_str}")
        print(f"  Flags: {', '.join(item['flags'])}")

        # Print error details
        if item["bl_errors"]:
            print(f"  Baseline error details:")
            for err in item["bl_errors"]:
                exc = err.get("exception_info", "")
                tokens = err.get("n_output_tokens", "?")
                verifier_err = err.get("verifier_error", err.get("verifier_stderr", ""))
                path = err.get("path", "")
                # Shorten path
                short_path = path.replace(str(OFFICIAL_DIR) + "/", "")
                print(f"    - tokens={tokens}, exception={exc or 'None'}, verifier_err={verifier_err or 'None'}")
                print(f"      path: {short_path}")

        if item["mcp_errors"]:
            print(f"  MCP error details:")
            for err in item["mcp_errors"]:
                exc = err.get("exception_info", "")
                tokens = err.get("n_output_tokens", "?")
                verifier_err = err.get("verifier_error", err.get("verifier_stderr", ""))
                path = err.get("path", "")
                short_path = path.replace(str(OFFICIAL_DIR) + "/", "")
                print(f"    - tokens={tokens}, exception={exc or 'None'}, verifier_err={verifier_err or 'None'}")
                print(f"      path: {short_path}")

    # Summary by suite
    print(f"\n\n{'='*120}")
    print(f"SUMMARY BY SUITE")
    print(f"{'='*120}")
    suite_counts = defaultdict(lambda: {"total_tasks": 0, "flagged": 0, "zero_bl": 0, "zero_mcp": 0, "large_delta": 0, "null_reward": 0})
    for task_id, info in task_data.items():
        suite = info["suite"]
        suite_counts[suite]["total_tasks"] += 1
    for item in flagged:
        suite = item["suite"]
        suite_counts[suite]["flagged"] += 1
        if "baseline_has_zero" in item["flags"]:
            suite_counts[suite]["zero_bl"] += 1
        if "mcp_has_zero" in item["flags"]:
            suite_counts[suite]["zero_mcp"] += 1
        if any("large_delta" in f for f in item["flags"]):
            suite_counts[suite]["large_delta"] += 1
        if any("null_reward" in f for f in item["flags"]):
            suite_counts[suite]["null_reward"] += 1

    print(f"\n  {'Suite':<25} {'Total':>6} {'Flagged':>8} {'Zero BL':>8} {'Zero MCP':>9} {'|Delta|>0.4':>12} {'Null Reward':>12}")
    print(f"  {'─'*25} {'─'*6} {'─'*8} {'─'*8} {'─'*9} {'─'*12} {'─'*12}")
    for suite in sorted(suite_counts.keys()):
        c = suite_counts[suite]
        print(f"  {suite:<25} {c['total_tasks']:>6} {c['flagged']:>8} {c['zero_bl']:>8} {c['zero_mcp']:>9} {c['large_delta']:>12} {c['null_reward']:>12}")

    print()


if __name__ == "__main__":
    main()

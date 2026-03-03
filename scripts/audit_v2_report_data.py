#!/usr/bin/env python3
"""Audit all V2 technical report data for integrity and completeness.

Scans runs/official/ (non-archive) handling BOTH old-format (batch dirs)
and new-format (timestamp dirs), validates rewards, checks pairing,
and flags suspicious data patterns.

Usage:
    python3 scripts/audit_v2_report_data.py [--verbose] [--fix-extract]
"""

import json
import re
import sys
import statistics
from collections import defaultdict
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "runs" / "official"
TASKS_FILE = ROOT / "configs" / "selected_benchmark_tasks.json"

# Load canonical tasks
with open(TASKS_FILE) as f:
    _tasks_raw = json.load(f)["tasks"]
    TASK_META = {t["task_id"].lower(): t for t in _tasks_raw}

SDLC_TASKS = set()
ORG_TASKS = set()
for tid, meta in TASK_META.items():
    bm = meta.get("benchmark", "")
    if "sdlc" in bm or (bm.startswith("ccb_") and not bm.startswith("ccb_mcp_")):
        SDLC_TASKS.add(tid)
    else:
        ORG_TASKS.add(tid)


def normalize_task_name(raw_name: str) -> str:
    name = raw_name
    name = re.sub(r"^mcp_", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^bl_", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^sgonly_", "", name, flags=re.IGNORECASE)
    name = re.sub(r"_[A-Za-z0-9]{6,8}$", "", name)
    return name.lower()


def classify_config(config_name: str) -> str:
    cn = config_name.lower()
    if "baseline" in cn:
        return "baseline"
    elif "mcp" in cn or "sg" in cn:
        return "mcp"
    return "unknown"


def extract_reward(result: dict):
    """Extract reward from result.json, checking all known locations."""
    agent_result = result.get("agent_result") or {}
    vr = result.get("verifier_result") or agent_result.get("verifier_result") or {}
    rewards = vr.get("rewards") or {}
    return rewards.get("reward")


def is_batch_level(result: dict) -> bool:
    """Check if this is a batch-level result (not task-level)."""
    return "stats" in result and "agent_result" not in result


def scan_task_dir(task_dir: Path) -> dict | None:
    """Extract task record from a task directory containing result.json."""
    result_file = task_dir / "result.json"
    if not result_file.exists():
        return None
    try:
        with open(result_file) as f:
            result = json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"error": "json_decode_error", "path": str(result_file)}

    if is_batch_level(result):
        return None

    reward = extract_reward(result)
    raw_name = result.get("task_name", task_dir.name)
    raw_name = re.sub(r"__[A-Za-z0-9]+$", "", raw_name)
    task_name = normalize_task_name(raw_name)

    agent_result = result.get("agent_result") or {}
    n_input = agent_result.get("n_input_tokens", 0) or 0
    n_output = agent_result.get("n_output_tokens", 0) or 0
    cost = agent_result.get("cost_usd")

    wall_clock = None
    started = result.get("started_at")
    finished = result.get("finished_at")
    if started and finished:
        try:
            ts = started.replace("Z", "+00:00")
            te = finished.replace("Z", "+00:00")
            t_start = datetime.fromisoformat(ts)
            t_end = datetime.fromisoformat(te)
            wall_clock = (t_end - t_start).total_seconds()
        except:
            pass

    return {
        "task_name": task_name,
        "raw_name": raw_name,
        "reward": reward,
        "input_tokens": n_input,
        "output_tokens": n_output,
        "cost_usd": cost,
        "wall_clock_seconds": wall_clock,
        "result_path": str(result_file),
    }


def scan_all_results():
    """Scan all task results handling both old and new directory formats."""
    records = []
    errors = []

    for run_dir in sorted(OFFICIAL.iterdir()):
        if not run_dir.is_dir() or run_dir.name == "archive":
            continue
        run_name = run_dir.name

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            config_type = classify_config(config_name)
            if config_type == "unknown":
                continue

            for sub_dir in sorted(config_dir.iterdir()):
                if not sub_dir.is_dir():
                    continue

                # New format: timestamp dir -> task dirs
                if re.match(r"^\d{4}-\d{2}-\d{2}", sub_dir.name):
                    for task_dir in sorted(sub_dir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        rec = scan_task_dir(task_dir)
                        if rec is None:
                            continue
                        if "error" in rec:
                            errors.append(rec)
                            continue
                        rec["run_name"] = run_name
                        rec["config_type"] = config_type
                        rec["dir_format"] = "new"
                        records.append(rec)

                # Old format: batch dir (ccb_*/csb_*) -> task dirs
                elif sub_dir.name.startswith(("ccb_", "csb_")):
                    # Check for task-level results inside batch dir
                    for task_dir in sorted(sub_dir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        rec = scan_task_dir(task_dir)
                        if rec is None:
                            continue
                        if "error" in rec:
                            errors.append(rec)
                            continue
                        rec["run_name"] = run_name
                        rec["config_type"] = config_type
                        rec["dir_format"] = "old"
                        records.append(rec)

    return records, errors


def audit_records(records):
    """Run all audit checks on the extracted records."""
    issues = []

    # Group by task + config
    grouped = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r["task_name"]][r["config_type"]].append(r)

    # 1. Check canonical coverage
    canonical_with_data = set()
    canonical_paired = set()
    for task_name in grouped:
        if task_name in TASK_META:
            canonical_with_data.add(task_name)
            if "baseline" in grouped[task_name] and "mcp" in grouped[task_name]:
                # Need at least 1 valid reward per side
                bl_valid = [r for r in grouped[task_name]["baseline"] if r["reward"] is not None]
                mcp_valid = [r for r in grouped[task_name]["mcp"] if r["reward"] is not None]
                if bl_valid and mcp_valid:
                    canonical_paired.add(task_name)

    missing_canonical = set(TASK_META.keys()) - canonical_with_data
    unpaired_canonical = canonical_with_data - canonical_paired
    non_canonical = set(grouped.keys()) - set(TASK_META.keys())

    # 2. Check for null rewards on canonical tasks
    null_reward_tasks = defaultdict(lambda: {"baseline": 0, "mcp": 0, "baseline_total": 0, "mcp_total": 0})
    for task_name, by_config in grouped.items():
        if task_name not in TASK_META:
            continue
        for config_type, recs in by_config.items():
            total = len(recs)
            nulls = sum(1 for r in recs if r["reward"] is None)
            null_reward_tasks[task_name][f"{config_type}"] = nulls
            null_reward_tasks[task_name][f"{config_type}_total"] = total

    tasks_with_null_rewards = {
        t: v for t, v in null_reward_tasks.items()
        if v["baseline"] > 0 or v["mcp"] > 0
    }

    # 3. Suspicious data patterns
    suspicious = []

    for task_name, by_config in grouped.items():
        if task_name not in TASK_META:
            continue

        for config_type, recs in by_config.items():
            valid_rewards = [r["reward"] for r in recs if r["reward"] is not None]
            if not valid_rewards:
                continue

            # All zeros
            if all(r == 0.0 for r in valid_rewards) and len(valid_rewards) >= 2:
                suspicious.append({
                    "task": task_name,
                    "config": config_type,
                    "pattern": "all_zero",
                    "rewards": valid_rewards,
                    "n": len(valid_rewards),
                })

            # All ones
            if all(r == 1.0 for r in valid_rewards) and len(valid_rewards) >= 2:
                suspicious.append({
                    "task": task_name,
                    "config": config_type,
                    "pattern": "all_perfect",
                    "rewards": valid_rewards,
                    "n": len(valid_rewards),
                })

            # High variance
            if len(valid_rewards) >= 3:
                stdev = statistics.stdev(valid_rewards)
                if stdev > 0.4:
                    suspicious.append({
                        "task": task_name,
                        "config": config_type,
                        "pattern": "high_variance",
                        "rewards": [round(r, 4) for r in valid_rewards],
                        "stdev": round(stdev, 4),
                        "n": len(valid_rewards),
                    })

            # Extreme cost outliers
            valid_costs = [r["cost_usd"] for r in recs if r.get("cost_usd") is not None and r["cost_usd"] > 0]
            if valid_costs:
                max_cost = max(valid_costs)
                if max_cost > 5.0:
                    suspicious.append({
                        "task": task_name,
                        "config": config_type,
                        "pattern": "extreme_cost",
                        "max_cost": round(max_cost, 4),
                        "costs": [round(c, 4) for c in valid_costs],
                    })

            # Extreme timing outliers
            valid_times = [r["wall_clock_seconds"] for r in recs if r.get("wall_clock_seconds") is not None and r["wall_clock_seconds"] > 0]
            if valid_times:
                max_time = max(valid_times)
                if max_time > 3600:  # > 1 hour
                    suspicious.append({
                        "task": task_name,
                        "config": config_type,
                        "pattern": "extreme_time",
                        "max_seconds": round(max_time, 1),
                        "times": [round(t, 1) for t in valid_times],
                    })

    # 4. Normalization check - look for potential duplicates
    norm_collisions = defaultdict(set)
    for r in records:
        norm_collisions[r["task_name"]].add(r["raw_name"])
    multi_raw = {t: sorted(raws) for t, raws in norm_collisions.items() if len(raws) > 1}

    # 5. Pairing balance check
    pairing_balance = {}
    for task_name in canonical_paired:
        bl = [r for r in grouped[task_name]["baseline"] if r["reward"] is not None]
        mcp = [r for r in grouped[task_name]["mcp"] if r["reward"] is not None]
        pairing_balance[task_name] = {
            "bl_valid": len(bl),
            "mcp_valid": len(mcp),
            "bl_mean": round(statistics.mean(r["reward"] for r in bl), 4),
            "mcp_mean": round(statistics.mean(r["reward"] for r in mcp), 4),
        }

    # Tasks with <3 runs on either side
    under_target = {
        t: v for t, v in pairing_balance.items()
        if v["bl_valid"] < 3 or v["mcp_valid"] < 3
    }

    # 6. Dir format breakdown
    new_format = sum(1 for r in records if r.get("dir_format") == "new")
    old_format = sum(1 for r in records if r.get("dir_format") == "old")

    return {
        "total_records": len(records),
        "new_format": new_format,
        "old_format": old_format,
        "canonical_tasks": len(TASK_META),
        "canonical_with_data": len(canonical_with_data),
        "canonical_paired": len(canonical_paired),
        "sdlc_paired": len(canonical_paired & SDLC_TASKS),
        "org_paired": len(canonical_paired & ORG_TASKS),
        "missing_canonical": sorted(missing_canonical),
        "unpaired_canonical": sorted(unpaired_canonical),
        "non_canonical_tasks": len(non_canonical),
        "tasks_with_null_rewards": tasks_with_null_rewards,
        "suspicious": suspicious,
        "multi_raw_names": multi_raw,
        "under_target_3": under_target,
        "pairing_balance": pairing_balance,
    }


def compare_with_extract_script(audit_paired, extract_count=369):
    """Compare audit findings with what extract_v2_report_data.py reports."""
    delta = len(audit_paired) - extract_count
    return {
        "extract_script_paired": extract_count,
        "audit_paired": len(audit_paired),
        "delta": delta,
        "note": f"Audit found {'+' if delta > 0 else ''}{delta} more paired tasks than extract script"
        if delta != 0 else "Counts match"
    }


def main():
    verbose = "--verbose" in sys.argv

    print("=" * 70)
    print("V2 TECHNICAL REPORT DATA AUDIT")
    print("=" * 70)
    print()

    print("Scanning runs/official/ (both old and new dir formats)...", file=sys.stderr)
    records, errors = scan_all_results()

    print(f"\n--- SCAN SUMMARY ---")
    print(f"Total task evaluations found: {len(records)}")
    print(f"  New-format (timestamp dirs): {sum(1 for r in records if r.get('dir_format') == 'new')}")
    print(f"  Old-format (batch dirs): {sum(1 for r in records if r.get('dir_format') == 'old')}")
    print(f"JSON decode errors: {len(errors)}")

    bl_count = sum(1 for r in records if r["config_type"] == "baseline")
    mcp_count = sum(1 for r in records if r["config_type"] == "mcp")
    print(f"Baseline records: {bl_count}")
    print(f"MCP records: {mcp_count}")

    valid_reward = sum(1 for r in records if r["reward"] is not None)
    null_reward = sum(1 for r in records if r["reward"] is None)
    print(f"Valid rewards: {valid_reward}")
    print(f"Null rewards: {null_reward}")

    print("\nRunning audit checks...")
    audit = audit_records(records)

    print(f"\n--- CANONICAL COVERAGE ---")
    print(f"Canonical tasks: {audit['canonical_tasks']}")
    print(f"Canonical with any data: {audit['canonical_with_data']}")
    print(f"Canonical paired (valid BL + MCP): {audit['canonical_paired']}")
    print(f"  SDLC paired: {audit['sdlc_paired']}")
    print(f"  Org paired: {audit['org_paired']}")

    comparison = compare_with_extract_script(
        set(audit["pairing_balance"].keys()),
        extract_count=369
    )
    print(f"\n--- COMPARISON WITH EXTRACT SCRIPT ---")
    print(f"Extract script reports: {comparison['extract_script_paired']} paired")
    print(f"Audit finds: {comparison['audit_paired']} paired")
    print(f"Delta: {comparison['note']}")

    if audit["missing_canonical"]:
        print(f"\n--- MISSING CANONICAL TASKS ({len(audit['missing_canonical'])}) ---")
        for t in audit["missing_canonical"]:
            suite = TASK_META[t].get("benchmark", "?")
            print(f"  {t} ({suite})")

    if audit["unpaired_canonical"]:
        print(f"\n--- UNPAIRED CANONICAL TASKS ({len(audit['unpaired_canonical'])}) ---")
        for t in audit["unpaired_canonical"]:
            suite = TASK_META[t].get("benchmark", "?")
            # Show what data exists
            grouped = defaultdict(list)
            for r in records:
                if r["task_name"] == t:
                    grouped[r["config_type"]].append(r)
            bl_n = len(grouped.get("baseline", []))
            mcp_n = len(grouped.get("mcp", []))
            bl_valid = sum(1 for r in grouped.get("baseline", []) if r["reward"] is not None)
            mcp_valid = sum(1 for r in grouped.get("mcp", []) if r["reward"] is not None)
            print(f"  {t} ({suite})")
            print(f"    BL: {bl_n} total, {bl_valid} valid | MCP: {mcp_n} total, {mcp_valid} valid")

    # Under-target tasks
    under = audit["under_target_3"]
    if under:
        print(f"\n--- TASKS BELOW 3-RUN TARGET ({len(under)}) ---")
        sdlc_under = {t: v for t, v in under.items() if t in SDLC_TASKS}
        org_under = {t: v for t, v in under.items() if t in ORG_TASKS}
        print(f"  SDLC: {len(sdlc_under)}, Org: {len(org_under)}")
        if verbose:
            for t, v in sorted(under.items()):
                print(f"  {t}: BL={v['bl_valid']}, MCP={v['mcp_valid']} "
                      f"(BL_mean={v['bl_mean']}, MCP_mean={v['mcp_mean']})")

    # Suspicious patterns
    if audit["suspicious"]:
        print(f"\n--- SUSPICIOUS DATA PATTERNS ({len(audit['suspicious'])}) ---")
        by_pattern = defaultdict(list)
        for s in audit["suspicious"]:
            by_pattern[s["pattern"]].append(s)
        for pattern, items in sorted(by_pattern.items()):
            print(f"\n  {pattern} ({len(items)} instances):")
            for item in items[:10]:  # Cap at 10 per pattern
                if pattern == "all_zero":
                    print(f"    {item['task']} [{item['config']}] - {item['n']} runs all scored 0.0")
                elif pattern == "all_perfect":
                    print(f"    {item['task']} [{item['config']}] - {item['n']} runs all scored 1.0")
                elif pattern == "high_variance":
                    print(f"    {item['task']} [{item['config']}] - stdev={item['stdev']} rewards={item['rewards']}")
                elif pattern == "extreme_cost":
                    print(f"    {item['task']} [{item['config']}] - max=${item['max_cost']}")
                elif pattern == "extreme_time":
                    print(f"    {item['task']} [{item['config']}] - max={item['max_seconds']}s ({item['max_seconds']/60:.0f}m)")
            if len(items) > 10:
                print(f"    ... and {len(items) - 10} more")

    # Multi raw names (normalization check)
    if audit["multi_raw_names"]:
        print(f"\n--- TASK NAME NORMALIZATION (tasks with multiple raw names) ---")
        shown = 0
        for t, raws in sorted(audit["multi_raw_names"].items()):
            if t in TASK_META:
                print(f"  {t}: {raws}")
                shown += 1
                if shown >= 20 and not verbose:
                    print(f"  ... ({len(audit['multi_raw_names'])} total, use --verbose for all)")
                    break

    # Bustub specific check
    print(f"\n--- BUSTUB-HYPERLOGLOG-IMPL-001 SPECIFIC ---")
    bustub_records = [r for r in records if r["task_name"] == "bustub-hyperloglog-impl-001"]
    bl_bustub = [r for r in bustub_records if r["config_type"] == "baseline"]
    mcp_bustub = [r for r in bustub_records if r["config_type"] == "mcp"]
    print(f"  Baseline records: {len(bl_bustub)}")
    for r in bl_bustub:
        print(f"    reward={r['reward']}, format={r.get('dir_format')}, path=...{'/'.join(r['result_path'].split('/')[-4:])}")
    print(f"  MCP records: {len(mcp_bustub)}")
    for r in mcp_bustub:
        print(f"    reward={r['reward']}, format={r.get('dir_format')}, path=...{'/'.join(r['result_path'].split('/')[-4:])}")

    # Aggregate stats for paired tasks
    print(f"\n--- PAIRED TASK AGGREGATE STATS ---")
    balance = audit["pairing_balance"]
    if balance:
        all_bl_means = [v["bl_mean"] for v in balance.values()]
        all_mcp_means = [v["mcp_mean"] for v in balance.values()]
        overall_bl = statistics.mean(all_bl_means)
        overall_mcp = statistics.mean(all_mcp_means)
        overall_delta = overall_mcp - overall_bl

        sdlc_bl = [v["bl_mean"] for t, v in balance.items() if t in SDLC_TASKS]
        sdlc_mcp = [v["mcp_mean"] for t, v in balance.items() if t in SDLC_TASKS]
        org_bl = [v["bl_mean"] for t, v in balance.items() if t in ORG_TASKS]
        org_mcp = [v["mcp_mean"] for t, v in balance.items() if t in ORG_TASKS]

        print(f"  Overall (n={len(balance)}): BL={overall_bl:.4f}, MCP={overall_mcp:.4f}, delta={overall_delta:+.4f}")
        if sdlc_bl:
            print(f"  SDLC (n={len(sdlc_bl)}): BL={statistics.mean(sdlc_bl):.4f}, MCP={statistics.mean(sdlc_mcp):.4f}, delta={statistics.mean(sdlc_mcp)-statistics.mean(sdlc_bl):+.4f}")
        if org_bl:
            print(f"  Org (n={len(org_bl)}): BL={statistics.mean(org_bl):.4f}, MCP={statistics.mean(org_mcp):.4f}, delta={statistics.mean(org_mcp)-statistics.mean(org_bl):+.4f}")

    # Tasks where old-format data changes pairing
    print(f"\n--- OLD-FORMAT DATA IMPACT ---")
    old_only_tasks = set()
    for r in records:
        if r.get("dir_format") == "old" and r["task_name"] in TASK_META:
            old_only_tasks.add(r["task_name"])

    # Check which paired tasks have data ONLY from old-format
    tasks_needing_old = set()
    for task_name in audit["pairing_balance"]:
        task_records = [r for r in records if r["task_name"] == task_name]
        for config_type in ["baseline", "mcp"]:
            config_records = [r for r in task_records if r["config_type"] == config_type and r["reward"] is not None]
            if config_records and all(r.get("dir_format") == "old" for r in config_records):
                tasks_needing_old.add(task_name)

    print(f"  Tasks with any old-format data: {len(old_only_tasks)}")
    print(f"  Paired tasks where one side is ONLY old-format: {len(tasks_needing_old)}")
    if tasks_needing_old:
        for t in sorted(tasks_needing_old):
            task_records = [r for r in records if r["task_name"] == t]
            bl_fmt = set(r.get("dir_format") for r in task_records if r["config_type"] == "baseline" and r["reward"] is not None)
            mcp_fmt = set(r.get("dir_format") for r in task_records if r["config_type"] == "mcp" and r["reward"] is not None)
            print(f"    {t}: BL formats={bl_fmt}, MCP formats={mcp_fmt}")

    print(f"\n--- NULL REWARD SUMMARY ---")
    tasks_null = audit["tasks_with_null_rewards"]
    if tasks_null:
        total_null_bl = sum(v["baseline"] for v in tasks_null.values())
        total_null_mcp = sum(v["mcp"] for v in tasks_null.values())
        print(f"  Tasks with any null rewards: {len(tasks_null)}")
        print(f"  Total null BL rewards: {total_null_bl}")
        print(f"  Total null MCP rewards: {total_null_mcp}")
        # Show tasks with ALL rewards null on one side
        all_null = {t: v for t, v in tasks_null.items()
                    if (v["baseline"] == v["baseline_total"] and v["baseline_total"] > 0) or
                       (v["mcp"] == v["mcp_total"] and v["mcp_total"] > 0)}
        if all_null:
            print(f"\n  Tasks with ALL rewards null on one side ({len(all_null)}):")
            for t, v in sorted(all_null.items()):
                sides = []
                if v["baseline"] == v["baseline_total"] and v["baseline_total"] > 0:
                    sides.append(f"BL: {v['baseline']}/{v['baseline_total']} null")
                if v["mcp"] == v["mcp_total"] and v["mcp_total"] > 0:
                    sides.append(f"MCP: {v['mcp']}/{v['mcp_total']} null")
                print(f"    {t}: {', '.join(sides)}")

    print(f"\n{'='*70}")
    print("AUDIT COMPLETE")
    print(f"{'='*70}")

    # Write detailed JSON report
    report_path = ROOT / "runs" / "official" / "v2_report_audit.json"
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_records": len(records),
        "canonical_paired": audit["canonical_paired"],
        "sdlc_paired": audit["sdlc_paired"],
        "org_paired": audit["org_paired"],
        "missing_canonical": audit["missing_canonical"],
        "unpaired_canonical": audit["unpaired_canonical"],
        "suspicious": audit["suspicious"],
        "under_target_3": {t: v for t, v in audit["under_target_3"].items()},
        "tasks_needing_old_format": sorted(tasks_needing_old) if 'tasks_needing_old' in dir() else [],
        "pairing_balance": audit["pairing_balance"],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nDetailed report: {report_path}")


if __name__ == "__main__":
    main()

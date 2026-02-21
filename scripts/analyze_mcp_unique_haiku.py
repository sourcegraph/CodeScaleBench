#!/usr/bin/env python3
"""
Comprehensive trace analysis of MCP-unique Haiku runs in staging.

Analyzes runs at: runs/staging/ccb_mcp_*_haiku_20260221_140913/
Configs: baseline-local-artifact and mcp-remote-artifact

Outputs a formatted report covering:
1. Result extraction (rewards, tokens, timing)
2. Transcript MCP analysis (tool calls, errors)
3. Baseline transcript analysis
4. Comparative analysis (BL vs MCP)
5. Aggregate summary
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev

# -- Configuration --

STAGING_DIR = Path("/home/stephanie_jarmak/CodeContextBench/runs/staging")
RUN_SUFFIX = "_haiku_20260221_140913"
BASELINE_CONFIG = "baseline-local-artifact"
MCP_CONFIG = "mcp-remote-artifact"

# Deep Search tool names
DEEP_SEARCH_NAMES = {
    "mcp__sourcegraph__sg_deepsearch",
    "mcp__sourcegraph__sg_deepsearch_read",
    "mcp__sourcegraph__deepsearch",
    "mcp__sourcegraph__deepsearch_read",
}

# Standard local tools
LOCAL_TOOLS = {"Bash", "Read", "Write", "Edit", "Glob", "Grep"}
# Other non-MCP tools
OTHER_TOOLS = {"Task", "TaskOutput", "WebFetch", "WebSearch", "TodoWrite",
               "NotebookEdit", "Skill", "EnterPlanMode", "ExitPlanMode",
               "ToolSearch", "AskUserQuestion", "TaskStop"}


# -- Data Structures --

class TaskResult:
    def __init__(self):
        self.task_name = ""
        self.suite = ""
        self.config = ""
        self.reward = None
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.n_cache_tokens = 0
        self.started_at = None
        self.finished_at = None
        self.wall_duration_sec = 0
        self.agent_started_at = None
        self.agent_finished_at = None
        self.agent_duration_sec = 0
        self.exception_info = None
        self.result_path = ""
        self.transcript_path = ""
        # Transcript analysis
        self.mcp_tools_available = False
        self.mcp_tool_calls = Counter()
        self.local_tool_calls = Counter()
        self.other_tool_calls = Counter()
        self.deep_search_calls = 0
        self.total_mcp_calls = 0
        self.total_local_calls = 0
        self.total_other_calls = 0
        self.mcp_errors = []
        self.auth_errors = []
        self.transcript_exists = False
        self.transcript_lines = 0


# -- Parsing Functions --

def parse_datetime(dt_str):
    """Parse ISO datetime string."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def compute_duration_sec(start_str, end_str):
    """Compute duration in seconds between two ISO datetime strings."""
    start = parse_datetime(start_str)
    end = parse_datetime(end_str)
    if start and end:
        return (end - start).total_seconds()
    return 0


def extract_result(result_path):
    """Extract fields from result.json."""
    with open(result_path) as f:
        data = json.load(f)

    tr = TaskResult()
    tr.result_path = str(result_path)
    tr.task_name = data.get("task_name", "")

    # Reward
    vr = data.get("verifier_result", {})
    rewards = vr.get("rewards", {})
    tr.reward = rewards.get("reward", rewards.get("score", None))

    # Tokens
    ar = data.get("agent_result", {})
    tr.n_input_tokens = ar.get("n_input_tokens", 0) or 0
    tr.n_output_tokens = ar.get("n_output_tokens", 0) or 0
    tr.n_cache_tokens = ar.get("n_cache_tokens", 0) or 0

    # Timing
    tr.started_at = data.get("started_at")
    tr.finished_at = data.get("finished_at")
    tr.wall_duration_sec = compute_duration_sec(tr.started_at, tr.finished_at)

    agent_exec = data.get("agent_execution", {})
    tr.agent_started_at = agent_exec.get("started_at")
    tr.agent_finished_at = agent_exec.get("finished_at")
    tr.agent_duration_sec = compute_duration_sec(tr.agent_started_at, tr.agent_finished_at)

    # Exception
    tr.exception_info = data.get("exception_info")

    return tr


def parse_transcript(transcript_path, is_mcp_config):
    """Parse agent/claude-code.txt transcript for tool usage."""
    result = {
        "mcp_tools_available": False,
        "mcp_tool_calls": Counter(),
        "local_tool_calls": Counter(),
        "other_tool_calls": Counter(),
        "deep_search_calls": 0,
        "mcp_errors": [],
        "auth_errors": [],
        "exists": False,
        "lines": 0,
    }

    if not os.path.exists(transcript_path):
        return result

    result["exists"] = True

    try:
        with open(transcript_path, "r", errors="replace") as f:
            content = f.read()
    except Exception as e:
        result["mcp_errors"].append(f"Failed to read transcript: {e}")
        return result

    lines = content.split("\n")
    result["lines"] = len(lines)

    # Check init line for MCP tools
    if lines:
        init_line = lines[0]
        if "mcp__sourcegraph__" in init_line:
            result["mcp_tools_available"] = True
        if '"mcp_servers":[]' in init_line:
            result["mcp_tools_available"] = False

    # Parse each line for tool_use blocks
    for line in lines:
        if not line.strip():
            continue

        # Look for tool_use type entries
        if '"tool_use"' not in line:
            continue

        # Find positions of tool_use type markers
        for match in re.finditer(r'"type"\s*:\s*"tool_use"', line):
            pos = match.start()
            # Look for the name field near this position (within a reasonable window)
            search_region = line[pos:pos + 500]
            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', search_region)
            if name_match:
                tool_name = name_match.group(1)

                # Classify the tool
                if tool_name.startswith("mcp__sourcegraph__"):
                    result["mcp_tool_calls"][tool_name] += 1

                    # Check for deep search
                    if tool_name in DEEP_SEARCH_NAMES:
                        result["deep_search_calls"] += 1
                elif tool_name in LOCAL_TOOLS:
                    result["local_tool_calls"][tool_name] += 1
                elif tool_name in OTHER_TOOLS:
                    result["other_tool_calls"][tool_name] += 1

        # Check for MCP errors
        if "mcp" in line.lower() and ("error" in line.lower() or "fail" in line.lower()):
            if '"type":"result"' in line or '"type":"error"' in line:
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "error":
                        msg = obj.get("message", "")[:200]
                        if "mcp" in msg.lower() or "sourcegraph" in msg.lower():
                            result["mcp_errors"].append(msg)
                except (json.JSONDecodeError, KeyError):
                    pass

        # Check for auth errors
        if "auth" in line.lower() and ("error" in line.lower() or "fail" in line.lower() or "denied" in line.lower()):
            try:
                obj = json.loads(line)
                if obj.get("type") == "error":
                    msg = obj.get("message", "")[:200]
                    result["auth_errors"].append(msg)
            except (json.JSONDecodeError, KeyError):
                pass

    return result


# -- Discovery --

def discover_runs():
    """Find all MCP-unique Haiku runs from the target timestamp."""
    runs = []
    for entry in sorted(STAGING_DIR.iterdir()):
        if entry.is_dir() and entry.name.startswith("ccb_mcp_") and entry.name.endswith(RUN_SUFFIX):
            runs.append(entry)
    return runs


def discover_tasks(run_dir, config_name):
    """Find all task directories under a given run/config."""
    config_dir = run_dir / config_name
    if not config_dir.exists():
        return []

    tasks = []
    for batch_dir in sorted(config_dir.iterdir()):
        if not batch_dir.is_dir():
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$", batch_dir.name):
            continue
        for task_dir in sorted(batch_dir.iterdir()):
            if task_dir.is_dir() and "__" in task_dir.name:
                result_file = task_dir / "result.json"
                transcript_file = task_dir / "agent" / "claude-code.txt"
                if result_file.exists():
                    tasks.append({
                        "dir": task_dir,
                        "result_path": result_file,
                        "transcript_path": transcript_file,
                    })
    return tasks


def extract_suite_name(run_dir_name):
    """Extract suite name from run directory name."""
    m = re.match(r"ccb_mcp_(.+?)_haiku_\d+_\d+", run_dir_name)
    if m:
        return m.group(1)
    return run_dir_name


# -- Main Analysis --

def main():
    runs = discover_runs()
    if not runs:
        print("ERROR: No matching runs found in staging.")
        sys.exit(1)

    print("=" * 100)
    print("COMPREHENSIVE TRACE ANALYSIS: MCP-UNIQUE HAIKU RUNS (20260221_140913)")
    print("=" * 100)
    print()

    # Collect all task results
    all_results = []
    by_config = defaultdict(list)
    by_task = defaultdict(dict)
    by_suite = defaultdict(lambda: defaultdict(list))

    for run_dir in runs:
        suite = extract_suite_name(run_dir.name)

        for config_name in [BASELINE_CONFIG, MCP_CONFIG]:
            tasks = discover_tasks(run_dir, config_name)
            is_mcp = config_name == MCP_CONFIG

            for task_info in tasks:
                try:
                    tr = extract_result(task_info["result_path"])
                except Exception as e:
                    print(f"  WARNING: Failed to parse {task_info['result_path']}: {e}")
                    continue

                tr.config = config_name
                tr.suite = suite

                tr.transcript_path = str(task_info["transcript_path"])

                # Parse transcript
                tx = parse_transcript(str(task_info["transcript_path"]), is_mcp)
                tr.mcp_tools_available = tx["mcp_tools_available"]
                tr.mcp_tool_calls = tx["mcp_tool_calls"]
                tr.local_tool_calls = tx["local_tool_calls"]
                tr.other_tool_calls = tx["other_tool_calls"]
                tr.deep_search_calls = tx["deep_search_calls"]
                tr.total_mcp_calls = sum(tx["mcp_tool_calls"].values())
                tr.total_local_calls = sum(tx["local_tool_calls"].values())
                tr.total_other_calls = sum(tx["other_tool_calls"].values())
                tr.mcp_errors = tx["mcp_errors"]
                tr.auth_errors = tx["auth_errors"]
                tr.transcript_exists = tx["exists"]
                tr.transcript_lines = tx["lines"]

                all_results.append(tr)
                by_config[config_name].append(tr)
                by_task[tr.task_name][config_name] = tr
                by_suite[suite][config_name].append(tr)

    total_tasks = len(all_results)
    total_unique = len(by_task)

    print(f"Discovered {len(runs)} run directories, {total_tasks} task results ({total_unique} unique tasks)")
    print(f"Configs: {BASELINE_CONFIG} ({len(by_config[BASELINE_CONFIG])} tasks), "
          f"{MCP_CONFIG} ({len(by_config[MCP_CONFIG])} tasks)")
    print()

    # ====================================================================
    # SECTION 1: RESULT EXTRACTION
    # ====================================================================

    print("=" * 100)
    print("SECTION 1: RESULT EXTRACTION (Per-Task Details)")
    print("=" * 100)
    print()

    for suite in sorted(by_suite.keys()):
        print(f"--- Suite: {suite} ---")
        suite_tasks = set()
        for config_name in [BASELINE_CONFIG, MCP_CONFIG]:
            for tr in by_suite[suite][config_name]:
                suite_tasks.add(tr.task_name)

        for task_name in sorted(suite_tasks):
            for config_name in [BASELINE_CONFIG, MCP_CONFIG]:
                if task_name in by_task and config_name in by_task[task_name]:
                    tr = by_task[task_name][config_name]
                    config_label = "BL" if config_name == BASELINE_CONFIG else "MCP"
                    exc = "None" if tr.exception_info is None else str(tr.exception_info)[:80]
                    print(f"  {task_name} [{config_label}]:")
                    print(f"    Reward:       {tr.reward}")
                    print(f"    Tokens:       in={tr.n_input_tokens:,}  out={tr.n_output_tokens:,}  cache={tr.n_cache_tokens:,}")
                    print(f"    Wall time:    {tr.wall_duration_sec:.1f}s")
                    print(f"    Agent time:   {tr.agent_duration_sec:.1f}s")
                    print(f"    Exception:    {exc}")
            print()

    # ====================================================================
    # SECTION 2: MCP TRANSCRIPT ANALYSIS
    # ====================================================================

    print("=" * 100)
    print("SECTION 2: MCP CONFIG TRANSCRIPT ANALYSIS")
    print("=" * 100)
    print()

    mcp_results = by_config[MCP_CONFIG]
    for tr in sorted(mcp_results, key=lambda x: (x.suite, x.task_name)):
        print(f"  {tr.task_name} (suite: {tr.suite}):")
        print(f"    Transcript exists:    {tr.transcript_exists} ({tr.transcript_lines} lines)")
        print(f"    MCP tools available:  {tr.mcp_tools_available}")
        print(f"    MCP tool calls:       {tr.total_mcp_calls}")
        if tr.mcp_tool_calls:
            for tool, count in tr.mcp_tool_calls.most_common():
                short_name = tool.replace("mcp__sourcegraph__", "")
                print(f"      {short_name}: {count}")
        print(f"    Deep Search calls:    {tr.deep_search_calls}")
        print(f"    Local tool calls:     {tr.total_local_calls}")
        if tr.local_tool_calls:
            for tool, count in tr.local_tool_calls.most_common():
                print(f"      {tool}: {count}")
        print(f"    Other tool calls:     {tr.total_other_calls}")
        if tr.other_tool_calls:
            for tool, count in tr.other_tool_calls.most_common():
                print(f"      {tool}: {count}")
        if tr.mcp_errors:
            print(f"    MCP errors ({len(tr.mcp_errors)}):")
            for err in tr.mcp_errors[:5]:
                print(f"      - {err}")
        if tr.auth_errors:
            print(f"    Auth errors ({len(tr.auth_errors)}):")
            for err in tr.auth_errors[:5]:
                print(f"      - {err}")
        print()

    # ====================================================================
    # SECTION 3: BASELINE TRANSCRIPT ANALYSIS
    # ====================================================================

    print("=" * 100)
    print("SECTION 3: BASELINE TRANSCRIPT ANALYSIS")
    print("=" * 100)
    print()

    bl_results = by_config[BASELINE_CONFIG]
    any_bl_mcp = False
    for tr in sorted(bl_results, key=lambda x: (x.suite, x.task_name)):
        print(f"  {tr.task_name} (suite: {tr.suite}):")
        print(f"    Transcript exists:    {tr.transcript_exists} ({tr.transcript_lines} lines)")
        print(f"    Local tool calls:     {tr.total_local_calls}")
        if tr.local_tool_calls:
            for tool, count in tr.local_tool_calls.most_common():
                print(f"      {tool}: {count}")
        print(f"    Other tool calls:     {tr.total_other_calls}")
        if tr.other_tool_calls:
            for tool, count in tr.other_tool_calls.most_common():
                print(f"      {tool}: {count}")
        if tr.mcp_tools_available:
            print(f"    WARNING: MCP tools available in baseline!")
            any_bl_mcp = True
        if tr.total_mcp_calls > 0:
            print(f"    WARNING: MCP tools USED in baseline! ({tr.total_mcp_calls} calls)")
            any_bl_mcp = True
        print()

    if not any_bl_mcp:
        print("  >> No baseline tasks had MCP tools available or used. (Clean separation confirmed.)")
        print()

    # ====================================================================
    # SECTION 4: COMPARATIVE ANALYSIS
    # ====================================================================

    print("=" * 100)
    print("SECTION 4: COMPARATIVE ANALYSIS (Baseline vs MCP)")
    print("=" * 100)
    print()

    # Header
    print(f"  {'Task':<30} {'BL Rew':>7} {'MCP Rew':>8} {'Delta':>7} {'BL AgSec':>9} {'MCP AgSec':>10} "
          f"{'BL OutTok':>10} {'MCP OutTok':>11} {'MCP Calls':>10}")
    print(f"  {'-'*29} {'-'*7} {'-'*8} {'-'*7} {'-'*9} {'-'*10} {'-'*10} {'-'*11} {'-'*10}")

    improved = []
    worsened = []
    equal = []

    for task_name in sorted(by_task.keys()):
        bl = by_task[task_name].get(BASELINE_CONFIG)
        mcp = by_task[task_name].get(MCP_CONFIG)

        if bl and mcp and bl.reward is not None and mcp.reward is not None:
            delta = mcp.reward - bl.reward
            print(f"  {task_name:<30} {bl.reward:>7.3f} {mcp.reward:>8.3f} {delta:>+7.3f} "
                  f"{bl.agent_duration_sec:>9.1f} {mcp.agent_duration_sec:>10.1f} "
                  f"{bl.n_output_tokens:>10,} {mcp.n_output_tokens:>11,} {mcp.total_mcp_calls:>10}")

            if delta > 0.001:
                improved.append((task_name, delta))
            elif delta < -0.001:
                worsened.append((task_name, delta))
            else:
                equal.append(task_name)
        elif bl and not mcp:
            bl_r = bl.reward if bl.reward is not None else "N/A"
            print(f"  {task_name:<30} {bl_r:>7} {'MISSING':>8}")
        elif mcp and not bl:
            mcp_r = mcp.reward if mcp.reward is not None else "N/A"
            print(f"  {task_name:<30} {'MISSING':>7} {mcp_r:>8}")

    print()

    # Token efficiency
    print("  Token Efficiency (output tokens per unit reward, lower = better):")
    print(f"  {'Task':<30} {'BL tok/rew':>12} {'MCP tok/rew':>13} {'Notes'}")
    print(f"  {'-'*29} {'-'*12} {'-'*13} {'-'*30}")
    for task_name in sorted(by_task.keys()):
        bl = by_task[task_name].get(BASELINE_CONFIG)
        mcp = by_task[task_name].get(MCP_CONFIG)
        bl_eff = ""
        mcp_eff = ""
        notes = ""
        if bl and bl.reward and bl.reward > 0:
            bl_eff = f"{bl.n_output_tokens / bl.reward:,.0f}"
        elif bl:
            bl_eff = "inf"
            notes = "BL=0 reward"
        if mcp and mcp.reward and mcp.reward > 0:
            mcp_eff = f"{mcp.n_output_tokens / mcp.reward:,.0f}"
        elif mcp:
            mcp_eff = "inf"
            notes += " MCP=0 reward"
        print(f"  {task_name:<30} {bl_eff:>12} {mcp_eff:>13} {notes}")
    print()

    # Time efficiency
    print("  Time Efficiency (agent seconds per unit reward, lower = better):")
    print(f"  {'Task':<30} {'BL sec/rew':>12} {'MCP sec/rew':>13}")
    print(f"  {'-'*29} {'-'*12} {'-'*13}")
    for task_name in sorted(by_task.keys()):
        bl = by_task[task_name].get(BASELINE_CONFIG)
        mcp = by_task[task_name].get(MCP_CONFIG)
        bl_eff = ""
        mcp_eff = ""
        if bl and bl.reward and bl.reward > 0:
            bl_eff = f"{bl.agent_duration_sec / bl.reward:.1f}"
        elif bl:
            bl_eff = "inf"
        if mcp and mcp.reward and mcp.reward > 0:
            mcp_eff = f"{mcp.agent_duration_sec / mcp.reward:.1f}"
        elif mcp:
            mcp_eff = "inf"
        print(f"  {task_name:<30} {bl_eff:>12} {mcp_eff:>13}")
    print()

    # Summary of improvements/regressions
    print("  IMPROVED tasks (MCP > Baseline):")
    if improved:
        for task_name, delta in sorted(improved, key=lambda x: -x[1]):
            print(f"    {task_name}: +{delta:.3f}")
    else:
        print("    (none)")
    print()

    print("  WORSENED tasks (MCP < Baseline):")
    if worsened:
        for task_name, delta in sorted(worsened, key=lambda x: x[1]):
            print(f"    {task_name}: {delta:.3f}")
    else:
        print("    (none)")
    print()

    print("  EQUAL tasks (MCP == Baseline):")
    if equal:
        for task_name in sorted(equal):
            bl_r = by_task[task_name].get(BASELINE_CONFIG)
            if bl_r and bl_r.reward is not None:
                print(f"    {task_name}: {bl_r.reward:.3f}")
            else:
                print(f"    {task_name}")
    else:
        print("    (none)")
    print()

    # ====================================================================
    # SECTION 5: AGGREGATE SUMMARY
    # ====================================================================

    print("=" * 100)
    print("SECTION 5: AGGREGATE SUMMARY")
    print("=" * 100)
    print()

    # Per-config aggregates
    for config_name, label in [(BASELINE_CONFIG, "BASELINE"), (MCP_CONFIG, "MCP")]:
        results = by_config[config_name]
        rewards = [tr.reward for tr in results if tr.reward is not None]
        agent_times = [tr.agent_duration_sec for tr in results]
        wall_times = [tr.wall_duration_sec for tr in results]
        input_toks = [tr.n_input_tokens for tr in results]
        output_toks = [tr.n_output_tokens for tr in results]
        cache_toks = [tr.n_cache_tokens for tr in results]

        print(f"  {label} ({len(results)} tasks):")
        if rewards:
            sd = f"  stdev={stdev(rewards):.3f}" if len(rewards) > 1 else ""
            print(f"    Reward:      mean={mean(rewards):.3f}  median={median(rewards):.3f}  "
                  f"min={min(rewards):.3f}  max={max(rewards):.3f}{sd}")
        if input_toks:
            print(f"    Input tok:   mean={mean(input_toks):,.0f}  median={median(input_toks):,.0f}  "
                  f"total={sum(input_toks):,}")
        if output_toks:
            print(f"    Output tok:  mean={mean(output_toks):,.0f}  median={median(output_toks):,.0f}  "
                  f"total={sum(output_toks):,}")
        if cache_toks:
            print(f"    Cache tok:   mean={mean(cache_toks):,.0f}  median={median(cache_toks):,.0f}  "
                  f"total={sum(cache_toks):,}")
        if agent_times:
            print(f"    Agent time:  mean={mean(agent_times):.1f}s  median={median(agent_times):.1f}s  "
                  f"total={sum(agent_times):.1f}s")
        if wall_times:
            print(f"    Wall time:   mean={mean(wall_times):.1f}s  median={median(wall_times):.1f}s  "
                  f"total={sum(wall_times):.1f}s")
        print()

    # Per-suite breakdown
    print("  PER-SUITE REWARD BREAKDOWN:")
    print(f"  {'Suite':<25} {'BL N':>5} {'BL Mean':>8} {'MCP N':>6} {'MCP Mean':>9} {'Delta':>7}")
    print(f"  {'-'*24} {'-'*5} {'-'*8} {'-'*6} {'-'*9} {'-'*7}")
    for suite in sorted(by_suite.keys()):
        bl_rewards = [tr.reward for tr in by_suite[suite].get(BASELINE_CONFIG, []) if tr.reward is not None]
        mcp_rewards = [tr.reward for tr in by_suite[suite].get(MCP_CONFIG, []) if tr.reward is not None]
        bl_mean = mean(bl_rewards) if bl_rewards else 0
        mcp_mean = mean(mcp_rewards) if mcp_rewards else 0
        delta = mcp_mean - bl_mean
        print(f"  {suite:<25} {len(bl_rewards):>5} {bl_mean:>8.3f} {len(mcp_rewards):>6} {mcp_mean:>9.3f} {delta:>+7.3f}")
    print()

    # MCP tool distribution
    print("  MCP TOOL DISTRIBUTION (across all MCP config tasks):")
    global_mcp_tools = Counter()
    total_ds = 0
    mcp_adopters = 0
    mcp_non_adopters = 0
    for tr in mcp_results:
        global_mcp_tools += tr.mcp_tool_calls
        total_ds += tr.deep_search_calls
        if tr.total_mcp_calls > 0:
            mcp_adopters += 1
        else:
            mcp_non_adopters += 1

    total_mcp = sum(global_mcp_tools.values())
    print(f"    Total MCP tool calls: {total_mcp}")
    print(f"    Deep Search calls:    {total_ds}")
    mcp_rate = 100 * mcp_adopters / len(mcp_results) if mcp_results else 0
    print(f"    MCP adopters:         {mcp_adopters}/{len(mcp_results)} tasks ({mcp_rate:.0f}%)")
    print(f"    MCP non-adopters:     {mcp_non_adopters}/{len(mcp_results)} tasks")
    print()
    if global_mcp_tools:
        print(f"    {'Tool':<45} {'Count':>6} {'Pct':>6}")
        print(f"    {'-'*44} {'-'*6} {'-'*6}")
        for tool, count in global_mcp_tools.most_common():
            short = tool.replace("mcp__sourcegraph__", "")
            pct = 100 * count / total_mcp if total_mcp else 0
            print(f"    {short:<45} {count:>6} {pct:>5.1f}%")
    print()

    # Local tool distribution comparison
    print("  LOCAL TOOL DISTRIBUTION COMPARISON:")
    bl_local = Counter()
    mcp_local = Counter()
    for tr in bl_results:
        bl_local += tr.local_tool_calls
    for tr in mcp_results:
        mcp_local += tr.local_tool_calls

    all_local_tools = sorted(set(bl_local.keys()) | set(mcp_local.keys()))
    print(f"    {'Tool':<15} {'BL Count':>10} {'MCP Count':>10} {'Delta':>8}")
    print(f"    {'-'*14} {'-'*10} {'-'*10} {'-'*8}")
    for tool in all_local_tools:
        bl_c = bl_local.get(tool, 0)
        mcp_c = mcp_local.get(tool, 0)
        delta = mcp_c - bl_c
        print(f"    {tool:<15} {bl_c:>10} {mcp_c:>10} {delta:>+8}")
    print(f"    {'TOTAL':<15} {sum(bl_local.values()):>10} {sum(mcp_local.values()):>10} "
          f"{sum(mcp_local.values()) - sum(bl_local.values()):>+8}")
    print()

    # Anomalies
    print("  ANOMALIES:")
    anomalies = []
    for tr in all_results:
        config_label = "BL" if tr.config == BASELINE_CONFIG else "MCP"
        if tr.reward is not None and tr.reward == 0:
            anomalies.append(f"    ZERO REWARD: {tr.task_name} [{config_label}]")
        if tr.n_output_tokens == 0:
            anomalies.append(f"    ZERO OUTPUT TOKENS: {tr.task_name} [{config_label}]")
        if not tr.transcript_exists:
            anomalies.append(f"    MISSING TRANSCRIPT: {tr.task_name} [{config_label}]")
        if tr.exception_info is not None:
            anomalies.append(f"    EXCEPTION: {tr.task_name} [{config_label}]: {str(tr.exception_info)[:100]}")
        if tr.config == MCP_CONFIG and tr.mcp_tools_available and tr.total_mcp_calls == 0:
            anomalies.append(f"    MCP_NEVER_USED: {tr.task_name} (tools available but 0 calls)")
        if tr.config == BASELINE_CONFIG and tr.total_mcp_calls > 0:
            anomalies.append(f"    BL_MCP_CONTAMINATION: {tr.task_name} ({tr.total_mcp_calls} MCP calls in baseline)")

    if anomalies:
        for a in sorted(anomalies):
            print(a)
    else:
        print("    (no anomalies detected)")
    print()

    # ====================================================================
    # OVERALL VERDICT
    # ====================================================================

    print("=" * 100)
    print("OVERALL VERDICT")
    print("=" * 100)
    print()

    bl_rewards_all = [tr.reward for tr in by_config[BASELINE_CONFIG] if tr.reward is not None]
    mcp_rewards_all = [tr.reward for tr in by_config[MCP_CONFIG] if tr.reward is not None]

    bl_mean_all = mean(bl_rewards_all) if bl_rewards_all else 0
    mcp_mean_all = mean(mcp_rewards_all) if mcp_rewards_all else 0
    overall_delta = mcp_mean_all - bl_mean_all

    print(f"  Baseline mean reward:  {bl_mean_all:.3f} (n={len(bl_rewards_all)})")
    print(f"  MCP mean reward:       {mcp_mean_all:.3f} (n={len(mcp_rewards_all)})")
    print(f"  Overall delta:         {overall_delta:+.3f}")
    print(f"  Tasks improved by MCP: {len(improved)}")
    print(f"  Tasks worsened by MCP: {len(worsened)}")
    print(f"  Tasks equal:           {len(equal)}")
    mcp_adopt_rate = 100 * mcp_adopters / len(mcp_results) if mcp_results else 0
    print(f"  MCP adoption rate:     {mcp_adopters}/{len(mcp_results)} ({mcp_adopt_rate:.0f}%)")
    print(f"  Total MCP tool calls:  {total_mcp}")
    print(f"  Deep Search calls:     {total_ds}")
    print()

    # Matched-pair analysis
    matched_bl = []
    matched_mcp = []
    for task_name in sorted(by_task.keys()):
        bl = by_task[task_name].get(BASELINE_CONFIG)
        mcp = by_task[task_name].get(MCP_CONFIG)
        if bl and mcp and bl.reward is not None and mcp.reward is not None:
            matched_bl.append(bl.reward)
            matched_mcp.append(mcp.reward)

    if matched_bl:
        deltas = [m - b for b, m in zip(matched_bl, matched_mcp)]
        print(f"  Matched-pair analysis ({len(matched_bl)} tasks with both configs):")
        print(f"    BL mean:     {mean(matched_bl):.3f}")
        print(f"    MCP mean:    {mean(matched_mcp):.3f}")
        print(f"    Mean delta:  {mean(deltas):+.3f}")
        if len(deltas) > 1:
            print(f"    Delta stdev: {stdev(deltas):.3f}")
        print()


if __name__ == "__main__":
    main()

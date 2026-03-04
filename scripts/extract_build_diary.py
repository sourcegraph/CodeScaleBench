#!/usr/bin/env python3
"""
Extract structured build-diary data from Claude Code conversation transcripts.

Parses all JSONL session files and produces:
  - build_diary_daily.csv   (per-day aggregates)
  - build_diary_sessions.csv (per-session summaries)
  - build_diary_milestones.json (annotated milestone events from git)

Usage:
    python3 scripts/extract_build_diary.py [--transcript-dir DIR] [--output-dir DIR]
"""

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict


# ── Tool categories for the "construction metaphor" visualization ──────────
TOOL_CATEGORIES = {
    "Explore": ["Read", "Grep", "Glob", "WebFetch", "WebSearch"],
    "Build":   ["Edit", "Write", "NotebookEdit"],
    "Execute": ["Bash", "TaskOutput", "TaskStop"],
    "Coordinate": ["Agent", "AskUserQuestion", "Skill",
                    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet",
                    "TodoWrite", "EnterPlanMode", "ExitPlanMode"],
    "MCP":     [],  # populated dynamically for mcp__* tools
}


def categorize_tool(name: str) -> str:
    if name.startswith("mcp__"):
        return "MCP"
    for cat, tools in TOOL_CATEGORIES.items():
        if name in tools:
            return cat
    return "Other"


def parse_transcripts(transcript_dir: str):
    """Parse all JSONL transcripts and return per-session and per-day data."""
    files = sorted(glob.glob(os.path.join(transcript_dir, "*.jsonl")))
    if not files:
        print(f"No .jsonl files found in {transcript_dir}", file=sys.stderr)
        sys.exit(1)

    sessions = []
    daily = defaultdict(lambda: {
        "sessions": 0,
        "user_msgs": 0,
        "assistant_msgs": 0,
        "tool_calls": Counter(),
        "tool_categories": Counter(),
        "files_read": set(),
        "files_edited": set(),
        "skills_used": Counter(),
        "errors": 0,
    })

    for i, fpath in enumerate(files):
        if (i + 1) % 100 == 0:
            print(f"  parsing {i+1}/{len(files)}...", file=sys.stderr)

        session_id = os.path.basename(fpath).replace(".jsonl", "")
        timestamps = []
        user_msgs = 0
        assistant_msgs = 0
        tool_calls = Counter()
        tool_categories = Counter()
        files_read = set()
        files_edited = set()
        skills = Counter()
        errors = 0
        user_text_chars = 0

        with open(fpath) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                if ts:
                    timestamps.append(ts)

                msg_type = obj.get("type", "")

                if msg_type == "user":
                    user_msgs += 1
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, str):
                        user_text_chars += len(content)

                elif msg_type == "assistant":
                    assistant_msgs += 1
                    content = obj.get("message", {}).get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                name = block.get("name", "unknown")
                                tool_calls[name] += 1
                                cat = categorize_tool(name)
                                tool_categories[cat] += 1

                                inp = block.get("input", {})
                                fp = inp.get("file_path", "")
                                if fp:
                                    fp = re.sub(
                                        r"^/home/stephanie_jarmak/CodeScaleBench/",
                                        "", fp,
                                    )
                                    if name == "Read":
                                        files_read.add(fp)
                                    elif name in ("Edit", "Write"):
                                        files_edited.add(fp)
                                if name == "Skill":
                                    skills[inp.get("skill", "?")] += 1

                elif msg_type == "tool_result":
                    # Count errors from tool results
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("is_error"):
                                errors += 1
                    elif isinstance(content, str) and content.startswith("<error>"):
                        errors += 1

        if not timestamps:
            continue

        first_ts = min(timestamps)
        last_ts = max(timestamps)
        day = first_ts[:10]

        # Session record
        sessions.append({
            "session_id": session_id,
            "date": day,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "user_msgs": user_msgs,
            "assistant_msgs": assistant_msgs,
            "total_msgs": user_msgs + assistant_msgs,
            "tool_calls_total": sum(tool_calls.values()),
            "cat_explore": tool_categories.get("Explore", 0),
            "cat_build": tool_categories.get("Build", 0),
            "cat_execute": tool_categories.get("Execute", 0),
            "cat_coordinate": tool_categories.get("Coordinate", 0),
            "cat_mcp": tool_categories.get("MCP", 0),
            "files_read": len(files_read),
            "files_edited": len(files_edited),
            "errors": errors,
            "user_text_chars": user_text_chars,
        })

        # Accumulate daily
        d = daily[day]
        d["sessions"] += 1
        d["user_msgs"] += user_msgs
        d["assistant_msgs"] += assistant_msgs
        d["tool_calls"] += tool_calls
        d["tool_categories"] += tool_categories
        d["files_read"] |= files_read
        d["files_edited"] |= files_edited
        d["skills_used"] += skills
        d["errors"] += errors

    return sessions, daily


def get_git_milestones(repo_dir: str) -> list[dict]:
    """Extract key milestones from git log, dedup to ~1 per day."""
    result = subprocess.run(
        ["git", "-C", repo_dir, "log", "--oneline",
         "--since=2026-01-31", "--until=2026-03-03",
         "--format=%ad|%s", "--date=short"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []

    # Key phrases that indicate milestones worth annotating
    milestone_keywords = [
        ("Initial commit", "Project created"),
        ("rename all benchmark suites to ccb_", "Suites renamed to ccb_*"),
        ("add SDLC-stratified task selection", "SDLC task selection"),
        ("enable subscription mode", "OAuth token auth"),
        ("Scaffold ccb_codereview", "Code review suite added"),
        ("archive DependEval", "DependEval archived"),
        ("[US-022]", "Difficulty calibration done"),
        ("add per-suite 3-config runners", "3-config runners"),
        ("Dashboard data curation", "Mirror mapping created"),
        ("pin all Sourcegraph repo names", "SG repos pinned"),
        ("rename MCP modes", "Config model: baseline + SG_full"),
        ("ccb_feature/ccb_refactor split", "Build suite split"),
        ("normalize all benchmark suites to 20 tasks", "20 tasks/suite target"),
        ("generate_sgonly_dockerfiles", "SG-only Dockerfiles"),
        ("HARBOR_ENV passthrough", "Daytona support added"),
        ("curate oracle_answer.json for all 130", "130 oracle answers"),
        ("DOE-driven SDLC task rebalance", "DOE rebalance (SDLC)"),
        ("DOE-driven MCP-unique rebalance", "DOE rebalance (MCP)"),
        ("Daytona 125-parallel auto-detect", "124-sandbox parallelism"),
        ("promote 80 partial runs", "80 runs promoted"),
        ("archive broken batches", "Broken runs archived"),
        ("security oracle", "Security oracle fix"),
        ("variance gap", "Variance gap closing"),
        ("SDLC variance 150/150", "SDLC variance complete"),
        ("ContextBench cross-validation", "ContextBench calibration"),
        ("redesign context retrieval agent", "Curator agent v2"),
    ]

    commits_by_day = defaultdict(list)
    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue
        date, msg = line.split("|", 1)
        commits_by_day[date.strip()].append(msg.strip())

    milestones = []
    used_dates = set()
    for keyword, label in milestone_keywords:
        for date, msgs in commits_by_day.items():
            for msg in msgs:
                if keyword.lower() in msg.lower() and date not in used_dates:
                    milestones.append({
                        "date": date,
                        "label": label,
                        "commit_msg": msg,
                    })
                    used_dates.add(date)
                    break

    # Also count commits per day
    commit_counts = {d: len(msgs) for d, msgs in commits_by_day.items()}

    return sorted(milestones, key=lambda m: m["date"]), commit_counts


def write_outputs(sessions, daily, milestones, commit_counts, output_dir):
    """Write CSV and JSON output files."""
    os.makedirs(output_dir, exist_ok=True)

    # 1. Per-session CSV
    session_path = os.path.join(output_dir, "build_diary_sessions.csv")
    fieldnames = list(sessions[0].keys()) if sessions else []
    with open(session_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted(sessions, key=lambda s: s["first_ts"]))
    print(f"Wrote {len(sessions)} sessions to {session_path}")

    # 2. Per-day CSV
    daily_path = os.path.join(output_dir, "build_diary_daily.csv")
    daily_rows = []
    for day in sorted(daily.keys()):
        d = daily[day]
        daily_rows.append({
            "date": day,
            "sessions": d["sessions"],
            "user_msgs": d["user_msgs"],
            "assistant_msgs": d["assistant_msgs"],
            "total_msgs": d["user_msgs"] + d["assistant_msgs"],
            "tool_calls": sum(d["tool_calls"].values()),
            "cat_explore": d["tool_categories"].get("Explore", 0),
            "cat_build": d["tool_categories"].get("Build", 0),
            "cat_execute": d["tool_categories"].get("Execute", 0),
            "cat_coordinate": d["tool_categories"].get("Coordinate", 0),
            "cat_mcp": d["tool_categories"].get("MCP", 0),
            "files_read": len(d["files_read"]),
            "files_edited": len(d["files_edited"]),
            "errors": d["errors"],
            "commits": commit_counts.get(day, 0),
            "human_ratio": (
                d["user_msgs"] / (d["user_msgs"] + d["assistant_msgs"])
                if (d["user_msgs"] + d["assistant_msgs"]) > 0 else 0
            ),
        })
    with open(daily_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(daily_rows[0].keys()))
        writer.writeheader()
        writer.writerows(daily_rows)
    print(f"Wrote {len(daily_rows)} days to {daily_path}")

    # 3. Milestones JSON
    ms_path = os.path.join(output_dir, "build_diary_milestones.json")
    with open(ms_path, "w") as f:
        json.dump(milestones, f, indent=2)
    print(f"Wrote {len(milestones)} milestones to {ms_path}")

    # 4. Summary stats JSON
    summary = {
        "total_sessions": len(sessions),
        "total_days": len(daily),
        "date_range": [min(daily.keys()), max(daily.keys())],
        "total_user_msgs": sum(s["user_msgs"] for s in sessions),
        "total_assistant_msgs": sum(s["assistant_msgs"] for s in sessions),
        "total_tool_calls": sum(s["tool_calls_total"] for s in sessions),
        "total_files_read": len(set().union(*(daily[d]["files_read"] for d in daily))),
        "total_files_edited": len(set().union(*(daily[d]["files_edited"] for d in daily))),
        "median_session_msgs": sorted(s["total_msgs"] for s in sessions)[len(sessions) // 2],
        "max_session_msgs": max(s["total_msgs"] for s in sessions),
        "tool_category_totals": {
            cat: sum(daily[d]["tool_categories"].get(cat, 0) for d in daily)
            for cat in ["Explore", "Build", "Execute", "Coordinate", "MCP"]
        },
    }
    summary_path = os.path.join(output_dir, "build_diary_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote summary to {summary_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript-dir",
        default=os.path.expanduser(
            "~/.claude/projects/-home-stephanie-jarmak-CodeScaleBench/"
        ),
    )
    parser.add_argument("--output-dir", default="data/build_diary")
    parser.add_argument(
        "--repo-dir",
        default=os.path.expanduser("~/CodeContextBench"),
    )
    args = parser.parse_args()

    print(f"Parsing transcripts from {args.transcript_dir}...")
    sessions, daily = parse_transcripts(args.transcript_dir)

    print("Extracting git milestones...")
    milestones, commit_counts = get_git_milestones(args.repo_dir)

    print(f"Writing outputs to {args.output_dir}/...")
    write_outputs(sessions, daily, milestones, commit_counts, args.output_dir)
    print("Done.")


if __name__ == "__main__":
    main()

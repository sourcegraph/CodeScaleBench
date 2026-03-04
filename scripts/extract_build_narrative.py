#!/usr/bin/env python3
"""
Extract the narrative arc of building CodeScaleBench from conversation transcripts
and git history. Focuses on WHAT was discussed and decided, not tool mechanics.

Produces:
  - build_narrative_topics.csv     (per-day topic intensity heatmap data)
  - build_narrative_phases.csv     (per-day commit arc classification)
  - build_narrative_decisions.json (curated decision points with context)
  - build_narrative_rework.csv     (fix-follows-feat rework patterns)

Usage:
    python3 scripts/extract_build_narrative.py
"""

import csv
import glob
import json
import os
import subprocess
from collections import Counter, defaultdict

# ── Topic keywords for conversation classification ────────────────────────
TOPIC_KEYWORDS = {
    "Task selection\n& curation": [
        "task", "tasks", "benchmark", "suite", "include", "exclude",
        "selection", "curate", "scope", "how many", "which tasks",
        "remove task", "add task", "difficulty", "calibrat",
    ],
    "Scoring &\nevaluation": [
        "score", "scoring", "reward", "evaluate", "verifier", "oracle",
        "ground truth", "false positive", "f1", "precision", "recall",
        "metric", "test.sh", "pass", "fail",
    ],
    "Infrastructure\n& containers": [
        "docker", "dockerfile", "container", "build fail", "image",
        "workspace", "root user", "permission", "chown", "environment",
        "copy", "apt-get", "base image",
    ],
    "MCP & code\nsearch design": [
        "mcp", "sourcegraph", "deep search", "code search",
        "context", "retrieval", "sg_full", "sg_only", "truncat",
        "preamble", "tool server", "mirror",
    ],
    "Execution\n& scaling": [
        "run", "launch", "batch", "promote", "staging", "official",
        "rerun", "status", "monitor", "parallel", "daytona", "sandbox",
        "harbor",
    ],
    "Statistical\ndesign": [
        "variance", "doe", "rebalance", "power", "sample size",
        "statistical", "neyman", "paired", "delta", "confidence",
    ],
    "Writing &\nreporting": [
        "paper", "blog", "report", "white paper", "write up",
        "describe", "explain", "document", "methodology", "figure",
        "table",
    ],
    "Agent prompt\nengineering": [
        "agent", "preamble", "prompt", "system prompt", "instruction",
        "claude_baseline", "v3", "v4", "v5", "truncation warning",
    ],
}

# ── Commit narrative arc classification ───────────────────────────────────
COMMIT_ARCS = {
    "Task Design": [
        "scaffold", "benchmark suite", "curate", "oracle", "ground truth",
        "difficulty", "calibrat", "task selection", "selected_benchmark",
        "task.toml", "instruction.md", "hydrate", "navprove", "populate",
        "benchmark task", "task pack", "task content",
    ],
    "Infrastructure": [
        "dockerfile", "docker", "harbor", "container", "runner",
        "config", "3-config", "2config", "environment/", "sgonly",
        "sg_only", "generate_sgonly", "verifier", "test.sh", "workspace",
        "chown", "symlink", "base image", "slash command", "skill",
        "preflight", "harness", "codex", "cursor", "copilot",
        "multi-harness", "openhands", "leaderboard", "pipeline",
    ],
    "Agent & MCP": [
        "agent", "preamble", "mcp", "sourcegraph", "tool usage",
        "prompt", "claude_baseline", "mcp server", "tool call",
        "context retrieval", "curator",
    ],
    "Execution": [
        "promote", "batch", "launch", "staging", "official",
        "manifest", "parallel", "daytona", "token", "oauth",
        "subscription", "storage", "disk", "rerun",
    ],
    "Analysis": [
        "report", "analysis", "metrics", "variance", "doe", "rebalance",
        "statistical", "power", "blog", "paper", "ir_analysis",
        "retrieval", "cost", "composite", "leaderboard", "score extract",
        "reextract", "judge", "llm judge", "triage",
    ],
    "Bug Fix": [],  # special: commits starting with "fix:"
    "Maintenance": [
        "rename", "refactor", "archive", "clean", "chore",
        "readme", "docs:", "remove unused", "beads", "sync",
        "us-0", "[us-0", "ralph", "stale", "close completed",
        "close p0", "close p1", "line ending", "gitignore",
    ],
}


def extract_conversation_topics(transcript_dir):
    """Parse transcripts for daily topic intensity."""
    files = sorted(glob.glob(os.path.join(transcript_dir, "*.jsonl")))

    topic_by_date = defaultdict(lambda: Counter())
    session_count_by_date = Counter()
    interactive_by_date = Counter()

    for fpath in files:
        first_ts = None
        user_texts = []

        with open(fpath) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                if ts and not first_ts:
                    first_ts = ts

                if obj.get("type") != "user" or obj.get("isMeta"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, str):
                    if content.startswith(("<", "# Ralph")):
                        continue
                    if len(content) > 15:
                        user_texts.append(content.lower())
                elif isinstance(content, list):
                    for p in content:
                        if isinstance(p, dict) and p.get("type") == "text":
                            t = p["text"]
                            if len(t) > 15 and not t.startswith("<"):
                                user_texts.append(t.lower())

        if not first_ts:
            continue

        date = first_ts[:10]
        session_count_by_date[date] += 1

        if len(user_texts) <= 1:
            continue

        interactive_by_date[date] += 1
        combined = " ".join(user_texts)

        for topic, keywords in TOPIC_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in combined)
            if hits >= 2:
                topic_by_date[date][topic] += 1

    return topic_by_date, session_count_by_date, interactive_by_date


def extract_commit_arcs():
    """Classify commits into narrative arcs."""
    result = subprocess.run(
        ["git", "log", "--since=2026-01-31", "--until=2026-03-03",
         "--format=%ad|%s", "--date=short"],
        capture_output=True, text=True,
    )

    arc_by_date = defaultdict(lambda: Counter())
    fix_after_feat = []  # rework tracking

    recent_feats = []  # (date, msg) of recent feat: commits

    for line in result.stdout.strip().split("\n"):
        if "|" not in line:
            continue
        date, msg = line.split("|", 1)
        date = date.strip()
        msg = msg.strip()
        msg_lower = msg.lower()

        # Special: fix: commits
        if msg.startswith("fix:"):
            arc_by_date[date]["Bug Fix"] += 1
            # Check if this fixes a recent feature
            fix_after_feat.append({
                "date": date,
                "fix_msg": msg,
            })
            continue

        classified = False
        for arc, keywords in COMMIT_ARCS.items():
            if arc == "Bug Fix":
                continue
            if any(kw in msg_lower for kw in keywords):
                arc_by_date[date][arc] += 1
                classified = True
                break

        if not classified:
            arc_by_date[date]["Other"] += 1

        if msg.startswith("feat:"):
            recent_feats.append((date, msg))

    return arc_by_date, fix_after_feat


def extract_decision_points(transcript_dir):
    """Find sessions where explicit decisions were discussed."""
    files = sorted(glob.glob(os.path.join(transcript_dir, "*.jsonl")))

    decision_markers = [
        "should we", "let's ", "do we need", "why did we",
        "I think we should", "decision", "trade-off", "trade off",
        "instead of", "rather than", "approach", "strategy",
        "move to", "switch to", "drop", "archive", "keep",
        "the reason", "because we", "pros and cons",
    ]

    decisions = []
    for fpath in files:
        first_ts = None
        user_texts = []

        with open(fpath) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = obj.get("timestamp", "")
                if ts and not first_ts:
                    first_ts = ts
                if obj.get("type") != "user" or obj.get("isMeta"):
                    continue
                content = obj.get("message", {}).get("content", "")
                if isinstance(content, str):
                    if content.startswith(("<", "# Ralph")):
                        continue
                    if len(content) > 20:
                        user_texts.append(content)

        if not first_ts or not user_texts:
            continue

        combined_lower = " ".join(user_texts).lower()
        hits = [m for m in decision_markers if m in combined_lower]
        if len(hits) >= 2:
            # Find the most decision-relevant message
            best = max(user_texts, key=lambda t: sum(
                1 for m in decision_markers if m in t.lower()
            ))
            decisions.append({
                "date": first_ts[:10],
                "markers": hits[:5],
                "message": best[:400],
                "n_markers": len(hits),
            })

    decisions.sort(key=lambda d: d["date"])
    return decisions


def write_outputs(topic_by_date, session_counts, interactive_counts,
                  arc_by_date, fix_after_feat, decisions, output_dir):
    """Write all narrative data files."""
    os.makedirs(output_dir, exist_ok=True)

    # All dates
    all_dates = sorted(set(list(topic_by_date.keys()) + list(arc_by_date.keys())))

    # 1. Topic intensity CSV
    topics = list(TOPIC_KEYWORDS.keys())
    topic_path = os.path.join(output_dir, "build_narrative_topics.csv")
    with open(topic_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "sessions", "interactive"] + topics)
        for date in all_dates:
            row = [date, session_counts.get(date, 0), interactive_counts.get(date, 0)]
            for t in topics:
                row.append(topic_by_date.get(date, {}).get(t, 0))
            writer.writerow(row)
    print(f"Wrote {topic_path}")

    # 2. Commit arc CSV
    arcs = ["Task Design", "Infrastructure", "Agent & MCP", "Execution",
            "Analysis", "Bug Fix", "Maintenance", "Other"]
    arc_path = os.path.join(output_dir, "build_narrative_phases.csv")
    with open(arc_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date"] + arcs)
        for date in all_dates:
            row = [date]
            for a in arcs:
                row.append(arc_by_date.get(date, {}).get(a, 0))
            writer.writerow(row)
    print(f"Wrote {arc_path}")

    # 3. Rework CSV
    rework_path = os.path.join(output_dir, "build_narrative_rework.csv")
    with open(rework_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "fix_msg"])
        writer.writeheader()
        writer.writerows(fix_after_feat)
    print(f"Wrote {rework_path} ({len(fix_after_feat)} fix commits)")

    # 4. Decisions JSON
    dec_path = os.path.join(output_dir, "build_narrative_decisions.json")
    with open(dec_path, "w") as f:
        json.dump(decisions, f, indent=2)
    print(f"Wrote {dec_path} ({len(decisions)} decision sessions)")


def main():
    transcript_dir = os.path.expanduser(
        "~/.claude/projects/-home-stephanie-jarmak-CodeContextBench/"
    )
    output_dir = "data/build_diary"

    print("Extracting conversation topics...")
    topic_by_date, session_counts, interactive_counts = extract_conversation_topics(
        transcript_dir
    )

    print("Classifying commit narrative arcs...")
    arc_by_date, fix_after_feat = extract_commit_arcs()

    print("Finding decision-point sessions...")
    decisions = extract_decision_points(transcript_dir)

    print("Writing outputs...")
    write_outputs(
        topic_by_date, session_counts, interactive_counts,
        arc_by_date, fix_after_feat, decisions, output_dir,
    )
    print("Done.")


if __name__ == "__main__":
    main()

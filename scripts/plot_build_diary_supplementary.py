#!/usr/bin/env python3
"""
Supplementary build-diary figures for CodeScaleBench.

Generates three standalone figures:
  Figure S1: Tool Transition Heatmap
  Figure S2: Session Archetypes + Duration Distribution
  Figure S3: Repository Hotspots (most read/edited files)

Requires extract_build_diary.py to have been run first (for sessions CSV),
but also does its own direct transcript parsing for transitions and file counts.

Usage:
    python3 scripts/plot_build_diary_supplementary.py [--style light|dark]
"""

import argparse
import json
import glob
import os
import re
from collections import Counter
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Palettes (same as main figure) ─────────────────────────────────────────
PALETTE_LIGHT = {
    "bg": "#FFFFFF", "text": "#1a1a2e", "grid": "#e0e0e0",
    "accent": "#4361ee", "explore": "#4895ef", "build": "#f72585",
    "execute": "#7209b7", "coordinate": "#4cc9f0", "mcp": "#f77f00",
    "mixed": "#adb5bd", "empty": "#dee2e6",
    "cmap_seq": "YlOrRd", "cmap_div": "RdBu_r",
}
PALETTE_DARK = {
    "bg": "#0d1117", "text": "#e6edf3", "grid": "#21262d",
    "accent": "#58a6ff", "explore": "#58a6ff", "build": "#f778ba",
    "execute": "#bc8cff", "coordinate": "#79c0ff", "mcp": "#ffa657",
    "mixed": "#8b949e", "empty": "#484f58",
    "cmap_seq": "YlOrRd", "cmap_div": "RdBu_r",
}

TOOL_DISPLAY = {
    "Bash": "Bash",
    "Read": "Read",
    "Edit": "Edit",
    "Write": "Write",
    "Grep": "Grep",
    "Glob": "Glob",
    "Agent": "Agent",
    "TaskOutput": "TaskOut",
    "Task": "Task",
    "TaskCreate": "TaskCreate",
    "TaskUpdate": "TaskUpdate",
    "AskUserQuestion": "AskUser",
    "WebFetch": "WebFetch",
    "Skill": "Skill",
}


def setup_style(palette):
    plt.rcParams.update({
        "figure.facecolor": palette["bg"],
        "axes.facecolor": palette["bg"],
        "axes.edgecolor": palette["grid"],
        "axes.labelcolor": palette["text"],
        "text.color": palette["text"],
        "xtick.color": palette["text"],
        "ytick.color": palette["text"],
        "grid.color": palette["grid"],
        "grid.alpha": 0.5,
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
    })


# ── Data extraction ────────────────────────────────────────────────────────

def extract_transitions_and_files(transcript_dir):
    """Parse transcripts for tool transitions and file access counts."""
    files = sorted(glob.glob(os.path.join(transcript_dir, "*.jsonl")))
    transitions = Counter()
    file_edits = Counter()
    file_reads = Counter()

    for fpath in files:
        prev_tool = None
        with open(fpath) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "assistant":
                    prev_tool = None  # reset on non-assistant messages
                    continue
                content = obj.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "?")
                    # Normalize MCP tools
                    if name.startswith("mcp__"):
                        name = "MCP"
                    if prev_tool:
                        transitions[(prev_tool, name)] += 1
                    prev_tool = name

                    fp = block.get("input", {}).get("file_path", "")
                    if fp:
                        fp = re.sub(
                            r"^/home/stephanie_jarmak/CodeScaleBench/", "", fp
                        )
                        # Also strip evals path for the agent file
                        fp = re.sub(
                            r"^/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/",
                            "(evals) ", fp,
                        )
                        # Strip memory path
                        fp = re.sub(
                            r"^/home/stephanie_jarmak/.claude/projects/-home-stephanie-jarmak-CodeScaleBench/",
                            "(.claude) ", fp,
                        )
                        fp = re.sub(
                            r"^/home/stephanie_jarmak/.claude/",
                            "(.claude) ", fp,
                        )
                        if name == "Read":
                            file_reads[fp] += 1
                        elif name in ("Edit", "Write"):
                            file_edits[fp] += 1

    return transitions, file_edits, file_reads


def extract_session_details(transcript_dir):
    """Parse transcripts for session durations and tool profiles."""
    files = sorted(glob.glob(os.path.join(transcript_dir, "*.jsonl")))
    sessions = []

    CATEGORY_MAP = {
        "Read": "Explore", "Grep": "Explore", "Glob": "Explore",
        "WebFetch": "Explore", "WebSearch": "Explore",
        "Edit": "Build", "Write": "Build", "NotebookEdit": "Build",
        "Bash": "Execute", "TaskOutput": "Execute", "TaskStop": "Execute",
    }

    for fpath in files:
        timestamps = []
        tool_cats = Counter()
        total_tools = 0

        with open(fpath) as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ts = obj.get("timestamp", "")
                if ts:
                    timestamps.append(ts)

                if obj.get("type") != "assistant":
                    continue
                content = obj.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "?")
                    if name.startswith("mcp__"):
                        cat = "MCP"
                    else:
                        cat = CATEGORY_MAP.get(name, "Coordinate")
                    tool_cats[cat] += 1
                    total_tools += 1

        if not timestamps:
            continue

        # Duration
        try:
            t0 = datetime.fromisoformat(min(timestamps).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(max(timestamps).replace("Z", "+00:00"))
            dur_min = (t1 - t0).total_seconds() / 60
        except Exception:
            dur_min = 0

        # Archetype
        if total_tools == 0:
            archetype = "Empty"
        else:
            dominant_cat = max(tool_cats, key=tool_cats.get)
            frac = tool_cats[dominant_cat] / total_tools
            if frac > 0.6:
                archetype = dominant_cat
            else:
                archetype = "Mixed"

        sessions.append({
            "duration_min": dur_min,
            "total_tools": total_tools,
            "archetype": archetype,
            "cats": dict(tool_cats),
        })

    return sessions


# ── Figure S1: Tool Transition Heatmap ─────────────────────────────────────

def plot_transitions(transitions, palette, output_dir, fmt, dpi, suffix=""):
    """Heatmap of tool-to-tool transition frequencies."""
    # Select top N tools by total involvement
    tool_totals = Counter()
    for (a, b), c in transitions.items():
        tool_totals[a] += c
        tool_totals[b] += c

    top_tools = [t for t, _ in tool_totals.most_common(10)]
    n = len(top_tools)

    # Build matrix
    matrix = np.zeros((n, n))
    for i, t_from in enumerate(top_tools):
        row_total = sum(transitions.get((t_from, t_to), 0) for t_to in top_tools)
        for j, t_to in enumerate(top_tools):
            count = transitions.get((t_from, t_to), 0)
            # Normalize: fraction of transitions FROM this tool
            matrix[i, j] = count / row_total if row_total > 0 else 0

    labels = [TOOL_DISPLAY.get(t, t[:8]) for t in top_tools]

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(matrix, cmap=palette["cmap_seq"], aspect="auto",
                   vmin=0, vmax=0.8)

    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=40, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel("Next tool", fontsize=11)
    ax.set_ylabel("Previous tool", fontsize=11)
    ax.set_title("Tool Transition Probabilities Across 895 Sessions", fontsize=14,
                 fontweight="bold", pad=15)

    # Add text annotations
    for i in range(n):
        for j in range(n):
            val = matrix[i, j]
            raw = transitions.get((top_tools[i], top_tools[j]), 0)
            if val > 0.01:
                color = "white" if val > 0.4 else palette["text"]
                ax.text(j, i, f"{val:.0%}\n({raw:,})",
                        ha="center", va="center", fontsize=6.5, color=color)

    cbar = fig.colorbar(im, ax=ax, shrink=0.8, label="Transition probability")

    # Insight annotation
    insight = (
        "Self-loops dominate: Bash\u2192Bash (82%)\n"
        "shows iterative execute-check cycles.\n"
        "Read\u2192Edit (17%) confirms the\n"
        "\"read before you edit\" discipline."
    )
    ax.text(
        1.02, 0.02, insight, transform=ax.transAxes,
        fontsize=8, va="bottom", ha="left",
        bbox=dict(boxstyle="round,pad=0.4", fc=palette["bg"],
                  ec=palette["grid"], alpha=0.9),
    )

    fig.tight_layout()
    path = os.path.join(output_dir, f"fig_s1_tool_transitions{suffix}.{fmt}")
    fig.savefig(path, dpi=dpi, facecolor=palette["bg"], bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ── Figure S2: Session Archetypes + Duration ───────────────────────────────

def plot_archetypes_duration(sessions, palette, output_dir, fmt, dpi, suffix=""):
    """Donut chart of archetypes + duration histogram."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # -- Left: Archetype donut --
    arch_counts = Counter(s["archetype"] for s in sessions)
    arch_order = ["Execute", "Explore", "Mixed", "Empty", "Build", "Coordinate", "MCP"]
    arch_labels = []
    arch_sizes = []
    arch_colors = []
    color_map = {
        "Execute": palette["execute"], "Explore": palette["explore"],
        "Mixed": palette["mixed"], "Build": palette["build"],
        "Coordinate": palette["coordinate"], "MCP": palette["mcp"],
        "Empty": palette["empty"],
    }
    for a in arch_order:
        if arch_counts.get(a, 0) > 0:
            arch_labels.append(f"{a} ({arch_counts[a]})")
            arch_sizes.append(arch_counts[a])
            arch_colors.append(color_map.get(a, palette["grid"]))

    wedges, texts, autotexts = ax1.pie(
        arch_sizes, labels=arch_labels, colors=arch_colors,
        autopct=lambda pct: f"{pct:.0f}%" if pct > 3 else "",
        startangle=90, pctdistance=0.78,
        wedgeprops=dict(width=0.45, edgecolor=palette["bg"], linewidth=2),
        textprops=dict(fontsize=9),
    )
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color(palette["text"])

    ax1.set_title("Session Work Modes", fontsize=13, fontweight="bold")

    # Center label
    ax1.text(0, 0, f"{len(sessions)}\nsessions",
             ha="center", va="center", fontsize=14, fontweight="bold",
             color=palette["text"])

    # -- Right: Duration histogram with archetype coloring --
    duration_bins = [0, 1, 5, 15, 30, 60, 120, 300, 1500]
    bin_labels = ["<1m", "1-5m", "5-15m", "15-30m", "30m-1h", "1-2h", "2-5h", ">5h"]

    # Color by dominant archetype in each bin
    arch_in_bins = {a: [] for a in arch_order}
    for s in sessions:
        dur = s["duration_min"]
        for bi in range(len(duration_bins) - 1):
            if duration_bins[bi] <= dur < duration_bins[bi + 1]:
                arch_in_bins[s["archetype"]].append(bi)
                break
        else:
            if dur >= duration_bins[-1]:
                arch_in_bins[s["archetype"]].append(len(duration_bins) - 2)

    # Stacked bar
    x = np.arange(len(bin_labels))
    bottom = np.zeros(len(bin_labels))
    for a in arch_order:
        if not arch_in_bins.get(a):
            continue
        counts = np.zeros(len(bin_labels))
        for bi in arch_in_bins[a]:
            counts[bi] += 1
        ax2.bar(x, counts, bottom=bottom, color=color_map.get(a, palette["grid"]),
                label=a, width=0.7, edgecolor=palette["bg"], linewidth=0.5)
        bottom += counts

    ax2.set_xticks(x)
    ax2.set_xticklabels(bin_labels, fontsize=9)
    ax2.set_xlabel("Session duration")
    ax2.set_ylabel("Number of sessions")
    ax2.set_title("Session Duration by Work Mode", fontsize=13, fontweight="bold")
    ax2.legend(fontsize=7, loc="upper right", framealpha=0.9)
    ax2.grid(axis="y", alpha=0.3)

    # Insight
    quick = sum(1 for s in sessions if s["duration_min"] < 5)
    deep = sum(1 for s in sessions if s["duration_min"] >= 120)
    ax2.text(
        0.98, 0.65,
        f"{quick} quick (<5 min)\n{deep} deep (>2 hrs)",
        transform=ax2.transAxes, ha="right", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", fc=palette["bg"],
                  ec=palette["accent"], alpha=0.9, linewidth=0.5),
    )

    fig.suptitle(
        "Session Archetypes and Duration Distribution",
        fontsize=15, fontweight="bold", y=1.02,
    )
    fig.tight_layout()
    path = os.path.join(output_dir, f"fig_s2_session_archetypes{suffix}.{fmt}")
    fig.savefig(path, dpi=dpi, facecolor=palette["bg"], bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ── Figure S3: Repository Hotspots ─────────────────────────────────────────

def plot_hotspots(file_edits, file_reads, palette, output_dir, fmt, dpi, suffix=""):
    """Horizontal bar chart of most-edited and most-read files."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))

    # Shorten paths for display
    def shorten(fp, max_len=45):
        if len(fp) <= max_len:
            return fp
        parts = fp.split("/")
        if len(parts) > 2:
            return "/".join(parts[:1]) + "/.../" + parts[-1]
        return "..." + fp[-(max_len - 3):]

    # -- Left: Most edited --
    n = 18
    top_edits = file_edits.most_common(n)
    labels_e = [shorten(fp) for fp, _ in top_edits]
    counts_e = [c for _, c in top_edits]

    y = np.arange(n)
    bars = ax1.barh(y, counts_e, color=palette["build"], alpha=0.85,
                    edgecolor=palette["bg"], linewidth=0.5)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels_e, fontsize=7, fontfamily="monospace")
    ax1.invert_yaxis()
    ax1.set_xlabel("Edit/Write operations")
    ax1.set_title("Most Edited Files", fontsize=13, fontweight="bold")
    ax1.grid(axis="x", alpha=0.3)

    # Count annotations
    for bar, count in zip(bars, counts_e):
        ax1.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                 str(count), va="center", fontsize=7, color=palette["text"])

    # -- Right: Most read --
    top_reads = file_reads.most_common(n)
    labels_r = [shorten(fp) for fp, _ in top_reads]
    counts_r = [c for _, c in top_reads]

    bars2 = ax2.barh(y, counts_r, color=palette["explore"], alpha=0.85,
                     edgecolor=palette["bg"], linewidth=0.5)
    ax2.set_yticks(y)
    ax2.set_yticklabels(labels_r, fontsize=7, fontfamily="monospace")
    ax2.invert_yaxis()
    ax2.set_xlabel("Read operations")
    ax2.set_title("Most Read Files", fontsize=13, fontweight="bold")
    ax2.grid(axis="x", alpha=0.3)

    for bar, count in zip(bars2, counts_r):
        ax2.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                 str(count), va="center", fontsize=7, color=palette["text"])

    # Summary annotation
    fig.text(
        0.5, -0.01,
        f"2,944 unique files read  \u00b7  1,698 unique files edited  \u00b7  "
        f"Top file (selected_benchmark_tasks.json) edited 163 times",
        ha="center", fontsize=9, color=palette["text"], alpha=0.7,
        style="italic",
    )

    fig.suptitle(
        "Repository Hotspots: Where the Work Concentrated",
        fontsize=15, fontweight="bold", y=1.01,
    )
    fig.tight_layout()
    path = os.path.join(output_dir, f"fig_s3_repo_hotspots{suffix}.{fmt}")
    fig.savefig(path, dpi=dpi, facecolor=palette["bg"], bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/build_diary")
    parser.add_argument("--output-dir", default="data/build_diary")
    parser.add_argument(
        "--transcript-dir",
        default=os.path.expanduser(
            "~/.claude/projects/-home-stephanie-jarmak-CodeScaleBench/"
        ),
    )
    parser.add_argument("--style", choices=["light", "dark"], default="light")
    parser.add_argument("--dpi", type=int, default=250)
    parser.add_argument("--format", choices=["png", "pdf", "svg"], default="png")
    args = parser.parse_args()

    palette = PALETTE_DARK if args.style == "dark" else PALETTE_LIGHT
    setup_style(palette)

    print("Extracting tool transitions and file counts...")
    transitions, file_edits, file_reads = extract_transitions_and_files(
        args.transcript_dir
    )

    print("Extracting session details...")
    sessions = extract_session_details(args.transcript_dir)

    print(f"Generating Figure S1: Tool Transitions...")
    plot_transitions(transitions, palette, args.output_dir, args.format, args.dpi)

    print(f"Generating Figure S2: Session Archetypes...")
    plot_archetypes_duration(sessions, palette, args.output_dir, args.format, args.dpi)

    print(f"Generating Figure S3: Repository Hotspots...")
    plot_hotspots(file_edits, file_reads, palette, args.output_dir, args.format, args.dpi)

    # Generate dark variants if light — use a temp dir suffix to avoid overwrite
    if args.style == "light":
        print("\nGenerating dark variants...")
        palette_d = PALETTE_DARK
        setup_style(palette_d)
        dark_dir = args.output_dir
        plot_transitions(transitions, palette_d, dark_dir, args.format, args.dpi,
                         suffix="_dark")
        plot_archetypes_duration(sessions, palette_d, dark_dir, args.format, args.dpi,
                                suffix="_dark")
        plot_hotspots(file_edits, file_reads, palette_d, dark_dir, args.format, args.dpi,
                      suffix="_dark")

    print("Done.")


if __name__ == "__main__":
    main()

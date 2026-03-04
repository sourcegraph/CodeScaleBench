#!/usr/bin/env python3
"""
Content-focused "Build Narrative" visualization for CodeScaleBench.

Three panels telling the intellectual story:
  Panel A: What were the conversations about? (topic heatmap over time)
  Panel B: What was being built? (commit narrative arcs, stacked)
  Panel C: The rework curve — features built vs bugs fixed (cumulative)

Usage:
    python3 scripts/extract_build_narrative.py   # extract data first
    python3 scripts/plot_build_narrative.py       # then visualize
"""

import argparse
import csv
import os
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import numpy as np

# ── Palettes ───────────────────────────────────────────────────────────────
PALETTE_LIGHT = {
    "bg": "#FFFFFF", "text": "#1a1a2e", "grid": "#e0e0e0",
    "heatmap": "YlOrRd",
    # Arc colors — warm-toned semantic palette
    "Task Design": "#2d6a4f",
    "Infrastructure": "#4361ee",
    "Agent & MCP": "#f77f00",
    "Execution": "#7209b7",
    "Analysis": "#e63946",
    "Bug Fix": "#d62828",
    "Maintenance": "#ced4da",
    "Other": "#e9ecef",
    # Rework curve
    "feat_line": "#2d6a4f",
    "fix_line": "#d62828",
    "ratio_line": "#7209b7",
    "milestone": "#4361ee",
}
PALETTE_DARK = {
    "bg": "#0d1117", "text": "#e6edf3", "grid": "#21262d",
    "heatmap": "YlOrRd",
    "Task Design": "#52b788",
    "Infrastructure": "#58a6ff",
    "Agent & MCP": "#ffa657",
    "Execution": "#bc8cff",
    "Analysis": "#ff7b72",
    "Bug Fix": "#f778ba",
    "Maintenance": "#484f58",
    "Other": "#30363d",
    "feat_line": "#52b788",
    "fix_line": "#f778ba",
    "ratio_line": "#bc8cff",
    "milestone": "#58a6ff",
}

# ── Milestones — curated decision points ──────────────────────────────────
MILESTONES = [
    ("2026-01-31", "Initial commit"),
    ("2026-02-01", "11 benchmark suites scaffolded"),
    ("2026-02-03", "OAuth billing + DependEval dropped"),
    ("2026-02-06", "First full runs (baseline + MCP)"),
    ("2026-02-14", "Agent prompt V3 redesign"),
    ("2026-02-16", "Verifier overhaul (190 test.sh)"),
    ("2026-02-20", "Custom SDLC task authoring begins"),
    ("2026-02-22", "SG mirror pinning + SG-only mode"),
    ("2026-02-28", "Daytona cloud (124 parallel sandboxes)"),
    ("2026-03-01", "DOE-driven statistical rebalancing"),
    ("2026-03-02", "Variance closure + ContextBench"),
]


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
        "grid.alpha": 0.4,
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
    })


def load_data(data_dir):
    """Load extracted narrative data."""
    # Topics
    topics_path = os.path.join(data_dir, "build_narrative_topics.csv")
    with open(topics_path) as f:
        topics_raw = list(csv.reader(f))

    topic_header = topics_raw[0]
    topic_names = topic_header[3:]  # after date, sessions, interactive
    topic_data = []
    for row in topics_raw[1:]:
        if not row or not row[0]:
            continue
        entry = {
            "date": row[0],
            "sessions": int(row[1]),
            "interactive": int(row[2]),
        }
        for i, t in enumerate(topic_names):
            entry[t] = int(row[3 + i])
        topic_data.append(entry)

    # Commit arcs
    arcs_path = os.path.join(data_dir, "build_narrative_phases.csv")
    with open(arcs_path) as f:
        arcs_raw = list(csv.reader(f))
    arc_header = arcs_raw[0]
    arc_names = arc_header[1:]
    arc_data = []
    for row in arcs_raw[1:]:
        if not row or not row[0]:
            continue
        entry = {"date": row[0]}
        for i, a in enumerate(arc_names):
            entry[a] = int(row[1 + i])
        arc_data.append(entry)

    # Rework
    rework_path = os.path.join(data_dir, "build_narrative_rework.csv")
    with open(rework_path) as f:
        rework = list(csv.DictReader(f))

    return topic_data, topic_names, arc_data, arc_names, rework


def plot_panel_a(ax, topic_data, topic_names, palette):
    """Panel A: Topic heatmap — what were conversations about?"""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in topic_data]
    n_days = len(dates)
    n_topics = len(topic_names)

    # Build matrix: rows=topics, cols=dates
    # Normalize per-topic to show relative intensity (0-1)
    matrix = np.zeros((n_topics, n_days))
    for j, r in enumerate(topic_data):
        interactive = max(r["interactive"], 1)
        for i, t in enumerate(topic_names):
            matrix[i, j] = r[t] / interactive  # fraction of interactive sessions

    # Clean up topic labels (remove line breaks from CSV artifact)
    clean_labels = [t.replace("\n", " ") for t in topic_names]

    im = ax.imshow(matrix, aspect="auto", cmap=palette["heatmap"],
                   vmin=0, vmax=1.0, interpolation="nearest")

    ax.set_yticks(range(n_topics))
    ax.set_yticklabels(clean_labels, fontsize=8.5)

    # X axis: dates
    tick_interval = max(1, n_days // 10)
    ax.set_xticks(range(0, n_days, tick_interval))
    ax.set_xticklabels(
        [dates[i].strftime("%b %d") for i in range(0, n_days, tick_interval)],
        rotation=30, ha="right", fontsize=8,
    )

    # Add session count as top axis labels
    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(range(0, n_days, tick_interval))
    ax2.set_xticklabels(
        [f"{topic_data[i]['interactive']}s" for i in range(0, n_days, tick_interval)],
        fontsize=7, color=palette["text"], alpha=0.6,
    )
    ax2.set_xlabel("Interactive sessions", fontsize=8, alpha=0.6)
    ax2.tick_params(length=0)

    ax.set_title("A. What Were the Conversations About?", pad=25)

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, shrink=0.7, pad=0.02,
                        label="Fraction of sessions")
    cbar.ax.tick_params(labelsize=7)

    # Phase bracket annotations below x-axis
    phases = [
        (0, 5, "Scaffolding\n& task design"),
        (5, 13, "Infrastructure\n& first runs"),
        (13, 22, "Execution\n& debugging"),
        (22, n_days - 1, "Statistical\nvalidation"),
    ]
    bracket_y = n_topics + 0.4
    for start, end, label in phases:
        s = min(start, n_days - 1)
        e = min(end, n_days - 1)
        mid = (s + e) / 2
        # Bracket
        ax.plot([s, s, e, e], [bracket_y, bracket_y + 0.3, bracket_y + 0.3, bracket_y],
                color=palette["milestone"], alpha=0.5, linewidth=1.2,
                clip_on=False, transform=ax.transData)
        ax.text(mid, bracket_y + 0.5, label, ha="center", va="top",
                fontsize=7.5, color=palette["milestone"], alpha=0.85,
                fontweight="bold", clip_on=False)


def plot_panel_b(ax, arc_data, arc_names, palette):
    """Panel B: What was being built? Stacked area of commit arcs."""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in arc_data]

    # Order arcs: forward-progress at bottom, operational overhead on top
    arc_order = ["Task Design", "Agent & MCP", "Analysis",
                 "Infrastructure", "Execution", "Bug Fix", "Maintenance", "Other"]
    colors = [palette.get(a, "#888") for a in arc_order]

    y = np.array([[r.get(a, 0) for r in arc_data] for a in arc_order], dtype=float)

    ax.stackplot(dates, y, labels=arc_order, colors=colors, alpha=0.85)

    ax.set_ylabel("Git commits per day")
    ax.set_title("B. What Was Being Built?")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax.legend(loc="upper left", fontsize=7, framealpha=0.9, ncol=2)
    ax.grid(axis="y", alpha=0.3)

    # Annotate the Feb 16 spike (207 commits — the massive verifier overhaul)
    feb16_idx = next((i for i, r in enumerate(arc_data)
                      if r["date"] == "2026-02-16"), None)
    if feb16_idx is not None:
        total = sum(arc_data[feb16_idx].get(a, 0) for a in arc_order)
        ax.annotate(
            f"{total} commits\n(verifier overhaul)",
            xy=(dates[feb16_idx], total),
            xytext=(dates[feb16_idx] + timedelta(days=2), total * 0.7),
            fontsize=7, color=palette["text"], alpha=0.7,
            arrowprops=dict(arrowstyle="->", color=palette["text"], alpha=0.5),
        )


def plot_panel_c(ax, arc_data, arc_names, palette):
    """Panel C: The rework curve — cumulative features vs fixes."""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in arc_data]

    # Cumulative features (Task Design + Infrastructure + Agent & MCP + Execution + Analysis)
    feat_arcs = ["Task Design", "Infrastructure", "Agent & MCP", "Execution", "Analysis"]
    cum_feat = np.cumsum([sum(r.get(a, 0) for a in feat_arcs) for r in arc_data])
    cum_fix = np.cumsum([r.get("Bug Fix", 0) for r in arc_data])

    ax.fill_between(dates, cum_feat, alpha=0.15, color=palette["feat_line"])
    ax.plot(dates, cum_feat, color=palette["feat_line"], linewidth=2.5,
            label="Forward progress (feat/infra/agent)")
    ax.fill_between(dates, cum_fix, alpha=0.15, color=palette["fix_line"])
    ax.plot(dates, cum_fix, color=palette["fix_line"], linewidth=2.5,
            label="Course corrections (fix:)")

    ax.set_ylabel("Cumulative commits")
    ax.set_title("C. Forward Progress vs Course Corrections")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)

    # Add fix:feat ratio on secondary axis
    ax2 = ax.twinx()
    ratio = cum_fix / np.maximum(cum_feat, 1)
    ax2.plot(dates, ratio, color=palette["ratio_line"], linewidth=1.5,
             linestyle="--", alpha=0.7, label="Fix:Feat ratio")
    ax2.set_ylabel("Fix:Feat ratio", color=palette["ratio_line"], fontsize=9)
    ax2.tick_params(axis="y", colors=palette["ratio_line"])
    ax2.set_ylim(0, 0.8)
    ax2.legend(loc="lower right", fontsize=7, framealpha=0.8)

    # Annotate the steepest fix periods
    # Find days with most fixes
    fix_counts = [r.get("Bug Fix", 0) for r in arc_data]
    max_fix_idx = max(range(len(fix_counts)), key=lambda i: fix_counts[i])
    if fix_counts[max_fix_idx] > 10:
        ax.annotate(
            f"{fix_counts[max_fix_idx]} fixes in one day\n({arc_data[max_fix_idx]['date']})",
            xy=(dates[max_fix_idx], cum_fix[max_fix_idx]),
            xytext=(dates[max_fix_idx] - timedelta(days=4), cum_fix[max_fix_idx] + 20),
            fontsize=7, color=palette["fix_line"],
            arrowprops=dict(arrowstyle="->", color=palette["fix_line"], alpha=0.6),
        )

    # Final ratio annotation
    final_ratio = ratio[-1]
    ax.text(
        0.98, 0.45,
        f"Final ratio: {final_ratio:.0%}\n"
        f"({int(cum_fix[-1])} fixes / {int(cum_feat[-1])} features)\n"
        f"≈ 1 fix per {1/final_ratio:.1f} features",
        transform=ax.transAxes, ha="right", va="top", fontsize=8,
        bbox=dict(boxstyle="round,pad=0.3", fc=palette["bg"],
                  ec=palette["ratio_line"], alpha=0.9, linewidth=0.5),
    )

    # Milestone markers along bottom
    for ms_date, ms_label in MILESTONES:
        md = datetime.strptime(ms_date, "%Y-%m-%d")
        if dates[0] <= md <= dates[-1]:
            ax.axvline(md, color=palette["milestone"], alpha=0.12,
                       linestyle=":", linewidth=0.6)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/build_diary")
    parser.add_argument("--output", default="data/build_diary/build_narrative.png")
    parser.add_argument("--style", choices=["light", "dark"], default="light")
    parser.add_argument("--dpi", type=int, default=250)
    parser.add_argument("--format", choices=["png", "pdf", "svg"], default="png")
    args = parser.parse_args()

    palette = PALETTE_DARK if args.style == "dark" else PALETTE_LIGHT
    setup_style(palette)

    print("Loading data...")
    topic_data, topic_names, arc_data, arc_names, rework = load_data(args.data_dir)

    print("Generating figure...")
    fig = plt.figure(figsize=(20, 14))
    gs = GridSpec(3, 1, figure=fig, hspace=0.45,
                  left=0.07, right=0.93, top=0.93, bottom=0.05,
                  height_ratios=[1.1, 0.8, 0.8])

    ax_a = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])
    ax_c = fig.add_subplot(gs[2])

    plot_panel_a(ax_a, topic_data, topic_names, palette)
    plot_panel_b(ax_b, arc_data, arc_names, palette)
    plot_panel_c(ax_c, arc_data, arc_names, palette)

    fig.suptitle(
        "Building CodeScaleBench: Decisions, Topics, and Rework Over 31 Days",
        fontsize=16, fontweight="bold", y=0.98,
    )

    # Output
    out_path = args.output
    if args.format != "png":
        out_path = out_path.rsplit(".", 1)[0] + "." + args.format

    fig.savefig(out_path, dpi=args.dpi, facecolor=palette["bg"],
                bbox_inches="tight")
    print(f"Saved {out_path}")

    # Dark variant
    if args.style == "light":
        plt.close("all")
        palette_d = PALETTE_DARK
        setup_style(palette_d)
        fig2 = plt.figure(figsize=(20, 14))
        gs2 = GridSpec(3, 1, figure=fig2, hspace=0.45,
                       left=0.07, right=0.93, top=0.93, bottom=0.05,
                       height_ratios=[1.1, 0.8, 0.8])
        ax_a2 = fig2.add_subplot(gs2[0])
        ax_b2 = fig2.add_subplot(gs2[1])
        ax_c2 = fig2.add_subplot(gs2[2])

        plot_panel_a(ax_a2, topic_data, topic_names, palette_d)
        plot_panel_b(ax_b2, arc_data, arc_names, palette_d)
        plot_panel_c(ax_c2, arc_data, arc_names, palette_d)

        fig2.suptitle(
            "Building CodeScaleBench: Decisions, Topics, and Rework Over 31 Days",
            fontsize=16, fontweight="bold", y=0.98,
        )
        dark_path = out_path.rsplit(".", 1)[0] + "_dark." + args.format
        fig2.savefig(dark_path, dpi=args.dpi, facecolor=palette_d["bg"],
                     bbox_inches="tight")
        print(f"Saved {dark_path}")

    plt.close("all")
    print("Done.")


if __name__ == "__main__":
    main()

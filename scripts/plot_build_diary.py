#!/usr/bin/env python3
"""
Generate the CodeScaleBench "Build Diary" visualization.

Produces a 4-panel figure from extract_build_diary.py outputs:
  Panel A: Daily activity heatmap with milestone annotations
  Panel B: Stacked tool-category area chart (Explore → Build → Execute)
  Panel C: Human steering ratio over time
  Panel D: Session size distribution (histogram)

Usage:
    python3 scripts/extract_build_diary.py          # extract first
    python3 scripts/plot_build_diary.py              # then visualize
    python3 scripts/plot_build_diary.py --style dark # dark theme variant
"""

import argparse
import csv
import json
import os
from datetime import datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
import numpy as np

# ── Color palettes ─────────────────────────────────────────────────────────
PALETTE_LIGHT = {
    "bg":          "#FFFFFF",
    "text":        "#1a1a2e",
    "grid":        "#e0e0e0",
    "accent":      "#4361ee",
    "explore":     "#4895ef",
    "build":       "#f72585",
    "execute":     "#7209b7",
    "coordinate":  "#4cc9f0",
    "mcp":         "#f77f00",
    "human_ratio": "#4361ee",
    "sessions":    "#3a0ca3",
    "commits":     "#f72585",
    "milestone":   "#e63946",
    "hist_bar":    "#4361ee",
    "hist_edge":   "#3a0ca3",
}

PALETTE_DARK = {
    "bg":          "#0d1117",
    "text":        "#e6edf3",
    "grid":        "#21262d",
    "accent":      "#58a6ff",
    "explore":     "#58a6ff",
    "build":       "#f778ba",
    "execute":     "#bc8cff",
    "coordinate":  "#79c0ff",
    "mcp":         "#ffa657",
    "human_ratio": "#58a6ff",
    "sessions":    "#bc8cff",
    "commits":     "#f778ba",
    "milestone":   "#ff7b72",
    "hist_bar":    "#58a6ff",
    "hist_edge":   "#388bfd",
}


def load_data(data_dir):
    daily_path = os.path.join(data_dir, "build_diary_daily.csv")
    sessions_path = os.path.join(data_dir, "build_diary_sessions.csv")
    milestones_path = os.path.join(data_dir, "build_diary_milestones.json")
    summary_path = os.path.join(data_dir, "build_diary_summary.json")

    with open(daily_path) as f:
        daily = list(csv.DictReader(f))
    with open(sessions_path) as f:
        sessions = list(csv.DictReader(f))
    with open(milestones_path) as f:
        milestones = json.load(f)
    with open(summary_path) as f:
        summary = json.load(f)

    # Convert types
    for row in daily:
        for k in row:
            if k == "date":
                continue
            try:
                row[k] = float(row[k])
            except (ValueError, TypeError):
                pass

    return daily, sessions, milestones, summary


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
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "figure.titlesize": 16,
        "figure.titleweight": "bold",
    })


def plot_panel_a(ax, daily, milestones, summary, palette):
    """Panel A: Daily activity bar chart with milestone annotations."""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in daily]
    sessions = [int(r["sessions"]) for r in daily]
    commits = [int(r["commits"]) for r in daily]

    bar_width = 0.8
    ax.bar(dates, sessions, width=bar_width, color=palette["sessions"],
           alpha=0.8, label="Sessions", zorder=3)

    # Commits as overlay line
    ax2 = ax.twinx()
    ax2.plot(dates, commits, color=palette["commits"], linewidth=2,
             marker="o", markersize=4, label="Git commits", zorder=4)
    ax2.set_ylabel("Git commits", color=palette["commits"], fontsize=9)
    ax2.tick_params(axis="y", colors=palette["commits"])
    ax2.spines["right"].set_color(palette["commits"])

    # Milestone annotations — place below bars using ax.transData for x, ax.transAxes for y
    max_sessions = max(sessions) if sessions else 1
    selected_ms = _select_spaced_milestones(milestones, max_labels=10)

    # Alternate between two y-bands at the top of the chart
    y_bands = [0.78, 0.90]
    for i, m in enumerate(selected_ms):
        md = datetime.strptime(m["date"], "%Y-%m-%d")
        ax.axvline(md, color=palette["milestone"], alpha=0.2,
                   linestyle=":", linewidth=0.7, zorder=2)
        y_frac = y_bands[i % 2]
        ax.annotate(
            m["label"],
            xy=(md, max_sessions * y_frac),
            fontsize=5.5,
            color=palette["milestone"],
            rotation=25,
            ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.15", fc=palette["bg"],
                      ec=palette["milestone"], alpha=0.9, linewidth=0.4),
        )

    ax.set_ylabel("Sessions per day")
    ax.set_title("A. Daily Activity & Project Milestones")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.grid(axis="y", alpha=0.3)

    # Annotate the Mar 2 spike
    mar2_idx = next((i for i, d in enumerate(daily) if d["date"] == "2026-03-02"), None)
    if mar2_idx is not None:
        mar2_date = dates[mar2_idx]
        ax.annotate(
            "310 sessions\n(rename + batch)",
            xy=(mar2_date, sessions[mar2_idx]),
            xytext=(mar2_date - timedelta(days=4), sessions[mar2_idx] * 0.85),
            fontsize=6.5, color=palette["text"], alpha=0.7,
            arrowprops=dict(arrowstyle="->", color=palette["text"], alpha=0.5),
            ha="center",
        )

    # Summary annotation
    txt = (
        f"{summary['total_sessions']} sessions  \u00b7  "
        f"{summary['total_days']} days  \u00b7  "
        f"{summary['total_user_msgs'] + summary['total_assistant_msgs']:,} messages  \u00b7  "
        f"{summary['total_tool_calls']:,} tool calls"
    )
    ax.text(
        0.5, -0.18, txt, transform=ax.transAxes,
        ha="center", fontsize=9, color=palette["text"], alpha=0.7,
        style="italic",
    )

    lines_a, labels_a = ax.get_legend_handles_labels()
    lines_b, labels_b = ax2.get_legend_handles_labels()
    ax.legend(lines_a + lines_b, labels_a + labels_b,
              loc="upper left", fontsize=8, framealpha=0.8)


def plot_panel_b(ax, daily, palette):
    """Panel B: Stacked area chart of tool categories over time."""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in daily]
    cats = ["cat_explore", "cat_build", "cat_execute", "cat_coordinate", "cat_mcp"]
    labels = ["Explore (Read/Grep/Glob)", "Build (Edit/Write)",
              "Execute (Bash/Tasks)", "Coordinate (Agent/Plan)", "MCP Tools"]
    colors = [palette["explore"], palette["build"], palette["execute"],
              palette["coordinate"], palette["mcp"]]

    y = np.array([[float(r[c]) for r in daily] for c in cats])

    ax.stackplot(dates, y, labels=labels, colors=colors, alpha=0.8)
    ax.set_ylabel("Tool calls per day")
    ax.set_title("B. Tool Usage by Category")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.legend(loc="upper left", fontsize=7, framealpha=0.9, ncol=1)
    ax.grid(axis="y", alpha=0.3)


def plot_panel_c(ax, daily, palette):
    """Panel C: Human steering ratio over time."""
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in daily]
    ratios = [float(r["human_ratio"]) for r in daily]

    ax.fill_between(dates, ratios, alpha=0.3, color=palette["human_ratio"])
    ax.plot(dates, ratios, color=palette["human_ratio"], linewidth=2,
            marker="o", markersize=4)

    # Mean line
    mean_ratio = np.mean(ratios)
    ax.axhline(mean_ratio, color=palette["human_ratio"], linestyle=":",
               linewidth=1, alpha=0.5)

    ax.set_ylabel("Human message fraction")
    ax.set_title("C. Human Steering Ratio")
    ax.set_ylim(0.30, 0.55)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")
    ax.grid(axis="y", alpha=0.3)

    # Annotate the stability finding
    trend_text = (
        f"Mean: {mean_ratio:.0%} human / {1-mean_ratio:.0%} AI\n"
        f"Remarkably stable across\n"
        f"all project phases"
    )
    ax.text(
        0.97, 0.95, trend_text, transform=ax.transAxes,
        ha="right", va="top", fontsize=7,
        bbox=dict(boxstyle="round,pad=0.3", fc=palette["bg"],
                  ec=palette["human_ratio"], alpha=0.8, linewidth=0.5),
    )

    # Annotate Feb 17 outlier
    feb17_idx = next((i for i, r in enumerate(daily) if r["date"] == "2026-02-17"), None)
    if feb17_idx is not None and ratios[feb17_idx] > 0.50:
        ax.annotate(
            "3 sessions\n(mostly manual work)",
            xy=(dates[feb17_idx], ratios[feb17_idx]),
            xytext=(dates[feb17_idx] + timedelta(days=2), ratios[feb17_idx] - 0.03),
            fontsize=6, color=palette["text"], alpha=0.6,
            arrowprops=dict(arrowstyle="->", color=palette["text"], alpha=0.4),
        )


def plot_panel_d(ax, sessions, palette):
    """Panel D: Session size distribution histogram."""
    sizes = [int(s["total_msgs"]) for s in sessions]

    # Use log-scale bins for the heavy tail
    bins = np.concatenate([
        np.arange(0, 50, 5),
        np.arange(50, 200, 25),
        np.arange(200, 500, 50),
        np.arange(500, max(sizes) + 200, 200),
    ])

    counts, edges, patches = ax.hist(
        sizes, bins=bins, color=palette["hist_bar"],
        edgecolor=palette["hist_edge"], alpha=0.8, linewidth=0.5,
    )

    ax.set_xlabel("Messages per session")
    ax.set_ylabel("Number of sessions")
    ax.set_title("D. Session Size Distribution")
    ax.grid(axis="y", alpha=0.3)

    # Annotate key stats
    median_size = sorted(sizes)[len(sizes) // 2]
    max_size = max(sizes)
    marathon_count = sum(1 for s in sizes if s > 500)

    stats_text = (
        f"Median: {median_size} msgs\n"
        f"Marathon (>500): {marathon_count} sessions\n"
        f"Largest: {max_size:,} msgs"
    )
    ax.text(
        0.97, 0.95, stats_text, transform=ax.transAxes,
        ha="right", va="top", fontsize=7,
        bbox=dict(boxstyle="round,pad=0.3", fc=palette["bg"],
                  ec=palette["hist_bar"], alpha=0.8, linewidth=0.5),
    )


def _select_spaced_milestones(milestones, max_labels=10):
    """Select milestones spaced at least 2 days apart, prioritizing early ones."""
    if len(milestones) <= max_labels:
        return milestones

    selected = []
    last_date = None
    for m in milestones:
        md = datetime.strptime(m["date"], "%Y-%m-%d")
        if last_date is None or (md - last_date).days >= 2:
            selected.append(m)
            last_date = md
        if len(selected) >= max_labels:
            break
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/build_diary")
    parser.add_argument("--output", default="data/build_diary/build_diary.png")
    parser.add_argument("--style", choices=["light", "dark"], default="light")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--format", choices=["png", "pdf", "svg"], default="png")
    args = parser.parse_args()

    palette = PALETTE_DARK if args.style == "dark" else PALETTE_LIGHT
    setup_style(palette)

    print("Loading data...")
    daily, sessions, milestones, summary = load_data(args.data_dir)

    print("Generating figure...")
    fig = plt.figure(figsize=(20, 13))
    gs = GridSpec(2, 6, figure=fig, hspace=0.40, wspace=0.55,
                  left=0.05, right=0.96, top=0.92, bottom=0.07,
                  height_ratios=[1.2, 1])

    ax_a = fig.add_subplot(gs[0, :])        # full width top row
    ax_b = fig.add_subplot(gs[1, :2])       # bottom left
    ax_c = fig.add_subplot(gs[1, 2:4])      # bottom center
    ax_d = fig.add_subplot(gs[1, 4:])       # bottom right

    plot_panel_a(ax_a, daily, milestones, summary, palette)
    plot_panel_b(ax_b, daily, palette)
    plot_panel_c(ax_c, daily, palette)
    plot_panel_d(ax_d, sessions, palette)

    fig.suptitle(
        "Building CodeScaleBench: 951 Human-AI Conversations Over 31 Days",
        fontsize=16, fontweight="bold", y=0.97,
    )

    # Output
    out_path = args.output
    if args.format != "png":
        out_path = out_path.rsplit(".", 1)[0] + "." + args.format

    fig.savefig(out_path, dpi=args.dpi, facecolor=palette["bg"],
                bbox_inches="tight")
    print(f"Saved to {out_path}")

    # Also save a dark variant if light was requested
    if args.style == "light":
        dark_path = out_path.rsplit(".", 1)[0] + "_dark." + args.format
        palette_d = PALETTE_DARK
        setup_style(palette_d)

        fig2 = plt.figure(figsize=(20, 13))
        gs2 = GridSpec(2, 6, figure=fig2, hspace=0.40, wspace=0.55,
                       left=0.05, right=0.96, top=0.92, bottom=0.07,
                       height_ratios=[1.2, 1])
        ax_a2 = fig2.add_subplot(gs2[0, :])
        ax_b2 = fig2.add_subplot(gs2[1, :2])
        ax_c2 = fig2.add_subplot(gs2[1, 2:4])
        ax_d2 = fig2.add_subplot(gs2[1, 4:])

        plot_panel_a(ax_a2, daily, milestones, summary, palette_d)
        plot_panel_b(ax_b2, daily, palette_d)
        plot_panel_c(ax_c2, daily, palette_d)
        plot_panel_d(ax_d2, sessions, palette_d)

        fig2.suptitle(
            "Building CodeScaleBench: 951 Human-AI Conversations Over 31 Days",
            fontsize=16, fontweight="bold", y=0.97,
        )
        fig2.savefig(dark_path, dpi=args.dpi, facecolor=palette_d["bg"],
                     bbox_inches="tight")
        print(f"Saved dark variant to {dark_path}")

    plt.close("all")


if __name__ == "__main__":
    main()

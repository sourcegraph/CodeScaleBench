#!/usr/bin/env python3
"""Paired MCP-vs-baseline cost analysis from runs/official/_raw.

Pairing rules produced:
  1) latest_task: canonical headline method
     - key by (model, normalized_task_id)
     - keep latest valid run per side
     - require both sides; one pair per task
  2) count_matched: sensitivity method
     - key by (model, normalized_task_id)
     - pair count = min(n_baseline, n_mcp)
     - newest-first matching on started_at within each side bucket

This script writes:
  - docs/analysis/mcp_cost_pairs_official_raw_YYYYMMDD.json
  - docs/assets/blog/codescalebench_mcp/figure_7_cost_pairing_by_model_and_loc.{png,svg}
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "runs" / "official" / "_raw"
TASK_META_PATH = ROOT / "configs" / "selected_benchmark_tasks.json"
ANALYSIS_DIR = ROOT / "docs" / "analysis"
ASSET_DIR = ROOT / "docs" / "assets" / "blog" / "codescalebench_mcp"

PALETTE = {
    "bg": "#020202",
    "text": "#ededed",
    "text_secondary": "#a9a9a9",
    "grid": "#343434",
    "pos": "#8552f2",   # MCP better/cheaper
    "neg": "#ff7867",   # MCP worse/more expensive
    "base": "#6b7280",
}


def _setup_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": PALETTE["bg"],
            "axes.facecolor": PALETTE["bg"],
            "axes.edgecolor": PALETTE["grid"],
            "axes.labelcolor": PALETTE["text"],
            "xtick.color": PALETTE["text"],
            "ytick.color": PALETTE["text"],
            "text.color": PALETTE["text"],
            "grid.color": PALETTE["grid"],
            "font.family": "sans-serif",
            "font.sans-serif": ["Poly Sans", "Arial", "DejaVu Sans", "sans-serif"],
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
        }
    )


def _normalize_task_id(raw: str) -> str:
    task = (raw or "").strip().lower()
    task = re.sub(r"^(mcp_|bl_|sgonly_)", "", task)
    task = re.sub(r"^sdlc_[a-z]+_", "", task)
    task = re.sub(r"_[a-z0-9]{6,8}$", "", task)
    return task


def _normalize_task_from_dirname(dirname: str) -> str:
    task = dirname
    if "__" in task:
        task = task.split("__", 1)[0]
    return _normalize_task_id(task)


def _infer_model(run_name: str) -> str | None:
    m = re.search(r"(haiku|sonnet|opus)", run_name, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _classify_side(config_name: str) -> str | None:
    name = config_name.lower()
    if "baseline" in name:
        return "baseline"
    if "mcp" in name or "sourcegraph" in name:
        return "mcp"
    return None


def _is_valid(metrics: dict) -> bool:
    out = metrics.get("output_tokens")
    if out is not None and out == 0:
        return False
    agent_sec = metrics.get("agent_execution_seconds")
    if agent_sec is not None and agent_sec < 10:
        return False
    return True


def _context_bin(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 100_000:
        return "<100k"
    if value < 1_000_000:
        return "100k-1m"
    return ">=1m"


def _files_bin(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 10:
        return "<10"
    if value <= 100:
        return "10-100"
    return ">100"


def _repo_loc_band(loc: int | None) -> str:
    if loc is None:
        return "unknown"
    if loc < 400_000:
        return "<400K"
    if loc < 2_000_000:
        return "400K-2M"
    if loc < 8_000_000:
        return "2M-8M"
    if loc < 40_000_000:
        return "8M-40M"
    return ">40M"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _collect_task_meta() -> dict[str, dict]:
    try:
        doc = json.loads(TASK_META_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for t in doc.get("tasks", []):
        task_id = _normalize_task_id(str(t.get("task_id", "")))
        if task_id:
            out[task_id] = t
    return out


def _collect_records() -> list[dict]:
    records = []
    for tm_path in RAW_DIR.rglob("task_metrics.json"):
        rel = tm_path.relative_to(RAW_DIR)
        run_name = rel.parts[0]
        model = _infer_model(run_name)
        if model not in {"haiku", "sonnet", "opus"}:
            continue

        config_name = None
        for part in rel.parts[1:]:
            side = _classify_side(part)
            if side is not None:
                config_name = part
                break
        if not config_name:
            continue
        side = _classify_side(config_name)
        if side is None:
            continue

        try:
            metrics = json.loads(tm_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        raw_task = metrics.get("task_id")
        task_id = _normalize_task_id(raw_task) if isinstance(raw_task, str) and raw_task else None
        if not task_id:
            task_id = _normalize_task_from_dirname(tm_path.parent.name)
        if not task_id:
            continue

        started_at = ""
        result_path = tm_path.parent / "result.json"
        if result_path.is_file():
            try:
                started_at = (json.loads(result_path.read_text()).get("started_at") or "")
            except (OSError, json.JSONDecodeError):
                pass

        records.append(
            {
                "model": model,
                "task_id": task_id,
                "side": side,
                "cost_usd": float(metrics.get("cost_usd") or 0.0),
                "input_tokens": int(metrics.get("input_tokens") or 0),
                "output_tokens": int(metrics.get("output_tokens") or 0),
                "valid": _is_valid(metrics),
                "started_at": started_at,
            }
        )
    return records


def _pair_records_count_matched(records: list[dict], valid_only: bool) -> list[dict]:
    buckets: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in records:
        if valid_only and not r["valid"]:
            continue
        buckets[(r["model"], r["task_id"], r["side"])].append(r)

    for key in buckets:
        buckets[key].sort(key=lambda x: x["started_at"], reverse=True)

    pairs = []
    task_keys = {(m, t) for (m, t, _s) in buckets.keys()}
    for model, task in task_keys:
        bl = buckets.get((model, task, "baseline"), [])
        mc = buckets.get((model, task, "mcp"), [])
        n = min(len(bl), len(mc))
        if n == 0:
            continue
        for i in range(n):
            pairs.append(
                {
                    "model": model,
                    "task_id": task,
                    "baseline_cost_usd": bl[i]["cost_usd"],
                    "mcp_cost_usd": mc[i]["cost_usd"],
                    "baseline_input_tokens": bl[i]["input_tokens"],
                    "mcp_input_tokens": mc[i]["input_tokens"],
                    "baseline_output_tokens": bl[i]["output_tokens"],
                    "mcp_output_tokens": mc[i]["output_tokens"],
                }
            )
    return pairs


def _pair_records_latest_task(records: list[dict], valid_only: bool) -> list[dict]:
    """One pair per (model, task_id), using latest record per side."""
    buckets: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in records:
        if valid_only and not r["valid"]:
            continue
        buckets[(r["model"], r["task_id"], r["side"])].append(r)

    for key in buckets:
        buckets[key].sort(key=lambda x: x["started_at"], reverse=True)

    pairs = []
    task_keys = {(m, t) for (m, t, _s) in buckets.keys()}
    for model, task in task_keys:
        bl = buckets.get((model, task, "baseline"), [])
        mc = buckets.get((model, task, "mcp"), [])
        if not bl or not mc:
            continue
        b0 = bl[0]
        m0 = mc[0]
        pairs.append(
            {
                "model": model,
                "task_id": task,
                "baseline_cost_usd": b0["cost_usd"],
                "mcp_cost_usd": m0["cost_usd"],
                "baseline_input_tokens": b0["input_tokens"],
                "mcp_input_tokens": m0["input_tokens"],
                "baseline_output_tokens": b0["output_tokens"],
                "mcp_output_tokens": m0["output_tokens"],
            }
        )
    return pairs


def _summarize_model(pairs: list[dict]) -> dict[str, dict]:
    out = {}
    for model in ("haiku", "sonnet", "opus"):
        rows = [p for p in pairs if p["model"] == model]
        bl = sum(r["baseline_cost_usd"] for r in rows)
        mc = sum(r["mcp_cost_usd"] for r in rows)
        n = len(rows)
        out[model] = {
            "pairs": n,
            "baseline_total_cost_usd": bl,
            "mcp_total_cost_usd": mc,
            "baseline_avg_cost_usd": (bl / n) if n else 0.0,
            "mcp_avg_cost_usd": (mc / n) if n else 0.0,
            "delta_cost_usd": mc - bl,
            "pct_delta_cost_of_means": ((mc / bl - 1) * 100) if bl else None,
            "input_ratio_mcp_over_baseline": (
                (sum(r["mcp_input_tokens"] for r in rows) / sum(r["baseline_input_tokens"] for r in rows))
                if rows and sum(r["baseline_input_tokens"] for r in rows) > 0
                else None
            ),
        }
    return out


def _summarize_size(
    pairs: list[dict],
    task_meta: dict[str, dict],
) -> dict[str, dict]:
    rows = [p for p in pairs if p["model"] == "haiku"]

    by_loc: dict[str, list[dict]] = defaultdict(list)
    for p in rows:
        meta = task_meta.get(p["task_id"], {})
        loc_value = meta.get("repo_approx_loc")
        try:
            loc_value = int(loc_value) if loc_value is not None else None
        except (TypeError, ValueError):
            loc_value = None
        loc_bin = _repo_loc_band(loc_value)
        by_loc[loc_bin].append(p)

    def summarize(groups: dict[str, list[dict]]) -> dict[str, dict]:
        out = {}
        for band, vals in sorted(groups.items()):
            n = len(vals)
            bl = sum(v["baseline_cost_usd"] for v in vals)
            mc = sum(v["mcp_cost_usd"] for v in vals)
            out[band] = {
                "pairs": n,
                "baseline_avg_cost_usd": (bl / n) if n else 0.0,
                "mcp_avg_cost_usd": (mc / n) if n else 0.0,
                "delta_avg_cost_usd": ((mc - bl) / n) if n else 0.0,
                "pct_delta_cost_of_means": ((mc / bl - 1) * 100) if bl else None,
            }
        return out

    return {
        "haiku_by_repo_loc": summarize(by_loc),
    }


def _plot_figure(report: dict) -> None:
    _setup_style()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    canonical = report["latest_task"]["valid_only"]
    loc = canonical["size_summary"]["haiku_by_repo_loc"]
    loc_order = ["<400K", "400K-2M", "2M-8M", "8M-40M", ">40M", "unknown"]
    bands = [b for b in loc_order if b in loc]
    vals = [loc[b]["pct_delta_cost_of_means"] or 0.0 for b in bands]
    cols = [PALETTE["pos"] if v < 0 else PALETTE["neg"] for v in vals]

    fig, ax = plt.subplots(1, 1, figsize=(8.8, 4.9))
    x = np.arange(len(bands))
    bars = ax.bar(x, vals, color=cols, width=0.64)
    ax.axhline(0, color=PALETTE["grid"], linewidth=1)
    ax.set_xticks(x)
    ax.set_xticklabels(bands, rotation=15, ha="right")
    ax.set_ylabel("% cost delta (MCP vs baseline)", color=PALETTE["text_secondary"])
    ax.set_title("Haiku Cost Delta by Estimated Codebase LOC")
    ax.grid(axis="y", alpha=0.3)
    for b, v in zip(bars, vals):
        y = v + 1.8 if v >= 0 else v - 2.6
        va = "bottom" if v >= 0 else "top"
        ax.text(b.get_x() + b.get_width() / 2, y, f"{v:+.1f}%", ha="center", va=va, fontsize=8)

    fig.suptitle(
        "MCP vs Baseline Cost (Haiku, Latest-Task Valid Pairing; cloc-derived LOC bands)",
        fontsize=11.5,
        fontweight="bold",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    fig.savefig(ASSET_DIR / "figure_7_cost_pairing_by_model_and_loc.png", dpi=220, bbox_inches="tight")
    fig.savefig(ASSET_DIR / "figure_7_cost_pairing_by_model_and_loc.svg", bbox_inches="tight")
    plt.close(fig)


def build_report() -> dict:
    records = _collect_records()
    task_meta = _collect_task_meta()

    latest_all = _pair_records_latest_task(records, valid_only=False)
    latest_valid = _pair_records_latest_task(records, valid_only=True)
    count_all = _pair_records_count_matched(records, valid_only=False)
    count_valid = _pair_records_count_matched(records, valid_only=True)

    now = datetime.now(timezone.utc).isoformat()
    report = {
        "generated_at": now,
        "source": "runs/official/_raw",
        "canonical_pairing_rule": "latest valid per side per (model, task_id); one pair per task",
        "sensitivity_pairing_rule": "count-matched per (model, task_id), newest-first within side",
        "valid_filter": "output_tokens > 0 and agent_execution_seconds >= 10",
        "size_binning": "cloc-derived repository LOC bands: <400K, 400K-2M, 2M-8M, 8M-40M, >40M",
        "records_scanned": len(records),
        "latest_task": {
            "all_pairs": {
                "pair_count": len(latest_all),
                "model_summary": _summarize_model(latest_all),
                "size_summary": _summarize_size(latest_all, task_meta),
            },
            "valid_only": {
                "pair_count": len(latest_valid),
                "model_summary": _summarize_model(latest_valid),
                "size_summary": _summarize_size(latest_valid, task_meta),
            },
        },
        "count_matched": {
            "all_pairs": {
                "pair_count": len(count_all),
                "model_summary": _summarize_model(count_all),
                "size_summary": _summarize_size(count_all, task_meta),
            },
            "valid_only": {
                "pair_count": len(count_valid),
                "model_summary": _summarize_model(count_valid),
                "size_summary": _summarize_size(count_valid, task_meta),
            },
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze paired MCP-vs-baseline costs from runs/official/_raw.")
    parser.add_argument("--date-tag", default=datetime.now(timezone.utc).strftime("%Y%m%d"))
    args = parser.parse_args()

    report = build_report()
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = ANALYSIS_DIR / f"mcp_cost_pairs_official_raw_{args.date_tag}.json"
    out_json.write_text(json.dumps(report, indent=2))

    _plot_figure(report)

    print(f"Wrote: {out_json}")
    print(f"Wrote: {ASSET_DIR / 'figure_7_cost_pairing_by_model_and_loc.png'}")
    print(f"Wrote: {ASSET_DIR / 'figure_7_cost_pairing_by_model_and_loc.svg'}")


if __name__ == "__main__":
    main()

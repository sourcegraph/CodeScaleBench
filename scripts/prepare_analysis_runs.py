#!/usr/bin/env python3
"""Prepare balanced analysis samples for CSB-SDLC and CSB-Org.

Selection policy:
- Only runs under runs/official whose run dir starts with csb_sdlc_ or csb_org_.
- Pair baseline/MCP at task level (not required to be same run timestamp).
- Exclude flagged/suspicious task+config entries from audit files.
- Keep only high-quality pairs (auditable traces present, non-trivial execution).
- For tasks with >=3 valid pairs, keep the most recent 3.

Output layout:
  runs/analysis/{csb_sdlc|csb_org}/{suite}/{baseline|mcp}/{task}/{task}_{1..3}/...
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
RUNS_OFFICIAL = ROOT / "runs" / "official"
ANALYSIS_ROOT = ROOT / "runs" / "analysis"


def normalize_variant(config_name: str | None) -> str | None:
    if not config_name:
        return None
    c = config_name.lower()
    if c in {"baseline", "baseline-local-direct", "baseline-local-artifact", "baseline-local"}:
        return "baseline"
    if c in {"mcp", "mcp-remote-direct", "mcp-remote-artifact", "sourcegraph_full"}:
        return "mcp"
    return None


def parse_suite_and_subset(run_dir_name: str) -> tuple[str, str] | tuple[None, None]:
    if run_dir_name.startswith("csb_sdlc_"):
        subset = "csb_sdlc"
    elif run_dir_name.startswith("csb_org_"):
        subset = "csb_org"
    else:
        return None, None

    tokens = run_dir_name.split("_")
    model_tokens = {"haiku", "sonnet", "opus", "gpt", "claude", "o1", "o3", "o4"}
    stop = len(tokens)
    for i, tok in enumerate(tokens):
        if tok.lower() in model_tokens and i >= 2:
            stop = i
            break
    suite = "_".join(tokens[:stop])
    return subset, suite


def parse_iso_to_epoch(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def canonicalize_task_id(task_id: str) -> str:
    t = task_id.strip()
    if not t:
        return t
    if "__" in t:
        t = t.split("__", 1)[0]
    for prefix in ("mcp_", "sgonly_"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            # Harbor MCP task dirs often append a short disambiguation suffix.
            t = re.sub(r"_[A-Za-z0-9]{6,8}$", "", t)
            break
    return t.lower()


def parse_batch_ts_to_epoch(batch_name: str) -> float:
    m = re.match(r"^(\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2})$", batch_name)
    if not m:
        return 0.0
    try:
        dt = datetime.strptime(m.group(1), "%Y-%m-%d__%H-%M-%S").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _iter_flag_entries(value: object) -> Iterable[dict]:
    if isinstance(value, dict):
        if "task" in value:
            yield value
        for v in value.values():
            yield from _iter_flag_entries(v)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_flag_entries(item)


def load_flagged_pairs(audit_report: Path, v2_report: Path) -> set[tuple[str, str]]:
    flagged: set[tuple[str, str]] = set()

    if audit_report.is_file():
        data = json.loads(audit_report.read_text())
        for entry in _iter_flag_entries(data.get("flags", {})):
            task = canonicalize_task_id((entry.get("task") or "").strip())
            variant = normalize_variant(entry.get("config"))
            if task and variant:
                flagged.add((task, variant))

    if v2_report.is_file():
        data = json.loads(v2_report.read_text())
        for item in data.get("suspicious", []):
            task = canonicalize_task_id((item.get("task") or "").strip())
            variant = normalize_variant(item.get("config"))
            if task and variant:
                flagged.add((task, variant))

    return flagged


def load_promotable_overrides(review_file: Path | None) -> set[tuple[str, str]]:
    """Load flagged task+variant pairs that should be treated as promotable."""
    promotable: set[tuple[str, str]] = set()
    if review_file is None or not review_file.is_file():
        return promotable
    try:
        data = json.loads(review_file.read_text())
    except Exception:
        return promotable
    for row in data.get("reviews", []):
        if row.get("recommended_status") != "promotable":
            continue
        task = canonicalize_task_id((row.get("task_id") or "").strip())
        variant = normalize_variant(row.get("variant"))
        if task and variant:
            promotable.add((task, variant))
    return promotable


def load_vetted_allowset(selection_file: Path | None) -> set[tuple[str, str, str]] | None:
    """Build allowset from selected_benchmark_tasks.json using metadata per-suite targets.

    Returns a set of (subset, suite, canonical_task_id), or None if no file provided.
    """
    if selection_file is None:
        return None
    if not selection_file.is_file():
        return None

    try:
        data = json.loads(selection_file.read_text())
    except Exception:
        return None

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return None

    per_suite = data.get("metadata", {}).get("per_suite", {})
    if not isinstance(per_suite, dict):
        return None

    # Keep first N tasks per suite in file order, where N is the metadata target.
    selected_per_suite: dict[str, int] = defaultdict(int)
    allowset: set[tuple[str, str, str]] = set()
    for row in tasks:
        if not isinstance(row, dict):
            continue
        suite = (row.get("benchmark") or row.get("mcp_suite") or "").strip()
        if suite not in per_suite:
            continue
        if not (suite.startswith("csb_sdlc") or suite.startswith("csb_org")):
            continue
        target_n = per_suite.get(suite)
        if not isinstance(target_n, int) or target_n <= 0:
            continue
        if selected_per_suite[suite] >= target_n:
            continue
        task_id = canonicalize_task_id(str(row.get("task_id") or "").strip())
        if not task_id:
            continue
        subset = "csb_sdlc" if suite.startswith("csb_sdlc") else "csb_org"
        allowset.add((subset, suite, task_id))
        selected_per_suite[suite] += 1
    return allowset


@dataclass
class TaskRun:
    subset: str
    suite: str
    run_dir: str
    variant: str
    task_id: str
    task_dir: Path
    started_at: str
    epoch: float
    output_tokens: int | None
    agent_execution_seconds: float | None
    has_trajectory: bool
    has_transcript: bool
    has_reward: bool

    def is_high_quality(self) -> bool:
        if not (self.has_trajectory and self.has_transcript and self.has_reward):
            return False
        if self.output_tokens is not None and self.output_tokens <= 0:
            return False
        if self.agent_execution_seconds is not None and self.agent_execution_seconds < 15:
            return False
        return True


def discover_runs(source_root: Path) -> list[TaskRun]:
    records: list[TaskRun] = []
    for run_dir in sorted(source_root.iterdir()):
        if not run_dir.is_dir():
            continue
        subset, suite = parse_suite_and_subset(run_dir.name)
        if not subset:
            continue

        for metrics_file in run_dir.rglob("task_metrics.json"):
            task_dir = metrics_file.parent
            rel_parts = task_dir.relative_to(run_dir).parts
            if len(rel_parts) < 3:
                continue

            config_name = rel_parts[0]
            variant = normalize_variant(config_name)
            if not variant:
                continue

            # Old and new formats both place batch/job in rel_parts[1]
            batch_or_job = rel_parts[1]
            try:
                metrics = json.loads(metrics_file.read_text())
            except Exception:
                continue

            task_id = canonicalize_task_id((metrics.get("task_id") or "").strip())
            if not task_id:
                # Fall back to dir name without hash suffix.
                task_id = canonicalize_task_id(task_dir.name.split("__")[0])

            result_file = task_dir / "result.json"
            started_at = ""
            epoch = 0.0
            if result_file.is_file():
                try:
                    result = json.loads(result_file.read_text())
                    started_at = result.get("started_at", "")
                    epoch = parse_iso_to_epoch(started_at)
                except Exception:
                    pass
            if epoch == 0.0:
                epoch = parse_batch_ts_to_epoch(batch_or_job)

            transcript = task_dir / "agent" / "claude-code.txt"
            if not transcript.is_file():
                transcript = task_dir / "claude-code.txt"
            trajectory = task_dir / "agent" / "trajectory.json"
            if not trajectory.is_file():
                trajectory = task_dir / "trajectory.json"
            reward = task_dir / "verifier" / "reward.txt"

            output_tokens = metrics.get("output_tokens")
            agent_secs = metrics.get("agent_execution_seconds")

            records.append(
                TaskRun(
                    subset=subset,
                    suite=suite,
                    run_dir=run_dir.name,
                    variant=variant,
                    task_id=task_id,
                    task_dir=task_dir,
                    started_at=started_at,
                    epoch=epoch,
                    output_tokens=output_tokens if isinstance(output_tokens, int) else None,
                    agent_execution_seconds=float(agent_secs) if isinstance(agent_secs, (int, float)) else None,
                    has_trajectory=trajectory.is_file(),
                    has_transcript=transcript.is_file(),
                    has_reward=reward.is_file(),
                )
            )
    return records


def choose_top3_paired(
    records: list[TaskRun],
    flagged_pairs: set[tuple[str, str]],
    promotable_pairs: set[tuple[str, str]],
    allowset: set[tuple[str, str, str]] | None = None,
) -> dict:
    # Keep latest run per (subset, suite, run_dir, task, variant) to avoid duplicate task_metrics views.
    dedup: dict[tuple[str, str, str, str, str], TaskRun] = {}
    for rec in records:
        key = (rec.subset, rec.suite, rec.run_dir, rec.task_id, rec.variant)
        existing = dedup.get(key)
        if existing is None or rec.epoch > existing.epoch:
            dedup[key] = rec

    # Build independent high-quality pools by task and variant, then pair by recency rank.
    grouped: dict[tuple[str, str, str], dict[str, list[TaskRun]]] = defaultdict(lambda: {"baseline": [], "mcp": []})
    for rec in dedup.values():
        if allowset is not None and (rec.subset, rec.suite, rec.task_id) not in allowset:
            continue
        pair_key = (rec.task_id, rec.variant)
        if pair_key in flagged_pairs and pair_key not in promotable_pairs:
            continue
        if not rec.is_high_quality():
            continue
        grouped[(rec.subset, rec.suite, rec.task_id)][rec.variant].append(rec)

    selected: dict = {}
    under_target: list[dict] = []
    for key, by_variant in grouped.items():
        baseline_runs = sorted(by_variant["baseline"], key=lambda r: r.epoch, reverse=True)
        mcp_runs = sorted(by_variant["mcp"], key=lambda r: r.epoch, reverse=True)
        pair_count = min(3, len(baseline_runs), len(mcp_runs))
        if pair_count <= 0:
            continue
        if pair_count < 3:
            subset, suite, task_id = key
            under_target.append(
                {
                    "subset": subset,
                    "suite": suite,
                    "task_id": task_id,
                    "baseline_available": len(baseline_runs),
                    "mcp_available": len(mcp_runs),
                    "paired_selected": pair_count,
                }
            )
        pairs = []
        for i in range(pair_count):
            bl = baseline_runs[i]
            mcp = mcp_runs[i]
            pairs.append(
                {
                    "pair_epoch": max(bl.epoch, mcp.epoch),
                    "baseline": bl,
                    "mcp": mcp,
                }
            )
        selected[key] = pairs
    return {"selected": selected, "under_target": under_target}


def copy_auditable_payload(src_task_dir: Path, dst_task_dir: Path) -> None:
    dst_task_dir.mkdir(parents=True, exist_ok=True)

    for dirname in ("agent", "verifier", "artifacts"):
        src = src_task_dir / dirname
        if src.is_dir():
            shutil.copytree(
                src,
                dst_task_dir / dirname,
                dirs_exist_ok=True,
                symlinks=True,
                ignore_dangling_symlinks=True,
            )

    for filename in ("task_metrics.json", "result.json", "config.json", "trial.log"):
        src = src_task_dir / filename
        if src.is_file():
            shutil.copy2(src, dst_task_dir / filename)


def materialize_analysis(selected: dict, output_root: Path) -> dict:
    summary = {
        "selected_tasks": 0,
        "selected_pairs": 0,
        "by_subset": {"csb_sdlc": 0, "csb_org": 0},
        "by_variant_runs": {"baseline": 0, "mcp": 0},
        "tasks": [],
    }

    for (subset, suite, task_id), pairs in sorted(selected.items()):
        summary["selected_tasks"] += 1
        summary["selected_pairs"] += len(pairs)
        summary["by_subset"][subset] += 1

        task_entry = {
            "subset": subset,
            "suite": suite,
            "task_id": task_id,
            "runs": [],
        }

        for idx, pair in enumerate(pairs, start=1):
            run_name = f"{task_id}_{idx}"
            run_meta = {"index": idx, "baseline_src": str(pair["baseline"].task_dir), "mcp_src": str(pair["mcp"].task_dir)}

            for variant in ("baseline", "mcp"):
                src = pair[variant].task_dir
                dst = output_root / subset / suite / variant / task_id / run_name
                copy_auditable_payload(src, dst)
                summary["by_variant_runs"][variant] += 1

            task_entry["runs"].append(run_meta)
        summary["tasks"].append(task_entry)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare balanced CSB analysis run samples.")
    parser.add_argument("--source", type=Path, default=RUNS_OFFICIAL)
    parser.add_argument("--output", type=Path, default=ANALYSIS_ROOT)
    parser.add_argument("--audit-report", type=Path, default=RUNS_OFFICIAL / "audit_report.json")
    parser.add_argument("--v2-audit-report", type=Path, default=RUNS_OFFICIAL / "v2_report_audit.json")
    parser.add_argument(
        "--reclassification-review",
        type=Path,
        default=ROOT / "runs" / "analysis" / "flag_reclassification_review.json",
        help="Optional review file; flagged sides marked promotable will be included.",
    )
    parser.add_argument(
        "--allowlist-selection-file",
        type=Path,
        default=None,
        help=(
            "Optional selected_benchmark_tasks.json path. When provided, only the vetted "
            "per-suite target counts from metadata.per_suite are included."
        ),
    )
    parser.add_argument("--no-clean", action="store_true", help="Do not remove existing output first.")
    args = parser.parse_args()

    if args.output.exists() and not args.no_clean:
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True, exist_ok=True)

    flagged_pairs = load_flagged_pairs(args.audit_report, args.v2_audit_report)
    promotable_pairs = load_promotable_overrides(args.reclassification_review)
    allowset = load_vetted_allowset(args.allowlist_selection_file)
    records = discover_runs(args.source)
    selected_result = choose_top3_paired(records, flagged_pairs, promotable_pairs, allowset=allowset)
    selected = selected_result["selected"]
    under_target = selected_result["under_target"]
    summary = materialize_analysis(selected, args.output)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "selection_policy": {
            "subset_filter": ["csb_sdlc_*", "csb_org_*"],
            "pairing_rule": "same task_id baseline/mcp (independent recency-ranked pools)",
            "quality_rule": "auditable files present + output_tokens>0 + agent_execution_seconds>=15 + not flagged",
            "task_inclusion_rule": "at least 1 valid paired run; keep up to most recent 3",
        },
        "inputs": {
            "source": str(args.source),
            "audit_report": str(args.audit_report),
            "v2_audit_report": str(args.v2_audit_report),
            "reclassification_review": str(args.reclassification_review),
            "allowlist_selection_file": str(args.allowlist_selection_file) if args.allowlist_selection_file else None,
            "allowset_size": len(allowset) if allowset is not None else None,
            "flagged_pairs_count": len(flagged_pairs),
            "promotable_override_pairs_count": len(promotable_pairs),
            "discovered_runs_count": len(records),
        },
        "summary": summary,
        "under_target_3_tasks": sorted(under_target, key=lambda x: (x["subset"], x["suite"], x["task_id"])),
    }
    (args.output / "selection_manifest.json").write_text(json.dumps(manifest, indent=2))

    print(json.dumps({
        "output": str(args.output),
        "selected_tasks": summary["selected_tasks"],
        "selected_pairs": summary["selected_pairs"],
        "by_subset": summary["by_subset"],
        "by_variant_runs": summary["by_variant_runs"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

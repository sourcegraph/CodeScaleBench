#!/usr/bin/env python3
"""Retrieval evaluation pipeline: metrics, probes, taxonomy, and artifact emission.

Runs the full v1 retrieval evaluation pipeline on normalized retrieval events:
1. File-level IR metrics (precision, recall, MRR, nDCG, MAP)
2. Chunk-level relevance metrics with fallback flags
3. Utilization probe metrics (evidence usage correctness)
4. Error taxonomy labels and calibration slices
5. Task-level and run-level artifact emission

Usage:
    python3 scripts/retrieval_eval_pipeline.py --run-dir runs/staging/fix_haiku_20260223
    python3 scripts/retrieval_eval_pipeline.py --run-dir runs/staging --all
    python3 scripts/retrieval_eval_pipeline.py --events-dir runs/staging/fix_haiku_20260223/retrieval_events
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from csb_metrics.ir_metrics import (
    precision_at_k,
    recall_at_k,
    f1_at_k,
    mrr,
    ndcg_at_k,
    mean_average_precision,
    file_level_recall,
    context_efficiency,
    _normalize,
)

DEFAULT_K_VALUES = [1, 3, 5, 10]

# =========================================================================
# Stage 1: File-level IR metrics (US-003)
# =========================================================================

def compute_file_level_metrics(doc: dict, k_values: list[int] | None = None) -> dict:
    """Compute file-level IR metrics from normalized events.

    Returns metric dict with `computable: false` when ground truth is absent.
    """
    if k_values is None:
        k_values = DEFAULT_K_VALUES

    coverage = doc.get("coverage", {})
    gt = doc.get("ground_truth", {})
    gt_files = gt.get("files", [])
    events = doc.get("events", [])

    if not coverage.get("has_ground_truth", False) or not gt_files:
        return {"computable": False, "reason": "no_ground_truth"}

    # Build ordered retrieved file list (first-seen, unique)
    retrieved: list[str] = []
    seen: set[str] = set()
    for evt in events:
        for tf in evt.get("target_files", []):
            norm = _normalize(tf)
            if norm and norm not in seen:
                seen.add(norm)
                retrieved.append(norm)

    relevant = {_normalize(f) for f in gt_files}

    prec, rec, f1, ndcg_d = {}, {}, {}, {}
    for k in k_values:
        prec[k] = round(precision_at_k(retrieved, relevant, k), 4)
        rec[k] = round(recall_at_k(retrieved, relevant, k), 4)
        f1[k] = round(f1_at_k(retrieved, relevant, k), 4)
        ndcg_d[k] = round(ndcg_at_k(retrieved, relevant, k), 4)

    overlap = relevant & {_normalize(f) for f in retrieved}

    # Time-to-first-relevant
    summary = doc.get("summary", {})
    first_gt_step = summary.get("first_ground_truth_hit_step")
    ttfr_seconds: float | None = None
    ttfr_tokens: int | None = None
    if first_gt_step is not None:
        for evt in events:
            if evt["step_index"] == first_gt_step:
                ttfr_seconds = evt.get("elapsed_seconds")
                ttfr_tokens = evt.get("cumulative_tokens")
                break

    return {
        "computable": True,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "mrr": round(mrr(retrieved, relevant), 4),
        "ndcg": ndcg_d,
        "map_score": round(mean_average_precision(retrieved, relevant), 4),
        "file_recall": round(file_level_recall(retrieved, relevant), 4),
        "context_efficiency": round(context_efficiency(retrieved, relevant), 4),
        "n_retrieved": len(retrieved),
        "n_ground_truth": len(relevant),
        "n_overlap": len(overlap),
        "first_gt_hit_step": first_gt_step,
        "ttfr_seconds": ttfr_seconds,
        "ttfr_tokens": ttfr_tokens,
    }


# =========================================================================
# Stage 2: Chunk-level relevance metrics (US-004)
# =========================================================================

def compute_chunk_level_metrics(doc: dict) -> dict:
    """Compute chunk-level relevance metrics with fallback.

    When chunk-level ground truth (line ranges) is absent, returns
    ``resolution: "file_level_only"`` and a placeholder score of null.
    When present, computes overlap ratio between ground-truth line ranges
    and retrieved file events.

    Chunking assumption: ground-truth chunks are line ranges within files.
    A retrieval event "covers" a chunk if any target_file matches the
    chunk's file path. Finer sub-line matching requires structured diffs
    and is deferred to future schema versions.
    """
    coverage = doc.get("coverage", {})
    gt = doc.get("ground_truth", {})
    chunks = gt.get("chunks", [])
    events = doc.get("events", [])

    if not coverage.get("has_chunk_ground_truth", False) or not chunks:
        return {
            "resolution": "file_level_only",
            "chunk_recall": None,
            "chunks_total": 0,
            "chunks_hit": 0,
            "validity": "unsupported",
        }

    # Build set of retrieved files (normalized)
    retrieved_files: set[str] = set()
    for evt in events:
        for tf in evt.get("target_files", []):
            retrieved_files.add(_normalize(tf))

    # Check which chunks have their file accessed
    chunks_hit = 0
    for chunk in chunks:
        chunk_file = _normalize(chunk.get("file", ""))
        if chunk_file in retrieved_files:
            chunks_hit += 1

    chunk_recall = round(chunks_hit / len(chunks), 4) if chunks else 0.0

    return {
        "resolution": "chunk_level",
        "chunk_recall": chunk_recall,
        "chunks_total": len(chunks),
        "chunks_hit": chunks_hit,
        "validity": "file_match_only",
    }


# =========================================================================
# Stage 3: Utilization probe metrics (US-005)
# =========================================================================

def compute_utilization_probes(doc: dict) -> dict:
    """Compute utilization probe metrics.

    Measures whether retrieved evidence was actually used by the agent,
    not just retrieved. The "referenced file correctness" probe checks
    whether files the agent wrote to (file_write events) overlap with
    ground-truth files — indicating the agent acted on the right evidence.

    Probe (primary): read_overlap_with_relevant_files
        = |files_read ∩ relevant_files| / |relevant_files|

    Probe (proxy): write_overlap_with_relevant_files_proxy
        = |files_written ∩ relevant_files| / |relevant_files|

    Coverage flag: `probe_available` is false when no write events exist
    or no ground truth exists.
    """
    coverage = doc.get("coverage", {})
    gt = doc.get("ground_truth", {})
    gt_files = gt.get("files", [])
    expected_edit_files = gt.get("expected_edit_files", []) or []
    events = doc.get("events", [])

    if not coverage.get("has_ground_truth", False) or not gt_files:
        return {
            "probe_available": False,
            "reason": "no_ground_truth",
            "util_read_overlap_with_relevant_files": None,
            "util_write_overlap_with_relevant_files_proxy": None,
            "util_write_overlap_with_expected_edit_files": None,
            "util_read_before_write_ratio": None,
            "expected_edit_probe_available": False,
            "expected_edit_probe_reason": "no_ground_truth",
            "files_read": 0,
            "files_read_relevant": 0,
            "files_written": 0,
            "files_written_relevant": 0,
            "files_written_expected_edit": 0,
        }

    gt_normalized = {_normalize(f) for f in gt_files}
    expected_edit_normalized = {_normalize(f) for f in expected_edit_files if _normalize(f)}

    # Files read by agent (explicit file reads only; MCP read_file is normalized to file_read)
    read_files: set[str] = set()
    for evt in events:
        if evt.get("tool_category") == "file_read":
            for tf in evt.get("target_files", []):
                read_files.add(_normalize(tf))

    relevant_reads = read_files & gt_normalized
    read_overlap = round(len(relevant_reads) / len(gt_normalized), 4)

    # Files written by agent
    written_files: set[str] = set()
    for evt in events:
        if evt.get("tool_category") == "file_write":
            for tf in evt.get("target_files", []):
                written_files.add(_normalize(tf))

    # Proxy write-overlap metric against relevant files.
    relevant_writes = written_files & gt_normalized
    write_overlap_relevant = (
        round(len(relevant_writes) / len(gt_normalized), 4) if gt_normalized else None
    )

    # Optional stronger write-overlap metric against expected edit targets.
    expected_edit_probe_available = bool(expected_edit_normalized)
    expected_edit_probe_reason = None if expected_edit_probe_available else "no_expected_edit_files"
    expected_edit_write_overlap = None
    if expected_edit_probe_available:
        expected_edit_write_overlap = round(
            len(written_files & expected_edit_normalized) / len(expected_edit_normalized), 4
        )

    # Probe 2: read-before-write ratio
    # For each written file, check if it was read first (in an earlier step)
    read_files_by_step: dict[str, int] = {}  # file -> first read step
    for evt in events:
        if evt.get("tool_category") in ("file_read", "code_search", "file_search"):
            for tf in evt.get("target_files", []):
                nf = _normalize(tf)
                if nf not in read_files_by_step:
                    read_files_by_step[nf] = evt["step_index"]

    write_files_by_step: dict[str, int] = {}  # file -> first write step
    for evt in events:
        if evt.get("tool_category") == "file_write":
            for tf in evt.get("target_files", []):
                nf = _normalize(tf)
                if nf not in write_files_by_step:
                    write_files_by_step[nf] = evt["step_index"]

    read_before_write = 0
    for wf, w_step in write_files_by_step.items():
        if wf in read_files_by_step and read_files_by_step[wf] < w_step:
            read_before_write += 1

    rbw_ratio = round(read_before_write / len(write_files_by_step), 4) if write_files_by_step else None

    return {
        "probe_available": True,
        "reason": None,
        "util_read_overlap_with_relevant_files": read_overlap,
        "util_write_overlap_with_relevant_files_proxy": write_overlap_relevant,
        # Back-compat alias (deprecated): previously misinterpreted as generic utilization quality.
        "util_referenced_file_correctness": write_overlap_relevant,
        "util_write_overlap_with_expected_edit_files": expected_edit_write_overlap,
        "util_read_before_write_ratio": rbw_ratio,
        "expected_edit_probe_available": expected_edit_probe_available,
        "expected_edit_probe_reason": expected_edit_probe_reason,
        "files_read": len(read_files),
        "files_read_relevant": len(relevant_reads),
        "files_written": len(written_files),
        "files_written_relevant": len(relevant_writes),
        "files_written_expected_edit": len(written_files & expected_edit_normalized) if expected_edit_probe_available else 0,
    }


# =========================================================================
# Stage 4: Error taxonomy and calibration slices (US-006)
# =========================================================================

# Taxonomy labels
TAXONOMY_LABELS = {
    "irrelevant_retrieval": "Retrieved files that are not in ground truth",
    "missed_key_evidence": "Ground truth files never retrieved",
    "wrong_evidence_used": "Wrote to non-GT files (false positive actions)",
    "unused_correct_retrieval": "Retrieved GT files but never wrote to them",
    "ambiguity_near_miss": "Retrieved file is in same directory as GT file",
}


def compute_error_taxonomy(doc: dict) -> dict:
    """Classify retrieval errors into taxonomy labels.

    Labels assigned per-task:
    - irrelevant_retrieval: count of non-GT files retrieved
    - missed_key_evidence: count of GT files never retrieved
    - wrong_evidence_used: count of non-GT files written to
    - unused_correct_retrieval: count of GT files retrieved but not written
    - ambiguity_near_miss: count of retrieved files in same dir as GT file
    """
    coverage = doc.get("coverage", {})
    gt = doc.get("ground_truth", {})
    gt_files = gt.get("files", [])
    events = doc.get("events", [])

    if not coverage.get("has_ground_truth", False) or not gt_files:
        return {
            "computable": False,
            "reason": "no_ground_truth",
            "labels": {},
            "slices": {},
        }

    gt_normalized = {_normalize(f) for f in gt_files}

    # All retrieved files
    retrieved: set[str] = set()
    for evt in events:
        for tf in evt.get("target_files", []):
            retrieved.add(_normalize(tf))

    # Written files
    written: set[str] = set()
    for evt in events:
        if evt.get("tool_category") == "file_write":
            for tf in evt.get("target_files", []):
                written.add(_normalize(tf))

    # Taxonomy labels
    irrelevant = retrieved - gt_normalized
    missed = gt_normalized - retrieved
    wrong_written = written - gt_normalized
    retrieved_gt = retrieved & gt_normalized
    unused_correct = retrieved_gt - written

    # Ambiguity: retrieved files in same directory as a GT file
    gt_dirs = {f.rsplit("/", 1)[0] if "/" in f else "" for f in gt_normalized}
    near_miss = set()
    for rf in irrelevant:
        rf_dir = rf.rsplit("/", 1)[0] if "/" in rf else ""
        if rf_dir in gt_dirs and rf_dir:
            near_miss.add(rf)

    labels = {
        "irrelevant_retrieval": len(irrelevant),
        "missed_key_evidence": len(missed),
        "wrong_evidence_used": len(wrong_written),
        "unused_correct_retrieval": len(unused_correct),
        "ambiguity_near_miss": len(near_miss),
    }

    # Calibration slices
    # Slice 1: candidate set size (how many unique files were retrieved)
    candidate_size = len(retrieved)
    if candidate_size <= 5:
        size_slice = "small"
    elif candidate_size <= 20:
        size_slice = "medium"
    else:
        size_slice = "large"

    # Slice 2: evidence type (dominant tool category used)
    cat_counts: dict[str, int] = {}
    for evt in events:
        cat = evt.get("tool_category", "other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    dominant_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "none"

    slices = {
        "candidate_set_size": size_slice,
        "candidate_set_count": candidate_size,
        "dominant_retrieval_category": dominant_cat,
        "evidence_type": "mcp" if any(e.get("is_mcp") for e in events) else "local",
    }

    return {
        "computable": True,
        "labels": labels,
        "slices": slices,
    }


# =========================================================================
# Stage 5: Task and run-level artifact assembly (US-007)
# =========================================================================

def assemble_task_artifact(
    doc: dict,
    file_metrics: dict,
    chunk_metrics: dict,
    util_probes: dict,
    error_taxonomy: dict,
) -> dict:
    """Assemble a complete task-level retrieval metric artifact."""
    provenance = doc.get("provenance", {})
    coverage = doc.get("coverage", {})
    summary = doc.get("summary", {})

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance,
        "coverage": coverage,
        "event_summary": summary,
        "file_level_metrics": file_metrics,
        "chunk_level_metrics": chunk_metrics,
        "utilization_probes": util_probes,
        "error_taxonomy": error_taxonomy,
    }


def assemble_run_summary(
    task_artifacts: list[dict],
    event_file_count: int,
    skipped_no_gt: int,
) -> dict:
    """Assemble run-level summary from task artifacts."""
    computable = [a for a in task_artifacts if a["file_level_metrics"].get("computable")]

    # Aggregate file-level metrics
    file_agg = _aggregate_scalar_metrics(computable, "file_level_metrics")

    # Aggregate utilization probes
    util_available = [a for a in computable if a["utilization_probes"].get("probe_available")]
    util_agg = {}
    if util_available:
        read_overlap = [a["utilization_probes"]["util_read_overlap_with_relevant_files"]
                        for a in util_available
                        if a["utilization_probes"].get("util_read_overlap_with_relevant_files") is not None]
        if read_overlap:
            util_agg["util_read_overlap_with_relevant_files"] = _stat_summary(read_overlap)

        write_overlap_rel = [a["utilization_probes"]["util_write_overlap_with_relevant_files_proxy"]
                             for a in util_available
                             if a["utilization_probes"].get("util_write_overlap_with_relevant_files_proxy") is not None]
        if write_overlap_rel:
            util_agg["util_write_overlap_with_relevant_files_proxy"] = _stat_summary(write_overlap_rel)
            # Back-compat alias
            util_agg["util_referenced_file_correctness"] = util_agg["util_write_overlap_with_relevant_files_proxy"]

        write_overlap_edit = [a["utilization_probes"]["util_write_overlap_with_expected_edit_files"]
                              for a in util_available
                              if a["utilization_probes"].get("util_write_overlap_with_expected_edit_files") is not None]
        if write_overlap_edit:
            util_agg["util_write_overlap_with_expected_edit_files"] = _stat_summary(write_overlap_edit)

        ref_corr = [a["utilization_probes"]["util_referenced_file_correctness"]
                     for a in util_available
                     if a["utilization_probes"].get("util_referenced_file_correctness") is not None]
        rbw = [a["utilization_probes"]["util_read_before_write_ratio"]
               for a in util_available
               if a["utilization_probes"].get("util_read_before_write_ratio") is not None]
        if rbw:
            util_agg["util_read_before_write_ratio"] = _stat_summary(rbw)
        util_agg["n_tasks_with_probes"] = len(util_available)
        util_agg["n_tasks_with_expected_edit_probe"] = len([
            a for a in util_available if a["utilization_probes"].get("expected_edit_probe_available")
        ])

    # Aggregate error taxonomy
    tax_computable = [a for a in computable if a["error_taxonomy"].get("computable")]
    tax_agg = {}
    if tax_computable:
        for label in TAXONOMY_LABELS:
            vals = [a["error_taxonomy"]["labels"].get(label, 0) for a in tax_computable]
            tax_agg[label] = _stat_summary(vals)

        # Slice distributions
        slice_dist: dict[str, dict[str, int]] = {}
        for a in tax_computable:
            slices = a["error_taxonomy"].get("slices", {})
            for sk, sv in slices.items():
                if isinstance(sv, str):
                    slice_dist.setdefault(sk, {})
                    slice_dist[sk][sv] = slice_dist[sk].get(sv, 0) + 1
        tax_agg["slice_distributions"] = slice_dist

    # Chunk metrics coverage
    chunk_capable = [a for a in task_artifacts if a["chunk_level_metrics"].get("resolution") == "chunk_level"]

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_event_files": event_file_count,
        "computable_tasks": len(computable),
        "skipped_no_ground_truth": skipped_no_gt,
        "chunk_capable_tasks": len(chunk_capable),
        "file_level_aggregates": file_agg,
        "utilization_aggregates": util_agg,
        "error_taxonomy_aggregates": tax_agg,
    }


def _stat_summary(values: list[float | int]) -> dict:
    if not values:
        return {"mean": None, "std": None, "median": None, "n": 0}
    return {
        "mean": round(statistics.mean(values), 4),
        "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "median": round(statistics.median(values), 4),
        "n": len(values),
    }


def _aggregate_scalar_metrics(artifacts: list[dict], section_key: str) -> dict:
    """Aggregate scalar metrics from a section of task artifacts."""
    if not artifacts:
        return {"n_tasks": 0}

    metrics = [a[section_key] for a in artifacts if a[section_key].get("computable")]
    if not metrics:
        return {"n_tasks": 0}

    scalars = {
        "mrr": [m["mrr"] for m in metrics],
        "map_score": [m["map_score"] for m in metrics],
        "file_recall": [m["file_recall"] for m in metrics],
        "context_efficiency": [m["context_efficiency"] for m in metrics],
    }

    # @K metrics
    k_values = set()
    for m in metrics:
        k_values.update(m.get("precision", {}).keys())
    for k in sorted(k_values, key=lambda x: int(x)):
        k_int = int(k)
        scalars[f"precision@{k_int}"] = [m["precision"].get(k, m["precision"].get(k_int, 0.0)) for m in metrics]
        scalars[f"recall@{k_int}"] = [m["recall"].get(k, m["recall"].get(k_int, 0.0)) for m in metrics]
        scalars[f"f1@{k_int}"] = [m["f1"].get(k, m["f1"].get(k_int, 0.0)) for m in metrics]
        scalars[f"ndcg@{k_int}"] = [m["ndcg"].get(k, m["ndcg"].get(k_int, 0.0)) for m in metrics]

    result: dict = {}
    for name, values in scalars.items():
        result[name] = _stat_summary(values)

    # Time-to-context
    ttfr = [m["ttfr_seconds"] for m in metrics if m.get("ttfr_seconds") is not None]
    if ttfr:
        result["ttfr_seconds"] = _stat_summary(ttfr)

    result["_totals"] = {
        "n_tasks": len(metrics),
        "mean_retrieved": round(statistics.mean([m["n_retrieved"] for m in metrics]), 1),
        "mean_ground_truth": round(statistics.mean([m["n_ground_truth"] for m in metrics]), 1),
        "mean_overlap": round(statistics.mean([m["n_overlap"] for m in metrics]), 1),
    }

    return result


# =========================================================================
# Event file discovery
# =========================================================================

def discover_event_files(path: Path) -> list[Path]:
    return sorted(path.rglob("*.retrieval_events.json"))


# =========================================================================
# CLI
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full retrieval evaluation pipeline on normalized events.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Pipeline stages:\n"
            "  1. File-level IR metrics (precision, recall, MRR, nDCG, MAP)\n"
            "  2. Chunk-level relevance metrics (with file_level_only fallback)\n"
            "  3. Utilization probes (referenced file correctness, read-before-write)\n"
            "  4. Error taxonomy (5 labels) and calibration slices (2 dimensions)\n"
            "  5. Task-level + run-level artifact emission\n"
        ),
    )
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Run directory containing retrieval_events/ subdirectory.",
    )
    parser.add_argument(
        "--events-dir", type=Path, default=None,
        help="Direct path to a retrieval_events/ directory.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Walk all runs under --run-dir.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Write per-task and run-summary artifacts here. Default: alongside retrieval_events/.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written without writing files.",
    )
    args = parser.parse_args()

    if not args.run_dir and not args.events_dir:
        parser.error("Provide --run-dir or --events-dir")

    # Discover event files
    event_files: list[Path] = []
    events_root: Path | None = None

    if args.events_dir:
        event_files = discover_event_files(args.events_dir)
        events_root = args.events_dir
    elif args.all:
        for rd in sorted(args.run_dir.iterdir()):
            if rd.is_dir():
                evdir = rd / "retrieval_events"
                if evdir.is_dir():
                    event_files.extend(discover_event_files(evdir))
                    if events_root is None:
                        events_root = evdir
        direct = args.run_dir / "retrieval_events"
        if direct.is_dir():
            event_files.extend(discover_event_files(direct))
            if events_root is None:
                events_root = direct
    else:
        evdir = args.run_dir / "retrieval_events"
        if evdir.is_dir():
            event_files = discover_event_files(evdir)
            events_root = evdir

    if not event_files:
        print("No retrieval event files found. Run normalize_retrieval_events.py first.", file=sys.stderr)
        sys.exit(0)

    # Process each task
    task_artifacts: list[dict] = []
    skipped_no_gt = 0
    skipped_parse = 0

    for ef in event_files:
        try:
            doc = json.loads(ef.read_text())
        except (json.JSONDecodeError, OSError):
            skipped_parse += 1
            continue

        # Run all stages
        file_metrics = compute_file_level_metrics(doc)
        chunk_metrics = compute_chunk_level_metrics(doc)
        util_probes = compute_utilization_probes(doc)
        error_taxonomy = compute_error_taxonomy(doc)

        artifact = assemble_task_artifact(
            doc, file_metrics, chunk_metrics, util_probes, error_taxonomy,
        )
        task_artifacts.append(artifact)

        if not file_metrics.get("computable"):
            skipped_no_gt += 1

        # Write task-level artifact
        prov = doc.get("provenance", {})
        task_name = prov.get("task_name", ef.stem.replace(".retrieval_events", ""))
        config_name = prov.get("config_name", "unknown")
        run_id = prov.get("run_id", "unknown_run")
        if args.output_dir:
            if args.all:
                out_dir = args.output_dir / run_id / config_name
            else:
                out_dir = args.output_dir / config_name
        else:
            out_dir = ef.parent
        out_path = out_dir / f"{task_name}.retrieval_metrics.json"

        if args.dry_run:
            computable = "yes" if file_metrics.get("computable") else "no"
            chunk_res = chunk_metrics.get("resolution", "?")
            probe_avail = "yes" if util_probes.get("probe_available") else "no"
            print(f"[dry-run] {task_name} ({config_name}): "
                  f"computable={computable} chunk={chunk_res} probes={probe_avail}")
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(artifact, indent=2) + "\n")

    # Write run-level summary
    run_summary = assemble_run_summary(task_artifacts, len(event_files), skipped_no_gt)

    if args.output_dir:
        summary_path = args.output_dir / "run_retrieval_summary.json"
    elif args.all and args.run_dir and not args.events_dir:
        # In --all mode this summary spans multiple runs; keep it out of any single run directory.
        summary_path = args.run_dir / "retrieval_events_aggregate" / "run_retrieval_summary.json"
    elif events_root:
        summary_path = events_root / "run_retrieval_summary.json"
    else:
        summary_path = Path("run_retrieval_summary.json")

    if args.dry_run:
        print(f"[dry-run] Would write run summary to: {summary_path}")
    else:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(run_summary, indent=2) + "\n")

    # Print summary
    computable_count = len([a for a in task_artifacts if a["file_level_metrics"].get("computable")])
    print(f"\nPipeline complete: {len(event_files)} event files -> "
          f"{computable_count} computable, {skipped_no_gt} no GT, {skipped_parse} parse errors",
          file=sys.stderr)

    if computable_count > 0:
        fa = run_summary.get("file_level_aggregates", {})
        print(f"  file_recall: {fa.get('file_recall', {}).get('mean', 'N/A')}", file=sys.stderr)
        print(f"  MRR: {fa.get('mrr', {}).get('mean', 'N/A')}", file=sys.stderr)
        ua = run_summary.get("utilization_aggregates", {})
        if ua.get("n_tasks_with_probes"):
            print(f"  util_read_overlap_relevant: {ua.get('util_read_overlap_with_relevant_files', {}).get('mean', 'N/A')}", file=sys.stderr)

    # Also print summary JSON to stdout
    print(json.dumps(run_summary, indent=2))


if __name__ == "__main__":
    main()

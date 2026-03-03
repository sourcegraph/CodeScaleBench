#!/usr/bin/env python3
"""Validate the context retrieval agent against ContextBench.

ContextBench (https://github.com/EuniAI/ContextBench) is an external
benchmark with 1,136 human-annotated SWE-bench tasks measuring context
retrieval quality at file/symbol/span/edit-location granularity.

This script:
1. Loads ContextBench tasks (from Hugging Face or local parquet)
2. Runs our context_retrieval_agent on each task
3. Converts output to ContextBench trajectory format
4. Evaluates against human-annotated gold contexts
5. Reports file recall, precision, and F1

Environment variables:
    ANTHROPIC_API_KEY           Required.
    SOURCEGRAPH_ACCESS_TOKEN    Required for deepsearch/hybrid backends.
    CCB_REPO_CACHE              Repo clone cache (default: ~/.cache/ccb_repos)

Usage:
    # Install ContextBench first
    pip install contextbench datasets

    # Download gold data
    python3 scripts/validate_on_contextbench.py --download-data

    # Quick pilot (5 tasks)
    python3 scripts/validate_on_contextbench.py --sample 5 --verbose

    # Medium pilot (50 tasks)
    python3 scripts/validate_on_contextbench.py --sample 50

    # Full verified subset (500 tasks)
    python3 scripts/validate_on_contextbench.py --verified

    # Custom backend/model
    python3 scripts/validate_on_contextbench.py --sample 10 \\
        --model claude-haiku-4-5-20251001 --backend local
"""

import argparse
import concurrent.futures
import json
import logging
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("validate_on_contextbench")

# Default paths
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "contextbench"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "contextbench"
REPO_CACHE = Path(os.environ.get("CCB_REPO_CACHE", str(Path.home() / ".cache" / "ccb_repos")))


def download_data(data_dir: Path = DATA_DIR) -> None:
    """Download ContextBench dataset from Hugging Face."""
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        from datasets import load_dataset
    except ImportError:
        log.error("Install datasets: pip install datasets")
        sys.exit(1)

    # Full dataset
    full_path = data_dir / "full.parquet"
    if not full_path.exists():
        log.info("Downloading ContextBench full dataset...")
        ds = load_dataset("Contextbench/ContextBench", "default")
        ds["train"].to_parquet(str(full_path))
        log.info("Saved: %s", full_path)
    else:
        log.info("Already exists: %s", full_path)

    # Verified subset
    verified_path = data_dir / "verified.parquet"
    if not verified_path.exists():
        log.info("Downloading ContextBench verified subset...")
        ds = load_dataset("Contextbench/ContextBench", "contextbench_verified")
        ds["train"].to_parquet(str(verified_path))
        log.info("Saved: %s", verified_path)
    else:
        log.info("Already exists: %s", verified_path)


def _infer_language(instance_id: str, task: Dict) -> str:
    """Infer primary language from task metadata."""
    # Try explicit field first
    lang = task.get("language", "")
    if lang:
        return lang.lower()
    # Infer from repo name patterns
    repo = task.get("repo", task.get("repo_url", ""))
    iid = instance_id.lower()
    lang_hints = {
        "django": "python", "flask": "python", "scikit": "python",
        "pandas": "python", "numpy": "python", "sympy": "python",
        "requests": "python", "sphinx": "python", "pytest": "python",
        "astropy": "python", "matplotlib": "python", "pylint": "python",
        "spring": "java", "kafka": "java",
        "rust": "rust", "servo": "rust",
        "react": "javascript", "express": "javascript", "node": "javascript",
        "typescript": "typescript", "angular": "typescript",
        "rails": "ruby",
        "go": "go", "kubernetes": "go",
    }
    for pattern, lang in lang_hints.items():
        if pattern in iid or pattern in repo.lower():
            return lang
    return "unknown"


def _gold_context_size(task: Dict) -> str:
    """Categorize gold context complexity: small/medium/large.
    
    Counts unique files in ContextBench's gold_context (human-annotated spans).
    """
    # Extract from gold_context (ContextBench's human annotations)
    gc_str = task.get("gold_context", "[]")
    gold_files = set()
    try:
        if isinstance(gc_str, str):
            gc = json.loads(gc_str)
        else:
            gc = gc_str
        for item in gc:
            if isinstance(item, dict) and "file" in item:
                gold_files.add(item["file"])
    except (json.JSONDecodeError, TypeError):
        pass
    
    n = len(gold_files)
    if n <= 2:
        return "small"
    elif n <= 5:
        return "medium"
    else:
        return "large"


def stratified_sample(
    tasks: List[Dict[str, Any]],
    n: int,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Stratified sampling across language, context complexity.

    Ensures coverage across programming languages and gold context sizes.
    """
    rng = random.Random(seed)

    # Group by (language, complexity)
    strata: Dict[Tuple, List[Dict]] = {}
    for task in tasks:
        iid = task.get("instance_id", "")
        lang = _infer_language(iid, task)
        complexity = _gold_context_size(task)
        key = (lang, complexity)
        strata.setdefault(key, []).append(task)

    # Proportional allocation with minimum 1 per non-empty stratum
    n_strata = len(strata)
    if n_strata == 0:
        return []

    # Allocate proportionally
    total = sum(len(v) for v in strata.values())
    allocation = {}
    remaining = n
    for key, group in sorted(strata.items(), key=lambda x: len(x[1]), reverse=True):
        share = max(1, round(n * len(group) / total))
        share = min(share, len(group), remaining)
        allocation[key] = share
        remaining -= share
        if remaining <= 0:
            break

    # Distribute any remainder to largest strata
    for key in sorted(strata.keys(), key=lambda k: len(strata[k]), reverse=True):
        if remaining <= 0:
            break
        can_add = len(strata[key]) - allocation.get(key, 0)
        if can_add > 0:
            add = min(can_add, remaining)
            allocation[key] = allocation.get(key, 0) + add
            remaining -= add

    # Sample from each stratum
    sampled = []
    for key, count in allocation.items():
        group = strata[key]
        sampled.extend(rng.sample(group, min(count, len(group))))

    rng.shuffle(sampled)
    log.info(
        "Stratified sample: %d tasks from %d strata (requested %d)",
        len(sampled), len(allocation), n,
    )
    for key, count in sorted(allocation.items()):
        log.info("  %s: %d tasks", key, count)

    return sampled


# Repos that overlap with CCB benchmark tasks — get 2x sampling weight
CCB_OVERLAP_REPOS = [
    "django", "kubernetes", "flask", "pandas", "kafka",
    "pytorch", "numpy", "scikit-learn", "sympy", "requests",
]


def ccb_weighted_sample(
    tasks: List[Dict[str, Any]],
    n: int,
    seed: int = 42,
    hard_floor: float = 0.20,
) -> List[Dict[str, Any]]:
    """Stratified sample with CCB repo boost and difficulty floor.

    - CCB-overlap strata get 2x allocation in proportional budgeting
    - At least `hard_floor` fraction are hard cases (>5 gold files)
    """
    rng = random.Random(seed)

    def _is_ccb_overlap(t: Dict) -> bool:
        repo = t.get("repo", t.get("repo_url", "")).lower()
        return any(r in repo for r in CCB_OVERLAP_REPOS)

    # Group by (language, complexity) — same as stratified_sample
    strata: Dict[Tuple, List[Dict]] = {}
    for task in tasks:
        iid = task.get("instance_id", "")
        lang = _infer_language(iid, task)
        complexity = _gold_context_size(task)
        key = (lang, complexity)
        strata.setdefault(key, []).append(task)

    if not strata:
        return []

    # Compute effective weight per stratum: base count * (2 if has CCB overlap)
    effective_sizes = {}
    for key, group in strata.items():
        ccb_count = sum(1 for t in group if _is_ccb_overlap(t))
        # Boost: CCB-heavy strata get proportionally more allocation
        effective_sizes[key] = len(group) + ccb_count  # +1 per CCB task = ~2x

    total_eff = sum(effective_sizes.values())

    # Proportional allocation with CCB boost baked in
    allocation = {}
    remaining = n
    for key in sorted(strata.keys(), key=lambda k: effective_sizes[k], reverse=True):
        share = max(1, round(n * effective_sizes[key] / total_eff))
        share = min(share, len(strata[key]), remaining)
        allocation[key] = share
        remaining -= share
        if remaining <= 0:
            break

    # Distribute remainder to largest effective strata
    for key in sorted(strata.keys(), key=lambda k: effective_sizes[k], reverse=True):
        if remaining <= 0:
            break
        can_add = len(strata[key]) - allocation.get(key, 0)
        if can_add > 0:
            add = min(can_add, remaining)
            allocation[key] = allocation.get(key, 0) + add
            remaining -= add

    # Within each stratum, prefer CCB-overlap tasks first, then fill randomly
    sampled = []
    for key, count in allocation.items():
        group = strata[key]
        ccb_tasks = [t for t in group if _is_ccb_overlap(t)]
        other_tasks = [t for t in group if not _is_ccb_overlap(t)]
        rng.shuffle(ccb_tasks)
        rng.shuffle(other_tasks)
        # Take CCB tasks first, then fill from others
        pick = (ccb_tasks + other_tasks)[:count]
        sampled.extend(pick)

    rng.shuffle(sampled)

    # Ensure hard-case floor (>5 gold files)
    hard = [t for t in sampled if _gold_context_size(t) == "large"]
    min_hard = max(1, int(n * hard_floor))

    if len(hard) < min_hard:
        seen_ids = {t.get("instance_id", id(t)) for t in sampled}
        hard_pool = [t for t in tasks
                     if _gold_context_size(t) == "large"
                     and t.get("instance_id", id(t)) not in seen_ids]
        rng.shuffle(hard_pool)
        needed = min_hard - len(hard)
        sampled.extend(hard_pool[:needed])

    # Trim to target size
    if len(sampled) > n:
        sampled = sampled[:n]

    log.info(
        "CCB-weighted sample: %d tasks from %d strata (requested %d)",
        len(sampled), len(allocation), n,
    )
    n_ccb = sum(1 for t in sampled if _is_ccb_overlap(t))
    n_hard = sum(1 for t in sampled if _gold_context_size(t) == "large")
    log.info("  CCB-overlap: %d/%d, hard cases: %d/%d", n_ccb, len(sampled), n_hard, len(sampled))

    return sampled


def load_tasks(
    data_dir: Path = DATA_DIR,
    verified: bool = False,
    sample: int = 0,
    stratified: bool = True,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """Load ContextBench tasks from parquet.

    Args:
        data_dir: Path to data directory with parquet files.
        verified: Use verified subset (500) vs full (1136).
        sample: Number of tasks to sample (0 = all).
        stratified: Use stratified sampling across language/complexity.
        seed: Random seed.

    Returns list of dicts with: instance_id, repo, commit, problem_statement,
    patch, gold_files, etc.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError:
        log.error("Install pyarrow: pip install pyarrow")
        sys.exit(1)

    fname = "verified.parquet" if verified else "full.parquet"
    path = data_dir / fname
    if not path.exists():
        log.error("Dataset not found: %s. Run --download-data first.", path)
        sys.exit(1)

    table = pq.read_table(str(path))
    df = table.to_pydict()

    # Convert columnar dict to list of row dicts
    n_rows = len(next(iter(df.values())))
    tasks = []
    keys = list(df.keys())
    for i in range(n_rows):
        row = {k: df[k][i] for k in keys}
        tasks.append(row)

    log.info("Loaded %d tasks from %s", len(tasks), fname)

    if sample > 0 and sample < len(tasks):
        if stratified:
            tasks = stratified_sample(tasks, sample, seed)
        else:
            rng = random.Random(seed)
            tasks = rng.sample(tasks, sample)
            log.info("Random sampled %d tasks (seed=%d)", len(tasks), seed)

    return tasks


def clone_for_contextbench(
    repo_url: str, commit: str, cache_dir: Path = REPO_CACHE
) -> Optional[Path]:
    """Clone a repo at a specific commit for ContextBench evaluation.

    ContextBench tasks reference repos by URL + commit hash.
    """
    # Extract org/repo from URL
    # e.g., "https://github.com/django/django" -> "django__django"
    repo_slug = repo_url.rstrip("/").split("github.com/")[-1].replace("/", "__")
    repo_dir = cache_dir / "contextbench" / f"{repo_slug}__{commit[:8]}"

    if repo_dir.exists() and (repo_dir / ".git").exists():
        return repo_dir

    repo_dir.mkdir(parents=True, exist_ok=True)
    log.info("Cloning %s @ %s", repo_url, commit[:8])
    try:
        # Clone and checkout specific commit
        subprocess.run(
            ["git", "clone", "--no-checkout", repo_url, str(repo_dir)],
            check=True, capture_output=True, text=True, timeout=300,
        )
        subprocess.run(
            ["git", "checkout", commit],
            check=True, capture_output=True, text=True,
            timeout=60, cwd=str(repo_dir),
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        log.error("Clone failed: %s @ %s: %s", repo_url, commit, e)
        return None
    return repo_dir


def run_retrieval_agent_on_cb_task(
    task: Dict[str, Any],
    repo_path: Path,
    client: Any,
    model: str,
    backend: str,
    sg: Any = None,
    verbose: bool = False,
    use_cli: bool = False,
    prune: bool = False,
) -> Dict[str, Any]:
    """Run our retrieval agent on a ContextBench task.

    Returns the agent's oracle output.
    """
    from context_retrieval_agent import (
        run_agent, run_agent_cli, prune_with_haiku,
    )

    # Build a CCB-style context dict from ContextBench task
    instance_id = task.get("instance_id", "")
    problem = task.get("problem_statement", "")

    # Extract repo name from instance_id (e.g., "django__django-12345" -> "django/django")
    parts = instance_id.rsplit("-", 1)
    repo_name = parts[0].replace("__", "/") if parts else instance_id

    ctx = {
        "task_dir": "",
        "task_name": instance_id,
        "suite_name": "contextbench",
        "seed_prompt": problem,
        "instruction": problem,
        "check_types": ["file_set_match"],
    }

    repo_paths = {repo_name: repo_path, instance_id: repo_path}

    if use_cli:
        oracle, metadata = run_agent_cli(
            ctx, repo_paths,
            model=model, backend=backend,
            verbose=verbose,
            prune=prune,
        )
    else:
        oracle, metadata = run_agent(
            ctx, repo_paths, client,
            model=model, backend=backend,
            sg=sg, verbose=verbose,
        )
        # Prune for SDK mode too
        if prune and oracle.get("files"):
            oracle = prune_with_haiku(
                oracle, problem, use_cli=use_cli, verbose=verbose,
            )
            metadata["pruned"] = True

    return {
        "oracle": oracle,
        "metadata": metadata,
        "instance_id": instance_id,
    }


def convert_to_trajectory(
    instance_id: str,
    oracle: Dict[str, Any],
    model_patch: str = "",
) -> Dict[str, Any]:
    """Convert our oracle output to ContextBench trajectory format.

    Handles both new curator format (files as strings, chunks as line ranges)
    and legacy format (files as {repo, path} dicts).

    ContextBench expects:
    {
        "instance_id": "owner__repo-1234",
        "traj_data": {
            "pred_steps": [{"files": [...], "spans": {}, "symbols": {}}],
            "pred_files": ["path/to/file1.py", ...],
            "pred_spans": {"path": [{"start": N, "end": M}]}
        },
        "model_patch": "..."
    }
    """
    # Handle both string and dict file formats
    files = []
    for f in oracle.get("files", []):
        if isinstance(f, str) and f:
            files.append(f)
        elif isinstance(f, dict) and f.get("path"):
            files.append(f["path"])

    # Build pred_spans from chunks (new curator format) or leave empty
    pred_spans: Dict[str, List[Dict[str, int]]] = {}
    for chunk in oracle.get("chunks", []):
        if isinstance(chunk, dict) and "file" in chunk:
            path = chunk["file"]
            start = chunk.get("line_start", 0)
            end = chunk.get("line_end", 0)
            if path and start and end:
                pred_spans.setdefault(path, []).append({"start": start, "end": end})

    return {
        "instance_id": instance_id,
        "traj_data": {
            "pred_steps": [{
                "files": files,
                "spans": pred_spans,
                "symbols": {},
            }],
            "pred_files": files,
            "pred_spans": pred_spans,
        },
        "model_patch": model_patch,
    }


def evaluate_trajectories(
    gold_path: Path,
    traj_path: Path,
    out_path: Path,
) -> Dict[str, Any]:
    """Run ContextBench evaluation.

    Returns aggregate metrics dict.
    """
    cmd = [
        sys.executable, "-m", "contextbench.evaluate",
        "--gold", str(gold_path),
        "--pred", str(traj_path),
        "--out", str(out_path),
    ]
    log.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            log.error("ContextBench eval failed:\n%s", result.stderr[:2000])
            return {}
        # Parse results from output file
        if out_path.exists():
            results = []
            for line in out_path.read_text().splitlines():
                if line.strip():
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return {"results": results, "stderr": result.stderr[:2000]}
    except subprocess.TimeoutExpired:
        log.error("ContextBench eval timed out")
    except FileNotFoundError:
        log.error("contextbench not installed. pip install contextbench")
    return {}


def compute_simple_file_metrics(
    tasks: List[Dict],
    trajectories: List[Dict],
) -> Dict[str, float]:
    """Compute file-level metrics without needing ContextBench installed.

    Compares predicted files against gold files from the dataset.
    """
    recalls = []
    precisions = []

    for task, traj in zip(tasks, trajectories):
        # Get gold files from ContextBench's gold_context (human annotations)
        # gold_context is a JSON list of span annotations: [{file, start_line, end_line, content}, ...]
        gc_str = task.get("gold_context", "[]")
        gold_files = set()
        try:
            if isinstance(gc_str, str):
                gc = json.loads(gc_str)
            else:
                gc = gc_str
            for item in gc:
                if isinstance(item, dict) and "file" in item:
                    gold_files.add(item["file"])
        except (json.JSONDecodeError, TypeError):
            pass

        pred_files = set(traj.get("traj_data", {}).get("pred_files", []))

        if not gold_files:
            continue

        # Normalize paths (strip leading /)
        gold_norm = {f.lstrip("/") for f in gold_files if f}
        pred_norm = {f.lstrip("/") for f in pred_files if f}

        inter = gold_norm & pred_norm
        recall = len(inter) / len(gold_norm) if gold_norm else 0
        precision = len(inter) / len(pred_norm) if pred_norm else 0
        recalls.append(recall)
        precisions.append(precision)

    if not recalls:
        return {"file_recall": 0, "file_precision": 0, "file_f1": 0, "n_evaluated": 0}

    avg_recall = sum(recalls) / len(recalls)
    avg_precision = sum(precisions) / len(precisions)
    f1 = (2 * avg_recall * avg_precision / (avg_recall + avg_precision)
           if (avg_recall + avg_precision) > 0 else 0)

    return {
        "file_recall": round(avg_recall, 4),
        "file_precision": round(avg_precision, 4),
        "file_f1": round(f1, 4),
        "n_evaluated": len(recalls),
    }


def compute_chunk_metrics(
    tasks: List[Dict],
    trajectories: List[Dict],
) -> Dict[str, float]:
    """Compute line-level overlap metrics against ContextBench gold spans.

    Compares agent chunks (from pred_spans) against gold_context line ranges.
    Returns chunk recall and precision.
    """
    chunk_recalls = []
    chunk_precisions = []

    for task, traj in zip(tasks, trajectories):
        # Extract gold spans from ContextBench gold_context
        gc_str = task.get("gold_context", "[]")
        try:
            if isinstance(gc_str, str):
                gc = json.loads(gc_str)
            else:
                gc = gc_str
        except (json.JSONDecodeError, TypeError):
            continue

        gold_spans: Dict[str, Set[int]] = {}
        for item in gc:
            if isinstance(item, dict) and "file" in item:
                f = item["file"].lstrip("/")
                start = item.get("start_line", 0)
                end = item.get("end_line", 0)
                if start and end:
                    gold_spans.setdefault(f, set()).update(range(start, end + 1))

        if not gold_spans:
            continue

        # Extract predicted spans from trajectory
        pred_spans_raw = traj.get("traj_data", {}).get("pred_spans", {})
        pred_spans: Dict[str, Set[int]] = {}
        for f, ranges in pred_spans_raw.items():
            f_norm = f.lstrip("/")
            for r in ranges:
                start = r.get("start", r.get("start_line", 0))
                end = r.get("end", r.get("end_line", 0))
                if start and end:
                    pred_spans.setdefault(f_norm, set()).update(range(start, end + 1))

        if not pred_spans:
            continue

        # Compute per-file line overlap
        total_gold_lines = sum(len(lines) for lines in gold_spans.values())
        total_pred_lines = sum(len(lines) for lines in pred_spans.values())
        overlap_lines = 0
        for f, gold_lines in gold_spans.items():
            if f in pred_spans:
                overlap_lines += len(gold_lines & pred_spans[f])

        if total_gold_lines > 0:
            chunk_recalls.append(overlap_lines / total_gold_lines)
        if total_pred_lines > 0:
            chunk_precisions.append(overlap_lines / total_pred_lines)

    if not chunk_recalls:
        return {"chunk_recall": 0, "chunk_precision": 0, "chunk_f1": 0, "n_chunk_evaluated": 0}

    avg_recall = sum(chunk_recalls) / len(chunk_recalls)
    avg_prec = sum(chunk_precisions) / len(chunk_precisions) if chunk_precisions else 0
    f1 = (2 * avg_recall * avg_prec / (avg_recall + avg_prec)
           if (avg_recall + avg_prec) > 0 else 0)

    return {
        "chunk_recall": round(avg_recall, 4),
        "chunk_precision": round(avg_prec, 4),
        "chunk_f1": round(f1, 4),
        "n_chunk_evaluated": len(chunk_recalls),
    }


# Default composite weights
DEFAULT_COMPOSITE_WEIGHTS = {
    "file_recall": 0.40,
    "file_precision": 0.30,
    "chain_recall": 0.20,
    "symbol_recall": 0.10,
}

COMPOSITE_THRESHOLD = 0.65  # Go/no-go threshold
STRATUM_WARNING_THRESHOLD = 0.50  # Warn if any stratum is below this


def compute_composite_score(
    file_recall: float,
    file_precision: float,
    chain_recall: float = 0.0,
    symbol_recall: float = 0.0,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """Compute weighted composite score for go/no-go decision.

    Default weights: file_recall=0.40, file_precision=0.30,
                     chain_recall=0.20, symbol_recall=0.10

    When chain_recall or symbol_recall are unavailable (None), their
    weight is redistributed proportionally to the available components
    so the score stays on a 0-1 scale.
    """
    w = weights or DEFAULT_COMPOSITE_WEIGHTS
    components = {
        "file_recall": file_recall,
        "file_precision": file_precision,
        "chain_recall": chain_recall,
        "symbol_recall": symbol_recall,
    }

    # Identify which components have real values
    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return 0.0

    # Sum weights for available components, renormalize
    raw_weight_sum = sum(w.get(k, 0) for k in available)
    if raw_weight_sum == 0:
        return 0.0

    return sum(
        (w.get(k, 0) / raw_weight_sum) * v
        for k, v in available.items()
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate context retrieval agent against ContextBench"
    )
    parser.add_argument(
        "--download-data", action="store_true",
        help="Download ContextBench dataset from Hugging Face",
    )
    parser.add_argument(
        "--sample", type=int, default=0,
        help="Number of tasks to sample (0 = all)",
    )
    parser.add_argument(
        "--verified", action="store_true",
        help="Use verified subset (500 tasks) instead of full (1136)",
    )
    parser.add_argument(
        "--model", type=str, default="claude-sonnet-4-6",
        help="Model to use",
    )
    parser.add_argument(
        "--backend", type=str, default="hybrid",
        choices=("local", "deepsearch", "hybrid"),
        help="Tool backend",
    )
    parser.add_argument(
        "--max-cost", type=float, default=0,
        help="Cost limit in USD",
    )
    parser.add_argument(
        "--out", type=str, default="",
        help="Output directory (default: results/contextbench/)",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for sampling",
    )
    parser.add_argument(
        "--phase", type=str, default="", choices=("", "test", "verify"),
        help="Calibration phase: 'test' (~10 tasks) or 'verify' (~50 tasks). Uses CCB-weighted sampling.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print selected tasks and stratum breakdown without running the agent",
    )
    parser.add_argument(
        "--composite-weights", type=str, default="",
        help='JSON string to override composite weights, e.g. \'{"file_recall":0.5,"file_precision":0.2,"chain_recall":0.2,"symbol_recall":0.1}\'',
    )
    parser.add_argument(
        "--verbose", action="store_true",
    )
    # Execution mode
    cli_group = parser.add_mutually_exclusive_group()
    cli_group.add_argument(
        "--use-cli", action="store_true", default=True,
        help="Use Claude CLI for subscription billing (default)",
    )
    cli_group.add_argument(
        "--use-sdk", action="store_true",
        help="Use Anthropic SDK directly (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--max-tasks", type=int, default=0,
        help="Process at most N tasks (0 = all)",
    )
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Number of tasks to run in parallel (default: 1)",
    )
    parser.add_argument(
        "--prune", action="store_true",
        help="Run a pruning pass with haiku to remove irrelevant files",
    )
    parser.add_argument(
        "--instance-ids", type=str, default="",
        help="Comma-separated instance ID suffixes to filter to (e.g., '7df7e1c0,157932b6')",
    )
    parser.add_argument(
        "--instance-ids-file", type=str, default="",
        help="JSON file containing a list of instance IDs to filter to",
    )
    args = parser.parse_args()
    use_cli = not args.use_sdk

    # Cap parallelism for CLI mode (MCP connection contention at >5)
    if use_cli and args.parallel > 5:
        log.warning("Capping --parallel to 5 for CLI mode (MCP contention). Use --use-sdk for higher parallelism.")
        args.parallel = 5

    # Parse composite weights if provided
    composite_weights = None
    if args.composite_weights:
        try:
            composite_weights = json.loads(args.composite_weights)
        except json.JSONDecodeError:
            log.error("Invalid JSON for --composite-weights: %s", args.composite_weights)
            return 1

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.download_data:
        download_data()
        return 0

    # Set up output dir
    out_dir = Path(args.out) if args.out else RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Phase-based calibration subset selection
    if args.phase:
        phase_size = 10 if args.phase == "test" else 50
        # --phase test uses verified subset by default
        use_verified = args.verified or (args.phase == "test")
        all_tasks = load_tasks(
            verified=use_verified,
            sample=0,  # Load all, then CCB-weighted sample
            seed=args.seed,
        )
        if not all_tasks:
            return 1
        tasks = ccb_weighted_sample(all_tasks, phase_size, seed=args.seed)
        log.info("Phase '%s': selected %d tasks (CCB-weighted)", args.phase, len(tasks))

        # Save subset for reproducibility
        subset_dir = DATA_DIR
        subset_dir.mkdir(parents=True, exist_ok=True)
        subset_path = subset_dir / f"{args.phase}_subset.json"
        subset_ids = [t.get("instance_id", f"task_{i}") for i, t in enumerate(tasks)]
        subset_path.write_text(json.dumps(subset_ids, indent=2) + "\n")
        log.info("Saved subset IDs: %s", subset_path)

        if args.dry_run:
            # Print stratum breakdown
            strata: Dict[str, int] = {}
            for t in tasks:
                iid = t.get("instance_id", "")
                lang = _infer_language(iid, t)
                complexity = _gold_context_size(t)
                key = f"{lang}/{complexity}"
                strata[key] = strata.get(key, 0) + 1
            print(f"\n--phase {args.phase}: {len(tasks)} tasks selected")
            print(f"Stratum breakdown:")
            for key, count in sorted(strata.items()):
                print(f"  {key}: {count}")
            n_hard = sum(1 for t in tasks if _gold_context_size(t) == "large")
            print(f"\nHard cases (>5 gold files): {n_hard}/{len(tasks)} ({n_hard/len(tasks):.0%})")
            ccb_count = sum(1 for t in tasks
                           if any(r in t.get("repo", t.get("repo_url", "")).lower()
                                  for r in CCB_OVERLAP_REPOS))
            print(f"CCB-overlap repos: {ccb_count}/{len(tasks)} ({ccb_count/len(tasks):.0%})")
            return 0
    else:
        # Standard load
        tasks = load_tasks(
            verified=args.verified,
            sample=args.sample,
            seed=args.seed,
        )
        if not tasks:
            return 1

    # Instance ID filtering (applies to both phase and standard modes)
    if args.instance_ids or args.instance_ids_file:
        filter_ids: set = set()
        if args.instance_ids:
            filter_ids.update(s.strip() for s in args.instance_ids.split(",") if s.strip())
        if args.instance_ids_file:
            with open(args.instance_ids_file) as f:
                filter_ids.update(json.load(f))
        before = len(tasks)
        tasks = [
            t for t in tasks
            if t.get("instance_id", "") in filter_ids
            or any(t.get("instance_id", "").endswith(suffix) for suffix in filter_ids)
        ]
        log.info("Instance ID filter: %d -> %d tasks", before, len(tasks))
        if not tasks:
            log.error("No tasks matched the instance ID filter")
            return 1

    if args.dry_run:
        print(f"Would process {len(tasks)} tasks (model={args.model}, backend={args.backend})")
        for t in tasks[:20]:
            print(f"  {t.get('instance_id', '?')}")
        return 0

    client = None
    sg = None
    if use_cli:
        log.info("Using Claude CLI (subscription billing)")
    else:
        # SDK mode: need anthropic package and API key
        try:
            import anthropic
        except ImportError:
            log.error("pip install anthropic")
            return 1

        api_key = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        if api_key:
            log.info("Using OAuth token (CLAUDE_CODE_OAUTH_TOKEN)")
        else:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if api_key:
                log.info("Using API key (ANTHROPIC_API_KEY)")
        if not api_key:
            log.error("Set CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY")
            return 1

        client = anthropic.Anthropic(api_key=api_key)

        # Set up SG client if needed (SDK mode only — CLI uses MCP)
        if args.backend in ("deepsearch", "hybrid"):
            from context_retrieval_agent import SourcegraphClient
            sg = SourcegraphClient()

    # -- Per-task worker function (can run in parallel) --
    def process_one_task(task_tuple):
        idx, task = task_tuple
        instance_id = task.get("instance_id", f"task_{idx}")
        repo_url = task.get("repo_url", "")
        if not repo_url:
            repo_slug = task.get("repo", "")
            if repo_slug and "/" in repo_slug:
                repo_url = f"https://github.com/{repo_slug}"
        commit = task.get("base_commit", task.get("commit", "HEAD"))

        if not repo_url:
            parts = instance_id.rsplit("-", 1)
            org_repo = parts[0].replace("__", "/") if parts else ""
            repo_url = f"https://github.com/{org_repo}" if org_repo else ""

        if not repo_url:
            log.warning("[%d] No repo URL, skipping %s", idx + 1, instance_id)
            return None

        log.info("[%d/%d] %s", idx + 1, len(tasks), instance_id)

        repo_path = clone_for_contextbench(repo_url, commit)
        if not repo_path:
            log.warning("[%d] Clone failed, skipping %s", idx + 1, instance_id)
            return None

        try:
            result = run_retrieval_agent_on_cb_task(
                task, repo_path, client,
                model=args.model, backend=args.backend,
                sg=sg, verbose=args.verbose,
                use_cli=use_cli,
                prune=args.prune,
            )
        except Exception as e:
            log.error("[%d] Agent failed for %s: %s", idx + 1, instance_id, e)
            return None

        # Retry once if agent returned 0 files (common in parallel CLI mode)
        n_pred = len(result.get("oracle", {}).get("files", []))
        is_error = result.get("metadata", {}).get("error", False)
        if n_pred == 0 and (is_error or not result.get("oracle", {}).get("text")):
            log.warning("[%d] Empty result for %s, retrying after 10s...", idx + 1, instance_id)
            time.sleep(10)
            try:
                result = run_retrieval_agent_on_cb_task(
                    task, repo_path, client,
                    model=args.model, backend=args.backend,
                    sg=sg, verbose=args.verbose,
                    use_cli=use_cli,
                    prune=args.prune,
                )
                n_retry = len(result.get("oracle", {}).get("files", []))
                log.info("[%d] Retry for %s: %d files", idx + 1, instance_id, n_retry)
            except Exception as e:
                log.error("[%d] Retry failed for %s: %s", idx + 1, instance_id, e)
                return None


        n_files = len(result["oracle"].get("files", []))
        log.info("[%d] %s -> %d files, $%.4f",
                 idx + 1, instance_id, n_files, result["metadata"]["cost_usd"])

        traj = convert_to_trajectory(
            instance_id, result["oracle"],
            model_patch=task.get("patch", ""),
        )
        return {"task": task, "traj": traj, "result": result}

    # -- Apply limits --
    run_tasks = tasks
    if args.max_tasks > 0:
        run_tasks = tasks[:args.max_tasks]

    # -- Execute tasks (parallel or sequential) --
    total_cost = 0.0
    trajectories = []
    evaluated_tasks = []

    task_tuples = list(enumerate(run_tasks))
    n_parallel = max(1, args.parallel)

    if n_parallel > 1 and len(task_tuples) > 1:
        log.info("Running %d tasks with %d workers", len(task_tuples), n_parallel)
        with concurrent.futures.ThreadPoolExecutor(max_workers=n_parallel) as executor:
            futures = {executor.submit(process_one_task, t): t for t in task_tuples}
            for future in concurrent.futures.as_completed(futures):
                outcome = future.result()
                if outcome is None:
                    continue
                total_cost += outcome["result"]["metadata"].get("cost_usd", 0)
                if args.max_cost > 0 and total_cost >= args.max_cost:
                    log.warning("Cost limit reached ($%.2f), cancelling remaining", total_cost)
                    for f in futures:
                        f.cancel()
                    break
                trajectories.append(outcome["traj"])
                evaluated_tasks.append(outcome["task"])
    else:
        for tt in task_tuples:
            if args.max_cost > 0 and total_cost >= args.max_cost:
                log.warning("Cost limit reached ($%.2f)", total_cost)
                break
            outcome = process_one_task(tt)
            if outcome is None:
                continue
            total_cost += outcome["result"]["metadata"].get("cost_usd", 0)
            trajectories.append(outcome["traj"])
            evaluated_tasks.append(outcome["task"])

    if not trajectories:
        log.error("No tasks completed")
        return 1

    # Write trajectories
    traj_path = out_dir / "trajectories.traj.json"
    with open(traj_path, "w") as f:
        for traj in trajectories:
            f.write(json.dumps(traj) + "\n")
    log.info("Wrote %d trajectories: %s", len(trajectories), traj_path)

    # Compute simple file metrics (works without contextbench installed)
    simple_metrics = compute_simple_file_metrics(evaluated_tasks, trajectories)
    log.info("Simple file metrics: %s", json.dumps(simple_metrics, indent=2))

    # Compute chunk-level metrics (line-range overlap)
    chunk_metrics = compute_chunk_metrics(evaluated_tasks, trajectories)
    if chunk_metrics.get("n_chunk_evaluated", 0) > 0:
        log.info("Chunk metrics: %s", json.dumps(chunk_metrics, indent=2))
    else:
        log.info("No chunk annotations to evaluate (agent did not produce chunks)")

    # Try running ContextBench evaluator
    gold_fname = "verified.parquet" if args.verified else "full.parquet"
    gold_path = DATA_DIR / gold_fname
    cb_results_path = out_dir / "contextbench_results.jsonl"

    cb_metrics = {}
    if gold_path.exists():
        cb_metrics = evaluate_trajectories(gold_path, traj_path, cb_results_path)

    # Build calibration report with error profile and bias analysis
    report = build_calibration_report(
        evaluated_tasks, trajectories, simple_metrics,
        cb_metrics=cb_metrics,
        model=args.model,
        backend=args.backend,
        total_cost=total_cost,
        n_attempted=len(tasks),
        composite_weights=composite_weights,
    )
    # Add chunk metrics to report
    report["chunk_metrics"] = chunk_metrics

    report_path = out_dir / "calibration_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    # Print summary
    print(f"\n{'=' * 70}")
    print("Oracle Agent Calibration Report (ContextBench)")
    print(f"{'=' * 70}")
    print(f"Model: {args.model} | Backend: {args.backend}")
    print(f"Tasks: {len(trajectories)}/{len(tasks)} completed | Cost: ${total_cost:.2f}")

    sm = report["file_metrics"]
    print(f"\nFile-Level Performance:")
    print(f"  Recall:    {sm['recall']:.4f}")
    print(f"  Precision: {sm['precision']:.4f}")
    print(f"  F1:        {sm['f1']:.4f}")

    # Chunk-level metrics
    cm = report.get("chunk_metrics", {})
    if cm.get("n_chunk_evaluated", 0) > 0:
        print(f"\nChunk-Level Performance (line ranges):")
        print(f"  Recall:    {cm['chunk_recall']:.4f}")
        print(f"  Precision: {cm['chunk_precision']:.4f}")
        print(f"  F1:        {cm['chunk_f1']:.4f}")
        print(f"  Evaluated: {cm['n_chunk_evaluated']} tasks")
    else:
        print(f"\nChunk-Level: no chunk annotations (agent did not produce line ranges)")

    # Composite score
    print(f"\nComposite Score: {report.get('composite_score', 0):.4f}")

    # Go/no-go
    threshold = report["go_no_go"]
    status = "PASS" if threshold["pass"] else "FAIL"
    print(f"\nGo/No-Go: {status}")
    print(f"  File recall >= {threshold['file_recall_threshold']}: "
          f"{threshold['file_recall_met']}")
    print(f"  Composite >= {threshold['composite_threshold']}: "
          f"{threshold['composite_met']}")

    # Bias analysis
    if report.get("bias_analysis", {}).get("by_language"):
        print(f"\nBy Language:")
        for lang, m in sorted(report["bias_analysis"]["by_language"].items()):
            print(f"  {lang:12s}: recall={m['recall']:.3f} precision={m['precision']:.3f} "
                  f"f1={m['f1']:.3f} (n={m['n']})")

    if report.get("bias_analysis", {}).get("by_complexity"):
        print(f"\nBy Context Complexity:")
        for comp, m in sorted(report["bias_analysis"]["by_complexity"].items()):
            print(f"  {comp:8s}: recall={m['recall']:.3f} precision={m['precision']:.3f} "
                  f"f1={m['f1']:.3f} (n={m['n']})")

    if report.get("systematic_gaps"):
        print(f"\nSystematic Gaps (file categories missed):")
        for gap in report["systematic_gaps"][:5]:
            print(f"  - {gap['category']}: missed {gap['miss_rate']:.0%} "
                  f"({gap['missed']}/{gap['total']})")

    if cb_metrics:
        print(f"\nContextBench evaluator results: see {cb_results_path}")
    print(f"\nCalibration report: {report_path}")
    print(f"Trajectories: {traj_path}")
    print(f"{'=' * 70}")

    # Paper-ready statement
    if threshold["pass"]:
        print(f"\nPaper-ready statement:")
        print(f'  "Our oracle achieves {sm["recall"]:.0%} file-level recall and '
              f'{sm["precision"]:.0%} precision against human expert annotations '
              f'on a calibration set of {sm["n"]} ContextBench tasks, providing '
              f'a quantified error profile for ground truth completeness."')

    return 0


def build_calibration_report(
    tasks: List[Dict],
    trajectories: List[Dict],
    simple_metrics: Dict[str, float],
    cb_metrics: Dict = None,
    model: str = "",
    backend: str = "",
    total_cost: float = 0,
    n_attempted: int = 0,
    composite_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Build the calibration report with error profile and bias analysis.

    This is the key artifact: a quantified error profile that lets us
    interpret oracle-generated ground truth through measured limitations.
    """
    # Per-task detail with language/complexity metadata
    per_task_detail = []
    by_language: Dict[str, List[Dict]] = {}
    by_complexity: Dict[str, List[Dict]] = {}
    missed_categories: Dict[str, Dict] = {}  # category -> {missed, total}

    for task, traj in zip(tasks, trajectories):
        iid = task.get("instance_id", "")
        lang = _infer_language(iid, task)
        complexity = _gold_context_size(task)

        # Compute per-task metrics
        gold_files = _extract_gold_files(task)
        pred_files = set(traj.get("traj_data", {}).get("pred_files", []))
        gold_norm = {f.lstrip("/") for f in gold_files if f}
        pred_norm = {f.lstrip("/") for f in pred_files if f}

        inter = gold_norm & pred_norm
        recall = len(inter) / len(gold_norm) if gold_norm else 0
        precision = len(inter) / len(pred_norm) if pred_norm else 0
        f1 = (2 * recall * precision / (recall + precision)
              if (recall + precision) > 0 else 0)

        detail = {
            "instance_id": iid,
            "language": lang,
            "complexity": complexity,
            "recall": round(recall, 4),
            "precision": round(precision, 4),
            "f1": round(f1, 4),
            "n_gold": len(gold_norm),
            "n_pred": len(pred_norm),
            "n_matched": len(inter),
            "missed": sorted(gold_norm - pred_norm),
            "extra": sorted(pred_norm - gold_norm),
        }
        per_task_detail.append(detail)

        by_language.setdefault(lang, []).append(detail)
        by_complexity.setdefault(complexity, []).append(detail)

        # Track missed file categories
        for missed_file in gold_norm - pred_norm:
            cat = _categorize_file(missed_file)
            missed_categories.setdefault(cat, {"missed": 0, "total": 0})
            missed_categories[cat]["missed"] += 1
        for gold_file in gold_norm:
            cat = _categorize_file(gold_file)
            missed_categories.setdefault(cat, {"missed": 0, "total": 0})
            missed_categories[cat]["total"] += 1

    # Aggregate by language
    lang_metrics = {}
    for lang, details in sorted(by_language.items()):
        lang_metrics[lang] = _aggregate_metrics(details)

    # Aggregate by complexity
    comp_metrics = {}
    for comp, details in sorted(by_complexity.items()):
        comp_metrics[comp] = _aggregate_metrics(details)

    # Systematic gaps (file categories with high miss rates)
    gaps = []
    for cat, counts in sorted(missed_categories.items()):
        if counts["total"] >= 3:  # minimum sample
            miss_rate = counts["missed"] / counts["total"]
            if miss_rate > 0.3:  # flag if >30% miss rate
                gaps.append({
                    "category": cat,
                    "miss_rate": round(miss_rate, 4),
                    "missed": counts["missed"],
                    "total": counts["total"],
                })
    gaps.sort(key=lambda g: g["miss_rate"], reverse=True)

    # Go/no-go threshold (legacy file-recall check, kept for backward compat)
    file_recall = simple_metrics.get("file_recall", 0)
    file_precision = simple_metrics.get("file_precision", 0)
    FILE_RECALL_THRESHOLD = 0.60  # Minimum to proceed
    go_file_recall = file_recall >= FILE_RECALL_THRESHOLD

    # Composite go/no-go (richer signal)
    # None signals "not measured" — weight is redistributed to available components
    chain_recall = simple_metrics.get("chain_recall", None)
    symbol_recall = simple_metrics.get("symbol_recall", None)
    cw = composite_weights or DEFAULT_COMPOSITE_WEIGHTS
    composite = compute_composite_score(file_recall, file_precision, chain_recall, symbol_recall, cw)
    go_composite = composite >= COMPOSITE_THRESHOLD
    go = go_file_recall and go_composite

    # Per-stratum composite scores
    stratum_composites = {}
    stratum_warnings = []
    for stratum_type in ("by_language", "by_complexity"):
        metrics_dict = lang_metrics if stratum_type == "by_language" else comp_metrics
        for key, m in metrics_dict.items():
            sc = compute_composite_score(
                m.get("recall", 0), m.get("precision", 0), None, None, cw,
            )
            stratum_composites[f"{stratum_type}/{key}"] = round(sc, 4)
            if sc < STRATUM_WARNING_THRESHOLD:
                stratum_warnings.append(f"{stratum_type}/{key}: composite={sc:.4f}")
                log.warning("Stratum %s/%s composite %.4f < %.2f", stratum_type, key, sc, STRATUM_WARNING_THRESHOLD)

    return {
        "calibration_metadata": {
            "model": model,
            "backend": backend,
            "n_attempted": n_attempted,
            "n_completed": len(trajectories),
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_task": round(total_cost / len(trajectories), 4) if trajectories else 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "contextbench_subset": "verified" if len(tasks) <= 500 else "full",
        },
        "file_metrics": {
            "recall": simple_metrics.get("file_recall", 0),
            "precision": simple_metrics.get("file_precision", 0),
            "f1": simple_metrics.get("file_f1", 0),
            "n": simple_metrics.get("n_evaluated", 0),
        },
        "composite_score": round(composite, 4),
        "go_no_go": {
            "pass": go,
            "file_recall_threshold": FILE_RECALL_THRESHOLD,
            "file_recall_met": go_file_recall,
            "composite_threshold": COMPOSITE_THRESHOLD,
            "composite_met": go_composite,
            "composite_weights": cw,
            "recommendation": (
                "PROCEED: Oracle meets calibration thresholds."
                if go else
                "ITERATE: Oracle below threshold. Improve agent before deploying."
            ),
        },
        "bias_analysis": {
            "by_language": lang_metrics,
            "by_complexity": comp_metrics,
            "stratum_composites": stratum_composites,
            "stratum_warnings": stratum_warnings,
        },
        "systematic_gaps": gaps,
        "domain_gap_warning": (
            "ContextBench tasks are single-repo issue resolution. "
            "CCB polyrepo tasks (cross-repo dependency tracing, org-scale discovery) "
            "are structurally different. Oracle calibration numbers for those task "
            "types should be treated as extrapolations. Consider a small human "
            "annotation effort (10-15 polyrepo tasks) to extend calibration."
        ),
        "contextbench_evaluator_metrics": cb_metrics or {},
        "per_task": per_task_detail,
    }


def _extract_gold_files(task: Dict) -> Set[str]:
    """Extract gold file set from a ContextBench task."""
    gold_files = set()
    files_raw = task.get("files", [])
    if isinstance(files_raw, str):
        try:
            files_raw = json.loads(files_raw)
        except json.JSONDecodeError:
            files_raw = []
    if isinstance(files_raw, list):
        for f in files_raw:
            if isinstance(f, str):
                gold_files.add(f)
            elif isinstance(f, dict):
                gold_files.add(f.get("path", ""))
    patch = task.get("patch", "")
    if patch:
        for line in patch.split("\n"):
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                path = line[6:].strip()
                if path and path != "/dev/null":
                    gold_files.add(path)
    return gold_files


def _aggregate_metrics(details: List[Dict]) -> Dict[str, float]:
    """Aggregate recall/precision/f1 from per-task details."""
    if not details:
        return {"recall": 0, "precision": 0, "f1": 0, "n": 0}
    recalls = [d["recall"] for d in details]
    precisions = [d["precision"] for d in details]
    avg_r = sum(recalls) / len(recalls)
    avg_p = sum(precisions) / len(precisions)
    f1 = (2 * avg_r * avg_p / (avg_r + avg_p)) if (avg_r + avg_p) > 0 else 0
    return {
        "recall": round(avg_r, 4),
        "precision": round(avg_p, 4),
        "f1": round(f1, 4),
        "n": len(details),
    }


def _categorize_file(path: str) -> str:
    """Categorize a file path into broad categories for bias analysis."""
    path_lower = path.lower()
    if any(t in path_lower for t in ["test", "spec", "mock", "fake", "fixture"]):
        return "test/fixture"
    if any(t in path_lower for t in ["config", "conf", "settings", "setup.py", "setup.cfg",
                                      ".toml", ".yaml", ".yml", ".ini", ".json"]):
        return "configuration"
    if any(t in path_lower for t in ["doc", "readme", "changelog", "license", "contributing"]):
        return "documentation"
    if any(t in path_lower for t in ["migration", "alembic", "schema"]):
        return "migration/schema"
    if any(t in path_lower for t in ["__init__", "index.", "mod.rs", "package.json"]):
        return "module_entry"
    return "source_code"


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""IR (Information Retrieval) analysis for CodeContextBench.

Computes IR quality metrics (precision, recall, MRR, nDCG, MAP) by comparing
the files each agent retrieved against ground-truth files that needed change.

Usage:
    # Build ground truth from benchmark task dirs
    python3 scripts/ir_analysis.py --build-ground-truth

    # Run IR analysis (builds ground truth if missing)
    python3 scripts/ir_analysis.py

    # JSON output
    python3 scripts/ir_analysis.py --json

    # Filter to one benchmark
    python3 scripts/ir_analysis.py --suite ccb_swebenchpro

    # Per-task scores
    python3 scripts/ir_analysis.py --per-task
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ccb_metrics.ground_truth import (
    build_ground_truth_registry,
    load_registry,
    save_registry,
    TaskGroundTruth,
)
from ccb_metrics.ir_metrics import (
    compute_ir_scores,
    aggregate_ir_scores,
    extract_retrieved_files,
    extract_time_to_context,
    IRScores,
    MCPValueScore,
)

RUNS_DIR = Path("/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/runs/official")
MANIFEST_PATH = RUNS_DIR / "MANIFEST.json"
BENCHMARKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
SELECTION_FILE = Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json"
GT_CACHE = Path(__file__).resolve().parent.parent / "configs" / "ground_truth_files.json"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived", "preamble_test_"]
CONFIGS = ["baseline", "sourcegraph_full"]
# Benchmarks dropped from evaluation — exclude from ground truth builds and IR analysis
DROPPED_BENCHMARKS = {"ccb_dependeval", "ccb_locobench"}

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "enterprise_": "ccb_enterprise",
    "governance_": "ccb_governance",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "paired_rerun_": None,
}


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def _is_batch_timestamp(name: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def _suite_from_run_dir(name: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            return suite
    if name.startswith("swebenchpro_gapfill_"):
        return "ccb_swebenchpro"
    return None


def _load_selected_tasks() -> list[dict]:
    """Load selected tasks from config, excluding dropped benchmarks."""
    if not SELECTION_FILE.is_file():
        return []
    data = json.loads(SELECTION_FILE.read_text())
    tasks = data.get("tasks", [])
    return [t for t in tasks if t.get("benchmark", "") not in DROPPED_BENCHMARKS]


def _ensure_ground_truth() -> dict[str, TaskGroundTruth]:
    """Load or build ground truth registry."""
    if GT_CACHE.is_file():
        registry = load_registry(GT_CACHE)
        if registry:
            return registry

    selected = _load_selected_tasks()
    registry = build_ground_truth_registry(BENCHMARKS_DIR, selected)
    if registry:
        save_registry(registry, GT_CACHE)
    return registry


def _walk_task_dirs() -> list[dict]:
    """Walk run directories, collect task info with dedup by timestamp."""
    all_tasks: dict[tuple[str, str, str], dict] = {}  # (suite, config, task_id) -> info

    if not RUNS_DIR.exists():
        return []

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("archive", "MANIFEST.json"):
            continue
        if should_skip(run_dir.name):
            continue

        suite = _suite_from_run_dir(run_dir.name)

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            if config_name not in CONFIGS:
                continue

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _is_batch_timestamp(batch_dir.name):
                    continue

                for task_dir in sorted(batch_dir.iterdir()):
                    if not task_dir.is_dir():
                        continue

                    # Extract task_id from dir name (strip hash suffix)
                    task_name = task_dir.name
                    # Task dirs: task_name__hash
                    if "__" in task_name:
                        parts = task_name.rsplit("__", 1)
                        if len(parts[1]) >= 6:  # hash-like suffix
                            task_name = parts[0]

                    # Find transcript (Harbor layout: agent/claude-code.txt)
                    transcript = task_dir / "agent" / "claude-code.txt"
                    if not transcript.is_file():
                        transcript = task_dir / "claude-code.txt"
                    if not transcript.is_file():
                        transcript = task_dir / "agent_output" / "claude-code.txt"

                    # Timestamp-based dedup
                    started_at = ""
                    result_file = task_dir / "result.json"
                    if result_file.is_file():
                        try:
                            rdata = json.loads(result_file.read_text())
                            started_at = rdata.get("started_at", "")
                            # Also try to get task_name from result
                            if "task_name" in rdata:
                                task_name = rdata["task_name"]
                        except Exception:
                            pass

                    task_suite = suite
                    if task_suite is None:
                        # Infer from task_name
                        task_suite = _infer_suite(task_name)

                    info = {
                        "task_id": task_name,
                        "suite": task_suite or "unknown",
                        "config": config_name,
                        "task_dir": str(task_dir),
                        "transcript": str(transcript) if transcript.is_file() else None,
                        "started_at": started_at,
                    }

                    key = (info["suite"], config_name, task_name)
                    if key in all_tasks:
                        if started_at > all_tasks[key].get("started_at", ""):
                            all_tasks[key] = info
                    else:
                        all_tasks[key] = info

    return list(all_tasks.values())


def _infer_suite(task_id: str) -> str | None:
    """Infer suite from task_id patterns."""
    if task_id.startswith("instance_"):
        return "ccb_swebenchpro"
    if task_id.startswith("sgt-"):
        return "ccb_pytorch"
    if task_id.endswith("-doc-001"):
        return "ccb_k8sdocs"
    if task_id.startswith("big-code-"):
        return "ccb_largerepo"
    if task_id.startswith("dibench-"):
        return "ccb_dibench"
    if task_id.startswith("cr-"):
        return "ccb_codereview"
    if task_id.startswith("lfl-"):
        return "ccb_linuxflbench"
    if task_id.startswith("tac-"):
        return "ccb_tac"
    if task_id.startswith("repoqa-"):
        return "ccb_repoqa"
    if task_id.startswith("sweperf-"):
        return "ccb_sweperf"
    if task_id.startswith(("bug_localization_", "refactor_rename_", "cross_file_reasoning_", "simple_test_")):
        return "ccb_crossrepo"
    if "_expert_" in task_id:
        return "ccb_locobench"
    if task_id.startswith(("multifile_editing-", "file_span_fix-", "dependency_recognition-")):
        return "ccb_dependeval"
    # Governance/enterprise/investigation task patterns
    if any(task_id.startswith(p) for p in (
        "repo-scoped-", "sensitive-file-", "credential-",
        "multi-team-", "degraded-context-", "dep-",
    )):
        return "ccb_enterprise"
    if any(task_id.startswith(p) for p in (
        "license-", "deprecated-api-", "security-vuln-",
        "code-quality-", "naming-convention-", "documentation-",
    )):
        return "ccb_governance"
    return None


# ---------------------------------------------------------------------------
# US-003: Retrieval-to-outcome correlation
# ---------------------------------------------------------------------------

def _load_manifest_rewards() -> dict[tuple[str, str], float]:
    """Load (task_id, config) -> reward from MANIFEST.json."""
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        manifest = json.loads(MANIFEST_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    rewards: dict[tuple[str, str], float] = {}
    for run_key, run_data in manifest.get("runs", {}).items():
        parts = run_key.rsplit("/", 1)
        if len(parts) != 2:
            continue
        _suite, config = parts
        for task_id, task_data in run_data.get("tasks", {}).items():
            reward = task_data.get("reward")
            if reward is not None:
                rewards[(task_id, config)] = reward
    return rewards


def _manual_spearman(x: list[float], y: list[float]) -> tuple[float, float]:
    """Spearman rank correlation without scipy. Returns (r, p_approx)."""
    n = len(x)
    if n < 3:
        return (0.0, 1.0)

    def _rank(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx, ry = _rank(x), _rank(y)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    r = 1.0 - (6.0 * d_sq) / (n * (n * n - 1))
    import math
    if abs(r) >= 1.0:
        return (round(r, 6), 0.0)
    t_stat = r * math.sqrt((n - 2) / (1 - r * r))
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
    return (round(r, 6), round(p, 6))


def compute_retrieval_outcome_correlation(ir_scores: list[IRScores]) -> dict | None:
    """Join IR scores with MANIFEST rewards and compute Spearman correlation."""
    manifest_rewards = _load_manifest_rewards()
    if not manifest_rewards:
        return None

    ir_by_key: dict[tuple[str, str], IRScores] = {}
    for s in ir_scores:
        ir_by_key[(s.task_id, s.config_name)] = s

    paired_mrr: list[float] = []
    paired_reward: list[float] = []
    bl_ir: dict[str, IRScores] = {}
    sg_ir: dict[str, IRScores] = {}
    bl_reward: dict[str, float] = {}
    sg_reward: dict[str, float] = {}

    for (task_id, config), score in ir_by_key.items():
        reward = manifest_rewards.get((task_id, config))
        if reward is None:
            continue
        paired_mrr.append(score.mrr)
        paired_reward.append(reward)
        if config == "baseline":
            bl_ir[task_id] = score
            bl_reward[task_id] = reward
        elif config == "sourcegraph_full":
            sg_ir[task_id] = score
            sg_reward[task_id] = reward

    if len(paired_mrr) < 5:
        return None

    try:
        from scipy.stats import spearmanr
        corr, pval = spearmanr(paired_mrr, paired_reward)
    except ImportError:
        corr, pval = _manual_spearman(paired_mrr, paired_reward)

    common_tasks = set(bl_ir) & set(sg_ir) & set(bl_reward) & set(sg_reward)
    scatter: list[dict] = []
    for task_id in sorted(common_tasks):
        suite = _infer_suite(task_id) or "unknown"
        scatter.append({
            "task_id": task_id, "suite": suite,
            "mrr_bl": round(bl_ir[task_id].mrr, 4),
            "mrr_sg": round(sg_ir[task_id].mrr, 4),
            "reward_bl": round(bl_reward[task_id], 4),
            "reward_sg": round(sg_reward[task_id], 4),
            "mrr_delta": round(sg_ir[task_id].mrr - bl_ir[task_id].mrr, 4),
            "reward_delta": round(sg_reward[task_id] - bl_reward[task_id], 4),
        })

    abs_r = abs(corr)
    strength = "strong" if abs_r >= 0.7 else "moderate" if abs_r >= 0.4 else "weak" if abs_r >= 0.2 else "negligible"
    sig_text = "statistically significant (p<0.05)" if pval < 0.05 else "not statistically significant"
    direction = "positive" if corr > 0 else "negative"
    interpretation = (
        f"There is a {strength} {direction} correlation (r={corr:.3f}) between "
        f"retrieval quality (MRR) and task outcome (reward), {sig_text} (p={pval:.4f}). "
        f"This {'supports' if corr > 0.2 else 'does not support'} the hypothesis that "
        f"better context retrieval leads to better task outcomes."
    )

    return {
        "n_paired": len(paired_mrr),
        "n_paired_both_configs": len(scatter),
        "spearman_r": round(corr, 4),
        "spearman_p": round(pval, 6),
        "interpretation": interpretation,
        "scatter": scatter,
    }


# ---------------------------------------------------------------------------
# US-004: Composite MCP value score with z-score normalization
# ---------------------------------------------------------------------------

def _load_task_metrics_tokens() -> dict[tuple[str, str], int]:
    """Load (task_id, config) -> input_tokens from task_metrics.json files."""
    tokens: dict[tuple[str, str], int] = {}
    if not RUNS_DIR.exists():
        return tokens
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue
        for config_dir in run_dir.iterdir():
            if not config_dir.is_dir() or config_dir.name not in CONFIGS:
                continue
            config = config_dir.name
            for batch_dir in config_dir.iterdir():
                if not batch_dir.is_dir() or not _is_batch_timestamp(batch_dir.name):
                    continue
                for task_dir in batch_dir.iterdir():
                    if not task_dir.is_dir():
                        continue
                    metrics_file = task_dir / "task_metrics.json"
                    if not metrics_file.is_file():
                        continue
                    try:
                        m = json.loads(metrics_file.read_text())
                        task_id = m.get("task_id", "")
                        inp = m.get("input_tokens")
                        if task_id and inp is not None:
                            key = (task_id, config)
                            # Keep latest by not overwriting (first seen wins — sorted dirs)
                            if key not in tokens:
                                tokens[key] = int(inp)
                    except (json.JSONDecodeError, OSError, ValueError):
                        continue
    return tokens


def _zscore(values: list[float]) -> list[float]:
    """Z-score normalize a list of values. Returns 0 for constant lists."""
    if len(values) < 2:
        return [0.0] * len(values)
    mean = statistics.mean(values)
    std = statistics.stdev(values)
    if std < 1e-10:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def compute_mcp_value_scores(
    ir_scores: list[IRScores],
    weights: tuple[float, float, float, float] = (0.3, 0.3, 0.25, 0.15),
) -> list[MCPValueScore]:
    """Compute composite MCP value scores for tasks with both configs.

    Components (all computed as SG_full - baseline deltas):
    - retrieval_lift: MRR delta
    - outcome_lift: reward delta
    - efficiency_lift: TTFR improvement ratio (negative = faster with MCP)
    - cost_ratio: token cost ratio (SG_full / baseline - 1, negative = cheaper)

    Each component is z-scored across all tasks before weighting.
    """
    manifest_rewards = _load_manifest_rewards()
    token_data = _load_task_metrics_tokens()

    # Build per-config lookups
    bl_ir: dict[str, IRScores] = {}
    sg_ir: dict[str, IRScores] = {}
    for s in ir_scores:
        if s.config_name == "baseline":
            bl_ir[s.task_id] = s
        elif s.config_name == "sourcegraph_full":
            sg_ir[s.task_id] = s

    common = set(bl_ir) & set(sg_ir)
    if len(common) < 3:
        return []

    # Compute raw component values for each task
    raw_scores: list[dict] = []
    for task_id in sorted(common):
        bl, sg = bl_ir[task_id], sg_ir[task_id]
        suite = _infer_suite(task_id) or "unknown"

        retrieval_lift = sg.mrr - bl.mrr
        outcome_lift = 0.0
        bl_r = manifest_rewards.get((task_id, "baseline"))
        sg_r = manifest_rewards.get((task_id, "sourcegraph_full"))
        if bl_r is not None and sg_r is not None:
            outcome_lift = sg_r - bl_r

        efficiency_lift = 0.0
        if bl.ttfr is not None and sg.ttfr is not None and bl.ttfr > 0:
            efficiency_lift = (bl.ttfr - sg.ttfr) / bl.ttfr  # positive = MCP faster

        cost_ratio = 0.0
        bl_tok = token_data.get((task_id, "baseline"))
        sg_tok = token_data.get((task_id, "sourcegraph_full"))
        if bl_tok and sg_tok and bl_tok > 0:
            cost_ratio = -(sg_tok / bl_tok - 1)  # positive = MCP cheaper

        raw_scores.append({
            "task_id": task_id,
            "suite": suite,
            "retrieval_lift": retrieval_lift,
            "outcome_lift": outcome_lift,
            "efficiency_lift": efficiency_lift,
            "cost_ratio": cost_ratio,
        })

    # Z-score each component
    w_ret, w_out, w_eff, w_cost = weights
    components = ["retrieval_lift", "outcome_lift", "efficiency_lift", "cost_ratio"]
    comp_weights = [w_ret, w_out, w_eff, w_cost]

    z_values: dict[str, list[float]] = {}
    for comp in components:
        vals = [r[comp] for r in raw_scores]
        z_values[comp] = _zscore(vals)

    # Build MCPValueScore objects
    results: list[MCPValueScore] = []
    for i, raw in enumerate(raw_scores):
        # Compute weighted composite from z-scored components
        composite = sum(
            z_values[comp][i] * w
            for comp, w in zip(components, comp_weights)
        )
        results.append(MCPValueScore(
            task_id=raw["task_id"],
            suite=raw["suite"],
            retrieval_lift=raw["retrieval_lift"],
            outcome_lift=raw["outcome_lift"],
            efficiency_lift=raw["efficiency_lift"],
            cost_ratio=raw["cost_ratio"],
            composite=composite,
        ))

    return results


# ---------------------------------------------------------------------------
# US-005: Cost-efficiency metrics
# ---------------------------------------------------------------------------

def compute_cost_efficiency(
    ir_scores: list[IRScores],
) -> dict | None:
    """Compute cost-efficiency metrics: tokens per relevant file found.

    Returns per-config and per-suite aggregates with deltas.
    """
    token_data = _load_task_metrics_tokens()
    if not token_data:
        return None

    # Build per-task data
    records: list[dict] = []
    for s in ir_scores:
        inp_tok = token_data.get((s.task_id, s.config_name))
        if inp_tok is None or inp_tok == 0:
            continue
        tokens_per_rel = inp_tok / s.n_overlap if s.n_overlap > 0 else None
        records.append({
            "task_id": s.task_id,
            "config": s.config_name,
            "suite": _infer_suite(s.task_id) or "unknown",
            "input_tokens": inp_tok,
            "n_overlap": s.n_overlap,
            "tokens_per_relevant_file": tokens_per_rel,
            "ttfr_step": s.ttfr_step,
            "n_steps_to_first": s.n_steps_to_first,
        })

    if not records:
        return None

    # Aggregate by (suite, config)
    by_suite_config: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_suite_config[(r["suite"], r["config"])].append(r)
        by_config[r["config"]].append(r)

    def _agg(recs: list[dict]) -> dict:
        tpr_vals = [r["tokens_per_relevant_file"] for r in recs if r["tokens_per_relevant_file"] is not None]
        tok_vals = [r["input_tokens"] for r in recs]
        overlap_vals = [r["n_overlap"] for r in recs]
        return {
            "n_tasks": len(recs),
            "mean_tokens_per_relevant_file": round(statistics.mean(tpr_vals), 0) if tpr_vals else None,
            "median_tokens_per_relevant_file": round(statistics.median(tpr_vals), 0) if tpr_vals else None,
            "mean_input_tokens": round(statistics.mean(tok_vals), 0) if tok_vals else None,
            "mean_overlap": round(statistics.mean(overlap_vals), 2) if overlap_vals else None,
        }

    overall = {cfg: _agg(recs) for cfg, recs in sorted(by_config.items())}
    per_suite = {
        f"{suite}__{cfg}": _agg(recs)
        for (suite, cfg), recs in sorted(by_suite_config.items())
    }

    # Compute deltas (baseline vs SG_full)
    bl = overall.get("baseline", {})
    sg = overall.get("sourcegraph_full", {})
    deltas = {}
    for metric in ("mean_tokens_per_relevant_file", "mean_input_tokens"):
        bl_val = bl.get(metric)
        sg_val = sg.get(metric)
        if bl_val and sg_val and bl_val > 0:
            deltas[metric] = {
                "baseline": bl_val,
                "sourcegraph_full": sg_val,
                "delta": round(sg_val - bl_val, 0),
                "pct_change": round((sg_val - bl_val) / bl_val * 100, 1),
            }

    return {
        "overall": overall,
        "per_suite": per_suite,
        "deltas": deltas,
    }


def run_ir_analysis(
    suite_filter: str | None = None,
    per_task: bool = False,
    value_weights: tuple[float, float, float, float] = (0.3, 0.3, 0.25, 0.15),
) -> dict:
    """Main analysis pipeline."""
    gt_registry = _ensure_ground_truth()
    if not gt_registry:
        return {"error": "No ground truth available. Run --build-ground-truth first."}

    tasks = _walk_task_dirs()
    # Exclude dropped benchmarks
    tasks = [t for t in tasks if t["suite"] not in DROPPED_BENCHMARKS]
    if suite_filter:
        tasks = [t for t in tasks if t["suite"] == suite_filter]

    # Compute IR scores for tasks with ground truth
    all_scores: list[IRScores] = []
    by_suite_config: dict[tuple[str, str], list[IRScores]] = defaultdict(list)
    skipped_no_gt = 0
    skipped_no_transcript = 0

    for task_info in tasks:
        task_id = task_info["task_id"]
        config = task_info["config"]
        suite = task_info["suite"]

        gt = gt_registry.get(task_id)
        if not gt:
            skipped_no_gt += 1
            continue

        if not task_info.get("transcript"):
            skipped_no_transcript += 1
            continue

        retrieved = extract_retrieved_files(Path(task_info["transcript"]))
        scores = compute_ir_scores(
            retrieved=retrieved,
            ground_truth_files=gt.files,
            task_id=task_id,
            config_name=config,
        )

        # Time-to-context from trajectory.json
        task_dir_path = Path(task_info["task_dir"])
        trajectory = task_dir_path / "agent" / "trajectory.json"
        if not trajectory.is_file():
            trajectory = task_dir_path / "trajectory.json"
        ttc = extract_time_to_context(
            trajectory_path=trajectory,
            transcript_path=Path(task_info["transcript"]),
            ground_truth_files=gt.files,
        )
        if ttc:
            scores.ttfr = ttc.get("ttfr")
            scores.ttfr_step = ttc.get("ttfr_step")
            scores.tt_all_r = ttc.get("tt_all_r")
            scores.n_steps_to_first = ttc.get("n_steps_to_first")

        all_scores.append(scores)
        by_suite_config[(suite, config)].append(scores)

    # Aggregate
    overall_by_config: dict[str, list[IRScores]] = defaultdict(list)
    for s in all_scores:
        overall_by_config[s.config_name].append(s)

    result: dict = {
        "summary": {
            "total_tasks_with_gt": len(gt_registry),
            "total_runs_analyzed": len(all_scores),
            "skipped_no_ground_truth": skipped_no_gt,
            "skipped_no_transcript": skipped_no_transcript,
        },
        "overall_by_config": {
            cfg: aggregate_ir_scores(scores)
            for cfg, scores in sorted(overall_by_config.items())
        },
        "by_suite_config": {
            f"{suite}__{cfg}": aggregate_ir_scores(scores)
            for (suite, cfg), scores in sorted(by_suite_config.items())
        },
    }

    # Statistical tests: compare baseline vs SG_full
    bl_scores = overall_by_config.get("baseline", [])
    sg_scores = overall_by_config.get("sourcegraph_full", [])
    if len(bl_scores) >= 5 and len(sg_scores) >= 5:
        try:
            from ccb_metrics.statistics import welchs_t_test, cohens_d, bootstrap_ci

            # Match by task_id for paired comparison
            bl_by_id = {s.task_id: s for s in bl_scores}
            sg_by_id = {s.task_id: s for s in sg_scores}
            common = set(bl_by_id) & set(sg_by_id)

            if len(common) >= 5:
                bl_recalls = [bl_by_id[tid].file_recall for tid in sorted(common)]
                sg_recalls = [sg_by_id[tid].file_recall for tid in sorted(common)]
                bl_mrrs = [bl_by_id[tid].mrr for tid in sorted(common)]
                sg_mrrs = [sg_by_id[tid].mrr for tid in sorted(common)]

                stat_tests: dict = {
                    "n_paired": len(common),
                    "file_recall": {
                        "welchs_t": welchs_t_test(bl_recalls, sg_recalls),
                        "cohens_d": cohens_d(bl_recalls, sg_recalls),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_recalls, sg_recalls)]
                        ),
                    },
                    "mrr": {
                        "welchs_t": welchs_t_test(bl_mrrs, sg_mrrs),
                        "cohens_d": cohens_d(bl_mrrs, sg_mrrs),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_mrrs, sg_mrrs)]
                        ),
                    },
                }

                # TTFR comparison (lower is better)
                bl_ttfrs = [bl_by_id[tid].ttfr for tid in sorted(common) if bl_by_id[tid].ttfr is not None]
                sg_ttfrs = [sg_by_id[tid].ttfr for tid in sorted(common) if sg_by_id[tid].ttfr is not None]
                if len(bl_ttfrs) >= 5 and len(sg_ttfrs) >= 5:
                    stat_tests["ttfr"] = {
                        "welchs_t": welchs_t_test(bl_ttfrs, sg_ttfrs),
                        "cohens_d": cohens_d(bl_ttfrs, sg_ttfrs),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_ttfrs, sg_ttfrs)]
                        ),
                    }

                # TTAR: time to ALL relevant files (lower is better)
                # Must be paired — both configs need tt_all_r for same task
                paired_ttar = [
                    (bl_by_id[tid].tt_all_r, sg_by_id[tid].tt_all_r)
                    for tid in sorted(common)
                    if bl_by_id[tid].tt_all_r is not None
                    and sg_by_id[tid].tt_all_r is not None
                ]
                if len(paired_ttar) >= 5:
                    bl_ttar = [p[0] for p in paired_ttar]
                    sg_ttar = [p[1] for p in paired_ttar]
                    stat_tests["tt_all_r"] = {
                        "n_paired": len(paired_ttar),
                        "welchs_t": welchs_t_test(bl_ttar, sg_ttar),
                        "cohens_d": cohens_d(bl_ttar, sg_ttar),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_ttar, sg_ttar)]
                        ),
                    }

                result["statistical_tests"] = stat_tests
        except ImportError:
            pass

    # US-003: Retrieval-outcome correlation
    corr = compute_retrieval_outcome_correlation(all_scores)
    if corr:
        result["retrieval_outcome_correlation"] = corr

    # US-004: Composite MCP value scores
    value_scores = compute_mcp_value_scores(all_scores, weights=value_weights)
    if value_scores:
        by_suite: dict[str, list[MCPValueScore]] = defaultdict(list)
        for vs in value_scores:
            by_suite[vs.suite].append(vs)
        result["mcp_value_scores"] = {
            "n_tasks": len(value_scores),
            "weights": {"retrieval": value_weights[0], "outcome": value_weights[1],
                        "efficiency": value_weights[2], "cost": value_weights[3]},
            "per_suite_mean": {
                suite: round(statistics.mean(v.composite for v in scores), 4)
                for suite, scores in sorted(by_suite.items())
            },
            "top_helped": [v.to_dict() for v in sorted(value_scores, key=lambda v: -v.composite)[:10]],
            "top_hurt": [v.to_dict() for v in sorted(value_scores, key=lambda v: v.composite)[:10]],
        }

    # US-005: Cost-efficiency metrics
    cost_eff = compute_cost_efficiency(all_scores)
    if cost_eff:
        result["cost_efficiency"] = cost_eff

    if per_task:
        result["per_task"] = [s.to_dict() for s in all_scores]

    return result


def format_table(data: dict) -> str:
    """Format IR analysis results as ASCII table."""
    lines = []
    lines.append("IR Analysis Report")
    lines.append("=" * 70)
    lines.append("")

    s = data.get("summary", {})
    lines.append(f"Tasks with ground truth: {s.get('total_tasks_with_gt', 0)}")
    lines.append(f"Runs analyzed:           {s.get('total_runs_analyzed', 0)}")
    lines.append(f"Skipped (no GT):         {s.get('skipped_no_ground_truth', 0)}")
    lines.append(f"Skipped (no transcript): {s.get('skipped_no_transcript', 0)}")
    lines.append("")

    # Overall by config
    overall = data.get("overall_by_config", {})
    if overall:
        lines.append("OVERALL BY CONFIG:")
        header = f"  {'Config':20s} {'MRR':>8s} {'MAP':>8s} {'F.Recall':>8s} {'Ctx.Eff':>8s} {'TTFR(s)':>8s} {'TTAR(s)':>8s} {'Steps':>6s} {'n':>5s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))

        for cfg, agg in sorted(overall.items()):
            if not agg:
                continue
            row = f"  {cfg:20s}"
            for metric in ("mrr", "map_score", "file_recall", "context_efficiency"):
                val = agg.get(metric, {}).get("mean", 0.0)
                row += f" {val:>8.3f}"
            ttfr = agg.get("ttfr", {}).get("median")
            ttar = agg.get("tt_all_r", {}).get("median")
            steps = agg.get("n_steps_to_first", {}).get("median")
            row += f" {ttfr:>8.1f}" if ttfr is not None else f" {'N/A':>8s}"
            row += f" {ttar:>8.1f}" if ttar is not None else f" {'N/A':>8s}"
            row += f" {steps:>6.0f}" if steps is not None else f" {'N/A':>6s}"
            n = agg.get("_totals", {}).get("n_tasks", 0)
            row += f" {n:>5d}"
            lines.append(row)
        lines.append("")

    # By suite+config
    by_sc = data.get("by_suite_config", {})
    if by_sc:
        lines.append("BY SUITE x CONFIG:")
        header = f"  {'Suite__Config':35s} {'MRR':>7s} {'F.Rec':>7s} {'TTFR':>7s} {'TTAR':>7s} {'Steps':>5s} {'n':>4s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))

        for key, agg in sorted(by_sc.items()):
            if not agg:
                continue
            mrr_m = agg.get("mrr", {}).get("mean", 0.0)
            fr_m = agg.get("file_recall", {}).get("mean", 0.0)
            ttfr_m = agg.get("ttfr", {}).get("median")
            ttar_m = agg.get("tt_all_r", {}).get("median")
            steps_m = agg.get("n_steps_to_first", {}).get("median")
            n = agg.get("_totals", {}).get("n_tasks", 0)
            ttfr_s = f"{ttfr_m:>7.1f}" if ttfr_m is not None else f"{'—':>7s}"
            ttar_s = f"{ttar_m:>7.1f}" if ttar_m is not None else f"{'—':>7s}"
            steps_s = f"{steps_m:>5.0f}" if steps_m is not None else f"{'—':>5s}"
            lines.append(f"  {key:35s} {mrr_m:>7.3f} {fr_m:>7.3f} {ttfr_s} {ttar_s} {steps_s} {n:>4d}")
        lines.append("")

    # Statistical tests
    stats = data.get("statistical_tests", {})
    if stats:
        lines.append("STATISTICAL TESTS (baseline vs SG_full):")
        lines.append(f"  Paired tasks: {stats.get('n_paired', 0)}")
        for metric_name in ("file_recall", "mrr", "ttfr", "tt_all_r"):
            ms = stats.get(metric_name, {})
            if not ms:
                continue
            t = ms.get("welchs_t", {})
            d = ms.get("cohens_d", {})
            bci = ms.get("bootstrap_ci_delta", {})
            sig = "***" if t.get("is_significant") else "n.s."
            n_note = f" (n={ms['n_paired']})" if "n_paired" in ms else ""
            lines.append(
                f"  {metric_name}: t={t.get('t_stat', 'N/A')}, "
                f"p={t.get('p_value', 'N/A')}, d={d.get('d', 'N/A')} "
                f"({d.get('magnitude', '')}), "
                f"delta CI=[{bci.get('ci_lower', 'N/A')}, {bci.get('ci_upper', 'N/A')}] "
                f"{sig}{n_note}"
            )
        lines.append("")

    # Retrieval-outcome correlation
    corr = data.get("retrieval_outcome_correlation", {})
    if corr:
        lines.append("RETRIEVAL-OUTCOME CORRELATION:")
        lines.append(f"  Paired observations: {corr.get('n_paired', 0)}")
        lines.append(f"  Tasks with both configs: {corr.get('n_paired_both_configs', 0)}")
        lines.append(f"  Spearman r:  {corr.get('spearman_r', 'N/A')}")
        lines.append(f"  p-value:     {corr.get('spearman_p', 'N/A')}")
        lines.append(f"  {corr.get('interpretation', '')}")
        scatter = corr.get("scatter", [])
        if scatter:
            lines.append("")
            lines.append("  Per-task deltas (SG_full - baseline):")
            header = f"    {'Task':40s} {'Suite':20s} {'MRR_d':>7s} {'Rew_d':>7s}"
            lines.append(header)
            lines.append("    " + "-" * (len(header) - 4))
            for row in scatter:
                lines.append(
                    f"    {row['task_id']:40s} {row['suite']:20s} "
                    f"{row.get('mrr_delta', 0):>+7.3f} {row.get('reward_delta', 0):>+7.3f}"
                )
        lines.append("")

    # MCP Value Scores
    mvs = data.get("mcp_value_scores", {})
    if mvs:
        lines.append("MCP VALUE SCORES (z-scored composite):")
        w = mvs.get("weights", {})
        lines.append(
            f"  Weights: retrieval={w.get('retrieval', 0.3)}, "
            f"outcome={w.get('outcome', 0.3)}, "
            f"efficiency={w.get('efficiency', 0.25)}, "
            f"cost={w.get('cost', 0.15)}"
        )
        lines.append(f"  Tasks scored: {mvs.get('n_tasks', 0)}")
        lines.append("")

        per_suite = mvs.get("per_suite_mean", {})
        if per_suite:
            lines.append("  Per-suite mean composite:")
            for suite, mean in sorted(per_suite.items(), key=lambda x: -x[1]):
                bar = "+" * max(0, int(mean * 5)) if mean > 0 else "-" * max(0, int(-mean * 5))
                lines.append(f"    {suite:30s} {mean:>+7.3f}  {bar}")
            lines.append("")

        top_helped = mvs.get("top_helped", [])
        if top_helped:
            lines.append("  Top 10 MCP-helped tasks:")
            header = f"    {'Task':40s} {'Suite':20s} {'Comp':>7s} {'Ret':>7s} {'Out':>7s} {'Eff':>7s} {'Cost':>7s}"
            lines.append(header)
            lines.append("    " + "-" * (len(header) - 4))
            for t in top_helped:
                lines.append(
                    f"    {t['task_id']:40s} {t['suite']:20s} "
                    f"{t['composite']:>+7.3f} {t['retrieval_lift']:>+7.3f} "
                    f"{t['outcome_lift']:>+7.3f} {t['efficiency_lift']:>+7.3f} "
                    f"{t['cost_ratio']:>+7.3f}"
                )
            lines.append("")

        top_hurt = mvs.get("top_hurt", [])
        if top_hurt:
            lines.append("  Top 10 MCP-hurt tasks:")
            header = f"    {'Task':40s} {'Suite':20s} {'Comp':>7s} {'Ret':>7s} {'Out':>7s} {'Eff':>7s} {'Cost':>7s}"
            lines.append(header)
            lines.append("    " + "-" * (len(header) - 4))
            for t in top_hurt:
                lines.append(
                    f"    {t['task_id']:40s} {t['suite']:20s} "
                    f"{t['composite']:>+7.3f} {t['retrieval_lift']:>+7.3f} "
                    f"{t['outcome_lift']:>+7.3f} {t['efficiency_lift']:>+7.3f} "
                    f"{t['cost_ratio']:>+7.3f}"
                )
            lines.append("")

    # Cost efficiency
    ce = data.get("cost_efficiency", {})
    if ce:
        lines.append("COST EFFICIENCY:")
        overall = ce.get("overall", {})
        if overall:
            header = f"  {'Config':20s} {'Tok/RelFile':>12s} {'MeanTokens':>12s} {'MeanOverlap':>12s} {'n':>5s}"
            lines.append(header)
            lines.append("  " + "-" * (len(header) - 2))
            for cfg, agg in sorted(overall.items()):
                tpr = agg.get("mean_tokens_per_relevant_file")
                tok = agg.get("mean_input_tokens")
                ovl = agg.get("mean_overlap")
                n = agg.get("n_tasks", 0)
                tpr_s = f"{tpr:>12,.0f}" if tpr else f"{'N/A':>12s}"
                tok_s = f"{tok:>12,.0f}" if tok else f"{'N/A':>12s}"
                ovl_s = f"{ovl:>12.1f}" if ovl else f"{'N/A':>12s}"
                lines.append(f"  {cfg:20s} {tpr_s} {tok_s} {ovl_s} {n:>5d}")
            lines.append("")

        deltas = ce.get("deltas", {})
        if deltas:
            lines.append("  Baseline vs SG_full deltas:")
            for metric, d in sorted(deltas.items()):
                label = metric.replace("mean_", "")
                lines.append(
                    f"    {label:30s} BL={d['baseline']:>12,.0f}  "
                    f"SG={d['sourcegraph_full']:>12,.0f}  "
                    f"delta={d['delta']:>+12,.0f}  ({d['pct_change']:>+.1f}%)"
                )
            lines.append("")

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="IR quality analysis for CodeContextBench."
    )
    parser.add_argument(
        "--build-ground-truth", action="store_true",
        help="Extract ground truth for all selected tasks and write cache",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output JSON instead of table",
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite",
    )
    parser.add_argument(
        "--per-task", action="store_true",
        help="Include per-task IR scores in output",
    )
    parser.add_argument(
        "--value-weights", default="0.3,0.3,0.25,0.15",
        help="Comma-separated weights for MCP value composite: retrieval,outcome,efficiency,cost",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.build_ground_truth:
        selected = _load_selected_tasks()
        registry = build_ground_truth_registry(BENCHMARKS_DIR, selected)
        save_registry(registry, GT_CACHE)
        print(f"Ground truth extracted for {len(registry)} tasks → {GT_CACHE}")
        # Show breakdown
        by_bench = defaultdict(int)
        by_source = defaultdict(int)
        by_confidence = defaultdict(int)
        for gt in registry.values():
            by_bench[gt.benchmark] += 1
            by_source[gt.source] += 1
            by_confidence[gt.confidence] += 1
        print(f"  By benchmark: {dict(sorted(by_bench.items()))}")
        print(f"  By source:    {dict(sorted(by_source.items()))}")
        print(f"  By confidence:{dict(sorted(by_confidence.items()))}")
        return

    # Parse value weights
    try:
        vw = tuple(float(x) for x in args.value_weights.split(","))
        if len(vw) != 4:
            raise ValueError
    except ValueError:
        print("ERROR: --value-weights must be 4 comma-separated floats", file=sys.stderr)
        sys.exit(1)

    data = run_ir_analysis(
        suite_filter=args.suite,
        per_task=args.per_task,
        value_weights=vw,
    )

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_table(data))


if __name__ == "__main__":
    main()

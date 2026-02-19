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
    extract_tokens_before_first_relevant,
    extract_cost_metrics_before_first_relevant,
    extract_agent_time_to_first_relevant,
    IRScores,
    MCPValueScore,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs" / "official"
STAGING_DIR = REPO_ROOT / "runs" / "staging"
MANIFEST_PATH = RUNS_DIR / "MANIFEST.json"
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
SELECTION_FILE = REPO_ROOT / "configs" / "selected_benchmark_tasks.json"
GT_CACHE = REPO_ROOT / "configs" / "ground_truth_files.json"

# __v1_hinted: old run dirs from before enterprise task de-hinting (US-001..US-003).
# Appended to batch dir names after reruns complete so pre-redesign data is excluded.
SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived", "preamble_test_", "__v1_hinted"]
CONFIGS = ["baseline", "sourcegraph_full"]
# Benchmarks dropped from evaluation — exclude from ground truth builds and IR analysis
DROPPED_BENCHMARKS = {"ccb_dependeval", "ccb_locobench"}

DIR_PREFIX_TO_SUITE = {
    # Legacy benchmark prefixes (runs/official/)
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "docgen_": "ccb_docgen",
    "enterprise_": "ccb_enterprise",
    "governance_": "ccb_governance",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "nlqa_": "ccb_nlqa",
    "onboarding_": "ccb_onboarding",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "security_": "ccb_security",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "paired_rerun_": None,
    # SDLC phase suite prefixes (runs/staging/)
    "build_": "ccb_build",
    "debug_": "ccb_debug",
    "design_": "ccb_design",
    "document_": "ccb_document",
    "fix_": "ccb_fix",
    "secure_": "ccb_secure",
    "test_": "ccb_test",
    "understand_": "ccb_understand",
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


def _walk_sdlc_staging_dirs(runs_dir: Path) -> list[dict]:
    """Walk SDLC staging run directories.

    SDLC staging layout:
        runs/staging/{suite_stem}_{model}_{ts}/{config}/{job_name}/{trial_dir}/
    Where:
        job_name = ccb_{suite_stem}_{task_id}_{config}
        trial_dir = sdlc_{suite_stem}_{task_prefix}__{hash}
    """
    all_tasks: dict[tuple[str, str, str], dict] = {}

    if not runs_dir.exists():
        return []

    for run_dir in sorted(runs_dir.iterdir()):
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

            for job_dir in sorted(config_dir.iterdir()):
                if not job_dir.is_dir():
                    continue
                job_name = job_dir.name

                # Extract task_id from job_name: ccb_{suite}_{task_id}_{config}
                # e.g. ccb_test_aspnetcore-code-review-001_sourcegraph_full
                task_id = _extract_task_id_from_job(job_name, config_name, suite)
                if not task_id:
                    continue

                # Find the trial subdirectory (there should be exactly one)
                trial_dir = None
                for sub in sorted(job_dir.iterdir()):
                    if sub.is_dir() and sub.name not in ("archive",):
                        # Skip non-trial dirs (logs, etc.)
                        if (sub / "result.json").is_file():
                            trial_dir = sub
                            break

                if trial_dir is None:
                    continue

                transcript = trial_dir / "agent" / "claude-code.txt"
                if not transcript.is_file():
                    transcript = trial_dir / "claude-code.txt"

                started_at = ""
                result_file = trial_dir / "result.json"
                if result_file.is_file():
                    try:
                        rdata = json.loads(result_file.read_text())
                        started_at = rdata.get("started_at", "")
                    except Exception:
                        pass

                task_suite = suite or _infer_suite(task_id)

                info = {
                    "task_id": task_id,
                    "suite": task_suite or "unknown",
                    "config": config_name,
                    "task_dir": str(trial_dir),
                    "transcript": str(transcript) if transcript.is_file() else None,
                    "started_at": started_at,
                }

                key = (info["suite"], config_name, task_id)
                if key in all_tasks:
                    if started_at > all_tasks[key].get("started_at", ""):
                        all_tasks[key] = info
                else:
                    all_tasks[key] = info

    return list(all_tasks.values())


def _extract_task_id_from_job(job_name: str, config_name: str, suite: str | None) -> str | None:
    """Extract task_id from SDLC job directory name.

    Job name format: ccb_{suite_stem}_{task_id}_{config}
    e.g. ccb_test_aspnetcore-code-review-001_sourcegraph_full → aspnetcore-code-review-001
    """
    # Strip config suffix
    for cfg in ("_sourcegraph_full", "_baseline"):
        if job_name.endswith(cfg):
            job_name = job_name[: -len(cfg)]
            break
    else:
        return None

    # Strip ccb_{suite_stem}_ prefix
    if suite:
        suite_stem = suite.removeprefix("ccb_")
        prefix = f"ccb_{suite_stem}_"
        if job_name.startswith(prefix):
            return job_name[len(prefix):]

    # Fallback: try all known SDLC suite stems
    for stem in ("build", "debug", "design", "document", "fix", "secure", "test", "understand"):
        prefix = f"ccb_{stem}_"
        if job_name.startswith(prefix):
            return job_name[len(prefix):]

    return None


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
    """Load (task_id, config) -> total input tokens from task_metrics.json files.

    Total input = input_tokens + cache_creation_tokens + cache_read_tokens.
    Raw input_tokens alone is just the uncached portion (often <100) and not
    meaningful for cost efficiency analysis.
    """
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
                        # Sum all input token types for total input consumption
                        inp = (
                            (m.get("input_tokens") or 0)
                            + (m.get("cache_creation_tokens") or 0)
                            + (m.get("cache_read_tokens") or 0)
                        )
                        if task_id and inp > 0:
                            key = (task_id, config)
                            # Keep latest by not overwriting (first seen wins — sorted dirs)
                            if key not in tokens:
                                tokens[key] = int(inp)
                    except (json.JSONDecodeError, OSError, ValueError):
                        continue
    return tokens


def _load_task_metrics_cost() -> dict[tuple[str, str], float]:
    """Load (task_id, config) -> total run cost in USD from task_metrics.json.

    Uses the pre-computed cost_usd field which accounts for all token types
    at Anthropic Opus pricing: input ($15/Mtok), cache_create ($18.75/Mtok),
    cache_read ($1.50/Mtok), output ($75/Mtok). This is the full-run cost,
    not just the cost up to first relevant file.
    """
    costs: dict[tuple[str, str], float] = {}
    if not RUNS_DIR.exists():
        return costs
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
                        cost = m.get("cost_usd")
                        if task_id and cost is not None and cost > 0:
                            key = (task_id, config)
                            if key not in costs:
                                costs[key] = float(cost)
                    except (json.JSONDecodeError, OSError, ValueError):
                        continue
    return costs


def _load_zero_mcp_sg_tasks() -> set[str]:
    """Load task_ids where SG_full config had zero MCP tool usage.

    These are invalid treatment runs — MCP tools were available but never
    invoked, so the run is effectively a baseline with extra prompt overhead.
    Exclude these from all SG_full aggregations.
    """
    zero_mcp: set[str] = set()
    if not RUNS_DIR.exists():
        return zero_mcp
    # Track latest per task_id (same dedup logic as other loaders)
    seen: dict[str, str] = {}  # task_id -> started_at
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue
        for config_dir in run_dir.iterdir():
            if not config_dir.is_dir() or config_dir.name != "sourcegraph_full":
                continue
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
                        if not task_id:
                            continue
                        mcp_calls = m.get("tool_calls_mcp")
                        mcp_ratio = m.get("mcp_ratio")
                        is_zero = (mcp_calls is None or mcp_calls == 0
                                   or (mcp_ratio is not None and mcp_ratio == 0))
                        # Timestamp-based dedup
                        started_at = ""
                        result_file = task_dir / "result.json"
                        if result_file.is_file():
                            try:
                                rdata = json.loads(result_file.read_text())
                                started_at = rdata.get("started_at", "")
                            except (json.JSONDecodeError, OSError):
                                pass
                        if task_id not in seen or started_at > seen[task_id]:
                            seen[task_id] = started_at
                            if is_zero:
                                zero_mcp.add(task_id)
                            else:
                                zero_mcp.discard(task_id)
                    except (json.JSONDecodeError, OSError, ValueError):
                        continue
    return zero_mcp


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
    weights: tuple[float, ...] = (0.25, 0.25, 0.20, 0.15, 0.15),
) -> list[MCPValueScore]:
    """Compute composite MCP value scores for tasks with both configs.

    5 components (all computed as SG_full - baseline deltas, positive = MCP helps):
    - retrieval_lift (0.25): MRR delta
    - outcome_lift (0.25): reward delta
    - time_efficiency (0.20): agent_time_to_first_relevant improvement ratio
    - cost_efficiency (0.15): dollar-cost-before-first-relevant improvement ratio
    - token_efficiency (0.15): output-tokens-before-first-relevant improvement ratio

    Each component is z-scored across all tasks before weighting.
    Efficiency is a first-class dimension with 3 sub-components (time, cost, token).
    """
    manifest_rewards = _load_manifest_rewards()
    token_data = _load_task_metrics_tokens()
    zero_mcp = _load_zero_mcp_sg_tasks()

    # Build per-config lookups (exclude zero-MCP SG_full runs)
    bl_ir: dict[str, IRScores] = {}
    sg_ir: dict[str, IRScores] = {}
    for s in ir_scores:
        if s.config_name == "baseline":
            bl_ir[s.task_id] = s
        elif s.config_name == "sourcegraph_full":
            if s.task_id not in zero_mcp:
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

        # Time efficiency: agent_time_to_first_relevant (positive = MCP faster)
        time_efficiency = 0.0
        bl_attfr = bl.agent_time_to_first_relevant
        sg_attfr = sg.agent_time_to_first_relevant
        if bl_attfr is not None and sg_attfr is not None and bl_attfr > 0:
            time_efficiency = (bl_attfr - sg_attfr) / bl_attfr
        elif bl.ttfr is not None and sg.ttfr is not None and bl.ttfr > 0:
            # Fallback to session TTFR if agent_time unavailable
            time_efficiency = (bl.ttfr - sg.ttfr) / bl.ttfr

        # Cost efficiency: dollar cost before first relevant (positive = MCP cheaper)
        cost_efficiency_val = 0.0
        bl_cost = bl.cost_before_first_relevant
        sg_cost = sg.cost_before_first_relevant
        if bl_cost is not None and sg_cost is not None and bl_cost > 0:
            cost_efficiency_val = -(sg_cost / bl_cost - 1)
        else:
            # Fallback to total token ratio
            bl_tok = token_data.get((task_id, "baseline"))
            sg_tok = token_data.get((task_id, "sourcegraph_full"))
            if bl_tok and sg_tok and bl_tok > 0:
                cost_efficiency_val = -(sg_tok / bl_tok - 1)

        # Token efficiency: output tokens before first relevant (positive = MCP fewer)
        token_efficiency = 0.0
        bl_out = bl.output_tokens_before_first_relevant
        sg_out = sg.output_tokens_before_first_relevant
        if bl_out is not None and sg_out is not None and bl_out > 0:
            token_efficiency = -(sg_out / bl_out - 1)

        raw_scores.append({
            "task_id": task_id,
            "suite": suite,
            "retrieval_lift": retrieval_lift,
            "outcome_lift": outcome_lift,
            "time_efficiency": time_efficiency,
            "cost_efficiency": cost_efficiency_val,
            "token_efficiency": token_efficiency,
        })

    # Z-score each component
    components = ["retrieval_lift", "outcome_lift", "time_efficiency", "cost_efficiency", "token_efficiency"]
    # Pad weights tuple if caller provides old 4-element tuple
    if len(weights) == 4:
        w_ret, w_out, w_eff_old, w_cost_old = weights
        comp_weights = [w_ret, w_out, w_eff_old * 0.8, w_cost_old, w_eff_old * 0.2]
    else:
        comp_weights = list(weights[:5])

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
        # For backward compat, pack time_efficiency into efficiency_lift
        # and cost_efficiency into cost_ratio in the MCPValueScore dataclass
        results.append(MCPValueScore(
            task_id=raw["task_id"],
            suite=raw["suite"],
            retrieval_lift=raw["retrieval_lift"],
            outcome_lift=raw["outcome_lift"],
            efficiency_lift=raw["time_efficiency"],
            cost_ratio=raw["cost_efficiency"],
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
    Includes both efficiency metrics (cost to first relevant) and
    full-run ROI metrics (total cost with vs without MCP).
    """
    token_data = _load_task_metrics_tokens()
    cost_data = _load_task_metrics_cost()
    zero_mcp = _load_zero_mcp_sg_tasks()
    if not token_data:
        return None

    # Build per-task data (exclude zero-MCP SG_full runs)
    records: list[dict] = []
    for s in ir_scores:
        if s.config_name == "sourcegraph_full" and s.task_id in zero_mcp:
            continue
        inp_tok = token_data.get((s.task_id, s.config_name))
        if inp_tok is None or inp_tok == 0:
            continue
        tokens_per_rel = inp_tok / s.n_overlap if s.n_overlap > 0 else None
        total_cost = cost_data.get((s.task_id, s.config_name))
        records.append({
            "task_id": s.task_id,
            "config": s.config_name,
            "suite": _infer_suite(s.task_id) or "unknown",
            "input_tokens": inp_tok,
            "n_overlap": s.n_overlap,
            "tokens_per_relevant_file": tokens_per_rel,
            "tokens_before_first_relevant": s.tokens_before_first_relevant,
            "cost_before_first_relevant": s.cost_before_first_relevant,
            "output_tokens_before_first_relevant": s.output_tokens_before_first_relevant,
            "agent_time_to_first_relevant": s.agent_time_to_first_relevant,
            "total_cost_usd": total_cost,
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

    def _safe_mean(vals: list) -> float | None:
        return round(statistics.mean(vals), 4) if vals else None

    def _agg(recs: list[dict]) -> dict:
        tpr_vals = [r["tokens_per_relevant_file"] for r in recs if r["tokens_per_relevant_file"] is not None]
        tok_vals = [r["input_tokens"] for r in recs]
        overlap_vals = [r["n_overlap"] for r in recs]
        tbfr_vals = [r["tokens_before_first_relevant"] for r in recs if r["tokens_before_first_relevant"] is not None]
        cost_vals = [r["cost_before_first_relevant"] for r in recs if r["cost_before_first_relevant"] is not None]
        out_tok_vals = [r["output_tokens_before_first_relevant"] for r in recs if r["output_tokens_before_first_relevant"] is not None]
        agent_ttfr_vals = [r["agent_time_to_first_relevant"] for r in recs if r["agent_time_to_first_relevant"] is not None]
        total_cost_vals = [r["total_cost_usd"] for r in recs if r["total_cost_usd"] is not None]
        return {
            "n_tasks": len(recs),
            "mean_tokens_per_relevant_file": round(statistics.mean(tpr_vals), 0) if tpr_vals else None,
            "median_tokens_per_relevant_file": round(statistics.median(tpr_vals), 0) if tpr_vals else None,
            "mean_tokens_before_first_relevant": round(statistics.mean(tbfr_vals), 0) if tbfr_vals else None,
            "median_tokens_before_first_relevant": round(statistics.median(tbfr_vals), 0) if tbfr_vals else None,
            "mean_cost_before_first_relevant": round(statistics.mean(cost_vals), 4) if cost_vals else None,
            "mean_output_tokens_before_first_relevant": round(statistics.mean(out_tok_vals), 0) if out_tok_vals else None,
            "mean_agent_time_to_first_relevant": round(statistics.mean(agent_ttfr_vals), 1) if agent_ttfr_vals else None,
            "mean_total_cost_usd": round(statistics.mean(total_cost_vals), 4) if total_cost_vals else None,
            "median_total_cost_usd": round(statistics.median(total_cost_vals), 4) if total_cost_vals else None,
            "mean_input_tokens": round(statistics.mean(tok_vals), 0) if tok_vals else None,
            "mean_overlap": round(statistics.mean(overlap_vals), 2) if overlap_vals else None,
            "n_with_tbfr": len(tbfr_vals),
            "n_with_total_cost": len(total_cost_vals),
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
    delta_metrics = (
        "mean_total_cost_usd",
        "mean_tokens_per_relevant_file",
        "mean_tokens_before_first_relevant",
        "mean_cost_before_first_relevant",
        "mean_output_tokens_before_first_relevant",
        "mean_agent_time_to_first_relevant",
        "mean_input_tokens",
    )
    for metric in delta_metrics:
        bl_val = bl.get(metric)
        sg_val = sg.get(metric)
        if bl_val and sg_val and bl_val > 0:
            delta_val = sg_val - bl_val
            # Round appropriately based on metric type
            if "cost" in metric:
                delta_val = round(delta_val, 4)
            elif "time" in metric:
                delta_val = round(delta_val, 1)
            else:
                delta_val = round(delta_val, 0)
            deltas[metric] = {
                "baseline": bl_val,
                "sourcegraph_full": sg_val,
                "delta": delta_val,
                "pct_change": round((sg_val - bl_val) / bl_val * 100, 1),
            }

    return {
        "overall": overall,
        "per_suite": per_suite,
        "deltas": deltas,
    }


def _compute_per_suite_correlation(
    ir_scores: list[IRScores],
    gt_registry: dict[str, TaskGroundTruth],
) -> dict | None:
    """Compute per-suite Spearman retrieval-outcome correlation.

    Uses retrieval_outcome_correlation from ccb_metrics.statistics for the
    heavy lifting: file_recall as IR metric, reward from MANIFEST.
    Returns per-suite rho, p-value, and effect size.
    """
    manifest_rewards = _load_manifest_rewards()
    if not manifest_rewards:
        return None

    # Build parallel lists: ir_score, reward, suite_label
    ir_vals: list[float] = []
    reward_vals: list[float] = []
    suite_labels: list[str] = []

    for s in ir_scores:
        reward = manifest_rewards.get((s.task_id, s.config_name))
        if reward is None:
            continue
        suite = _infer_suite(s.task_id) or "unknown"
        ir_vals.append(s.file_recall)
        reward_vals.append(reward)
        suite_labels.append(suite)

    if len(ir_vals) < 3:
        return None

    try:
        from ccb_metrics.statistics import retrieval_outcome_correlation
        return retrieval_outcome_correlation(ir_vals, reward_vals, suite_labels)
    except ImportError:
        return None


def run_ir_analysis(
    suite_filter: str | None = None,
    per_task: bool = False,
    value_weights: tuple[float, ...] = (0.25, 0.25, 0.20, 0.15, 0.15),
    runs_dir: Path | None = None,
    staging: bool = False,
    min_confidence: str = "medium",
    correlate: bool = False,
) -> dict:
    """Main analysis pipeline.

    Args:
        min_confidence: Minimum GT confidence for aggregate metrics.
            "low" includes everything (backwards compatible).
            "medium" excludes low-confidence tasks from aggregates.
            "high" restricts aggregates to high-confidence GT only.
            Tasks excluded from aggregates are still included in per-task
            output with a [low-conf] marker.
        correlate: If True, compute per-suite Spearman retrieval-outcome
            correlation via ccb_metrics.statistics.retrieval_outcome_correlation.
    """
    gt_registry = _ensure_ground_truth()
    if not gt_registry:
        return {"error": "No ground truth available. Run --build-ground-truth first."}

    if runs_dir:
        # Custom runs directory: try SDLC layout first, then official layout
        tasks = _walk_sdlc_staging_dirs(runs_dir)
        if not tasks:
            tasks = _walk_task_dirs()
    elif staging:
        tasks = _walk_sdlc_staging_dirs(STAGING_DIR)
    else:
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
            # Cost metrics before first relevant file
            cost_metrics = extract_cost_metrics_before_first_relevant(
                transcript_path=Path(task_info["transcript"]),
                n_steps_to_first=scores.n_steps_to_first,
            )
            if cost_metrics:
                scores.tokens_before_first_relevant = cost_metrics.get("tokens_total")
                scores.output_tokens_before_first_relevant = cost_metrics.get("output_tokens")
                scores.cost_before_first_relevant = cost_metrics.get("cost_usd")
            # Agent-time TTFR (excludes Docker/setup, measures from first tool exec)
            scores.agent_time_to_first_relevant = extract_agent_time_to_first_relevant(
                trajectory_path=trajectory,
                n_steps_to_first=scores.n_steps_to_first,
            )

        all_scores.append(scores)
        by_suite_config[(suite, config)].append(scores)

    # Filter out zero-MCP SG_full runs (invalid treatment data)
    zero_mcp_tasks = _load_zero_mcp_sg_tasks()
    n_before = len(all_scores)
    flagged_ids = set()
    if zero_mcp_tasks:
        filtered_scores: list[IRScores] = []
        filtered_by_sc: dict[tuple[str, str], list[IRScores]] = defaultdict(list)
        for s in all_scores:
            if s.config_name == "sourcegraph_full" and s.task_id in zero_mcp_tasks:
                flagged_ids.add(s.task_id)
                continue
            filtered_scores.append(s)
            suite_key = _infer_suite(s.task_id) or "unknown"
            filtered_by_sc[(suite_key, s.config_name)].append(s)
        all_scores = filtered_scores
        by_suite_config = filtered_by_sc

    n_flagged = n_before - len(all_scores)

    # --- Confidence gating (US-011) ---
    # Build lookup: task_id -> confidence level from ground truth registry
    _CONF_ORDER = {"high": 3, "medium": 2, "low": 1}
    min_conf_level = _CONF_ORDER.get(min_confidence, 2)

    # Identify tasks below the confidence threshold
    low_conf_task_ids: set[str] = set()
    for s in all_scores:
        gt = gt_registry.get(s.task_id)
        if gt:
            task_conf = _CONF_ORDER.get(gt.confidence, 1)
            if task_conf < min_conf_level:
                low_conf_task_ids.add(s.task_id)

    # Split scores: agg_scores for aggregation, all_scores kept for per-task
    agg_scores: list[IRScores] = [
        s for s in all_scores if s.task_id not in low_conf_task_ids
    ]
    agg_by_suite_config: dict[tuple[str, str], list[IRScores]] = defaultdict(list)
    for s in agg_scores:
        suite_key = _infer_suite(s.task_id) or "unknown"
        agg_by_suite_config[(suite_key, s.config_name)].append(s)

    # Per-suite confidence breakdown
    conf_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in all_scores:
        gt = gt_registry.get(s.task_id)
        if gt:
            suite_key = _infer_suite(s.task_id) or "unknown"
            conf_breakdown[suite_key][gt.confidence] += 1

    # Aggregate (using confidence-filtered scores)
    overall_by_config: dict[str, list[IRScores]] = defaultdict(list)
    for s in agg_scores:
        overall_by_config[s.config_name].append(s)

    result: dict = {
        "summary": {
            "total_tasks_with_gt": len(gt_registry),
            "total_runs_analyzed": len(all_scores),
            "total_in_aggregates": len(agg_scores),
            "excluded_low_confidence": len(all_scores) - len(agg_scores),
            "low_confidence_task_ids": sorted(low_conf_task_ids),
            "min_confidence": min_confidence,
            "skipped_no_ground_truth": skipped_no_gt,
            "skipped_no_transcript": skipped_no_transcript,
            "excluded_zero_mcp_sg": n_flagged,
            "excluded_zero_mcp_task_ids": sorted(flagged_ids),
            "confidence_breakdown_by_suite": {
                suite: dict(sorted(counts.items()))
                for suite, counts in sorted(conf_breakdown.items())
            },
        },
        "overall_by_config": {
            cfg: aggregate_ir_scores(scores)
            for cfg, scores in sorted(overall_by_config.items())
        },
        "by_suite_config": {
            f"{suite}__{cfg}": aggregate_ir_scores(scores)
            for (suite, cfg), scores in sorted(agg_by_suite_config.items())
        },
    }

    # Statistical tests: compare baseline vs SG_full
    bl_scores = overall_by_config.get("baseline", [])
    sg_scores = overall_by_config.get("sourcegraph_full", [])
    if len(bl_scores) >= 5 and len(sg_scores) >= 5:
        try:
            from ccb_metrics.statistics import welchs_t_test, cohens_d, bootstrap_ci_dict as bootstrap_ci

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

                # Dollar-weighted cost before first relevant (lower is better)
                paired_cost = [
                    (bl_by_id[tid].cost_before_first_relevant, sg_by_id[tid].cost_before_first_relevant)
                    for tid in sorted(common)
                    if bl_by_id[tid].cost_before_first_relevant is not None
                    and sg_by_id[tid].cost_before_first_relevant is not None
                ]
                if len(paired_cost) >= 5:
                    bl_cost = [p[0] for p in paired_cost]
                    sg_cost = [p[1] for p in paired_cost]
                    stat_tests["cost_before_first_relevant"] = {
                        "n_paired": len(paired_cost),
                        "welchs_t": welchs_t_test(bl_cost, sg_cost),
                        "cohens_d": cohens_d(bl_cost, sg_cost),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_cost, sg_cost)]
                        ),
                    }

                # Output tokens before first relevant (lower is better)
                paired_out_tok = [
                    (bl_by_id[tid].output_tokens_before_first_relevant, sg_by_id[tid].output_tokens_before_first_relevant)
                    for tid in sorted(common)
                    if bl_by_id[tid].output_tokens_before_first_relevant is not None
                    and sg_by_id[tid].output_tokens_before_first_relevant is not None
                ]
                if len(paired_out_tok) >= 5:
                    bl_out = [p[0] for p in paired_out_tok]
                    sg_out = [p[1] for p in paired_out_tok]
                    stat_tests["output_tokens_before_first_relevant"] = {
                        "n_paired": len(paired_out_tok),
                        "welchs_t": welchs_t_test(bl_out, sg_out),
                        "cohens_d": cohens_d(bl_out, sg_out),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_out, sg_out)]
                        ),
                    }

                # Agent time to first relevant (lower is better)
                paired_agent_ttfr = [
                    (bl_by_id[tid].agent_time_to_first_relevant, sg_by_id[tid].agent_time_to_first_relevant)
                    for tid in sorted(common)
                    if bl_by_id[tid].agent_time_to_first_relevant is not None
                    and sg_by_id[tid].agent_time_to_first_relevant is not None
                ]
                if len(paired_agent_ttfr) >= 5:
                    bl_attfr = [p[0] for p in paired_agent_ttfr]
                    sg_attfr = [p[1] for p in paired_agent_ttfr]
                    stat_tests["agent_time_to_first_relevant"] = {
                        "n_paired": len(paired_agent_ttfr),
                        "welchs_t": welchs_t_test(bl_attfr, sg_attfr),
                        "cohens_d": cohens_d(bl_attfr, sg_attfr),
                        "bootstrap_ci_delta": bootstrap_ci(
                            [s - b for b, s in zip(bl_attfr, sg_attfr)]
                        ),
                    }

                # Total run cost (full ROI comparison)
                cost_data = _load_task_metrics_cost()
                if cost_data:
                    paired_total_cost = [
                        (cost_data[(tid, "baseline")], cost_data[(tid, "sourcegraph_full")])
                        for tid in sorted(common)
                        if (tid, "baseline") in cost_data
                        and (tid, "sourcegraph_full") in cost_data
                    ]
                    if len(paired_total_cost) >= 5:
                        bl_tc = [p[0] for p in paired_total_cost]
                        sg_tc = [p[1] for p in paired_total_cost]
                        stat_tests["total_cost_usd"] = {
                            "n_paired": len(paired_total_cost),
                            "welchs_t": welchs_t_test(bl_tc, sg_tc),
                            "cohens_d": cohens_d(bl_tc, sg_tc),
                            "bootstrap_ci_delta": bootstrap_ci(
                                [s - b for b, s in zip(bl_tc, sg_tc)]
                            ),
                        }

                result["statistical_tests"] = stat_tests
        except ImportError:
            pass

    # US-003: Retrieval-outcome correlation (uses agg_scores for confidence gating)
    corr = compute_retrieval_outcome_correlation(agg_scores)
    if corr:
        result["retrieval_outcome_correlation"] = corr

    # US-004: Composite MCP value scores
    value_scores = compute_mcp_value_scores(agg_scores, weights=value_weights)
    if value_scores:
        by_suite: dict[str, list[MCPValueScore]] = defaultdict(list)
        for vs in value_scores:
            by_suite[vs.suite].append(vs)
        result["mcp_value_scores"] = {
            "n_tasks": len(value_scores),
            "weights": {
                "retrieval": value_weights[0],
                "outcome": value_weights[1],
                "time_efficiency": value_weights[2] if len(value_weights) > 2 else 0.20,
                "cost_efficiency": value_weights[3] if len(value_weights) > 3 else 0.15,
                "token_efficiency": value_weights[4] if len(value_weights) > 4 else 0.15,
            },
            "per_suite_mean": {
                suite: round(statistics.mean(v.composite for v in scores), 4)
                for suite, scores in sorted(by_suite.items())
            },
            "top_helped": [v.to_dict() for v in sorted(value_scores, key=lambda v: -v.composite)[:10]],
            "top_hurt": [v.to_dict() for v in sorted(value_scores, key=lambda v: v.composite)[:10]],
        }

    # US-005: Cost-efficiency metrics
    cost_eff = compute_cost_efficiency(agg_scores)
    if cost_eff:
        result["cost_efficiency"] = cost_eff

    # US-011: --correlate — per-suite Spearman retrieval-outcome correlation
    if correlate:
        corr_data = _compute_per_suite_correlation(agg_scores, gt_registry)
        if corr_data:
            result["per_suite_correlation"] = corr_data

    if per_task:
        # Mark low-confidence tasks in per-task output
        per_task_list = []
        for s in all_scores:
            d = s.to_dict()
            gt = gt_registry.get(s.task_id)
            d["gt_confidence"] = gt.confidence if gt else "unknown"
            if s.task_id in low_conf_task_ids:
                d["confidence_excluded"] = True
            per_task_list.append(d)
        result["per_task"] = per_task_list

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
    lines.append(f"In aggregates:           {s.get('total_in_aggregates', s.get('total_runs_analyzed', 0))}")
    min_conf = s.get("min_confidence", "medium")
    n_low_conf = s.get("excluded_low_confidence", 0)
    if n_low_conf:
        lines.append(f"Excluded (low-conf GT):  {n_low_conf}  (below --min-confidence={min_conf})")
    lines.append(f"Skipped (no GT):         {s.get('skipped_no_ground_truth', 0)}")
    lines.append(f"Skipped (no transcript): {s.get('skipped_no_transcript', 0)}")
    n_zero_mcp = s.get("excluded_zero_mcp_sg", 0)
    if n_zero_mcp:
        lines.append(f"Excluded (zero-MCP SG):  {n_zero_mcp}  (invalid: MCP available but never used)")
    lines.append("")

    # Per-suite confidence breakdown
    conf_bd = s.get("confidence_breakdown_by_suite", {})
    if conf_bd:
        lines.append("GT CONFIDENCE BREAKDOWN BY SUITE:")
        for suite, counts in sorted(conf_bd.items()):
            parts = [f"{c} {n}" for c, n in sorted(counts.items(), key=lambda x: -{"high": 3, "medium": 2, "low": 1}.get(x[0], 0))]
            lines.append(f"  {suite:35s} {', '.join(parts)}")
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
        for metric_name in (
            "file_recall", "mrr", "ttfr", "tt_all_r",
            "total_cost_usd",
            "cost_before_first_relevant", "output_tokens_before_first_relevant",
            "agent_time_to_first_relevant",
        ):
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

    # Per-suite retrieval-outcome correlation (--correlate)
    psc = data.get("per_suite_correlation", {})
    if psc:
        lines.append("PER-SUITE RETRIEVAL-OUTCOME CORRELATION (--correlate):")
        overall_c = psc.get("overall", {})
        if overall_c:
            lines.append(
                f"  Overall: rho={overall_c.get('rho', 'N/A')}, "
                f"p={overall_c.get('p_value', 'N/A')}, "
                f"effect_size={overall_c.get('effect_size', 'N/A')}"
            )
        header = f"  {'Suite':30s} {'rho':>8s} {'p-value':>10s} {'effect':>8s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for key, vals in sorted(psc.items()):
            if key == "overall":
                continue
            rho = vals.get("rho", 0.0)
            p_val = vals.get("p_value", 1.0)
            eff = vals.get("effect_size", 0.0)
            lines.append(f"  {key:30s} {rho:>+8.4f} {p_val:>10.6f} {eff:>+8.4f}")
        lines.append("")

    # MCP Value Scores
    mvs = data.get("mcp_value_scores", {})
    if mvs:
        lines.append("MCP VALUE SCORES (z-scored composite, 5 components):")
        w = mvs.get("weights", {})
        lines.append(
            f"  Weights: retrieval={w.get('retrieval', 0.25)}, "
            f"outcome={w.get('outcome', 0.25)}, "
            f"time_eff={w.get('time_efficiency', 0.20)}, "
            f"cost_eff={w.get('cost_efficiency', 0.15)}, "
            f"tok_eff={w.get('token_efficiency', 0.15)}"
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
            header = f"    {'Task':40s} {'Suite':20s} {'Comp':>7s} {'Ret':>7s} {'Out':>7s} {'TimeE':>7s} {'CostE':>7s}"
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
            header = f"    {'Task':40s} {'Suite':20s} {'Comp':>7s} {'Ret':>7s} {'Out':>7s} {'TimeE':>7s} {'CostE':>7s}"
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
            lines.append("  Full-run ROI (total cost per task):")
            roi_header = f"    {'Config':20s} {'TotalCost':>12s} {'n':>5s}"
            lines.append(roi_header)
            lines.append("    " + "-" * (len(roi_header) - 4))
            for cfg, agg in sorted(overall.items()):
                total_cost = agg.get("mean_total_cost_usd")
                n_cost = agg.get("n_with_total_cost", 0)
                tc_s = f"${total_cost:>11.4f}" if total_cost else f"{'N/A':>12s}"
                lines.append(f"    {cfg:20s} {tc_s} {n_cost:>5d}")
            lines.append("")

            lines.append("  Efficiency metrics (cost to first relevant file):")
            header = (
                f"    {'Config':20s} {'$Before1st':>10s} {'AgentTTFR':>10s} "
                f"{'OutTokB1st':>12s} {'Tok/RelFile':>12s} {'MeanOverlap':>12s} {'n':>5s}"
            )
            lines.append(header)
            lines.append("    " + "-" * (len(header) - 4))
            for cfg, agg in sorted(overall.items()):
                cost = agg.get("mean_cost_before_first_relevant")
                agent_ttfr = agg.get("mean_agent_time_to_first_relevant")
                out_tok = agg.get("mean_output_tokens_before_first_relevant")
                tpr = agg.get("mean_tokens_per_relevant_file")
                ovl = agg.get("mean_overlap")
                n = agg.get("n_tasks", 0)
                cost_s = f"${cost:>9.4f}" if cost else f"{'N/A':>10s}"
                attfr_s = f"{agent_ttfr:>9.1f}s" if agent_ttfr else f"{'N/A':>10s}"
                out_tok_s = f"{out_tok:>12,.0f}" if out_tok else f"{'N/A':>12s}"
                tpr_s = f"{tpr:>12,.0f}" if tpr else f"{'N/A':>12s}"
                ovl_s = f"{ovl:>12.1f}" if ovl else f"{'N/A':>12s}"
                lines.append(
                    f"    {cfg:20s} {cost_s} {attfr_s} "
                    f"{out_tok_s} {tpr_s} {ovl_s} {n:>5d}"
                )
            lines.append("")

        deltas = ce.get("deltas", {})
        if deltas:
            lines.append("  Baseline vs SG_full deltas:")
            for metric, d in sorted(deltas.items()):
                label = metric.replace("mean_", "")
                bl_val = d['baseline']
                sg_val = d['sourcegraph_full']
                delta_val = d['delta']
                pct = d['pct_change']
                # Format based on metric type
                if "cost" in metric:
                    lines.append(
                        f"    {label:35s} BL=${bl_val:>10.4f}  "
                        f"SG=${sg_val:>10.4f}  "
                        f"delta=${delta_val:>+10.4f}  ({pct:>+.1f}%)"
                    )
                elif "time" in metric:
                    lines.append(
                        f"    {label:35s} BL={bl_val:>10.1f}s  "
                        f"SG={sg_val:>10.1f}s  "
                        f"delta={delta_val:>+10.1f}s  ({pct:>+.1f}%)"
                    )
                else:
                    lines.append(
                        f"    {label:35s} BL={bl_val:>12,.0f}  "
                        f"SG={sg_val:>12,.0f}  "
                        f"delta={delta_val:>+12,.0f}  ({pct:>+.1f}%)"
                    )
            lines.append("")

    # Per-task scores (if present)
    per_task_data = data.get("per_task", [])
    if per_task_data:
        lines.append("PER-TASK IR SCORES:")
        header = (
            f"  {'Task':40s} {'Config':20s} {'MRR':>7s} {'F.Rec':>7s} "
            f"{'Conf':>6s}"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for t in per_task_data:
            conf = t.get("gt_confidence", "?")
            marker = " [low-conf]" if t.get("confidence_excluded") else ""
            lines.append(
                f"  {t.get('task_id', ''):40s} {t.get('config_name', ''):20s} "
                f"{t.get('mrr', 0):>7.3f} {t.get('file_recall', 0):>7.3f} "
                f"{conf:>6s}{marker}"
            )
        lines.append("")

    return "\n".join(lines)


REPORT_PATH = Path(__file__).resolve().parent.parent / "docs" / "ir_analysis_report.md"

FRIENDLY_LABELS = {
    "baseline": "IDE-native",
    "sourcegraph_full": "Context infrastructure",
}


def _fl(config: str) -> str:
    """Friendly label for config name."""
    return FRIENDLY_LABELS.get(config, config)


def format_report_markdown(data: dict) -> str:
    """Generate stakeholder-ready markdown report from IR analysis data."""
    lines: list[str] = []
    lines.append("# IR Analysis Report: Context Infrastructure Impact")
    lines.append("")
    lines.append("*Auto-generated by CodeContextBench IR analysis pipeline*")
    lines.append("")

    # --- Executive Summary ---
    lines.append("## Executive Summary")
    lines.append("")
    overall = data.get("overall_by_config", {})
    bl = overall.get("baseline", {})
    sg = overall.get("sourcegraph_full", {})
    bl_mrr = bl.get("mrr", {}).get("mean", 0) if bl else 0
    sg_mrr = sg.get("mrr", {}).get("mean", 0) if sg else 0
    mrr_pct = ((sg_mrr - bl_mrr) / bl_mrr * 100) if bl_mrr > 0 else 0

    corr = data.get("retrieval_outcome_correlation", {})
    ce = data.get("cost_efficiency", {})
    ce_deltas = ce.get("deltas", {}) if ce else {}
    tpr_delta = ce_deltas.get("tokens_per_relevant_file", {})

    stats = data.get("statistical_tests", {})
    mrr_stat = stats.get("mrr", {})
    mrr_t = mrr_stat.get("welchs_t", {})
    mrr_sig = "p<0.05" if mrr_t.get("is_significant") else f"p={mrr_t.get('p_value', 'N/A')}"

    bullets = [
        f"Context infrastructure improves retrieval quality (MRR) by **{mrr_pct:+.0f}%** "
        f"({_fl('baseline')}: {bl_mrr:.3f} vs {_fl('sourcegraph_full')}: {sg_mrr:.3f}), "
        f"{mrr_sig}.",
    ]
    if tpr_delta:
        bullets.append(
            f"Cost per relevant file found drops **{tpr_delta.get('pct_change', 0):.0f}%** "
            f"({_fl('baseline')}: {tpr_delta.get('baseline', 0):,.0f} tokens vs "
            f"{_fl('sourcegraph_full')}: {tpr_delta.get('sourcegraph_full', 0):,.0f} tokens)."
        )
    if corr:
        bullets.append(
            f"Retrieval-outcome correlation: Spearman r={corr.get('spearman_r', 0):.3f} "
            f"(p={corr.get('spearman_p', 1):.4f})."
        )

    s = data.get("summary", {})
    bullets.append(
        f"Analysis covers **{s.get('total_runs_analyzed', 0)}** task runs "
        f"across {len(data.get('by_suite_config', {}))} suite-config pairs."
    )

    for b in bullets:
        lines.append(f"- {b}")
    lines.append("")

    # --- Retrieval Quality ---
    lines.append("## Retrieval Quality")
    lines.append("")
    if overall:
        lines.append("| Config | MRR | MAP | File Recall | Context Efficiency | n |")
        lines.append("|--------|-----|-----|-------------|-------------------|---|")
        for cfg, agg in sorted(overall.items()):
            if not agg:
                continue
            n = agg.get("_totals", {}).get("n_tasks", 0)
            lines.append(
                f"| {_fl(cfg)} | "
                f"{agg.get('mrr', {}).get('mean', 0):.3f} | "
                f"{agg.get('map_score', {}).get('mean', 0):.3f} | "
                f"{agg.get('file_recall', {}).get('mean', 0):.3f} | "
                f"{agg.get('context_efficiency', {}).get('mean', 0):.3f} | "
                f"{n} |"
            )
        lines.append("")

    by_sc = data.get("by_suite_config", {})
    if by_sc:
        lines.append("### Per-Suite Breakdown")
        lines.append("")
        lines.append("| Suite | Config | MRR | File Recall | n |")
        lines.append("|-------|--------|-----|-------------|---|")
        for key, agg in sorted(by_sc.items()):
            if not agg:
                continue
            parts = key.split("__", 1)
            suite = parts[0] if parts else key
            cfg = _fl(parts[1]) if len(parts) > 1 else ""
            n = agg.get("_totals", {}).get("n_tasks", 0)
            lines.append(
                f"| {suite} | {cfg} | "
                f"{agg.get('mrr', {}).get('mean', 0):.3f} | "
                f"{agg.get('file_recall', {}).get('mean', 0):.3f} | "
                f"{n} |"
            )
        lines.append("")

    # --- Time-to-Context ---
    lines.append("## Time-to-Context")
    lines.append("")
    if overall:
        lines.append("| Config | TTFR (s) | TTAR (s) | Steps to First |")
        lines.append("|--------|----------|----------|----------------|")
        for cfg, agg in sorted(overall.items()):
            if not agg:
                continue
            ttfr = agg.get("ttfr", {}).get("median")
            ttar = agg.get("tt_all_r", {}).get("median")
            steps = agg.get("n_steps_to_first", {}).get("median")
            lines.append(
                f"| {_fl(cfg)} | "
                f"{ttfr:.1f}" if ttfr is not None else f"| {_fl(cfg)} | N/A"
            )
            # Rebuild properly
        # Redo as clean loop
        lines = lines[:-len(list(overall.items()))]  # remove bad rows
        for cfg, agg in sorted(overall.items()):
            if not agg:
                continue
            ttfr = agg.get("ttfr", {}).get("median")
            ttar = agg.get("tt_all_r", {}).get("median")
            steps = agg.get("n_steps_to_first", {}).get("median")
            ttfr_s = f"{ttfr:.1f}" if ttfr is not None else "N/A"
            ttar_s = f"{ttar:.1f}" if ttar is not None else "N/A"
            steps_s = f"{steps:.0f}" if steps is not None else "N/A"
            lines.append(f"| {_fl(cfg)} | {ttfr_s} | {ttar_s} | {steps_s} |")
        lines.append("")

    # --- Cost Efficiency ---
    lines.append("## Cost Efficiency")
    lines.append("")
    if ce:
        ce_overall = ce.get("overall", {})
        if ce_overall:
            lines.append("| Config | Tokens/Relevant File | Tokens Before 1st Relevant | Mean Input Tokens | Mean Files Found | n |")
            lines.append("|--------|---------------------|---------------------------|-------------------|-----------------|---|")
            for cfg, agg in sorted(ce_overall.items()):
                tpr = agg.get("mean_tokens_per_relevant_file")
                tbfr = agg.get("mean_tokens_before_first_relevant")
                tok = agg.get("mean_input_tokens")
                ovl = agg.get("mean_overlap")
                n = agg.get("n_tasks", 0)
                tpr_s = f"{tpr:,.0f}" if tpr else "N/A"
                tbfr_s = f"{tbfr:,.0f}" if tbfr else "N/A"
                tok_s = f"{tok:,.0f}" if tok else "N/A"
                ovl_s = f"{ovl:.1f}" if ovl else "N/A"
                lines.append(f"| {_fl(cfg)} | {tpr_s} | {tbfr_s} | {tok_s} | {ovl_s} | {n} |")
            lines.append("")

        if ce_deltas:
            lines.append("**Delta summary:**")
            lines.append("")
            for metric, d in sorted(ce_deltas.items()):
                label = metric.replace("mean_", "").replace("_", " ").title()
                lines.append(
                    f"- {label}: {_fl('sourcegraph_full')} uses "
                    f"**{d['pct_change']:+.1f}%** vs {_fl('baseline')}"
                )
            lines.append("")

    # --- MCP Value Rankings ---
    mvs = data.get("mcp_value_scores", {})
    if mvs:
        lines.append("## MCP Value Rankings")
        lines.append("")
        w = mvs.get("weights", {})
        lines.append(
            f"*Composite score: weighted z-score of retrieval lift ({w.get('retrieval', 0.25)}), "
            f"outcome lift ({w.get('outcome', 0.25)}), "
            f"time efficiency ({w.get('time_efficiency', 0.20)}), "
            f"cost efficiency ({w.get('cost_efficiency', 0.15)}), "
            f"token efficiency ({w.get('token_efficiency', 0.15)})*"
        )
        lines.append("")

        per_suite = mvs.get("per_suite_mean", {})
        if per_suite:
            lines.append("### Per-Suite Mean Composite")
            lines.append("")
            lines.append("| Suite | Mean Composite |")
            lines.append("|-------|---------------|")
            for suite, mean in sorted(per_suite.items(), key=lambda x: -x[1]):
                lines.append(f"| {suite} | {mean:+.3f} |")
            lines.append("")

        top_helped = mvs.get("top_helped", [])
        if top_helped:
            lines.append("### Top 10 Tasks Where Context Infrastructure Helps Most")
            lines.append("")
            lines.append("| Task | Suite | Composite | Retrieval | Outcome | Efficiency | Cost |")
            lines.append("|------|-------|-----------|-----------|---------|------------|------|")
            for t in top_helped:
                lines.append(
                    f"| {t['task_id'][:40]} | {t['suite']} | "
                    f"{t['composite']:+.3f} | {t['retrieval_lift']:+.3f} | "
                    f"{t['outcome_lift']:+.3f} | {t['efficiency_lift']:+.3f} | "
                    f"{t['cost_ratio']:+.3f} |"
                )
            lines.append("")

    # --- Statistical Methodology ---
    lines.append("## Statistical Methodology")
    lines.append("")
    lines.append("- **Retrieval metrics**: MRR, MAP, file recall computed against ground-truth files")
    lines.append("- **Time-to-context**: TTFR/TTAR from trajectory.json (synthesized from transcript when missing)")
    lines.append("- **Statistical tests**: Welch's t-test, Cohen's d effect size, bootstrap 95% CI")
    lines.append("- **Correlation**: Spearman rank correlation between MRR and task reward")
    lines.append("- **MCP value composite**: Z-score normalized weighted sum across retrieval, outcome, efficiency, cost")
    lines.append("- **Cost efficiency**: Input tokens per relevant file found from task_metrics.json")
    lines.append("")
    if stats:
        lines.append("### Statistical Test Results")
        lines.append("")
        lines.append(f"Paired tasks: {stats.get('n_paired', 0)}")
        lines.append("")
        lines.append("| Metric | t-stat | p-value | Cohen's d | Magnitude | Significant |")
        lines.append("|--------|--------|---------|-----------|-----------|-------------|")
        for metric_name in (
            "file_recall", "mrr", "ttfr", "tt_all_r",
            "total_cost_usd",
            "cost_before_first_relevant", "output_tokens_before_first_relevant",
            "agent_time_to_first_relevant",
        ):
            ms = stats.get(metric_name, {})
            if not ms:
                continue
            t = ms.get("welchs_t", {})
            d = ms.get("cohens_d", {})
            sig = "Yes" if t.get("is_significant") else "No"
            lines.append(
                f"| {metric_name} | {t.get('t_stat', 'N/A')} | "
                f"{t.get('p_value', 'N/A')} | {d.get('d', 'N/A')} | "
                f"{d.get('magnitude', '')} | {sig} |"
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
        "--value-weights", default="0.25,0.25,0.20,0.15,0.15",
        help="Comma-separated weights for MCP value composite: retrieval,outcome,time_eff,cost_eff,token_eff",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="Generate stakeholder-ready markdown report to docs/ir_analysis_report.md",
    )
    parser.add_argument(
        "--staging", action="store_true",
        help="Scan runs/staging/ instead of runs/official/ (SDLC phase suite layout)",
    )
    parser.add_argument(
        "--runs-dir", default=None,
        help="Custom runs directory to scan (overrides --staging)",
    )
    parser.add_argument(
        "--min-confidence", choices=["high", "medium", "low"], default="medium",
        help=(
            "Minimum GT confidence for aggregate metrics. "
            "'medium' (default) excludes low-confidence tasks from aggregates "
            "(still shown in per-task output with [low-conf] marker). "
            "'low' includes everything (backwards compatible). "
            "'high' restricts aggregates to high-confidence GT only."
        ),
    )
    parser.add_argument(
        "--correlate", action="store_true",
        help=(
            "Compute per-suite Spearman retrieval-outcome correlation "
            "using retrieval_outcome_correlation from ccb_metrics.statistics. "
            "Outputs rho, p-value, and effect size per suite."
        ),
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
        if len(vw) not in (4, 5):
            raise ValueError
    except ValueError:
        print("ERROR: --value-weights must be 4 or 5 comma-separated floats", file=sys.stderr)
        sys.exit(1)

    custom_runs_dir = Path(args.runs_dir) if args.runs_dir else None

    data = run_ir_analysis(
        suite_filter=args.suite,
        per_task=args.per_task,
        value_weights=vw,
        runs_dir=custom_runs_dir,
        staging=args.staging,
        min_confidence=args.min_confidence,
        correlate=args.correlate,
    )

    if args.report:
        report = format_report_markdown(data)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report)
        print(f"Report written to {REPORT_PATH}")
    elif args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_table(data))


if __name__ == "__main__":
    main()

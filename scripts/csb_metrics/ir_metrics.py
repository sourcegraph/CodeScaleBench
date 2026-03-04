"""Information retrieval metrics for CodeScaleBench.

Provides standard IR metrics (precision, recall, MRR, nDCG, MAP, F1) plus
file-level recall and context efficiency. Operates on simple file-path lists
rather than the full CodeLocation/GroundTruth hierarchy used by IR-SDLC-Factory.

Also provides transcript parsing to extract the ordered list of files
retrieved by an agent during a task run.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Anthropic Claude pricing (per million tokens) — Opus 4, Feb 2026
# ---------------------------------------------------------------------------
_PRICE_PER_MTOK_INPUT = 15.0          # uncached input
_PRICE_PER_MTOK_CACHE_CREATE = 18.75  # cache creation (1.25× input)
_PRICE_PER_MTOK_CACHE_READ = 1.50     # cache read (0.1× input)
_PRICE_PER_MTOK_OUTPUT = 75.0         # output / completion


# ---------------------------------------------------------------------------
# Core IR metric functions (pure math, stdlib only)
# ---------------------------------------------------------------------------

def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Precision@K = |relevant ∩ retrieved[:k]| / k."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for f in top_k if _normalize(f) in relevant)
    return hits / k


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Recall@K = |relevant ∩ retrieved[:k]| / |relevant|."""
    if not relevant:
        return 1.0
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    norm_top = {_normalize(f) for f in top_k}
    found = sum(1 for r in relevant if r in norm_top)
    return found / len(relevant)


def f1_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """F1@K = harmonic mean of precision@K and recall@K."""
    p = precision_at_k(retrieved, relevant, k)
    r = recall_at_k(retrieved, relevant, k)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def mrr(retrieved: list[str], relevant: set[str]) -> float:
    """Mean Reciprocal Rank = 1 / rank_of_first_relevant."""
    for i, f in enumerate(retrieved):
        if _normalize(f) in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain @ K (binary relevance)."""
    if k <= 0 or not relevant:
        return 0.0

    top_k = retrieved[:k]

    # DCG
    dcg = 0.0
    for i, f in enumerate(top_k):
        if _normalize(f) in relevant:
            dcg += 1.0 / math.log2(i + 2)  # i+2 because log2(1)=0

    # Ideal DCG: all relevant items first
    ideal_k = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_k))

    if idcg == 0:
        return 0.0
    return dcg / idcg


def mean_average_precision(retrieved: list[str], relevant: set[str]) -> float:
    """Average Precision (MAP for a single query)."""
    if not relevant:
        return 1.0

    n_relevant = len(relevant)
    sum_prec = 0.0
    hits = 0

    for i, f in enumerate(retrieved):
        if _normalize(f) in relevant:
            hits += 1
            sum_prec += hits / (i + 1)

    if hits == 0:
        return 0.0
    return sum_prec / n_relevant


def file_level_recall(retrieved: list[str], relevant: set[str]) -> float:
    """Fraction of ground-truth files found anywhere in retrieved list."""
    if not relevant:
        return 1.0
    norm_retrieved = {_normalize(f) for f in retrieved}
    found = sum(1 for r in relevant if r in norm_retrieved)
    return found / len(relevant)


def context_efficiency(retrieved: list[str], relevant: set[str]) -> float:
    """Fraction of retrieved files that are relevant (= precision over all)."""
    if not retrieved:
        return 0.0
    norm_relevant = relevant  # already normalized by caller
    hits = sum(1 for f in retrieved if _normalize(f) in norm_relevant)
    return hits / len(retrieved)


def _normalize(path: str) -> str:
    """Normalize a file path for comparison.

    Strips /workspace/ prefix, a/ b/ diff prefixes, leading/trailing slashes,
    and lowercases the result.
    """
    p = path.strip()
    # Strip /workspace/ prefix (Harbor container paths)
    for prefix in ("/workspace/", "workspace/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    # Strip diff a/ b/ prefixes
    if p.startswith(("a/", "b/")):
        p = p[2:]
    p = p.strip("/")
    return p.lower()


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class IRScores:
    """IR evaluation scores for a single (task, config) pair."""

    task_id: str
    config_name: str

    precision: dict[int, float] = field(default_factory=dict)   # {1: .., 3: .., 5: .., 10: ..}
    recall: dict[int, float] = field(default_factory=dict)
    f1: dict[int, float] = field(default_factory=dict)
    mrr: float = 0.0
    ndcg: dict[int, float] = field(default_factory=dict)
    map_score: float = 0.0
    file_recall: float = 0.0
    context_efficiency: float = 0.0
    n_retrieved: int = 0
    n_ground_truth: int = 0
    n_overlap: int = 0

    # Time-to-context metrics (seconds from session start)
    ttfr: Optional[float] = None    # Time to First Relevant file
    ttfr_step: Optional[int] = None # Step index of first relevant file
    tt_all_r: Optional[float] = None  # Time to find ALL relevant files (None if not all found)
    n_steps_to_first: Optional[int] = None  # Tool calls before first relevant file
    tokens_before_first_relevant: Optional[int] = None  # Cumulative all tokens up to TTFR step

    # Dollar-weighted cost metrics (added 2026-02-16)
    cost_before_first_relevant: Optional[float] = None    # USD cost up to TTFR step
    output_tokens_before_first_relevant: Optional[int] = None  # Output tokens only up to TTFR
    agent_time_to_first_relevant: Optional[float] = None  # Seconds from first tool exec to TTFR

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "config_name": self.config_name,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "map_score": self.map_score,
            "file_recall": self.file_recall,
            "context_efficiency": self.context_efficiency,
            "n_retrieved": self.n_retrieved,
            "n_ground_truth": self.n_ground_truth,
            "n_overlap": self.n_overlap,
            "ttfr": self.ttfr,
            "ttfr_step": self.ttfr_step,
            "tt_all_r": self.tt_all_r,
            "n_steps_to_first": self.n_steps_to_first,
            "tokens_before_first_relevant": self.tokens_before_first_relevant,
            "cost_before_first_relevant": self.cost_before_first_relevant,
            "output_tokens_before_first_relevant": self.output_tokens_before_first_relevant,
            "agent_time_to_first_relevant": self.agent_time_to_first_relevant,
        }


@dataclass
class MCPValueScore:
    """Composite MCP value score for a single task (SG_full vs baseline delta)."""

    task_id: str
    suite: str
    retrieval_lift: float = 0.0
    outcome_lift: float = 0.0
    efficiency_lift: float = 0.0
    cost_ratio: float = 0.0
    composite: float = 0.0

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "suite": self.suite,
            "retrieval_lift": round(self.retrieval_lift, 4),
            "outcome_lift": round(self.outcome_lift, 4),
            "efficiency_lift": round(self.efficiency_lift, 4),
            "cost_ratio": round(self.cost_ratio, 4),
            "composite": round(self.composite, 4),
        }


def compute_ir_scores(
    retrieved: list[str],
    ground_truth_files: list[str],
    task_id: str,
    config_name: str,
    k_values: list[int] | None = None,
) -> IRScores:
    """Compute all IR metrics for a (task, config) pair.

    Args:
        retrieved: Ordered list of file paths the agent accessed.
        ground_truth_files: Files that needed modification (from TaskGroundTruth).
        task_id: Task identifier.
        config_name: Config label (e.g. "baseline", "sourcegraph_full").
        k_values: K values for @K metrics (default [1, 3, 5, 10]).

    Returns:
        IRScores dataclass.
    """
    if k_values is None:
        k_values = [1, 3, 5, 10]

    relevant = {_normalize(f) for f in ground_truth_files}
    norm_retrieved = {_normalize(f) for f in retrieved}
    overlap = relevant & norm_retrieved

    scores = IRScores(
        task_id=task_id,
        config_name=config_name,
        mrr=mrr(retrieved, relevant),
        map_score=mean_average_precision(retrieved, relevant),
        file_recall=file_level_recall(retrieved, relevant),
        context_efficiency=context_efficiency(retrieved, relevant),
        n_retrieved=len(retrieved),
        n_ground_truth=len(relevant),
        n_overlap=len(overlap),
    )

    for k in k_values:
        scores.precision[k] = round(precision_at_k(retrieved, relevant, k), 4)
        scores.recall[k] = round(recall_at_k(retrieved, relevant, k), 4)
        scores.f1[k] = round(f1_at_k(retrieved, relevant, k), 4)
        scores.ndcg[k] = round(ndcg_at_k(retrieved, relevant, k), 4)

    scores.mrr = round(scores.mrr, 4)
    scores.map_score = round(scores.map_score, 4)
    scores.file_recall = round(scores.file_recall, 4)
    scores.context_efficiency = round(scores.context_efficiency, 4)

    return scores


def aggregate_ir_scores(scores: list[IRScores]) -> dict:
    """Aggregate IR scores across tasks: mean/std/median per metric."""
    if not scores:
        return {}

    # Collect scalar metrics
    scalars = {
        "mrr": [s.mrr for s in scores],
        "map_score": [s.map_score for s in scores],
        "file_recall": [s.file_recall for s in scores],
        "context_efficiency": [s.context_efficiency for s in scores],
    }

    # Collect @k metrics
    k_values = set()
    for s in scores:
        k_values.update(s.precision.keys())
    k_values = sorted(k_values)

    for k in k_values:
        scalars[f"precision@{k}"] = [s.precision.get(k, 0.0) for s in scores]
        scalars[f"recall@{k}"] = [s.recall.get(k, 0.0) for s in scores]
        scalars[f"f1@{k}"] = [s.f1.get(k, 0.0) for s in scores]
        scalars[f"ndcg@{k}"] = [s.ndcg.get(k, 0.0) for s in scores]

    result = {}
    for name, values in scalars.items():
        result[name] = {
            "mean": round(statistics.mean(values), 4),
            "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "median": round(statistics.median(values), 4),
            "n": len(values),
        }

    # Time-to-context metrics (only for tasks that have them)
    ttfr_values = [s.ttfr for s in scores if s.ttfr is not None]
    if ttfr_values:
        result["ttfr"] = {
            "mean": round(statistics.mean(ttfr_values), 1),
            "std": round(statistics.stdev(ttfr_values), 1) if len(ttfr_values) > 1 else 0.0,
            "median": round(statistics.median(ttfr_values), 1),
            "n": len(ttfr_values),
        }
    tt_all_values = [s.tt_all_r for s in scores if s.tt_all_r is not None]
    if tt_all_values:
        result["tt_all_r"] = {
            "mean": round(statistics.mean(tt_all_values), 1),
            "std": round(statistics.stdev(tt_all_values), 1) if len(tt_all_values) > 1 else 0.0,
            "median": round(statistics.median(tt_all_values), 1),
            "n": len(tt_all_values),
        }
    steps_values = [s.n_steps_to_first for s in scores if s.n_steps_to_first is not None]
    if steps_values:
        result["n_steps_to_first"] = {
            "mean": round(statistics.mean(steps_values), 1),
            "median": round(statistics.median(steps_values), 1),
            "n": len(steps_values),
        }

    result["_totals"] = {
        "n_tasks": len(scores),
        "mean_retrieved": round(statistics.mean([s.n_retrieved for s in scores]), 1),
        "mean_ground_truth": round(statistics.mean([s.n_ground_truth for s in scores]), 1),
        "mean_overlap": round(statistics.mean([s.n_overlap for s in scores]), 1),
    }

    return result


# ---------------------------------------------------------------------------
# Transcript parsing — extract retrieved files
# ---------------------------------------------------------------------------

# MCP tool names that read/search remote files
_MCP_READ_TOOLS = {
    "mcp__sourcegraph__sg_read_file", "mcp__sourcegraph__read_file",
}
_MCP_SEARCH_TOOLS = {
    "mcp__sourcegraph__sg_keyword_search", "mcp__sourcegraph__keyword_search",
    "mcp__sourcegraph__sg_nls_search", "mcp__sourcegraph__nls_search",
    "mcp__sourcegraph__sg_find_references", "mcp__sourcegraph__find_references",
    "mcp__sourcegraph__sg_go_to_definition", "mcp__sourcegraph__go_to_definition",
    "mcp__sourcegraph__sg_list_files", "mcp__sourcegraph__list_files",
    "mcp__sourcegraph__sg_diff_search", "mcp__sourcegraph__diff_search",
    "mcp__sourcegraph__sg_commit_search", "mcp__sourcegraph__commit_search",
    "mcp__sourcegraph__sg_compare_revisions", "mcp__sourcegraph__compare_revisions",
}
_LOCAL_FILE_TOOLS = {"Read", "Grep", "Glob"}

# Regex for "path": "some/file.ext" in JSON-like text
_PATH_JSON_RE = re.compile(r'"path"\s*:\s*"([^"]+)"')


def extract_retrieved_files(transcript_path: Path) -> list[str]:
    """Parse a claude-code.txt JSONL transcript and extract accessed files.

    Returns ordered list of unique file paths (first-seen order).
    For MCP tools: extracts paths from tool_result content.
    For local tools (Read/Grep/Glob): extracts paths from tool input params.
    """
    if not transcript_path.is_file():
        return []

    files: list[str] = []
    seen: set[str] = set()

    def _add(path: str) -> None:
        norm = _normalize(path)
        if norm and norm not in seen and _looks_like_file(norm):
            seen.add(norm)
            files.append(path.strip())

    def _process_tool_use(tool_name: str, tool_input: dict) -> None:
        """Process a tool_use block and extract file paths."""
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except json.JSONDecodeError:
                tool_input = {}
        if not isinstance(tool_input, dict):
            return

        if tool_name in _LOCAL_FILE_TOOLS:
            fp = tool_input.get("file_path") or tool_input.get("path") or ""
            if fp:
                _add(fp)
        elif tool_name in _MCP_READ_TOOLS:
            fp = tool_input.get("path", "")
            if fp:
                _add(fp)

    def _process_tool_result(tool_name: str, content: str) -> None:
        """Process a tool_result and extract file paths from output."""
        if tool_name in _MCP_SEARCH_TOOLS or tool_name in _MCP_READ_TOOLS:
            for m in _PATH_JSON_RE.finditer(content):
                _add(m.group(1))
        elif tool_name == "Glob":
            for fline in content.splitlines():
                fline = fline.strip()
                if fline and "/" in fline and "." in fline:
                    _add(fline)
        elif tool_name == "Grep":
            for fline in content.splitlines():
                fline = fline.strip()
                if fline and "/" in fline and "." in fline and not fline.startswith("#"):
                    _add(fline)

    # Map tool_use_id → tool_name for matching results to their calls
    tool_id_to_name: dict[str, str] = {}

    for line in transcript_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = entry.get("type", "")

        # Harbor claude-code.txt: tool calls and results are nested inside
        # "assistant" and "user" messages within message.content arrays.
        if msg_type == "assistant":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        tid = block.get("id", "")
                        inp = block.get("input", {})
                        if tid and name:
                            tool_id_to_name[tid] = name
                        _process_tool_use(name, inp)

        elif msg_type == "user":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        name = tool_id_to_name.get(tid, "")
                        raw = block.get("content", "")
                        if isinstance(raw, list):
                            raw = " ".join(
                                item.get("text", "") if isinstance(item, dict) else str(item)
                                for item in raw
                            )
                        if not isinstance(raw, str):
                            raw = str(raw)
                        if name:
                            _process_tool_result(name, raw)

            # Also check top-level tool_use_result (Harbor shortcut)
            tur = entry.get("tool_use_result", {})
            if isinstance(tur, dict):
                stdout = tur.get("stdout", "")
                if stdout and isinstance(stdout, str):
                    # Associate with last tool call via parent_tool_use_id
                    ptid = entry.get("parent_tool_use_id") or ""
                    if not ptid:
                        # Try matching the tool_use_id in content blocks
                        if isinstance(content_blocks, list):
                            for block in content_blocks:
                                if isinstance(block, dict) and block.get("type") == "tool_result":
                                    ptid = block.get("tool_use_id", "")
                    name = tool_id_to_name.get(ptid, "")
                    if name:
                        _process_tool_result(name, stdout)

        # Top-level tool_use / tool_result entries (non-Harbor format)
        elif msg_type == "tool_use":
            name = entry.get("tool_name", "") or entry.get("name", "")
            tid = entry.get("id", "")
            inp = entry.get("input", {}) or entry.get("tool_input", {})
            if tid and name:
                tool_id_to_name[tid] = name
            _process_tool_use(name, inp)

        elif msg_type == "tool_result":
            tid = entry.get("tool_use_id", "")
            name = entry.get("tool_name", "") or entry.get("name", "") or tool_id_to_name.get(tid, "")
            raw = entry.get("content", "") or entry.get("result", "")
            if isinstance(raw, list):
                raw = " ".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in raw
                )
            if not isinstance(raw, str):
                raw = str(raw)
            if name:
                _process_tool_result(name, raw)

    return files


_TOOL_EXEC_RE = re.compile(r"Executed (\S+) (toolu_\S+)")

# Calibration: median seconds between consecutive tool steps.
# Derived from 1347 intervals across 31 paired runs (trajectory.json + claude-code.txt).
_CALIBRATION_SECS_PER_STEP = 2.6


def synthesize_trajectory(transcript_path: Path) -> dict:
    """Synthesize a trajectory dict from claude-code.txt when trajectory.json is missing.

    Parses the JSONL transcript to extract tool_use blocks with their tool_use_ids,
    then estimates timestamps using a calibrated seconds-per-step rate derived from
    runs that have both trajectory.json and claude-code.txt.

    Args:
        transcript_path: Path to agent/claude-code.txt.

    Returns:
        Dict with "steps" list compatible with extract_time_to_context(), or empty
        dict if the transcript cannot be parsed.
    """
    if not transcript_path.is_file():
        return {}

    from datetime import datetime, timedelta, timezone

    anchor = datetime(2000, 1, 1, tzinfo=timezone.utc)
    steps: list[dict] = []
    step_id = 0
    cumulative_secs = 0.0

    for line in transcript_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = entry.get("type", "")

        if msg_type == "system" and step_id == 0:
            step_id = 1
            steps.append({
                "step_id": step_id,
                "timestamp": anchor.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "source": "system",
                "message": "Session start (synthesized)",
            })
            continue

        if msg_type == "assistant":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_name = block.get("name", "")
                    tool_id = block.get("id", "")
                    if not tool_id:
                        continue
                    step_id += 1
                    cumulative_secs += _CALIBRATION_SECS_PER_STEP
                    ts = anchor + timedelta(seconds=cumulative_secs)
                    steps.append({
                        "step_id": step_id,
                        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z",
                        "source": "agent",
                        "message": f"Executed {tool_name} {tool_id}",
                    })

    if len(steps) < 2:
        return {}

    return {"schema_version": "synthesized-v1", "steps": steps}


def extract_time_to_context(
    trajectory_path: Path,
    transcript_path: Path,
    ground_truth_files: list[str],
) -> dict:
    """Compute time-to-context metrics from trajectory.json + claude-code.txt.

    Uses trajectory.json for per-step timestamps and claude-code.txt for
    file paths in tool results. Returns dict with ttfr, ttfr_step,
    tt_all_r, n_steps_to_first.

    Args:
        trajectory_path: Path to agent/trajectory.json.
        transcript_path: Path to agent/claude-code.txt.
        ground_truth_files: Ground truth file paths.

    Returns:
        Dict with timing metrics, or empty dict if data unavailable.
    """
    if not transcript_path.is_file():
        return {}
    if not ground_truth_files:
        return {}

    # Try real trajectory.json first, fall back to synthesis from transcript
    traj = None
    if trajectory_path.is_file():
        try:
            traj = json.loads(trajectory_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            traj = None
    if not traj or not traj.get("steps"):
        traj = synthesize_trajectory(transcript_path)

    steps = traj.get("steps", [])
    if not steps:
        return {}

    # Parse timestamps from trajectory steps
    from datetime import datetime

    def _parse_ts(s: str) -> Optional[float]:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    # Find session start time
    start_ts = _parse_ts(steps[0].get("timestamp", ""))
    if start_ts is None:
        return {}

    # Build tool_id -> (timestamp_epoch, step_index) from trajectory
    tool_timestamps: dict[str, tuple[float, int]] = {}
    step_idx = 0
    for step in steps:
        msg = step.get("message", "")
        if not isinstance(msg, str):
            continue
        m = _TOOL_EXEC_RE.match(msg)
        if m:
            tool_id = m.group(2)
            ts = _parse_ts(step.get("timestamp", ""))
            if ts is not None:
                tool_timestamps[tool_id] = (ts, step_idx)
                step_idx += 1

    if not tool_timestamps:
        return {}

    # Build tool_id -> file_paths from claude-code.txt
    tool_files: dict[str, list[str]] = {}
    tool_id_to_name: dict[str, str] = {}

    for line in transcript_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = entry.get("type", "")

        if msg_type == "assistant":
            message = entry.get("message", entry)
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id", "")
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    if tid and name:
                        tool_id_to_name[tid] = name
                    if isinstance(inp, dict):
                        fp = inp.get("file_path") or inp.get("path") or ""
                        if fp and _looks_like_file(_normalize(fp)):
                            tool_files.setdefault(tid, []).append(fp)

        elif msg_type == "user":
            message = entry.get("message", entry)
            for block in message.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    raw = block.get("content", "")
                    if isinstance(raw, list):
                        raw = " ".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in raw
                        )
                    if isinstance(raw, str):
                        for pm in _PATH_JSON_RE.finditer(raw):
                            p = pm.group(1)
                            if _looks_like_file(_normalize(p)):
                                tool_files.setdefault(tid, []).append(p)

    # Match tool files against ground truth
    gt_normalized = {_normalize(f) for f in ground_truth_files}
    gt_found: set[str] = set()
    ttfr = None
    ttfr_step = None
    tt_all_r = None
    n_steps_to_first = None

    # Process tools in timestamp order
    sorted_tools = sorted(
        tool_timestamps.items(),
        key=lambda x: x[1][0],
    )

    for tool_id, (ts, sidx) in sorted_tools:
        files = tool_files.get(tool_id, [])
        for f in files:
            fn = _normalize(f)
            if fn in gt_normalized:
                gt_found.add(fn)
                if ttfr is None:
                    ttfr = ts - start_ts
                    ttfr_step = sidx
                    n_steps_to_first = sidx
                if gt_found >= gt_normalized:
                    tt_all_r = ts - start_ts
                    break
        if tt_all_r is not None:
            break

    result: dict = {}
    if ttfr is not None:
        result["ttfr"] = round(ttfr, 1)
        result["ttfr_step"] = ttfr_step
        result["n_steps_to_first"] = n_steps_to_first
    if tt_all_r is not None:
        result["tt_all_r"] = round(tt_all_r, 1)
    return result


def extract_tokens_before_first_relevant(
    transcript_path: Path,
    n_steps_to_first: int | None,
) -> int | None:
    """Sum total tokens from claude-code.txt up to the TTFR step.

    Backward-compatible wrapper around extract_cost_metrics_before_first_relevant.
    """
    metrics = extract_cost_metrics_before_first_relevant(transcript_path, n_steps_to_first)
    return metrics.get("tokens_total") if metrics else None


def extract_cost_metrics_before_first_relevant(
    transcript_path: Path,
    n_steps_to_first: int | None,
) -> dict:
    """Extract multiple cost metrics from claude-code.txt up to the TTFR step.

    Tracks per-type token totals and computes dollar-weighted cost using
    Anthropic Opus pricing. Cache reads ($1.50/Mtok) are properly distinguished
    from output tokens ($75/Mtok), fixing the measurement artifact where
    all-token sums made SG_full appear 384% more expensive.

    Returns dict with:
        tokens_total: sum of all token types (backward compatible)
        output_tokens: output tokens only (model reasoning work)
        cost_usd: dollar-weighted cost using Anthropic pricing
        input_tokens: uncached input tokens
        cache_creation_tokens: cache creation tokens
        cache_read_tokens: cache read tokens
    """
    if n_steps_to_first is None or not transcript_path.is_file():
        return {}

    cum_input = 0
    cum_cache_create = 0
    cum_cache_read = 0
    cum_output = 0
    tool_step = 0

    for line in transcript_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue

        message = entry.get("message", entry)
        usage = message.get("usage", {})
        cum_input += usage.get("input_tokens", 0)
        cum_cache_create += usage.get("cache_creation_input_tokens", 0)
        cum_cache_read += usage.get("cache_read_input_tokens", 0)
        cum_output += usage.get("output_tokens", 0)

        # Count tool_use blocks in this message as steps
        content_blocks = message.get("content", [])
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if tool_step >= n_steps_to_first:
                        tokens_total = cum_input + cum_cache_create + cum_cache_read + cum_output
                        cost_usd = (
                            cum_input * _PRICE_PER_MTOK_INPUT
                            + cum_cache_create * _PRICE_PER_MTOK_CACHE_CREATE
                            + cum_cache_read * _PRICE_PER_MTOK_CACHE_READ
                            + cum_output * _PRICE_PER_MTOK_OUTPUT
                        ) / 1_000_000
                        return {
                            "tokens_total": tokens_total,
                            "output_tokens": cum_output,
                            "cost_usd": round(cost_usd, 6),
                            "input_tokens": cum_input,
                            "cache_creation_tokens": cum_cache_create,
                            "cache_read_tokens": cum_cache_read,
                        }
                    tool_step += 1

    return {}


def extract_agent_time_to_first_relevant(
    trajectory_path: Path,
    n_steps_to_first: int | None,
) -> float | None:
    """Seconds from first agent tool execution to the TTFR step.

    Unlike TTFR (measured from session start including Docker/setup), this
    measures from the first tool execution, capturing only agent working time.

    Args:
        trajectory_path: Path to agent/trajectory.json.
        n_steps_to_first: Step index (0-based) of the first relevant file.

    Returns:
        Seconds from first tool to TTFR tool, or None if unavailable.
    """
    if n_steps_to_first is None or not trajectory_path.is_file():
        return None

    try:
        traj = json.loads(trajectory_path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None

    steps = traj.get("steps", [])
    if not steps:
        return None

    from datetime import datetime

    def _parse_ts(s: str) -> float | None:
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            return None

    # Find tool execution steps via the "Executed <tool> <id>" pattern
    tool_timestamps: list[float] = []
    for step in steps:
        msg = step.get("message", "")
        if not isinstance(msg, str):
            continue
        if _TOOL_EXEC_RE.match(msg):
            ts = _parse_ts(step.get("timestamp", ""))
            if ts is not None:
                tool_timestamps.append(ts)

    if not tool_timestamps or n_steps_to_first >= len(tool_timestamps):
        return None

    first_tool_ts = tool_timestamps[0]
    ttfr_tool_ts = tool_timestamps[n_steps_to_first]
    delta = ttfr_tool_ts - first_tool_ts
    return round(delta, 1) if delta >= 0 else None


def _looks_like_file(path: str) -> bool:
    """Heuristic: does the normalized path look like a real file?"""
    if not path or len(path) < 2:
        return False
    # Must have an extension
    basename = path.rsplit("/", 1)[-1] if "/" in path else path
    if "." not in basename:
        return False
    # Skip obvious non-files
    if path.startswith(("http:", "https:", "ftp:")):
        return False
    # Skip grep-like output lines (contain line numbers after filename)
    if re.search(r"-\d+-", path) or re.search(r":\d+:", path):
        return False
    # Skip lines that look like code snippets
    if any(c in path for c in ("(", ")", "{", "}", "=", ";", "#", "\\", "  ")):
        return False
    # Path should be reasonably short
    if len(path) > 200:
        return False
    return True

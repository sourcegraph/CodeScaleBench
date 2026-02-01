#!/usr/bin/env python3
"""Select ~100 benchmark tasks stratified by SDLC phase with MCP benefit scoring.

Reads task.toml files from 8 benchmarks under benchmarks/, assigns each task an
SDLC phase and MCP benefit score, then performs stratified selection to produce
selected_benchmark_tasks.json and docs/TASK_SELECTION.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from random import Random
from statistics import mean

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RANDOM_SEED = 42

# SWE-Bench Pro language corrections: repo slug -> correct language
SWEBENCH_LANGUAGE_OVERRIDES: dict[str, str] = {
    "navidrome/navidrome": "go",
    "element-hq/element-web": "typescript",
    "nodebb/nodebb": "javascript",
    "qutebrowser/qutebrowser": "python",
}

# (benchmark, category) -> SDLC phase
SDLC_PHASE_MAP: dict[tuple[str, str], str] = {
    # Requirements & Discovery
    ("tac_mcp_value", "find-in-codebase"): "Requirements & Discovery",
    # Architecture & Design
    ("locobench_agent", "architectural_understanding"): "Architecture & Design",
    # Implementation (feature)
    ("big_code_mcp", "big_code_feature"): "Implementation (feature)",
    ("tac_mcp_value", "implement"): "Implementation (feature)",
    ("tac_mcp_value", "endpoint"): "Implementation (feature)",
    ("github_mined", "feature_implementation"): "Implementation (feature)",
    # Implementation (bug fix)
    ("swebench_pro", "debugging"): "Implementation (bug fix)",
    ("swebench_pro", "swebench_pro"): "Implementation (bug fix)",
    ("github_mined", "cross_module_bug_fix"): "Implementation (bug fix)",
    ("locobench_agent", "bug_investigation"): "Implementation (bug fix)",
    # Implementation (refactoring)
    ("locobench_agent", "cross_file_refactoring"): "Implementation (refactoring)",
    ("dependeval_benchmark", "multifile_editing"): "Implementation (refactoring)",
    # Testing & QA
    ("tac_mcp_value", "unit-test"): "Testing & QA",
    ("sweperf", "performance"): "Testing & QA",
    # Documentation
    ("kubernetes_docs", "package-documentation"): "Documentation",
    # Maintenance
    ("dependeval_benchmark", "dependency_recognition"): "Maintenance",
    ("dependeval_benchmark", "repository_construction"): "Maintenance",
    ("tac_mcp_value", "dependency"): "Maintenance",
    ("tac_mcp_value", "troubleshoot"): "Maintenance",
}

# Per-category MCP affinity weights (for task_category_weight component)
MCP_CATEGORY_AFFINITY: dict[str, float] = {
    "architectural_understanding": 1.0,
    "big_code_feature": 0.95,
    "cross_file_refactoring": 0.9,
    "cross_module_bug_fix": 0.85,
    "feature_implementation": 0.8,
    "find-in-codebase": 0.8,
    "debugging": 0.75,
    "swebench_pro": 0.75,
    "package-documentation": 0.7,
    "bug_investigation": 0.7,
    "performance": 0.65,
    "unit-test": 0.6,
    "implement": 0.7,
    "endpoint": 0.65,
    "dependency": 0.5,
    "troubleshoot": 0.55,
    "multifile_editing": 0.8,
    "dependency_recognition": 0.5,
    "repository_construction": 0.6,
}

# MCP scoring weights
MCP_WEIGHTS = {
    "context_complexity": 0.25,
    "cross_file_deps": 0.30,
    "semantic_search_potential": 0.20,
    "task_category_weight": 0.25,
}

# TAC task-id -> effective category for SDLC mapping
TAC_CATEGORY_MAP: dict[str, str] = {
    "tac-buffer-pool-manager": "implement",
    "tac-copilot-arena-endpoint": "endpoint",
    "tac-dependency-change": "dependency",
    "tac-find-in-codebase-1": "find-in-codebase",
    "tac-find-in-codebase-2": "find-in-codebase",
    "tac-implement-hyperloglog": "implement",
    "tac-troubleshoot-dev-setup": "troubleshoot",
    "tac-write-unit-test": "unit-test",
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    task_id: str
    benchmark: str
    category: str
    language: str
    difficulty: str = "unknown"
    repo: str = ""
    sdlc_phase: str = ""
    mcp_benefit_score: float = 0.0
    mcp_breakdown: dict[str, float] = field(default_factory=dict)
    selection_rationale: str = ""
    task_dir: str = ""
    # Extra metadata used during scoring / selection
    context_length: int = 0
    files_count: int = 0
    solution_files_changed: int = 0


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_swebench_pro(bench_dir: Path) -> list[TaskRecord]:
    tasks_dir = bench_dir / "tasks"
    records: list[TaskRecord] = []
    for d in sorted(tasks_dir.iterdir()):
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        meta = data.get("metadata", {})
        task_sec = data.get("task", {})
        repo = task_sec.get("repo", meta.get("repo", ""))
        language = meta.get("language", "unknown")

        # Apply language corrections
        repo_lower = repo.lower()
        for slug, correct_lang in SWEBENCH_LANGUAGE_OVERRIDES.items():
            if slug in repo_lower:
                language = correct_lang
                break

        # Count files changed from solution/solve.sh
        files_changed = 0
        solve_sh = d / "solution" / "solve.sh"
        if solve_sh.exists():
            text = solve_sh.read_text(errors="replace")
            files_changed = text.count("diff --git")

        task_id = task_sec.get("id", d.name)
        category = task_sec.get("category", meta.get("category", "swebench_pro"))
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="swebench_pro",
            category=category,
            language=language,
            difficulty=meta.get("difficulty", "hard"),
            repo=repo,
            task_dir=f"swebench_pro/tasks/{d.name}",
            solution_files_changed=files_changed,
        ))
    return records


def load_locobench_agent(bench_dir: Path) -> list[TaskRecord]:
    tasks_dir = bench_dir / "tasks"
    records: list[TaskRecord] = []
    for d in sorted(tasks_dir.iterdir()):
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        meta = data.get("metadata", {})
        records.append(TaskRecord(
            task_id=meta.get("task_id", d.name),
            benchmark="locobench_agent",
            category=meta.get("category", "unknown"),
            language=meta.get("language", "unknown"),
            difficulty=meta.get("difficulty", "unknown"),
            task_dir=f"locobench_agent/tasks/{d.name}",
            context_length=int(meta.get("context_length", 0)),
            files_count=int(meta.get("files_count", 0)),
        ))
    return records


def load_big_code_mcp(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.startswith("big-code-"):
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        meta = data.get("metadata", {})
        task_sec = data.get("task", {})
        records.append(TaskRecord(
            task_id=task_sec.get("id", d.name),
            benchmark="big_code_mcp",
            category=task_sec.get("category", "big_code_feature"),
            language=task_sec.get("language", meta.get("language", "unknown")),
            difficulty=task_sec.get("difficulty", "hard"),
            repo=task_sec.get("repo", ""),
            task_dir=f"big_code_mcp/{d.name}",
        ))
    return records


def load_tac_mcp_value(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.startswith("tac-"):
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        meta = data.get("metadata", {})
        task_sec = data.get("task", {})
        task_id = task_sec.get("id", d.name)
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="tac_mcp_value",
            category=TAC_CATEGORY_MAP.get(task_id, task_sec.get("category", "tac_mcp_value")),
            language=task_sec.get("language", "unknown"),
            difficulty=task_sec.get("difficulty", "medium"),
            task_dir=f"tac_mcp_value/{d.name}",
        ))
    return records


def load_github_mined(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.startswith("sgt-"):
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        task_sec = data.get("task", {})

        # Parse files modified from instruction.md
        files_modified = 0
        instr = d / "instruction.md"
        if instr.exists():
            text = instr.read_text(errors="replace")
            m = re.search(r"(\d+)\s+files?\s+modified", text)
            if m:
                files_modified = int(m.group(1))

        records.append(TaskRecord(
            task_id=task_sec.get("id", d.name),
            benchmark="github_mined",
            category=task_sec.get("category", "cross_module_bug_fix"),
            language=task_sec.get("language", "cpp"),
            difficulty=task_sec.get("difficulty", "medium"),
            repo=task_sec.get("repo", "pytorch"),
            task_dir=f"github_mined/{d.name}",
            solution_files_changed=files_modified,
        ))
    return records


def load_kubernetes_docs(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.endswith("-doc-001") and "-doc-" not in d.name:
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        task_sec = data.get("task", {})
        records.append(TaskRecord(
            task_id=task_sec.get("id", d.name),
            benchmark="kubernetes_docs",
            category=task_sec.get("category", "package-documentation"),
            language=task_sec.get("language", "go"),
            difficulty=task_sec.get("difficulty", "hard"),
            repo=task_sec.get("repo", "kubernetes"),
            task_dir=f"kubernetes_docs/{d.name}",
        ))
    return records


def load_dependeval_benchmark(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for parent in sorted(bench_dir.iterdir()):
        if not parent.is_dir() or parent.name.startswith("."):
            continue
        for child in sorted(parent.iterdir()):
            toml_path = child / "task.toml"
            if not toml_path.exists():
                continue
            data = _read_toml(toml_path)
            task_sec = data.get("task", {})
            records.append(TaskRecord(
                task_id=task_sec.get("name", child.name),
                benchmark="dependeval_benchmark",
                category=task_sec.get("task_type", "unknown"),
                language=task_sec.get("language", "unknown"),
                difficulty=task_sec.get("difficulty", "medium"),
                task_dir=f"dependeval_benchmark/{parent.name}/{child.name}",
            ))
    return records


def load_sweperf(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    sel_path = bench_dir / "selected_tasks.json"
    if not sel_path.exists():
        return records
    sel_data = json.loads(sel_path.read_text())
    for t in sel_data.get("tasks", []):
        task_id = t["task_id"]
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="sweperf",
            category="performance",
            language="python",  # all sweperf tasks are Python
            difficulty=t.get("difficulty", "medium"),
            repo=t.get("repo_name", ""),
            task_dir=f"sweperf/data",
        ))
    return records


LOADERS: dict[str, tuple[str, callable]] = {
    "swebench_pro": ("swebench_pro", load_swebench_pro),
    "locobench_agent": ("locobench_agent", load_locobench_agent),
    "big_code_mcp": ("big_code_mcp", load_big_code_mcp),
    "tac_mcp_value": ("tac_mcp_value", load_tac_mcp_value),
    "github_mined": ("github_mined", load_github_mined),
    "kubernetes_docs": ("kubernetes_docs", load_kubernetes_docs),
    "dependeval_benchmark": ("dependeval_benchmark", load_dependeval_benchmark),
    "sweperf": ("sweperf", load_sweperf),
}

# ---------------------------------------------------------------------------
# SDLC phase assignment
# ---------------------------------------------------------------------------


def assign_sdlc_phase(task: TaskRecord) -> str:
    """Assign an SDLC phase based on (benchmark, category)."""
    key = (task.benchmark, task.category)
    if key in SDLC_PHASE_MAP:
        return SDLC_PHASE_MAP[key]

    # Fallback: try prefix matching for tac categories
    if task.benchmark == "tac_mcp_value":
        for (bm, cat), phase in SDLC_PHASE_MAP.items():
            if bm == "tac_mcp_value" and task.category.startswith(cat):
                return phase

    # Default by benchmark
    defaults = {
        "swebench_pro": "Implementation (bug fix)",
        "github_mined": "Implementation (bug fix)",
        "locobench_agent": "Architecture & Design",
        "big_code_mcp": "Implementation (feature)",
        "kubernetes_docs": "Documentation",
        "sweperf": "Testing & QA",
        "dependeval_benchmark": "Maintenance",
        "tac_mcp_value": "Implementation (feature)",
    }
    return defaults.get(task.benchmark, "Implementation (feature)")


# ---------------------------------------------------------------------------
# MCP benefit scoring
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_mcp_benefit(task: TaskRecord) -> tuple[float, dict[str, float]]:
    """Compute MCP benefit score in [0, 1] with breakdown."""

    # --- context_complexity ---
    if task.context_length > 0:
        cc = _clamp(task.context_length / 1_000_000)
    elif task.benchmark == "big_code_mcp":
        cc = 0.95  # huge codebases
    elif task.benchmark == "swebench_pro":
        cc = 0.6
    elif task.benchmark == "github_mined":
        cc = 0.7  # PyTorch is large
    elif task.benchmark == "tac_mcp_value":
        cc = 0.5
    elif task.benchmark == "sweperf":
        cc = 0.5
    elif task.benchmark == "kubernetes_docs":
        cc = 0.6
    elif task.benchmark == "dependeval_benchmark":
        cc = 0.3
    else:
        cc = 0.4

    # --- cross_file_deps ---
    if task.files_count > 0:
        cfd = _clamp(task.files_count / 20.0)
    elif task.solution_files_changed > 0:
        cfd = _clamp(task.solution_files_changed / 20.0)
    elif task.benchmark == "big_code_mcp":
        cfd = 0.8
    elif task.benchmark == "locobench_agent":
        cfd = 1.0  # all have 70+ files
    elif task.benchmark == "github_mined":
        cfd = 0.3
    elif task.benchmark == "dependeval_benchmark":
        cfd = 0.4
    else:
        cfd = 0.3

    # --- semantic_search_potential ---
    if task.benchmark == "big_code_mcp":
        ssp = 0.9
    elif task.category in ("find-in-codebase",):
        ssp = 0.8
    elif task.context_length > 500_000:
        ssp = 0.7
    elif task.benchmark in ("swebench_pro", "github_mined"):
        ssp = 0.6
    elif task.benchmark == "kubernetes_docs":
        ssp = 0.5
    elif task.benchmark == "tac_mcp_value":
        ssp = 0.5
    else:
        ssp = 0.4

    # --- task_category_weight ---
    tcw = MCP_CATEGORY_AFFINITY.get(task.category, 0.5)

    breakdown = {
        "context_complexity": round(cc, 3),
        "cross_file_deps": round(cfd, 3),
        "semantic_search_potential": round(ssp, 3),
        "task_category_weight": round(tcw, 3),
    }

    score = (
        MCP_WEIGHTS["context_complexity"] * cc
        + MCP_WEIGHTS["cross_file_deps"] * cfd
        + MCP_WEIGHTS["semantic_search_potential"] * ssp
        + MCP_WEIGHTS["task_category_weight"] * tcw
    )
    return round(score, 4), breakdown


# ---------------------------------------------------------------------------
# Stratified selection
# ---------------------------------------------------------------------------


def select_swebench_pro(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
    """Select ~35 from SWE-Bench Pro, proportional by repo, >=1 per repo."""
    target = 35

    # Group by repo
    by_repo: dict[str, list[TaskRecord]] = {}
    for t in tasks:
        by_repo.setdefault(t.repo, []).append(t)

    # Sort each group by files changed desc, then by score desc
    for repo_tasks in by_repo.values():
        repo_tasks.sort(key=lambda t: (t.solution_files_changed, t.mcp_benefit_score), reverse=True)

    selected: list[TaskRecord] = []
    # First pass: pick top 1 from each repo
    for repo in sorted(by_repo):
        selected.append(by_repo[repo][0])

    remaining_budget = target - len(selected)
    if remaining_budget <= 0:
        return selected[:target]

    # Proportional allocation of remaining budget
    total = len(tasks)
    repo_quotas: dict[str, int] = {}
    for repo, repo_tasks in sorted(by_repo.items()):
        share = (len(repo_tasks) / total) * remaining_budget
        repo_quotas[repo] = max(0, int(share))

    # Distribute rounding remainders
    allocated = sum(repo_quotas.values())
    shortfall = remaining_budget - allocated
    repos_by_size = sorted(by_repo, key=lambda r: len(by_repo[r]), reverse=True)
    for i in range(shortfall):
        repo_quotas[repos_by_size[i % len(repos_by_size)]] += 1

    # Second pass: fill quotas
    for repo in sorted(by_repo):
        extra = repo_quotas[repo]
        candidates = by_repo[repo][1:]  # skip already-selected first
        selected.extend(candidates[:extra])

    # Ensure language diversity: at least 3 Go, 3 TS/JS tasks
    selected_langs = {t.language for t in selected}
    for lang in ("go", "typescript", "javascript"):
        lang_in = [t for t in selected if t.language == lang]
        if len(lang_in) < 3:
            lang_pool = [t for t in tasks if t.language == lang and t not in selected]
            lang_pool.sort(key=lambda t: t.mcp_benefit_score, reverse=True)
            need = 3 - len(lang_in)
            selected.extend(lang_pool[:need])

    # Deduplicate preserving order
    seen: set[str] = set()
    deduped: list[TaskRecord] = []
    for t in selected:
        if t.task_id not in seen:
            seen.add(t.task_id)
            deduped.append(t)

    for t in deduped:
        t.selection_rationale = "Proportional by repo, prefer most files changed"
    return deduped


def select_locobench_agent(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
    """Select ~25 from LoCoBench, prioritizing arch > refactoring > bug."""
    target = 25
    priority_order = ["architectural_understanding", "cross_file_refactoring", "bug_investigation"]

    by_cat: dict[str, list[TaskRecord]] = {}
    for t in tasks:
        by_cat.setdefault(t.category, []).append(t)

    for cat_tasks in by_cat.values():
        cat_tasks.sort(key=lambda t: t.mcp_benefit_score, reverse=True)

    selected: list[TaskRecord] = []
    # Take all bug_investigation (3), all cross_file_refactoring (13), then fill with arch
    for cat in ["bug_investigation", "cross_file_refactoring", "architectural_understanding"]:
        pool = by_cat.get(cat, [])
        remaining = target - len(selected)
        selected.extend(pool[:remaining])

    for t in selected:
        t.selection_rationale = f"Priority: {t.category}, by MCP score"
    return selected[:target]


def select_github_mined(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
    """Select ~12 from github_mined, prefer hard difficulty, then most files modified."""
    target = 12

    # Sort: hard first, then by files modified desc, then by score
    diff_rank = {"hard": 0, "medium": 1, "easy": 2, "unknown": 3}
    tasks_sorted = sorted(
        tasks,
        key=lambda t: (diff_rank.get(t.difficulty, 3), -t.solution_files_changed, -t.mcp_benefit_score),
    )
    selected = tasks_sorted[:target]
    for t in selected:
        t.selection_rationale = f"Prefer hard difficulty, {t.solution_files_changed} files modified"
    return selected


def select_all(tasks: list[TaskRecord], benchmark_name: str) -> list[TaskRecord]:
    """Select all tasks from a small benchmark."""
    for t in tasks:
        t.selection_rationale = f"All {benchmark_name} tasks selected (small benchmark)"
    return list(tasks)


def select_tasks(all_tasks: dict[str, list[TaskRecord]], rng: Random) -> list[TaskRecord]:
    """Run per-benchmark selection strategies."""
    selected: list[TaskRecord] = []

    if "swebench_pro" in all_tasks:
        selected.extend(select_swebench_pro(all_tasks["swebench_pro"], rng))
    if "locobench_agent" in all_tasks:
        selected.extend(select_locobench_agent(all_tasks["locobench_agent"], rng))
    if "github_mined" in all_tasks:
        selected.extend(select_github_mined(all_tasks["github_mined"], rng))

    for bm in ("big_code_mcp", "kubernetes_docs", "tac_mcp_value", "dependeval_benchmark", "sweperf"):
        if bm in all_tasks:
            selected.extend(select_all(all_tasks[bm], bm))

    # Stable sort by benchmark then task_id for deterministic output
    selected.sort(key=lambda t: (t.benchmark, t.task_id))
    return selected


# ---------------------------------------------------------------------------
# Output: JSON
# ---------------------------------------------------------------------------


def build_statistics(selected: list[TaskRecord]) -> dict:
    by_phase: dict[str, int] = {}
    by_bench: dict[str, int] = {}
    by_lang: dict[str, int] = {}
    scores: list[float] = []

    for t in selected:
        by_phase[t.sdlc_phase] = by_phase.get(t.sdlc_phase, 0) + 1
        by_bench[t.benchmark] = by_bench.get(t.benchmark, 0) + 1
        by_lang[t.language] = by_lang.get(t.language, 0) + 1
        scores.append(t.mcp_benefit_score)

    return {
        "tasks_per_sdlc_phase": dict(sorted(by_phase.items())),
        "tasks_per_benchmark": dict(sorted(by_bench.items())),
        "tasks_per_language": dict(sorted(by_lang.items())),
        "avg_mcp_benefit_score": round(mean(scores), 4) if scores else 0.0,
    }


def write_json(selected: list[TaskRecord], total_available: int, output_path: Path) -> None:
    task_dicts = []
    for t in selected:
        task_dicts.append({
            "task_id": t.task_id,
            "benchmark": t.benchmark,
            "sdlc_phase": t.sdlc_phase,
            "language": t.language,
            "difficulty": t.difficulty,
            "category": t.category,
            "repo": t.repo,
            "mcp_benefit_score": t.mcp_benefit_score,
            "mcp_breakdown": t.mcp_breakdown,
            "selection_rationale": t.selection_rationale,
            "task_dir": t.task_dir,
        })

    stats = build_statistics(selected)
    doc = {
        "metadata": {
            "title": "CodeContextBench Selected Benchmark Tasks",
            "version": "1.0",
            "generated_by": "scripts/select_benchmark_tasks.py",
            "random_seed": RANDOM_SEED,
            "total_available": total_available,
            "total_selected": len(selected),
        },
        "methodology": {
            "description": (
                "Tasks selected via stratified sampling across 8 benchmarks, "
                "covering all SDLC phases. Each task scored for MCP benefit using "
                "weighted combination of context complexity, cross-file dependencies, "
                "semantic search potential, and task category affinity."
            ),
            "sdlc_phases": [
                "Requirements & Discovery",
                "Architecture & Design",
                "Implementation (feature)",
                "Implementation (bug fix)",
                "Implementation (refactoring)",
                "Testing & QA",
                "Documentation",
                "Maintenance",
            ],
            "mcp_scoring_weights": MCP_WEIGHTS,
            "selection_targets": {
                "swebench_pro": "~35 (proportional by repo)",
                "locobench_agent": "~25 (priority: arch > refactoring > bug)",
                "github_mined": "~12 (prefer hard, most files)",
                "big_code_mcp": "all (4)",
                "kubernetes_docs": "all (5)",
                "tac_mcp_value": "all (8)",
                "dependeval_benchmark": "all (9)",
                "sweperf": "all (3)",
            },
        },
        "statistics": stats,
        "tasks": task_dicts,
    }

    output_path.write_text(json.dumps(doc, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Output: Markdown
# ---------------------------------------------------------------------------


def write_markdown(
    selected: list[TaskRecord],
    total_available: int,
    available_per_benchmark: dict[str, int],
    output_path: Path,
) -> None:
    stats = build_statistics(selected)
    lines: list[str] = []

    lines.append("# Task Selection Methodology")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append(
        f"Selected **{len(selected)} tasks** from {total_available} available across "
        f"8 benchmarks, stratified by SDLC phase with MCP benefit scoring."
    )
    lines.append("")

    # SDLC Phase Coverage
    lines.append("## SDLC Phase Coverage")
    lines.append("")
    lines.append("| SDLC Phase | Tasks | Benchmarks |")
    lines.append("|------------|-------|------------|")
    phase_benchmarks: dict[str, set[str]] = {}
    for t in selected:
        phase_benchmarks.setdefault(t.sdlc_phase, set()).add(t.benchmark)
    for phase in [
        "Requirements & Discovery",
        "Architecture & Design",
        "Implementation (feature)",
        "Implementation (bug fix)",
        "Implementation (refactoring)",
        "Testing & QA",
        "Documentation",
        "Maintenance",
    ]:
        count = stats["tasks_per_sdlc_phase"].get(phase, 0)
        benchmarks = ", ".join(sorted(phase_benchmarks.get(phase, set())))
        lines.append(f"| {phase} | {count} | {benchmarks} |")
    lines.append("")

    # Benchmark Coverage
    lines.append("## Benchmark Coverage")
    lines.append("")
    lines.append("| Benchmark | Available | Selected | Strategy |")
    lines.append("|-----------|-----------|----------|----------|")
    strategies = {
        "swebench_pro": "Proportional by repo, prefer most files changed",
        "locobench_agent": "Priority: arch > refactoring > bug, by MCP score",
        "github_mined": "Prefer hard difficulty, then most files modified",
        "big_code_mcp": "All selected (small benchmark)",
        "kubernetes_docs": "All selected (small benchmark)",
        "tac_mcp_value": "All selected (small benchmark)",
        "dependeval_benchmark": "All selected (small benchmark)",
        "sweperf": "All selected (small benchmark)",
    }
    # We need available counts per benchmark — estimate from selected + rationale
    for bm in sorted(strategies):
        sel_count = stats["tasks_per_benchmark"].get(bm, 0)
        avail = available_per_benchmark.get(bm, "—")
        lines.append(f"| {bm} | {avail} | {sel_count} | {strategies[bm]} |")
    lines.append("")

    # Language Distribution
    lines.append("## Language Distribution")
    lines.append("")
    lines.append("| Language | Tasks |")
    lines.append("|----------|-------|")
    for lang, count in sorted(stats["tasks_per_language"].items(), key=lambda x: -x[1]):
        lines.append(f"| {lang} | {count} |")
    lines.append("")

    # MCP Scoring
    lines.append("## MCP Benefit Scoring")
    lines.append("")
    lines.append("Each task receives an MCP benefit score in [0.0, 1.0] computed as:")
    lines.append("")
    lines.append("```")
    lines.append("score = 0.25 * context_complexity")
    lines.append("      + 0.30 * cross_file_deps")
    lines.append("      + 0.20 * semantic_search_potential")
    lines.append("      + 0.25 * task_category_weight")
    lines.append("```")
    lines.append("")
    lines.append(f"**Average MCP benefit score:** {stats['avg_mcp_benefit_score']:.4f}")
    lines.append("")

    lines.append("### Component Definitions")
    lines.append("")
    lines.append("- **context_complexity**: Derived from codebase token count "
                 "(LoCoBench `context_length`) or benchmark-level proxy. Normalized: 1M+ tokens = 1.0")
    lines.append("- **cross_file_deps**: From `files_count`, `solution_files_changed`, or parsed "
                 "from instruction.md. Normalized: 20+ files = 1.0")
    lines.append("- **semantic_search_potential**: High for large repos (big_code_mcp=0.9), "
                 "find-in-codebase tasks (0.8), large context (0.7)")
    lines.append("- **task_category_weight**: Per-category MCP affinity "
                 "(architectural_understanding=1.0, cross_file_refactoring=0.9, etc.)")
    lines.append("")

    # Per-benchmark selection details
    lines.append("## Per-Benchmark Selection Strategies")
    lines.append("")

    lines.append("### SWE-Bench Pro (~35 tasks)")
    lines.append("Proportional allocation by repository, ensuring at least 1 task per repo. "
                 "Within each repo, tasks with the most files changed in their solution patch "
                 "are preferred. Language corrections applied (e.g., NodeBB -> javascript, "
                 "navidrome -> go). Diversity check ensures >=3 tasks each for Go, TypeScript, "
                 "and JavaScript language families.")
    lines.append("")

    lines.append("### LoCoBench Agent (~25 tasks)")
    lines.append("All bug_investigation tasks (3) selected first, then all cross_file_refactoring "
                 "(13), then top architectural_understanding tasks by MCP score to fill remaining "
                 "budget. All tasks have >700K token context and 70+ files.")
    lines.append("")

    lines.append("### GitHub Mined (~12 tasks)")
    lines.append("All PyTorch cross-module tasks. Selection prioritizes hard difficulty, then "
                 "tasks with the most files modified in the ground truth PR.")
    lines.append("")

    lines.append("### Small Benchmarks (all selected)")
    lines.append("big_code_mcp (4), kubernetes_docs (5), tac_mcp_value (8), "
                 "dependeval_benchmark (9), sweperf (3) — all tasks selected due to small size.")
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select benchmark tasks stratified by SDLC phase with MCP benefit scoring."
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=Path("benchmarks"),
        help="Root directory containing benchmark subdirectories (default: benchmarks/)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("selected_benchmark_tasks.json"),
        help="Output JSON file path (default: selected_benchmark_tasks.json)",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=Path("docs/TASK_SELECTION.md"),
        help="Output Markdown file path (default: docs/TASK_SELECTION.md)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=RANDOM_SEED,
        help=f"Random seed for reproducibility (default: {RANDOM_SEED})",
    )
    args = parser.parse_args()

    rng = Random(args.seed)
    benchmarks_dir = args.benchmarks_dir

    # Load all tasks
    all_tasks: dict[str, list[TaskRecord]] = {}
    available_per_benchmark: dict[str, int] = {}
    total_available = 0
    for bm_key, (subdir, loader_fn) in LOADERS.items():
        bm_path = benchmarks_dir / subdir
        if not bm_path.exists():
            print(f"WARNING: {bm_path} not found, skipping {bm_key}", file=sys.stderr)
            continue
        tasks = loader_fn(bm_path)
        if tasks:
            all_tasks[bm_key] = tasks
            available_per_benchmark[bm_key] = len(tasks)
            total_available += len(tasks)
            print(f"Loaded {len(tasks):>4d} tasks from {bm_key}")

    print(f"\nTotal available: {total_available}")

    # Assign SDLC phase and MCP scores
    for bm_tasks in all_tasks.values():
        for t in bm_tasks:
            t.sdlc_phase = assign_sdlc_phase(t)
            t.mcp_benefit_score, t.mcp_breakdown = score_mcp_benefit(t)

    # Select
    selected = select_tasks(all_tasks, rng)
    print(f"Total selected:  {len(selected)}")

    # Statistics summary
    stats = build_statistics(selected)
    print(f"\nBy SDLC phase:")
    for phase, count in sorted(stats["tasks_per_sdlc_phase"].items()):
        print(f"  {phase:35s} {count:3d}")
    print(f"\nBy benchmark:")
    for bm, count in sorted(stats["tasks_per_benchmark"].items()):
        print(f"  {bm:30s} {count:3d}")
    print(f"\nBy language:")
    for lang, count in sorted(stats["tasks_per_language"].items(), key=lambda x: -x[1]):
        print(f"  {lang:20s} {count:3d}")
    print(f"\nAvg MCP benefit score: {stats['avg_mcp_benefit_score']:.4f}")

    # Write outputs
    write_json(selected, total_available, args.output_json)
    print(f"\nWrote {args.output_json}")

    write_markdown(selected, total_available, available_per_benchmark, args.output_md)
    print(f"Wrote {args.output_md}")


if __name__ == "__main__":
    main()

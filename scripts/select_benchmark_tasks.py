#!/usr/bin/env python3
"""Select ~100 benchmark tasks stratified by SDLC phase with MCP benefit scoring.

Reads task.toml files from 7 benchmarks under benchmarks/, assigns each task an
SDLC phase and MCP benefit score, then performs stratified selection to produce
selected_benchmark_tasks.json and docs/TASK_SELECTION.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
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
EXCLUDED_FROM_DEFAULT_SELECTION = {"ccb_dependeval", "csb_dependeval"}

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
    ("ccb_tac", "find-in-codebase"): "Requirements & Discovery",
    # Architecture & Design
    ("ccb_locobench", "architectural_understanding"): "Architecture & Design",
    # Implementation (feature)
    ("ccb_largerepo", "big_code_feature"): "Implementation (feature)",
    ("ccb_tac", "implement"): "Implementation (feature)",
    ("ccb_tac", "endpoint"): "Implementation (feature)",
    ("ccb_pytorch", "feature_implementation"): "Implementation (feature)",
    # Implementation (bug fix)
    ("ccb_swebenchpro", "debugging"): "Implementation (bug fix)",
    ("ccb_swebenchpro", "ccb_swebenchpro"): "Implementation (bug fix)",
    ("ccb_pytorch", "cross_module_bug_fix"): "Implementation (bug fix)",
    ("ccb_locobench", "bug_investigation"): "Implementation (bug fix)",
    # Implementation (refactoring)
    ("ccb_locobench", "cross_file_refactoring"): "Implementation (refactoring)",
    # Testing & QA
    ("ccb_tac", "unit-test"): "Testing & QA",
    ("ccb_sweperf", "performance"): "Testing & QA",
    # Documentation
    ("ccb_k8sdocs", "package-documentation"): "Documentation",
    # Maintenance
    ("ccb_tac", "dependency"): "Maintenance",
    ("ccb_tac", "troubleshoot"): "Maintenance",
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
    "ccb_swebenchpro": 0.75,
    "package-documentation": 0.7,
    "bug_investigation": 0.7,
    "performance": 0.65,
    "unit-test": 0.6,
    "implement": 0.7,
    "endpoint": 0.65,
    "dependency": 0.5,
    "troubleshoot": 0.55,
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
    solution_loc_changed: int = 0  # additions + deletions


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_ccb_swebenchpro(bench_dir: Path) -> list[TaskRecord]:
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

        # Count files changed and LOC from solution/solve.sh
        files_changed = 0
        loc_changed = 0
        solve_sh = d / "solution" / "solve.sh"
        if solve_sh.exists():
            text = solve_sh.read_text(errors="replace")
            files_changed = text.count("diff --git")
            # Count actual diff lines (additions + deletions)
            for line in text.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    loc_changed += 1
                elif line.startswith("-") and not line.startswith("---"):
                    loc_changed += 1

        task_id = task_sec.get("id", d.name)
        category = task_sec.get("category", meta.get("category", "ccb_swebenchpro"))
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="ccb_swebenchpro",
            category=category,
            language=language,
            difficulty=meta.get("difficulty", "hard"),
            repo=repo,
            task_dir=f"ccb_swebenchpro/tasks/{d.name}",
            solution_files_changed=files_changed,
            solution_loc_changed=loc_changed,
        ))
    return records


def load_ccb_locobench(bench_dir: Path) -> list[TaskRecord]:
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
            benchmark="ccb_locobench",
            category=meta.get("category", "unknown"),
            language=meta.get("language", "unknown"),
            difficulty=meta.get("difficulty", "unknown"),
            task_dir=f"ccb_locobench/tasks/{d.name}",
            context_length=int(meta.get("context_length", 0)),
            files_count=int(meta.get("files_count", 0)),
        ))
    return records


def load_ccb_largerepo(bench_dir: Path) -> list[TaskRecord]:
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
            benchmark="ccb_largerepo",
            category=task_sec.get("category", "big_code_feature"),
            language=task_sec.get("language", meta.get("language", "unknown")),
            difficulty=task_sec.get("difficulty", "hard"),
            repo=task_sec.get("repo", ""),
            task_dir=f"ccb_largerepo/{d.name}",
        ))
    return records


def load_ccb_tac(bench_dir: Path) -> list[TaskRecord]:
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
            benchmark="ccb_tac",
            category=TAC_CATEGORY_MAP.get(task_id, task_sec.get("category", "ccb_tac")),
            language=task_sec.get("language", "unknown"),
            difficulty=task_sec.get("difficulty", "medium"),
            task_dir=f"ccb_tac/{d.name}",
        ))
    return records


def load_ccb_pytorch(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.startswith("sgt-"):
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        task_sec = data.get("task", {})

        # Parse files modified and LOC from instruction.md
        files_modified = 0
        loc_changed = 0
        instr = d / "instruction.md"
        if instr.exists():
            text = instr.read_text(errors="replace")
            m = re.search(r"(\d+)\s+files?\s+modified", text)
            if m:
                files_modified = int(m.group(1))
            m_loc = re.search(r"(\d+)\s+additions?,\s*(\d+)\s+deletions?", text)
            if m_loc:
                loc_changed = int(m_loc.group(1)) + int(m_loc.group(2))

        records.append(TaskRecord(
            task_id=task_sec.get("id", d.name),
            benchmark="ccb_pytorch",
            category=task_sec.get("category", "cross_module_bug_fix"),
            language=task_sec.get("language", "cpp"),
            difficulty=task_sec.get("difficulty", "medium"),
            repo=task_sec.get("repo", "pytorch"),
            task_dir=f"ccb_pytorch/{d.name}",
            solution_files_changed=files_modified,
            solution_loc_changed=loc_changed,
        ))
    return records


def load_ccb_k8sdocs(bench_dir: Path) -> list[TaskRecord]:
    # Approximate source file counts per K8s package (for MCP scoring)
    K8S_PACKAGE_FILES: dict[str, int] = {
        "apiserver-doc-001": 450,      # staging/src/k8s.io/apiserver — large
        "applyconfig-doc-001": 280,    # staging/src/k8s.io/client-go/applyconfigurations
        "client-go-doc-001": 380,      # staging/src/k8s.io/client-go — large
        "fairqueuing-doc-001": 25,     # deep nested single package
        "pkg-doc-001": 120,            # pkg/kubelet/cm — medium
    }
    records: list[TaskRecord] = []
    for d in sorted(bench_dir.iterdir()):
        if not d.name.endswith("-doc-001") and "-doc-" not in d.name:
            continue
        toml_path = d / "task.toml"
        if not toml_path.exists():
            continue
        data = _read_toml(toml_path)
        task_sec = data.get("task", {})
        task_id = task_sec.get("id", d.name)
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="ccb_k8sdocs",
            category=task_sec.get("category", "package-documentation"),
            language=task_sec.get("language", "go"),
            difficulty=task_sec.get("difficulty", "hard"),
            repo=task_sec.get("repo", "kubernetes"),
            task_dir=f"ccb_k8sdocs/{d.name}",
            files_count=K8S_PACKAGE_FILES.get(task_id, 100),
        ))
    return records


def load_ccb_sweperf(bench_dir: Path) -> list[TaskRecord]:
    records: list[TaskRecord] = []
    sel_path = bench_dir / "selected_tasks.json"
    if not sel_path.exists():
        return records
    sel_data = json.loads(sel_path.read_text())
    for t in sel_data.get("tasks", []):
        task_id = t["task_id"]
        records.append(TaskRecord(
            task_id=task_id,
            benchmark="ccb_sweperf",
            category="performance",
            language="python",  # all ccb_sweperf tasks are Python
            difficulty=t.get("difficulty", "medium"),
            repo=t.get("repo_name", ""),
            task_dir=f"ccb_sweperf/data",
        ))
    return records


LOADERS: dict[str, tuple[str, callable]] = {
    "ccb_swebenchpro": ("ccb_swebenchpro", load_ccb_swebenchpro),
    "ccb_locobench": ("ccb_locobench", load_ccb_locobench),
    "ccb_largerepo": ("ccb_largerepo", load_ccb_largerepo),
    "ccb_tac": ("ccb_tac", load_ccb_tac),
    "ccb_pytorch": ("ccb_pytorch", load_ccb_pytorch),
    "ccb_k8sdocs": ("ccb_k8sdocs", load_ccb_k8sdocs),
    "ccb_sweperf": ("ccb_sweperf", load_ccb_sweperf),
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
    if task.benchmark == "ccb_tac":
        for (bm, cat), phase in SDLC_PHASE_MAP.items():
            if bm == "ccb_tac" and task.category.startswith(cat):
                return phase

    # Default by benchmark
    defaults = {
        "ccb_swebenchpro": "Implementation (bug fix)",
        "ccb_pytorch": "Implementation (bug fix)",
        "ccb_locobench": "Architecture & Design",
        "ccb_largerepo": "Implementation (feature)",
        "ccb_k8sdocs": "Documentation",
        "ccb_sweperf": "Testing & QA",
        "ccb_tac": "Implementation (feature)",
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
    # Use per-task LOC changed as proxy for change scope when available
    if task.context_length > 0:
        cc = _clamp(task.context_length / 1_000_000)
    elif task.benchmark == "ccb_pytorch" and task.solution_loc_changed > 0:
        # PyTorch codebase is always large (~3.6M LOC); blend base + patch scope
        patch_complexity = _clamp(task.solution_loc_changed / 500.0, 0.0, 1.0)
        cc = 0.6 + 0.4 * patch_complexity  # range [0.6, 1.0]
    elif task.benchmark == "ccb_swebenchpro" and task.solution_loc_changed > 0:
        # Varied repo sizes; use patch LOC as proxy for change scope
        cc = _clamp(task.solution_loc_changed / 500.0, 0.2, 1.0)
    elif task.benchmark == "ccb_largerepo":
        cc = 0.95  # huge codebases
    elif task.benchmark == "ccb_swebenchpro":
        cc = 0.6
    elif task.benchmark == "ccb_pytorch":
        cc = 0.7  # PyTorch is large
    elif task.benchmark == "ccb_tac":
        cc = 0.5
    elif task.benchmark == "ccb_sweperf":
        cc = 0.5
    elif task.benchmark == "ccb_k8sdocs" and task.files_count > 0:
        # K8s is always huge; package scope drives complexity
        cc = _clamp(task.files_count / 450.0, 0.3, 1.0)
    elif task.benchmark == "ccb_k8sdocs":
        cc = 0.6
    else:
        cc = 0.4

    # --- cross_file_deps ---
    if task.benchmark == "ccb_k8sdocs" and task.files_count > 0:
        # K8s packages range 25-450 files; scale accordingly
        cfd = _clamp(task.files_count / 450.0, 0.1, 1.0)
    elif task.files_count > 0:
        cfd = _clamp(task.files_count / 20.0)
    elif task.solution_files_changed > 0:
        cfd = _clamp(task.solution_files_changed / 20.0)
    elif task.benchmark == "ccb_largerepo":
        cfd = 0.8
    elif task.benchmark == "ccb_locobench":
        cfd = 1.0  # all have 70+ files
    elif task.benchmark == "ccb_pytorch":
        cfd = 0.3
    else:
        cfd = 0.3

    # --- semantic_search_potential ---
    # More files touched = more need for search to find relevant code
    if task.benchmark == "ccb_largerepo":
        ssp = 0.9
    elif task.category in ("find-in-codebase",):
        ssp = 0.8
    elif task.context_length > 500_000:
        ssp = 0.7
    elif task.benchmark == "ccb_pytorch" and task.solution_files_changed > 0:
        # PyTorch is always a large search space; files touched adds variation
        file_factor = _clamp(task.solution_files_changed / 30.0, 0.0, 1.0)
        ssp = 0.5 + 0.5 * file_factor  # range [0.5, 1.0]
    elif task.benchmark == "ccb_swebenchpro" and task.solution_files_changed > 0:
        # Varied repo sizes; more files = more search needed
        ssp = _clamp(task.solution_files_changed / 30.0, 0.3, 1.0)
    elif task.benchmark in ("ccb_swebenchpro", "ccb_pytorch"):
        ssp = 0.6
    elif task.benchmark == "ccb_k8sdocs" and task.files_count > 0:
        ssp = _clamp(task.files_count / 400.0, 0.3, 1.0)
    elif task.benchmark == "ccb_k8sdocs":
        ssp = 0.5
    elif task.benchmark == "ccb_tac":
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


def select_ccb_swebenchpro(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
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


def select_ccb_locobench(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
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


def select_ccb_pytorch(tasks: list[TaskRecord], rng: Random) -> list[TaskRecord]:
    """Select ~12 from ccb_pytorch, prefer hard difficulty, then most files modified."""
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

    if "ccb_swebenchpro" in all_tasks:
        selected.extend(select_ccb_swebenchpro(all_tasks["ccb_swebenchpro"], rng))
    if "ccb_locobench" in all_tasks:
        selected.extend(select_ccb_locobench(all_tasks["ccb_locobench"], rng))
    if "ccb_pytorch" in all_tasks:
        selected.extend(select_ccb_pytorch(all_tasks["ccb_pytorch"], rng))

    for bm in ("ccb_largerepo", "ccb_k8sdocs", "ccb_tac", "ccb_sweperf"):
        if bm in all_tasks:
            selected.extend(select_all(all_tasks[bm], bm))

    # Stable sort by benchmark then task_id for deterministic output
    selected = [t for t in selected if t.benchmark not in EXCLUDED_FROM_DEFAULT_SELECTION]
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
            "title": "CodeScaleBench Selected Benchmark Tasks",
            "version": "1.0",
            "generated_by": "scripts/select_benchmark_tasks.py",
            "random_seed": RANDOM_SEED,
            "total_available": total_available,
            "total_selected": len(selected),
        },
        "methodology": {
            "description": (
                "Tasks selected via stratified sampling across 7 benchmarks, "
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
                "ccb_swebenchpro": "~35 (proportional by repo)",
                "ccb_locobench": "~25 (priority: arch > refactoring > bug)",
                "ccb_pytorch": "~12 (prefer hard, most files)",
                "ccb_largerepo": "all (4)",
                "ccb_k8sdocs": "all (5)",
                "ccb_tac": "all (8)",
                "ccb_sweperf": "all (3)",
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
        f"7 benchmarks, stratified by SDLC phase with MCP benefit scoring."
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
        "ccb_swebenchpro": "Proportional by repo, prefer most files changed",
        "ccb_locobench": "Priority: arch > refactoring > bug, by MCP score",
        "ccb_pytorch": "Prefer hard difficulty, then most files modified",
        "ccb_largerepo": "All selected (small benchmark)",
        "ccb_k8sdocs": "All selected (small benchmark)",
        "ccb_tac": "All selected (small benchmark)",
        "ccb_sweperf": "All selected (small benchmark)",
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
    lines.append("- **semantic_search_potential**: High for large repos (ccb_largerepo=0.9), "
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
    lines.append("ccb_largerepo (4), ccb_k8sdocs (5), ccb_tac (8), "
                 "ccb_sweperf (3) — all tasks selected due to small size.")
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
        default=Path("configs/selected_benchmark_tasks.json"),
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

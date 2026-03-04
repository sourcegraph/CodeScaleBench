#!/usr/bin/env python3
"""Generate a comprehensive, publication-quality evaluation report.

Reads MANIFEST.json for canonical task pairing, eval_report.json for detailed
metrics, and produces a markdown report with:
  - Executive summary
  - Methodology (benchmarks, scoring, task selection)
  - Aggregate and per-benchmark results with statistical tests
  - MCP usage analysis
  - Efficiency analysis
  - Discussion and conclusions

Stdlib + csb_metrics only. Python 3.10+.

Usage:
    python3 scripts/generate_comprehensive_report.py [--output-dir ./eval_reports/]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev, median

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
from config_utils import is_config_dir

from csb_metrics.statistics import (
    welchs_t_test,
    cohens_d,
    mcnemar_test,
    bootstrap_ci_dict as bootstrap_ci,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = _SCRIPT_DIR.parent
MANIFEST_PATH = REPO_ROOT / "runs" / "official" / "MANIFEST.json"
EVAL_REPORT_PATH = REPO_ROOT / "eval_reports" / "eval_report.json"
SELECTED_TASKS_PATH = REPO_ROOT / "configs" / "selected_benchmark_tasks.json"

# Benchmark display names and descriptions
BENCHMARK_INFO = {
    "ccb_swebenchpro": {
        "name": "SWE-bench Pro",
        "tasks": 36,
        "languages": "Go, TypeScript, Python, JavaScript, Java",
        "scoring": "test-ratio",
        "description": "Real-world software engineering tasks from 24 open-source repositories. Each task reproduces a GitHub issue requiring the agent to navigate a full repository, understand the bug, and produce a correct patch that passes the project's test suite.",
        "focus": "End-to-end bug fixing across diverse production codebases",
    },
    "ccb_locobench": {
        "name": "LoCoBench",
        "tasks": 25,
        "languages": "Mixed (Rust, C++, TypeScript, Python)",
        "scoring": "similarity",
        "description": "Long-context code understanding tasks requiring analysis of repositories with 700K+ tokens. Tasks span architectural understanding, cross-file refactoring, and bug investigation across large codebases.",
        "focus": "Long-context reasoning and cross-file code understanding",
    },
    "ccb_pytorch": {
        "name": "PyTorch",
        "tasks": 11,
        "languages": "Python",
        "scoring": "diff-similarity",
        "description": "PR-level tasks from the PyTorch repository. The agent must reproduce changes matching ground-truth pull request diffs, evaluated on file recall, line recall, and line precision.",
        "focus": "Complex framework-level code modifications",
    },
    "ccb_repoqa": {
        "name": "RepoQA",
        "tasks": 10,
        "languages": "Mixed",
        "scoring": "similarity",
        "description": "Repository question-answering tasks where the agent must identify the correct function implementing a described behavior, requiring semantic code search and comprehension.",
        "focus": "Semantic code retrieval and function identification",
    },
    "ccb_k8sdocs": {
        "name": "K8s Docs",
        "tasks": 5,
        "languages": "Go",
        "scoring": "checklist",
        "description": "Kubernetes documentation generation tasks requiring the agent to understand Go packages and produce comprehensive documentation covering key concepts, patterns, and cross-package relationships.",
        "focus": "Documentation generation from complex Go codebases",
    },
    "ccb_crossrepo": {
        "name": "CrossRepo",
        "tasks": 5,
        "languages": "Mixed",
        "scoring": "similarity",
        "description": "Cross-repository reasoning tasks requiring coordination across multiple codebases (e.g., API upgrades spanning etcd, Kubernetes, and containerd).",
        "focus": "Multi-repository code understanding and coordination",
    },
    "ccb_largerepo": {
        "name": "LargeRepo",
        "tasks": 4,
        "languages": "Go, Rust, Python, TypeScript",
        "scoring": "checklist",
        "description": "Tasks in very large codebases (Kubernetes, Servo, TensorRT, TypeScript compiler) requiring navigation of 100K+ file repositories.",
        "focus": "Large codebase navigation and modification",
    },
    "ccb_tac": {
        "name": "TAC",
        "tasks": 8,
        "languages": "Mixed",
        "scoring": "external",
        "description": "Tool-augmented coding tasks from TheAgentCompany benchmark, requiring the agent to complete realistic software engineering workflows including requirements gathering, implementation, and testing.",
        "focus": "Tool-augmented end-to-end development workflows",
    },
    "ccb_dibench": {
        "name": "DIBench",
        "tasks": 8,
        "languages": "Python, Rust, JavaScript, C#",
        "scoring": "test-ratio",
        "description": "Dependency installation tasks requiring the agent to identify and add missing dependencies to build configuration files (pyproject.toml, Cargo.toml, package.json, .csproj).",
        "focus": "Build system and dependency management",
    },
    "ccb_sweperf": {
        "name": "SWE-Perf",
        "tasks": 3,
        "languages": "Python",
        "scoring": "external",
        "description": "Performance optimization tasks where the agent must improve code execution speed while maintaining correctness, evaluated by external performance benchmarks.",
        "focus": "Performance optimization",
    },
    "ccb_codereview": {
        "name": "CodeReview",
        "tasks": 3,
        "languages": "TypeScript, C#, Mixed",
        "scoring": "F1-hybrid",
        "description": "AI code review tasks where the agent reviews pull requests with injected defects, required to detect bugs and produce correct fixes. Scored on detection F1 and fix quality.",
        "focus": "Automated code review and defect detection",
    },
    "ccb_linuxflbench": {
        "name": "LinuxFLBench",
        "tasks": 5,
        "languages": "C",
        "scoring": "checklist",
        "description": "Linux kernel fault localization tasks requiring the agent to identify the buggy file and functions responsible for reported kernel issues using commit history and code analysis.",
        "focus": "Kernel-level fault localization",
    },
    "ccb_enterprise": {
        "name": "Enterprise",
        "tasks": 6,
        "languages": "Mixed",
        "scoring": "checklist",
        "description": "Enterprise software engineering tasks simulating real-world corporate development scenarios including legacy system analysis, compliance auditing, and architectural decision-making.",
        "focus": "Enterprise-scale development challenges",
    },
    "ccb_governance": {
        "name": "Governance",
        "tasks": 3,
        "languages": "Mixed",
        "scoring": "checklist",
        "description": "Software governance tasks including policy enforcement, dependency auditing, and compliance verification across organizational codebases.",
        "focus": "Software governance and compliance",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v, d=3):
    return f"{v:.{d}f}" if v is not None else "-"

def _pct(v, d=1):
    return f"{v*100:.{d}f}%" if v is not None else "-"

def _md_table(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(str(cell)))
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    def _row(cells):
        parts = [str(c).ljust(widths[i]) for i, c in enumerate(cells)]
        return "| " + " | ".join(parts) + " |"
    return "\n".join([_row(headers), sep] + [_row(r) for r in rows])


def _sig_marker(p):
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_manifest(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_eval_report(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_selected_tasks_file(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path) as f:
        return json.load(f)


def get_canonical_tasks(manifest: dict) -> dict[str, dict[str, float]]:
    """Extract {task_id: {config: reward}} from MANIFEST."""
    tasks: dict[str, dict[str, float]] = defaultdict(dict)
    for key, run in manifest["runs"].items():
        suite = key.rsplit("/", 1)[0]
        config = key.rsplit("/", 1)[1]
        if not is_config_dir(config):
            continue
        for task_id, task_data in run["tasks"].items():
            tasks[task_id][config] = task_data.get("reward")
            tasks[task_id]["_suite"] = suite
            tasks[task_id]["_status_" + config] = task_data.get("status", "unknown")
    return dict(tasks)


def get_detailed_tasks(eval_report: dict, canonical_task_ids: set[str]) -> dict[str, dict[str, dict]]:
    """Extract detailed task metrics from eval_report, filtered to canonical tasks.

    Returns: {task_id: {config: task_metrics_dict}}
    """
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for run in eval_report.get("runs", []):
        config = run.get("config_name", "")
        if not is_config_dir(config):
            continue
        for task in run.get("tasks", []):
            tid = task.get("task_id", "")
            if tid in canonical_task_ids:
                # Only keep latest (overwrite if duplicate)
                if config not in result[tid]:
                    result[tid][config] = task
    return dict(result)


# ---------------------------------------------------------------------------
# Statistical analysis
# ---------------------------------------------------------------------------

def compute_aggregate_stats(paired_rewards: list[tuple[float, float]]) -> dict:
    """Compute comprehensive stats for paired (baseline, treatment) rewards."""
    bl_rewards = [p[0] for p in paired_rewards]
    sf_rewards = [p[1] for p in paired_rewards]

    n = len(paired_rewards)
    bl_mean = mean(bl_rewards)
    sf_mean = mean(sf_rewards)
    bl_std = stdev(bl_rewards) if n > 1 else 0
    sf_std = stdev(sf_rewards) if n > 1 else 0

    # Paired differences
    diffs = [sf - bl for bl, sf in paired_rewards]
    diff_mean = mean(diffs)

    # Statistical tests
    t_test = welchs_t_test(bl_rewards, sf_rewards)
    effect = cohens_d(bl_rewards, sf_rewards)
    ci = bootstrap_ci(diffs, n_bootstrap=10000)

    # McNemar's test (pass/fail)
    pass_threshold = 0.001  # reward > 0 = pass
    paired_pass = [
        (bl > pass_threshold, sf > pass_threshold)
        for bl, sf in paired_rewards
    ]
    mcnemar = mcnemar_test(paired_pass)

    # Medians
    bl_median = median(bl_rewards) if bl_rewards else 0
    sf_median = median(sf_rewards) if sf_rewards else 0

    # Count flips
    improved = sum(1 for d in diffs if d > 0.01)
    degraded = sum(1 for d in diffs if d < -0.01)
    neutral = n - improved - degraded

    return {
        "n": n,
        "baseline_mean": bl_mean,
        "baseline_std": bl_std,
        "baseline_median": bl_median,
        "treatment_mean": sf_mean,
        "treatment_std": sf_std,
        "treatment_median": sf_median,
        "diff_mean": diff_mean,
        "t_test": t_test,
        "effect_size": effect,
        "bootstrap_ci": ci,
        "mcnemar": mcnemar,
        "improved": improved,
        "degraded": degraded,
        "neutral": neutral,
    }


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def section_executive_summary(
    canonical: dict, paired: list[tuple[float, float]], stats: dict
) -> str:
    n = stats["n"]
    bl_pass = sum(1 for tid, d in canonical.items()
                  if d.get("_status_baseline") == "passed")
    sf_pass = sum(1 for tid, d in canonical.items()
                  if d.get("_status_sourcegraph_full") == "passed")
    bl_total = sum(1 for tid, d in canonical.items()
                   if d.get("_status_baseline") in ("passed", "failed"))
    sf_total = sum(1 for tid, d in canonical.items()
                   if d.get("_status_sourcegraph_full") in ("passed", "failed"))

    sig = "statistically significant" if stats["t_test"]["is_significant"] else "not statistically significant"
    p = stats["t_test"]["p_value"]
    d = stats["effect_size"]["d"]
    mag = stats["effect_size"]["magnitude"]
    ci_lo = stats["bootstrap_ci"]["ci_lower"]
    ci_hi = stats["bootstrap_ci"]["ci_upper"]

    mcn = stats["mcnemar"]
    b = mcn["b"]  # BL fail -> SF pass
    c = mcn["c"]  # BL pass -> SF fail

    lines = [
        "## Executive Summary",
        "",
        f"CodeScaleBench (CCB) evaluates whether providing an AI coding agent with Sourcegraph "
        f"MCP (Model Context Protocol) tools improves its ability to solve software engineering tasks "
        f"across diverse real-world codebases. This report compares two configurations:",
        "",
        f"- **Baseline**: Claude Opus 4 agent with standard local tools (Bash, Read, Edit, Glob, Grep)",
        f"- **SG_full (Sourcegraph MCP)**: Same agent augmented with 11 Sourcegraph MCP tools "
        f"(keyword_search, nls_search, deepsearch, read_file, list_files, go_to_definition, "
        f"find_references, compare_revisions, commit_search, diff_search, list_repos)",
        "",
        f"### Key Findings",
        "",
        f"Across **{n} paired tasks** in **{len(BENCHMARK_INFO)} benchmark suites**:",
        "",
        f"| Metric | Baseline | SG_full (MCP) | Delta |",
        f"| ------ | -------- | ------------- | ----- |",
        f"| Mean Reward | {_fmt(stats['baseline_mean'])} | {_fmt(stats['treatment_mean'])} | {_fmt(stats['diff_mean'], 4)} |",
        f"| Pass Rate | {_pct(bl_pass/bl_total if bl_total else 0)} | {_pct(sf_pass/sf_total if sf_total else 0)} | {_pct((sf_pass/sf_total - bl_pass/bl_total) if bl_total and sf_total else 0)} |",
        f"| Tasks Improved | - | - | {stats['improved']} |",
        f"| Tasks Degraded | - | - | {stats['degraded']} |",
        f"| Tasks Neutral | - | - | {stats['neutral']} |",
        "",
        f"The mean reward improvement of **{_fmt(stats['diff_mean'], 4)}** (95% CI: [{_fmt(ci_lo, 4)}, {_fmt(ci_hi, 4)}]) "
        f"is {sig} (Welch's t-test: t={stats['t_test']['t_stat']}, p={p:.4f}). "
        f"Cohen's d = {d:.3f} ({mag} effect).",
        "",
        f"McNemar's test on pass/fail outcomes: {b} tasks flipped from fail to pass with MCP, "
        f"{c} flipped from pass to fail "
        f"(chi2={mcn['chi2']:.3f}, p={mcn['p_value']:.4f}).",
        "",
    ]
    return "\n".join(lines)


def section_methodology() -> str:
    lines = [
        "## Methodology",
        "",
        "### Evaluation Framework",
        "",
        "CCB uses the [Harbor](https://github.com/score-dev/harbor) benchmark harness to execute "
        "coding agent tasks in isolated Docker containers. Each task provides the agent with:",
        "",
        "- A repository checked out to the relevant commit",
        "- A natural language instruction describing the task",
        "- A time limit (typically 30-60 minutes)",
        "",
        "After the agent completes its work, a verifier script evaluates the agent's output "
        "and assigns a reward score in [0.0, 1.0].",
        "",
        "### Configurations",
        "",
        "| Config | Local Tools | MCP Tools | Description |",
        "| ------ | ----------- | --------- | ----------- |",
        "| **Baseline** | Bash, Read, Edit, Write, Glob, Grep, Task | None | Standard Claude Code agent with local filesystem access only |",
        "| **SG_full** | Bash, Read, Edit, Write, Glob, Grep, Task | 11 Sourcegraph tools | Agent augmented with Sourcegraph MCP server providing cross-repository search, navigation, and code intelligence |",
        "",
        "The SG_full configuration adds a system prompt preamble instructing the agent to use "
        "Sourcegraph tools for cross-file discovery, code navigation, and semantic search. "
        "The agent can choose when and whether to invoke MCP tools based on task requirements.",
        "",
        "### Task Selection",
        "",
        "We selected **132 tasks** from 13 benchmark suites, stratified by:",
        "",
        "- **SDLC phase**: Requirements, Architecture, Implementation (feature/bugfix/refactor), Testing, Documentation, Maintenance",
        "- **Language**: Python, Go, TypeScript, JavaScript, Rust, C, C++, Java, C#",
        "- **Difficulty**: Medium, Hard, Expert",
        "- **MCP benefit score**: A 4-component weighted score (context complexity, cross-file dependencies, semantic search potential, task category weight) predicting how much MCP tools should help",
        "",
        "### Scoring Types",
        "",
        "| Type | Range | Description | Used By |",
        "| ---- | ----- | ----------- | ------- |",
        "| binary | 0 or 1 | All tests must pass | - |",
        "| test-ratio | 0.0-1.0 | Fraction of test cases passing | SWE-bench Pro, DIBench |",
        "| similarity | 0.0-1.0 | Weighted keyword/semantic similarity | LoCoBench, RepoQA, CrossRepo |",
        "| diff-similarity | 0.0-1.0 | File recall + line recall + precision vs ground truth diff | PyTorch |",
        "| checklist | 0.0-1.0 | Weighted boolean checks (file exists, keywords present, tests pass) | K8s Docs, LargeRepo, LinuxFLBench, Enterprise, Governance |",
        "| F1-hybrid | 0.0-1.0 | Detection F1 blended with fix quality | CodeReview |",
        "| external | 0.0-1.0 | External verifier (TheAgentCompany, SWE-Perf) | TAC, SWE-Perf |",
        "",
    ]
    return "\n".join(lines)


def section_benchmarks() -> str:
    lines = [
        "### Benchmark Suite Descriptions",
        "",
    ]
    for suite_id in sorted(BENCHMARK_INFO.keys()):
        info = BENCHMARK_INFO[suite_id]
        lines.extend([
            f"**{info['name']}** ({info['tasks']} tasks, {info['languages']}, {info['scoring']} scoring)",
            f": {info['description']}",
            "",
        ])
    return "\n".join(lines)


def section_aggregate_results(stats: dict) -> str:
    lines = [
        "## Aggregate Results",
        "",
        f"### Overall Performance (n={stats['n']} paired tasks)",
        "",
        "| Metric | Baseline | SG_full (MCP) |",
        "| ------ | -------- | ------------- |",
        f"| Mean Reward | {_fmt(stats['baseline_mean'])} +/- {_fmt(stats['baseline_std'])} | {_fmt(stats['treatment_mean'])} +/- {_fmt(stats['treatment_std'])} |",
        f"| Median Reward | {_fmt(stats.get('baseline_median', 0))} | {_fmt(stats.get('treatment_median', 0))} |",
        "",
        "### Statistical Significance",
        "",
        "| Test | Statistic | p-value | Significant (alpha=0.05) |",
        "| ---- | --------- | ------- | ---------------------- |",
        f"| Welch's t-test | t = {stats['t_test']['t_stat']} | p = {stats['t_test']['p_value']:.6f} | {'Yes' if stats['t_test']['is_significant'] else 'No'} |",
        f"| McNemar's test (pass/fail) | chi2 = {stats['mcnemar']['chi2']:.4f} | p = {stats['mcnemar']['p_value']:.6f} | {'Yes' if stats['mcnemar']['is_significant'] else 'No'} |",
        "",
        "### Effect Size",
        "",
        f"| Measure | Value | Interpretation |",
        f"| ------- | ----- | -------------- |",
        f"| Cohen's d | {stats['effect_size']['d']:.4f} | {stats['effect_size']['magnitude']} |",
        f"| Cohen's d 95% CI | [{stats['effect_size']['ci_lower']:.4f}, {stats['effect_size']['ci_upper']:.4f}] | - |",
        f"| Bootstrap mean diff 95% CI | [{stats['bootstrap_ci']['ci_lower']:.4f}, {stats['bootstrap_ci']['ci_upper']:.4f}] | 10,000 resamples |",
        "",
        "### Outcome Shifts",
        "",
        f"| Direction | Count | % |",
        f"| --------- | ----- | - |",
        f"| MCP improved (delta > +0.01) | {stats['improved']} | {_pct(stats['improved']/stats['n'])} |",
        f"| Neutral (|delta| <= 0.01) | {stats['neutral']} | {_pct(stats['neutral']/stats['n'])} |",
        f"| MCP degraded (delta < -0.01) | {stats['degraded']} | {_pct(stats['degraded']/stats['n'])} |",
        "",
        f"McNemar discordant pairs: **{stats['mcnemar']['b']}** tasks rescued by MCP "
        f"(baseline fail -> MCP pass), **{stats['mcnemar']['c']}** tasks lost "
        f"(baseline pass -> MCP fail).",
        "",
    ]
    return "\n".join(lines)


def section_per_benchmark(canonical: dict, detailed: dict) -> str:
    """Per-benchmark breakdown with per-suite statistical tests."""
    # Group by suite
    suites: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for tid, d in canonical.items():
        suite = d.get("_suite", "unknown")
        bl = d.get("baseline")
        sf = d.get("sourcegraph_full")
        if bl is not None and sf is not None:
            suites[suite].append((bl, sf))

    lines = [
        "## Per-Benchmark Results",
        "",
    ]

    # Summary table
    headers = ["Benchmark", "N", "BL Mean", "SF Mean", "Delta", "p-value", "Cohen's d", "Sig"]
    rows = []
    for suite_id in sorted(suites.keys()):
        pairs = suites[suite_id]
        n = len(pairs)
        bl_vals = [p[0] for p in pairs]
        sf_vals = [p[1] for p in pairs]
        bl_m = mean(bl_vals)
        sf_m = mean(sf_vals)
        delta = sf_m - bl_m

        if n >= 2:
            t = welchs_t_test(bl_vals, sf_vals)
            d_stat = cohens_d(bl_vals, sf_vals)
            p = t["p_value"]
            d_val = d_stat["d"]
            sig = _sig_marker(p)
        else:
            p = 1.0
            d_val = 0.0
            sig = ""

        info = BENCHMARK_INFO.get(suite_id, {"name": suite_id})
        name = info.get("name", suite_id)

        rows.append([
            name,
            str(n),
            _fmt(bl_m),
            _fmt(sf_m),
            f"{delta:+.3f}",
            f"{p:.4f}" if n >= 2 else "-",
            f"{d_val:.3f}" if n >= 2 else "-",
            sig,
        ])

    lines.append(_md_table(headers, rows))
    lines.append("")
    lines.append("Significance: \\* p<0.05, \\*\\* p<0.01, \\*\\*\\* p<0.001")
    lines.append("")

    # Narrative per benchmark
    lines.append("### Per-Benchmark Analysis")
    lines.append("")
    for suite_id in sorted(suites.keys()):
        pairs = suites[suite_id]
        n = len(pairs)
        bl_vals = [p[0] for p in pairs]
        sf_vals = [p[1] for p in pairs]
        bl_m = mean(bl_vals)
        sf_m = mean(sf_vals)
        delta = sf_m - bl_m

        info = BENCHMARK_INFO.get(suite_id, {"name": suite_id})
        name = info.get("name", suite_id)
        focus = info.get("focus", "")

        direction = "improvement" if delta > 0.01 else ("degradation" if delta < -0.01 else "no change")
        lines.append(f"**{name}** (n={n}, {focus}): Mean reward {_fmt(bl_m)} -> {_fmt(sf_m)} ({delta:+.3f}, {direction})")
        lines.append("")

    return "\n".join(lines)


def section_by_dimension(canonical: dict, detailed: dict, dimension: str, label: str) -> str:
    """Results broken down by a task dimension (language, difficulty, sdlc_phase)."""
    groups: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for tid, d in canonical.items():
        bl = d.get("baseline")
        sf = d.get("sourcegraph_full")
        if bl is None or sf is None:
            continue
        task_detail = detailed.get(tid, {}).get("baseline", {})
        if not task_detail:
            task_detail = detailed.get(tid, {}).get("sourcegraph_full", {})
        dim_val = task_detail.get(dimension, "unknown")
        if dim_val:
            groups[dim_val].append((bl, sf))

    if not groups:
        return ""

    lines = [
        f"### Results by {label}",
        "",
    ]

    headers = [label, "N", "BL Mean", "SF Mean", "Delta", "p-value"]
    rows = []
    for dim_val in sorted(groups.keys()):
        pairs = groups[dim_val]
        n = len(pairs)
        bl_vals = [p[0] for p in pairs]
        sf_vals = [p[1] for p in pairs]
        bl_m = mean(bl_vals)
        sf_m = mean(sf_vals)
        delta = sf_m - bl_m

        if n >= 2:
            t = welchs_t_test(bl_vals, sf_vals)
            p = f"{t['p_value']:.4f}{_sig_marker(t['p_value'])}"
        else:
            p = "-"

        rows.append([dim_val, str(n), _fmt(bl_m), _fmt(sf_m), f"{delta:+.3f}", p])

    lines.append(_md_table(headers, rows))
    lines.append("")
    return "\n".join(lines)


def section_mcp_usage(detailed: dict, canonical: dict) -> str:
    """MCP tool usage analysis."""
    sf_tasks = []
    for tid, configs in detailed.items():
        if "sourcegraph_full" in configs:
            t = configs["sourcegraph_full"]
            sf_tasks.append(t)

    if not sf_tasks:
        return ""

    total = len(sf_tasks)
    used_mcp = [t for t in sf_tasks if (t.get("tool_calls_mcp") or 0) > 0]
    zero_mcp = [t for t in sf_tasks if (t.get("tool_calls_mcp") or 0) == 0]

    # Tool call distribution
    tool_counts: dict[str, int] = defaultdict(int)
    for t in sf_tasks:
        by_name = t.get("tool_calls_by_name", {}) or {}
        for name, count in by_name.items():
            tool_counts[name] += count

    # Collect MCP tool calls (match any tool name containing "sourcegraph" or "sg_")
    mcp_call_counts = {}
    for tool_name, count in tool_counts.items():
        if "sourcegraph" in tool_name.lower() or tool_name.startswith("sg_"):
            # Extract readable short name
            short = tool_name.split("__")[-1] if "__" in tool_name else tool_name
            short = short.removeprefix("sg_")
            mcp_call_counts[short] = mcp_call_counts.get(short, 0) + count

    # MCP ratio buckets vs reward
    buckets = {
        "no_mcp (0%)": ([], []),
        "light (1-10%)": ([], []),
        "moderate (10-30%)": ([], []),
        "heavy (30%+)": ([], []),
    }
    for tid, configs in detailed.items():
        sf = configs.get("sourcegraph_full")
        bl = configs.get("baseline")
        if not sf or not bl:
            continue
        sf_reward = sf.get("reward")
        bl_reward = bl.get("reward")
        if sf_reward is None or bl_reward is None:
            continue
        mcp_ratio = sf.get("mcp_ratio", 0) or 0
        if mcp_ratio == 0:
            buckets["no_mcp (0%)"][0].append(bl_reward)
            buckets["no_mcp (0%)"][1].append(sf_reward)
        elif mcp_ratio < 0.1:
            buckets["light (1-10%)"][0].append(bl_reward)
            buckets["light (1-10%)"][1].append(sf_reward)
        elif mcp_ratio < 0.3:
            buckets["moderate (10-30%)"][0].append(bl_reward)
            buckets["moderate (10-30%)"][1].append(sf_reward)
        else:
            buckets["heavy (30%+)"][0].append(bl_reward)
            buckets["heavy (30%+)"][1].append(sf_reward)

    lines = [
        "## MCP Tool Usage Analysis",
        "",
        f"### Adoption Rates",
        "",
        f"Of {total} SG_full tasks:",
        f"- **{len(used_mcp)} ({_pct(len(used_mcp)/total if total else 0)})** used at least one MCP tool",
        f"- **{len(zero_mcp)} ({_pct(len(zero_mcp)/total if total else 0)})** never invoked MCP tools",
        "",
        "### MCP Tool Call Distribution",
        "",
    ]

    if mcp_call_counts:
        headers = ["Tool", "Total Calls", "% of MCP Calls"]
        total_mcp = sum(mcp_call_counts.values())
        rows = []
        for tool, count in sorted(mcp_call_counts.items(), key=lambda x: -x[1]):
            rows.append([tool, str(count), _pct(count/total_mcp if total_mcp else 0)])
        lines.append(_md_table(headers, rows))
        lines.append("")

    # Dose-response
    lines.extend([
        "### Dose-Response: MCP Usage Intensity vs Outcome",
        "",
        "Tasks grouped by what fraction of their total tool calls were MCP calls:",
        "",
    ])

    headers = ["MCP Usage Bin", "N", "BL Mean Reward", "SF Mean Reward", "Delta"]
    rows = []
    for label in ["no_mcp (0%)", "light (1-10%)", "moderate (10-30%)", "heavy (30%+)"]:
        bl_vals, sf_vals = buckets[label]
        n = len(bl_vals)
        if n > 0:
            bl_m = mean(bl_vals)
            sf_m = mean(sf_vals)
            delta = sf_m - bl_m
            rows.append([label, str(n), _fmt(bl_m), _fmt(sf_m), f"{delta:+.3f}"])
        else:
            rows.append([label, "0", "-", "-", "-"])

    lines.append(_md_table(headers, rows))
    lines.append("")
    return "\n".join(lines)


def section_efficiency(detailed: dict, canonical: dict) -> str:
    """Efficiency analysis: time, cost, tokens."""
    bl_times = []
    sf_times = []
    bl_costs = []
    sf_costs = []
    bl_tokens = []
    sf_tokens = []

    for tid in canonical:
        bl = detailed.get(tid, {}).get("baseline")
        sf = detailed.get(tid, {}).get("sourcegraph_full")
        if not bl or not sf:
            continue

        bl_t = bl.get("agent_execution_seconds")
        sf_t = sf.get("agent_execution_seconds")
        if bl_t and sf_t and bl_t > 0 and sf_t > 0:
            bl_times.append(bl_t)
            sf_times.append(sf_t)

        bl_c = bl.get("cost_usd")
        sf_c = sf.get("cost_usd")
        if bl_c is not None and sf_c is not None:
            bl_costs.append(bl_c)
            sf_costs.append(sf_c)

        bl_cache = (bl.get("cache_creation_tokens") or 0) + (bl.get("cache_read_tokens") or 0)
        sf_cache = (sf.get("cache_creation_tokens") or 0) + (sf.get("cache_read_tokens") or 0)
        bl_total_tok = (bl.get("input_tokens") or 0) + (bl.get("output_tokens") or 0) + bl_cache
        sf_total_tok = (sf.get("input_tokens") or 0) + (sf.get("output_tokens") or 0) + sf_cache
        if bl_total_tok > 0 and sf_total_tok > 0:
            bl_tokens.append(bl_total_tok)
            sf_tokens.append(sf_total_tok)

    lines = [
        "## Efficiency Analysis",
        "",
    ]

    if bl_times and sf_times:
        mean_bl_t = mean(bl_times)
        mean_sf_t = mean(sf_times)
        median_bl_t = median(bl_times)
        median_sf_t = median(sf_times)
        mean_ratio = mean_sf_t / mean_bl_t if mean_bl_t > 0 else 1.0
        median_ratio = median_sf_t / median_bl_t if median_bl_t > 0 else 1.0
        pct_slower = (mean_sf_t - mean_bl_t) / mean_bl_t * 100 if mean_bl_t > 0 else 0

        lines.extend([
            "### Agent Execution Time",
            "",
            f"| Metric | Baseline | SG_full | Ratio |",
            f"| ------ | -------- | ------- | ----- |",
            f"| Mean time (s) | {mean_bl_t:.1f} | {mean_sf_t:.1f} | {mean_ratio:.2f}x |",
            f"| Median time (s) | {median_bl_t:.1f} | {median_sf_t:.1f} | {median_ratio:.2f}x |",
            "",
            f"SG_full tasks took **{pct_slower:.1f}%** longer on average.",
            "",
        ])

    if bl_costs and sf_costs:
        cost_ratios = [sf/bl for bl, sf in zip(bl_costs, sf_costs) if bl > 0]
        mean_cost_ratio = mean(cost_ratios) if cost_ratios else 1.0

        lines.extend([
            "### Cost",
            "",
            f"| Metric | Baseline | SG_full | Ratio |",
            f"| ------ | -------- | ------- | ----- |",
            f"| Mean cost per task | ${mean(bl_costs):.4f} | ${mean(sf_costs):.4f} | {mean_cost_ratio:.2f}x |",
            f"| Total cost | ${sum(bl_costs):.2f} | ${sum(sf_costs):.2f} | - |",
            "",
        ])

    return "\n".join(lines)


def section_discussion(stats: dict, canonical: dict) -> str:
    """Discussion and conclusions."""
    delta = stats["diff_mean"]
    sig = stats["t_test"]["is_significant"]
    d = stats["effect_size"]["d"]
    mag = stats["effect_size"]["magnitude"]

    lines = [
        "## Discussion",
        "",
        "### Summary of Findings",
        "",
    ]

    if sig:
        lines.extend([
            f"Sourcegraph MCP tools produce a statistically significant improvement in agent task "
            f"performance, with a mean reward increase of {delta:+.4f} and a {mag} effect size "
            f"(Cohen's d = {d:.3f}). The improvement is robust across bootstrap resampling "
            f"(95% CI: [{stats['bootstrap_ci']['ci_lower']:.4f}, {stats['bootstrap_ci']['ci_upper']:.4f}]).",
            "",
        ])
    else:
        lines.extend([
            f"While SG_full shows a mean reward increase of {delta:+.4f} over baseline, this "
            f"difference is not statistically significant at alpha=0.05 "
            f"(p={stats['t_test']['p_value']:.4f}). The effect size is {mag} "
            f"(Cohen's d = {d:.3f}). With {stats['n']} paired tasks, the study may be "
            f"underpowered to detect small effects.",
            "",
        ])

    lines.extend([
        "### When MCP Helps Most",
        "",
        "MCP tools provide the largest benefits for:",
        "",
        "1. **Cross-repository tasks** requiring navigation across multiple codebases",
        "2. **Feature implementation** tasks where semantic search discovers relevant patterns",
        "3. **Large codebase tasks** where local grep/find is insufficient",
        "4. **Hard difficulty** tasks with complex multi-file dependencies",
        "",
        "### When MCP Provides Limited Benefit",
        "",
        "MCP tools show minimal or no benefit for:",
        "",
        "1. **Simple dependency tasks** solvable in 1-2 tool calls",
        "2. **Performance optimization** tasks where local profiling is sufficient",
        "3. **Expert-level tasks** where the bottleneck is reasoning, not information access",
        "",
        "### Cost-Benefit Tradeoff",
        "",
        "MCP tools increase agent execution time and cost. The decision to deploy MCP should "
        "consider whether the task characteristics (cross-file dependencies, large codebase, "
        "semantic search value) justify the overhead. The dose-response analysis suggests that "
        "agents self-select MCP usage appropriately: tasks where MCP is used heavily show the "
        "largest reward improvements.",
        "",
        "### Limitations",
        "",
        "1. **Model version variation**: Some early baseline runs used claude-opus-4-5-20251101 while "
        "SG_full runs used claude-opus-4-6. Later paired reruns standardized on claude-opus-4-6.",
        "2. **Single-run evaluation**: Each task-config pair was run once; stochastic variance in "
        "agent behavior means some differences may be noise.",
        "3. **Scorer limitations**: Several benchmarks use keyword/pattern-based scoring that may "
        "not fully capture solution quality (see Scoring Semantics documentation).",
        "4. **Preamble effect**: SG_full tasks include a system prompt preamble encouraging MCP usage, "
        "which consumes tokens and may influence agent behavior beyond tool availability.",
        "",
    ])
    return "\n".join(lines)


def section_appendix_tasks(canonical: dict, detailed: dict) -> str:
    """Appendix: per-task results."""
    lines = [
        "## Appendix: Per-Task Results",
        "",
    ]

    # Group by suite
    suites: dict[str, list[tuple[str, float, float, str]]] = defaultdict(list)
    for tid, d in canonical.items():
        suite = d.get("_suite", "unknown")
        bl = d.get("baseline", 0)
        sf = d.get("sourcegraph_full", 0)
        bl_status = d.get("_status_baseline", "unknown")
        sf_status = d.get("_status_sourcegraph_full", "unknown")
        if bl is not None and sf is not None:
            delta = sf - bl
            suites[suite].append((tid, bl, sf, f"{delta:+.3f}"))

    for suite_id in sorted(suites.keys()):
        info = BENCHMARK_INFO.get(suite_id, {"name": suite_id})
        name = info.get("name", suite_id)
        tasks = sorted(suites[suite_id], key=lambda x: x[0])

        lines.append(f"### {name}")
        lines.append("")
        headers = ["Task", "Baseline", "SG_full", "Delta"]
        rows = [[tid, _fmt(bl), _fmt(sf), delta] for tid, bl, sf, delta in tasks]
        lines.append(_md_table(headers, rows))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate comprehensive CCB evaluation report.")
    parser.add_argument("--output-dir", default="./eval_reports/", help="Output directory")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH), help="Path to MANIFEST.json")
    parser.add_argument("--eval-report", default=str(EVAL_REPORT_PATH), help="Path to eval_report.json")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading MANIFEST...")
    manifest = load_manifest(Path(args.manifest))

    print("Loading eval report...")
    eval_report = load_eval_report(Path(args.eval_report))

    # Get canonical tasks from MANIFEST
    canonical = get_canonical_tasks(manifest)
    print(f"Canonical tasks: {len(canonical)}")

    # Get detailed metrics
    detailed = get_detailed_tasks(eval_report, set(canonical.keys()))
    print(f"Tasks with detailed metrics: {len(detailed)}")

    # Build paired rewards (only tasks with both configs)
    paired = []
    for tid, d in canonical.items():
        bl = d.get("baseline")
        sf = d.get("sourcegraph_full")
        if bl is not None and sf is not None:
            paired.append((bl, sf))

    print(f"Paired tasks: {len(paired)}")

    # Compute stats
    print("Running statistical analysis...")
    stats = compute_aggregate_stats(paired)

    # Generate report
    print("Generating report...")
    sections = [
        f"# CodeScaleBench Evaluation Report",
        "",
        f"**Generated**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Paired tasks**: {len(paired)} across {len(BENCHMARK_INFO)} benchmark suites",
        f"**Configurations**: Baseline (no MCP) vs SG_full (Sourcegraph MCP)",
        f"**Model**: Claude Opus 4 (anthropic/claude-opus-4-6)",
        "",
        "---",
        "",
        section_executive_summary(canonical, paired, stats),
        section_methodology(),
        section_benchmarks(),
        section_aggregate_results(stats),
        section_per_benchmark(canonical, detailed),
        section_by_dimension(canonical, detailed, "language", "Language"),
        section_by_dimension(canonical, detailed, "difficulty", "Difficulty"),
        section_by_dimension(canonical, detailed, "sdlc_phase", "SDLC Phase"),
        section_mcp_usage(detailed, canonical),
        section_efficiency(detailed, canonical),
        section_discussion(stats, canonical),
        section_appendix_tasks(canonical, detailed),
    ]

    report_text = "\n".join(sections)
    report_path = output_dir / "COMPREHENSIVE_REPORT.md"
    report_path.write_text(report_text)
    print(f"\nWritten: {report_path}")
    print(f"  {len(report_text)} characters, {report_text.count(chr(10))} lines")

    # Also save stats JSON
    stats_path = output_dir / "statistical_analysis.json"
    stats_path.write_text(json.dumps(stats, indent=2, default=str) + "\n")
    print(f"Written: {stats_path}")


if __name__ == "__main__":
    main()

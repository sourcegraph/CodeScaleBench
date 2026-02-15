#!/usr/bin/env python3
"""Workflow taxonomy module for CodeContextBench enterprise metrics.

Maps benchmark suites to engineering workflow categories with conservative
time-conversion multipliers for modeling developer productivity impact.

All time projections are MODELED ESTIMATES based on published developer
productivity research. They are NOT direct measurements.
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Workflow Categories
# ---------------------------------------------------------------------------
# Each category represents a distinct engineering workflow observed in
# day-to-day software development.  The time multipliers convert raw agent
# metrics (tokens, tool calls) into modeled engineer-equivalent minutes.
#
# Multiplier methodology:
#   tokens_per_minute — conservative reading/comprehension rate for an
#       experienced engineer reviewing unfamiliar code (based on DORA and
#       Microsoft Developer Velocity studies).
#   tool_calls_per_minute — modeled rate at which an engineer performs
#       equivalent IDE actions (file opens, searches, edits) manually.
#
# All values are *lower-bound* estimates to avoid overstating productivity
# gains.
# ---------------------------------------------------------------------------

WORKFLOW_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "code_comprehension": {
        "description": (
            "Understanding existing codebases: reading source files, "
            "answering questions about architecture, and navigating "
            "unfamiliar repositories."
        ),
        "benchmark_suites": [
            "ccb_locobench",
            "ccb_repoqa",
            "ccb_codereview",
        ],
        "time_multiplier_tokens_per_minute": 800.0,
        "time_multiplier_tool_calls_per_minute": 3.0,
    },
    "cross_repo_navigation": {
        "description": (
            "Navigating across multiple repositories or large monorepos "
            "to trace dependencies, find related code, and understand "
            "cross-cutting concerns."
        ),
        "benchmark_suites": [
            "ccb_crossrepo",
            "ccb_largerepo",
        ],
        "time_multiplier_tokens_per_minute": 600.0,
        "time_multiplier_tool_calls_per_minute": 2.5,
    },
    "dependency_analysis": {
        "description": (
            "Analyzing, resolving, and installing project dependencies; "
            "understanding dependency graphs and compatibility constraints."
        ),
        "benchmark_suites": [
            "ccb_dependeval",
            "ccb_dibench",
        ],
        "time_multiplier_tokens_per_minute": 700.0,
        "time_multiplier_tool_calls_per_minute": 2.0,
    },
    "bug_localization": {
        "description": (
            "Localizing bugs in large codebases — fault localization, "
            "root-cause analysis, and identifying the minimal change set "
            "to fix defects."
        ),
        "benchmark_suites": [
            "ccb_linuxflbench",
            "ccb_sweperf",
        ],
        "time_multiplier_tokens_per_minute": 500.0,
        "time_multiplier_tool_calls_per_minute": 2.0,
    },
    "feature_implementation": {
        "description": (
            "Implementing new features or modifying existing functionality "
            "based on issue descriptions — the core coding workflow "
            "including planning, editing, and testing."
        ),
        "benchmark_suites": [
            "ccb_swebenchpro",
            "ccb_pytorch",
            "ccb_tac",
        ],
        "time_multiplier_tokens_per_minute": 1000.0,
        "time_multiplier_tool_calls_per_minute": 4.0,
    },
    "onboarding": {
        "description": (
            "Ramping up on unfamiliar projects: reading documentation, "
            "understanding build systems, and completing first tasks in "
            "a new codebase."
        ),
        "benchmark_suites": [
            "ccb_k8sdocs",
            "ccb_investigation",
        ],
        "time_multiplier_tokens_per_minute": 900.0,
        "time_multiplier_tool_calls_per_minute": 3.5,
    },
}

# ---------------------------------------------------------------------------
# Reverse mapping: benchmark suite -> primary workflow category
# ---------------------------------------------------------------------------

SUITE_TO_CATEGORY: Dict[str, str] = {}
for _cat_name, _cat_info in WORKFLOW_CATEGORIES.items():
    for _suite in _cat_info["benchmark_suites"]:
        SUITE_TO_CATEGORY[_suite] = _cat_name


def print_summary_table() -> None:
    """Print a human-readable summary of the workflow taxonomy."""
    header = f"{'Category':<26} {'Suites':<55} {'tok/min':>8} {'calls/min':>10}"
    print(header)
    print("-" * len(header))
    for name, info in WORKFLOW_CATEGORIES.items():
        suites_str = ", ".join(info["benchmark_suites"])
        print(
            f"{name:<26} {suites_str:<55} "
            f"{info['time_multiplier_tokens_per_minute']:>8.0f} "
            f"{info['time_multiplier_tool_calls_per_minute']:>10.1f}"
        )
    print()
    print(f"Total categories: {len(WORKFLOW_CATEGORIES)}")
    print(f"Total suites mapped: {len(SUITE_TO_CATEGORY)}")


def to_dict() -> Dict[str, Any]:
    """Return the full taxonomy as a serializable dict."""
    return {
        "workflow_categories": WORKFLOW_CATEGORIES,
        "suite_to_category": SUITE_TO_CATEGORY,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--json" in sys.argv:
        print(json.dumps(to_dict(), indent=2))
    else:
        print_summary_table()

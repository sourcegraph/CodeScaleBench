#!/usr/bin/env python3
"""Diagnostic script: show exactly what the LLM judge sees and produces.

Runs on a single task for both baseline and SG_full configs.
Prints the full context, prompt, and judge scoring with justification.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Load .env.local (handles `export KEY="val"` format)
env_path = Path(__file__).resolve().parent.parent / ".env.local"
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            # Strip leading 'export '
            if line.startswith("export "):
                line = line[7:]
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and val:
                os.environ.setdefault(key, val)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from csb_metrics.judge import LLMJudge, JudgeInput, OracleBundle
from csb_metrics.judge.oracle import discover_oracle
from csb_metrics.judge.prompts import (
    REFERENCE_CORRECTNESS_PROMPT,
    REFERENCE_COMPLETENESS_PROMPT,
    DIRECT_REVIEW_PROMPT,
)
from csb_metrics.judge.engine import _select_prompt, _render_prompt

# Import the same helpers used by run_judge.py
from run_judge import (
    _load_verifier_reward,
    _load_task_description,
    _extract_agent_output,
    _extract_tool_calls_summary,
    _extract_mcp_tools_used,
    BENCHMARKS_DIR,
)

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent

BL_TASK_DIR = Path(
    REPO_ROOT / "runs" / "staging" /
    "test_sonnet_20260219_015458_to_20260219_213932" /
    "baseline" / "ccb_test_test-unitgen-go-001_baseline" /
    "test-unitgen-go-001__7SxXhsF"
)

SG_TASK_DIR = Path(
    REPO_ROOT / "runs" / "staging" /
    "test_sonnet_20260219_015458_to_20260219_213932" /
    "sourcegraph_full" / "ccb_test_test-unitgen-go-001_sourcegraph_full" /
    "sdlc_test_test-unitgen-go-001_TJ__VwAEJTL"
)

TASK_ID = "test-unitgen-go-001"
BENCHMARK = "csb_sdlc_test"
MODEL = "gpt-4o"


def separator(title: str) -> str:
    return f"\n{'=' * 70}\n  {title}\n{'=' * 70}\n"


def build_judge_input(task_dir: Path, config_name: str) -> JudgeInput:
    """Assemble JudgeInput exactly as run_judge.py does."""
    result_path = task_dir / "result.json"
    verifier_reward = _load_verifier_reward(result_path) or 0.0
    task_description = _load_task_description(task_dir)
    agent_output = _extract_agent_output(task_dir)
    tool_calls_summary = _extract_tool_calls_summary(task_dir)
    mcp_tools = _extract_mcp_tools_used(task_dir)
    oracle = discover_oracle(TASK_ID, BENCHMARK, BENCHMARKS_DIR)

    ji = JudgeInput(
        task_id=TASK_ID,
        task_description=task_description,
        code_changes=agent_output,
        tool_calls=tool_calls_summary,
        verifier_reward=verifier_reward,
        oracle_ground_truth=oracle.ground_truth_text,
        oracle_expected_approach=oracle.expected_approach,
        oracle_evaluation_criteria=oracle.evaluation_criteria,
        oracle_context_files=oracle.context_files,
        mcp_tools_used=mcp_tools,
    )
    return ji, oracle


def show_context(config_name: str, ji: JudgeInput, oracle: OracleBundle) -> None:
    """Print exactly what the judge sees."""
    print(separator(f"CONTEXT for {config_name}"))

    print(f"Task ID:           {ji.task_id}")
    print(f"Verifier reward:   {ji.verifier_reward}")
    print(f"Oracle confidence: {oracle.confidence}")
    print(f"MCP tools used:    {ji.mcp_tools_used or '(none)'}")
    print(f"Tool calls:        {ji.tool_calls[:200]}...")

    print(f"\n--- Task Description (first 800 chars) ---")
    print(ji.task_description[:800])

    print(f"\n--- Agent Output / Code Changes (first 2000 chars) ---")
    print(ji.code_changes[:2000])

    print(f"\n--- Oracle Ground Truth (first 500 chars) ---")
    print((ji.oracle_ground_truth or "(none)")[:500])

    print(f"\n--- Oracle Evaluation Criteria ---")
    for c in (ji.oracle_evaluation_criteria or []):
        print(f"  - {c[:120]}")
    if not ji.oracle_evaluation_criteria:
        print("  (none)")

    print(f"\n--- Oracle Context Files ---")
    for f in (ji.oracle_context_files or []):
        print(f"  {f}")
    if not ji.oracle_context_files:
        print("  (none)")


def show_prompt(config_name: str, ji: JudgeInput) -> None:
    """Print the actual prompt that would be sent to the judge model."""
    print(separator(f"JUDGE PROMPT for {config_name}"))

    template = _select_prompt(ji)
    template_name = {
        REFERENCE_CORRECTNESS_PROMPT: "REFERENCE_CORRECTNESS_PROMPT",
        REFERENCE_COMPLETENESS_PROMPT: "REFERENCE_COMPLETENESS_PROMPT",
        DIRECT_REVIEW_PROMPT: "DIRECT_REVIEW_PROMPT",
    }.get(template, "UNKNOWN")
    print(f"Selected template: {template_name}\n")

    rendered = _render_prompt(template, ji)
    # Print full prompt (may be long)
    print(rendered[:3000])
    if len(rendered) > 3000:
        print(f"\n... [TRUNCATED — full prompt is {len(rendered)} chars] ...")


def run_judge(config_name: str, ji: JudgeInput) -> dict:
    """Actually call the judge and return the result dict."""
    print(separator(f"JUDGE OUTPUT for {config_name}"))

    judge = LLMJudge(model=MODEL, temperature=0.0)
    result = judge.evaluate(ji)
    result.benchmark = BENCHMARK
    result.config = config_name

    result_dict = result.to_dict()
    print(json.dumps(result_dict, indent=2))
    return result_dict


def main() -> int:
    print(f"Judge model: {MODEL}")
    print(f"Task: {TASK_ID} (suite: {BENCHMARK})")

    # ── Baseline ──
    if not BL_TASK_DIR.exists():
        print(f"ERROR: baseline dir not found: {BL_TASK_DIR}")
        return 1

    ji_bl, oracle_bl = build_judge_input(BL_TASK_DIR, "baseline")
    show_context("BASELINE", ji_bl, oracle_bl)
    show_prompt("BASELINE", ji_bl)
    result_bl = run_judge("baseline", ji_bl)

    # ── SG_full ──
    if not SG_TASK_DIR.exists():
        print(f"ERROR: sg_full dir not found: {SG_TASK_DIR}")
        return 1

    ji_sg, oracle_sg = build_judge_input(SG_TASK_DIR, "sourcegraph_full")
    show_context("SOURCEGRAPH_FULL", ji_sg, oracle_sg)
    show_prompt("SOURCEGRAPH_FULL", ji_sg)
    result_sg = run_judge("sourcegraph_full", ji_sg)

    # ── Comparison ──
    print(separator("COMPARISON"))
    print(f"{'Dimension':<22} {'Baseline':>10} {'SG_full':>10} {'Delta':>10}")
    print("-" * 55)
    for dim in ("correctness", "completeness", "code_quality", "retrieval_quality", "efficiency"):
        bl_s = result_bl["rubric"].get(dim, 0.0)
        sg_s = result_sg["rubric"].get(dim, 0.0)
        delta = sg_s - bl_s
        sign = "+" if delta > 0 else ""
        print(f"{dim:<22} {bl_s:>10.2f} {sg_s:>10.2f} {sign}{delta:>9.2f}")
    print("-" * 55)
    bl_total = result_bl["judge_score"]
    sg_total = result_sg["judge_score"]
    delta_total = sg_total - bl_total
    sign = "+" if delta_total > 0 else ""
    print(f"{'OVERALL (weighted)':<22} {bl_total:>10.3f} {sg_total:>10.3f} {sign}{delta_total:>9.3f}")

    print(f"\nVerifier rewards:  BL={ji_bl.verifier_reward:.2f}  SG={ji_sg.verifier_reward:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

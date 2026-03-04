#!/usr/bin/env python3
"""Fix H3 token-logging bug: patch result.json with tokens from claude-code.txt.

The H3 bug occurs when Harbor's _get_session_dir fails because Claude Code
spawns subagents via the Task tool. When this happens, trajectory.json is not
written and token counts in result.json are None — but the agent ran normally
and claude-code.txt has the full transcript with token data.

This script:
1. Finds task dirs where trajectory.json is missing but claude-code.txt exists
2. Extracts tokens from the transcript's "type":"result" JSONL entry
3. Patches result.json with the recovered token data
4. Optionally re-runs extract_task_metrics to regenerate task_metrics.json

Usage:
    # Dry run (show what would be patched)
    python3 scripts/fix_h3_tokens.py --dry-run

    # Fix all H3-affected tasks
    python3 scripts/fix_h3_tokens.py

    # Fix specific suites only
    python3 scripts/fix_h3_tokens.py --filter ccb_largerepo --filter ccb_crossrepo
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from config_utils import discover_configs

RUNS_DIR = PROJECT_ROOT / "runs" / "official"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived"]

DIR_PREFIX_TO_SUITE = {
    # Legacy benchmark prefixes
    "bigcode_mcp_": "ccb_largerepo",
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
    # Legacy SDLC prefixes (ccb_{phase}_)
    "ccb_feature_": "csb_sdlc_feature",
    "ccb_refactor_": "csb_sdlc_refactor",
    "ccb_build_": "csb_sdlc_build",
    "ccb_debug_": "csb_sdlc_debug",
    "ccb_design_": "csb_sdlc_design",
    "ccb_document_": "csb_sdlc_document",
    "ccb_fix_": "csb_sdlc_fix",
    "ccb_secure_": "csb_sdlc_secure",
    "ccb_test_": "csb_sdlc_test",
    "ccb_understand_": "csb_sdlc_understand",
    # Legacy MCP-unique prefixes (ccb_mcp_{suite}_)
    "ccb_mcp_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "ccb_mcp_crossrepo_": "csb_org_crossrepo",
    "ccb_mcp_security_": "csb_org_security",
    "ccb_mcp_migration_": "csb_org_migration",
    "ccb_mcp_incident_": "csb_org_incident",
    "ccb_mcp_onboarding_": "csb_org_onboarding",
    "ccb_mcp_compliance_": "csb_org_compliance",
    "ccb_mcp_crossorg_": "csb_org_crossorg",
    "ccb_mcp_domain_": "csb_org_domain",
    "ccb_mcp_org_": "csb_org_org",
    "ccb_mcp_platform_": "csb_org_platform",
    # CodeScaleBench renamed suites (new canonical names)
    "csb_sdlc_feature_": "csb_sdlc_feature",
    "csb_sdlc_refactor_": "csb_sdlc_refactor",
    "csb_sdlc_build_": "csb_sdlc_build",
    "csb_sdlc_debug_": "csb_sdlc_debug",
    "csb_sdlc_design_": "csb_sdlc_design",
    "csb_sdlc_document_": "csb_sdlc_document",
    "csb_sdlc_fix_": "csb_sdlc_fix",
    "csb_sdlc_secure_": "csb_sdlc_secure",
    "csb_sdlc_test_": "csb_sdlc_test",
    "csb_sdlc_understand_": "csb_sdlc_understand",
    # CSB Org suites (must check crossrepo_tracing before crossrepo)
    "csb_org_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "csb_org_crossrepo_": "csb_org_crossrepo",
    "csb_org_security_": "csb_org_security",
    "csb_org_migration_": "csb_org_migration",
    "csb_org_incident_": "csb_org_incident",
    "csb_org_onboarding_": "csb_org_onboarding",
    "csb_org_compliance_": "csb_org_compliance",
    "csb_org_crossorg_": "csb_org_crossorg",
    "csb_org_domain_": "csb_org_domain",
    "csb_org_org_": "csb_org_org",
    "csb_org_platform_": "csb_org_platform",
    # Bare sdlc_ and org_ prefixes (short-form run names)
    "sdlc_feature_": "csb_sdlc_feature",
    "sdlc_refactor_": "csb_sdlc_refactor",
    "sdlc_build_": "csb_sdlc_build",
    "sdlc_debug_": "csb_sdlc_debug",
    "sdlc_design_": "csb_sdlc_design",
    "sdlc_document_": "csb_sdlc_document",
    "sdlc_fix_": "csb_sdlc_fix",
    "sdlc_secure_": "csb_sdlc_secure",
    "sdlc_test_": "csb_sdlc_test",
    "sdlc_understand_": "csb_sdlc_understand",
    "org_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "org_crossrepo_": "csb_org_crossrepo",
    "org_security_": "csb_org_security",
    "org_migration_": "csb_org_migration",
    "org_incident_": "csb_org_incident",
    "org_onboarding_": "csb_org_onboarding",
    "org_compliance_": "csb_org_compliance",
    "org_crossorg_": "csb_org_crossorg",
    "org_domain_": "csb_org_domain",
    "org_org_": "csb_org_org",
    "org_platform_": "csb_org_platform",
}


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def suite_from_run_dir(name: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            return suite
    if name.startswith("swebenchpro_gapfill_"):
        return "ccb_swebenchpro"
    return None


def _is_batch_timestamp(name: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def extract_tokens_from_transcript(cc_path: Path) -> dict | None:
    """Extract token usage from claude-code.txt JSONL.

    Reads backwards to find the last "type":"result" entry with usage data.
    Returns dict with input/output/cache tokens and cost, or None if not found.
    """
    if not cc_path.is_file():
        return None

    try:
        lines = cc_path.read_text().splitlines()
    except OSError:
        return None

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "result":
            usage = entry.get("usage") or {}
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if input_tokens is not None or output_tokens is not None:
                return {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
                    "total_cost_usd": entry.get("total_cost_usd"),
                }
    return None


def is_h3_affected(task_dir: Path) -> bool:
    """Check if a task dir has the H3 bug pattern:
    - No trajectory.json
    - Has claude-code.txt (agent ran)
    - result.json has None/0 tokens
    """
    traj = task_dir / "agent" / "trajectory.json"
    cc = task_dir / "agent" / "claude-code.txt"
    result = task_dir / "result.json"

    if traj.is_file():
        return False  # Has trajectory, not H3
    if not cc.is_file():
        return False  # No transcript, can't recover
    if not result.is_file():
        return False

    try:
        data = json.loads(result.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    # Must be a task-level result (not batch-level)
    if "n_total_trials" in data and "task_name" not in data:
        return False

    # Check if tokens are missing
    ar = data.get("agent_result") or {}
    n_input = ar.get("n_input_tokens")
    n_output = ar.get("n_output_tokens")

    # H3: tokens are None (not explicitly 0 — zero tokens means auth failure)
    return n_input is None and n_output is None


def patch_result_json(task_dir: Path, tokens: dict, dry_run: bool = False) -> bool:
    """Patch result.json with recovered token data.

    Adds tokens to agent_result and sets a _h3_patched flag.
    Returns True if patched successfully.
    """
    result_path = task_dir / "result.json"
    try:
        data = json.loads(result_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    if data.get("_h3_patched"):
        return False  # Already patched

    ar = data.get("agent_result")
    if ar is None:
        ar = {}
        data["agent_result"] = ar

    # n_input_tokens in result.json is the TOTAL input (uncached + cache_create + cache_read).
    # The transcript's "input_tokens" is only the uncached portion (often very small, e.g. 2).
    # Compute the total to match what Harbor normally writes.
    uncached = tokens["input_tokens"] or 0
    cache_create = tokens.get("cache_creation_input_tokens") or 0
    cache_read = tokens.get("cache_read_input_tokens") or 0
    total_input = uncached + cache_create + cache_read

    ar["n_input_tokens"] = total_input
    ar["n_output_tokens"] = tokens["output_tokens"]
    ar["cache_creation_input_tokens"] = cache_create
    ar["cache_read_input_tokens"] = cache_read
    if tokens.get("total_cost_usd") is not None:
        ar["total_cost_usd"] = tokens["total_cost_usd"]

    # Mark as H3-patched so we don't double-patch
    data["_h3_patched"] = True

    if not dry_run:
        result_path.write_text(json.dumps(data, indent=2) + "\n")

    return True


def find_h3_tasks(
    runs_dir: Path,
    suite_filters: list[str] | None = None,
) -> list[tuple[Path, str, str]]:
    """Find all H3-affected task dirs.

    Returns list of (task_dir, suite, config).
    """
    results = []

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
            continue

        suite = suite_from_run_dir(run_dir.name)
        if suite is None:
            continue
        if suite_filters and suite not in suite_filters:
            continue

        for config in discover_configs(run_dir):
            config_dir = run_dir / config

            for subdir in sorted(config_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                if should_skip(subdir.name):
                    continue

                if _is_batch_timestamp(subdir.name):
                    for task_dir in sorted(subdir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        if should_skip(task_dir.name):
                            continue
                        if is_h3_affected(task_dir):
                            results.append((task_dir, suite, config))
                elif is_h3_affected(subdir):
                    results.append((subdir, suite, config))

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Fix H3 token-logging bug by patching result.json from transcripts."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be patched without writing",
    )
    parser.add_argument(
        "--filter", action="append", dest="filters",
        help="Only fix tasks in these suites (can specify multiple)",
    )
    parser.add_argument(
        "--regenerate-metrics", action="store_true",
        help="Also re-run extract_task_metrics for patched tasks",
    )
    args = parser.parse_args()

    if not RUNS_DIR.exists():
        print(f"ERROR: Runs directory not found: {RUNS_DIR}", file=sys.stderr)
        sys.exit(1)

    h3_tasks = find_h3_tasks(RUNS_DIR, args.filters)
    print(f"Found {len(h3_tasks)} H3-affected task(s)")

    if not h3_tasks:
        print("Nothing to fix.")
        return

    patched = 0
    failed = 0
    total_cost = 0.0

    for task_dir, suite, config in h3_tasks:
        task_name = task_dir.name.rsplit("__", 1)[0] if "__" in task_dir.name else task_dir.name

        # Extract tokens from transcript
        cc_path = task_dir / "agent" / "claude-code.txt"
        tokens = extract_tokens_from_transcript(cc_path)

        if tokens is None:
            print(f"  SKIP {suite}/{config}/{task_name}: no token data in transcript")
            failed += 1
            continue

        cost = tokens.get("total_cost_usd") or 0.0
        total_cost += cost

        # Compute total input for display
        uncached = tokens["input_tokens"] or 0
        cache_create = tokens.get("cache_creation_input_tokens") or 0
        cache_read = tokens.get("cache_read_input_tokens") or 0
        total_input = uncached + cache_create + cache_read

        action = "WOULD PATCH" if args.dry_run else "PATCHED"

        if patch_result_json(task_dir, tokens, dry_run=args.dry_run):
            patched += 1
            print(
                f"  {action} {suite}/{config}/{task_name}: "
                f"in={total_input:,} out={tokens['output_tokens']:,} "
                f"cost=${cost:.2f}"
            )
        else:
            # Already patched or error
            print(f"  SKIP {suite}/{config}/{task_name}: already patched or error")

    print(f"\n{'Would patch' if args.dry_run else 'Patched'}: {patched}, "
          f"skipped/failed: {failed}, "
          f"total recovered cost: ${total_cost:.2f}")

    if args.regenerate_metrics and not args.dry_run and patched > 0:
        print("\nRegenerating task_metrics.json for patched tasks...")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from extract_task_metrics import process_task_dir

        for task_dir, suite, config in h3_tasks:
            try:
                tm = process_task_dir(task_dir, suite, config)
                if tm:
                    out_path = task_dir / "task_metrics.json"
                    out_path.write_text(json.dumps(tm.to_dict(), indent=2) + "\n")
            except Exception as e:
                print(f"  ERROR regenerating metrics for {task_dir.name}: {e}",
                      file=sys.stderr)


if __name__ == "__main__":
    main()

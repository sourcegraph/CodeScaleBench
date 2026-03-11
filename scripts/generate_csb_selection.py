#!/usr/bin/env python3
"""Generate configs/selected_csb_tasks.json for the unified benchmarks/csb/ benchmark.

Reads existing selected_benchmark_tasks.json for metadata, maps tasks into the new
merged suite structure, and writes the new selection file.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Merge map: old suite -> new suite (must match scaffold_csb_unified.py)
SUITE_MERGE = {
    "csb_sdlc_secure": "csb_security",
    "csb_org_security": "csb_security",
    "csb_org_compliance": "csb_security",
    "csb_sdlc_debug": "csb_debug",
    "csb_org_incident": "csb_debug",
    "csb_sdlc_fix": "csb_fix",
    "csb_sdlc_feature": "csb_feature",
    "csb_org_org": "csb_feature",
    "csb_sdlc_refactor": "csb_refactor",
    "csb_org_migration": "csb_refactor",
    "csb_sdlc_understand": "csb_understand",
    "csb_sdlc_design": "csb_understand",
    "csb_org_domain": "csb_understand",
    "csb_org_onboarding": "csb_understand",
    "csb_sdlc_document": "csb_document",
    "csb_sdlc_test": "csb_test",
    "csb_org_crossrepo": "csb_crossrepo",
    "csb_org_crossrepo_tracing": "csb_crossrepo",
    "csb_org_crossorg": "csb_crossrepo",
    "csb_org_platform": "csb_crossrepo",
}


def main():
    # Load existing selection for metadata
    old_sel_path = os.path.join(ROOT, "configs", "selected_benchmark_tasks.json")
    with open(old_sel_path) as f:
        old_sel = json.load(f)

    old_tasks_by_id = {t["task_id"]: t for t in old_sel.get("tasks", [])}

    # Discover all tasks in benchmarks/csb/
    csb_dir = os.path.join(ROOT, "benchmarks", "csb")
    tasks = []
    suite_counts = {}

    for suite in sorted(os.listdir(csb_dir)):
        suite_path = os.path.join(csb_dir, suite)
        if not os.path.isdir(suite_path):
            continue
        new_suite = f"csb_{suite}"
        for task_name in sorted(os.listdir(suite_path)):
            task_path = os.path.join(suite_path, task_name)
            if not os.path.isdir(task_path) or not os.path.exists(
                os.path.join(task_path, "task.toml")
            ):
                continue

            # Start with existing metadata if available
            entry = dict(old_tasks_by_id.get(task_name, {}))
            entry["task_id"] = task_name
            entry["benchmark"] = new_suite
            entry["suite"] = new_suite
            entry["task_dir"] = f"csb/{suite}/{task_name}"
            # Remove excluded flag — all 275 are active in the unified benchmark
            entry.pop("excluded", None)

            tasks.append(entry)
            suite_counts[new_suite] = suite_counts.get(new_suite, 0) + 1

    # Build output
    output = {
        "metadata": {
            "title": "CodeScaleBench Unified Benchmark (CSB)",
            "version": "4.0",
            "generated_by": "scripts/generate_csb_selection.py",
            "total_tasks": len(tasks),
            "suites": 9,
            "per_suite": suite_counts,
            "note": "Unified benchmark with dual scoring (reward_direct + reward_artifact). "
                    "Merged from 20 legacy suites into 9 thematic suites.",
        },
        "tasks": tasks,
    }

    out_path = os.path.join(ROOT, "configs", "selected_csb_tasks.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(tasks)} tasks to {out_path}")
    for suite, count in sorted(suite_counts.items()):
        print(f"  {suite:20s} {count:3d}")


if __name__ == "__main__":
    main()

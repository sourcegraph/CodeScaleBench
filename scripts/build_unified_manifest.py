#!/usr/bin/env python3
"""Build the unified benchmark manifest organized by task_type.

Replaces the suite-centric 220-task core manifest with a task-type-centric
~280 task manifest. No SDLC/Org split — all tasks are peers, grouped by
comprehension / implementation / quality.

Selection criteria:
  - Must have tests/test.sh (deterministic reward)
  - Must have tests/ground_truth.json (IR retrieval scoring)
  - Maximizes LOC band diversity within each task_type
  - Ensures multi-repo representation in every task_type
  - Ensures suite diversity (no single suite dominates a task_type)
  - Prefers core_ready over conditional verifier quality

Output: configs/unified_benchmark_manifest.json
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BENCHMARKS_DIR = ROOT / "benchmarks"
TAXONOMY_FILE = ROOT / "configs" / "task_type_taxonomy.json"
LABELS_FILE = ROOT / "configs" / "verifier_quality_labels.json"
SELECTED_FILE = ROOT / "configs" / "selected_benchmark_tasks.json"
PROMOTION_FILE = ROOT / "configs" / "org_promotion_manifest.json"
OUTPUT_FILE = ROOT / "configs" / "unified_benchmark_manifest.json"

# Target allocation by task_type
TYPE_TARGETS = {
    "comprehension": 100,
    "implementation": 90,
    "quality": 90,
}
TARGET_TOTAL = sum(TYPE_TARGETS.values())  # 280

LOC_BANDS = ["<400K", "400K-2M", "2M-8M", "8M-40M", ">40M"]


def loc_band(loc):
    if loc is None:
        return "unknown"
    if loc < 400_000:
        return "<400K"
    if loc < 2_000_000:
        return "400K-2M"
    if loc < 8_000_000:
        return "2M-8M"
    if loc < 40_000_000:
        return "8M-40M"
    return ">40M"


def _build_repo_set_loc_map():
    """Build repo_set_id -> median LOC from tasks with known LOC.

    Uses promotion manifest and selected_benchmark_tasks as LOC sources,
    then groups by repo_set_id parsed from task.toml.
    """
    import re
    from collections import defaultdict

    # Collect all known LOC values
    known_locs = {}  # task_id (lower) -> loc

    if PROMOTION_FILE.exists():
        promo = json.loads(PROMOTION_FILE.read_text())
        for t in promo.get("tasks", []):
            known_locs[t["task_id"].lower()] = t["repo_approx_loc"]

    if SELECTED_FILE.exists():
        data = json.loads(SELECTED_FILE.read_text())
        tasks = data.get("tasks", data) if isinstance(data, dict) else data
        for t in tasks:
            loc = t.get("repo_approx_loc")
            if loc:
                known_locs[t["task_id"].lower()] = loc

    # Map repo_set_id -> list of LOC values
    rsid_locs = defaultdict(list)
    for suite_dir in os.listdir(BENCHMARKS_DIR):
        if not suite_dir.startswith("csb_"):
            continue
        suite_path = BENCHMARKS_DIR / suite_dir
        if not suite_path.is_dir():
            continue
        for task_name in os.listdir(suite_path):
            toml_path = suite_path / task_name / "task.toml"
            if not toml_path.is_file():
                continue
            loc = known_locs.get(task_name.lower())
            if not loc:
                continue
            try:
                content = toml_path.read_text()
                m = re.search(r'repo_set_id\s*=\s*"([^"]+)"', content)
                if m:
                    rsid_locs[m.group(1)].append(loc)
            except Exception:
                pass

    # Compute median per repo_set_id
    result = {}
    for rsid, locs in rsid_locs.items():
        locs.sort()
        mid = len(locs) // 2
        result[rsid] = locs[mid]
    return result


def discover_eligible_tasks(suite_to_type, vq_labels, selected_metadata):
    """Scan benchmarks/ for tasks with both test.sh and ground_truth.json."""
    import re

    eligible = []
    meta_index = {t["task_id"]: t for t in selected_metadata}

    # Build LOC fallback from promotion manifest
    promo_locs = {}
    if PROMOTION_FILE.exists():
        promo = json.loads(PROMOTION_FILE.read_text())
        for t in promo.get("tasks", []):
            promo_locs[t["task_id"].lower()] = t["repo_approx_loc"]

    # Build repo_set_id -> LOC fallback
    rsid_loc_map = _build_repo_set_loc_map()

    for suite_dir in sorted(os.listdir(BENCHMARKS_DIR)):
        if not suite_dir.startswith("csb_"):
            continue
        suite_path = BENCHMARKS_DIR / suite_dir
        if not suite_path.is_dir():
            continue
        task_type = suite_to_type.get(suite_dir)
        if not task_type:
            continue

        for task_name in sorted(os.listdir(suite_path)):
            task_path = suite_path / task_name
            if not (task_path / "task.toml").is_file():
                continue
            if not (task_path / "tests" / "test.sh").is_file():
                continue
            if not (task_path / "tests" / "ground_truth.json").is_file():
                continue

            # Get metadata from selected_benchmark_tasks if available
            meta = meta_index.get(task_name, {})
            approx_loc = meta.get("repo_approx_loc")
            n_repos = meta.get("n_repos", 1)

            # Fallback 1: promotion manifest
            if approx_loc is None:
                approx_loc = promo_locs.get(task_name.lower())

            # Fallback 2: task.toml repo_set_id -> LOC mapping
            if approx_loc is None:
                try:
                    content = (task_path / "task.toml").read_text()
                    m = re.search(r'repo_set_id\s*=\s*"([^"]+)"', content)
                    if m:
                        approx_loc = rsid_loc_map.get(m.group(1))
                except Exception:
                    pass

            # Fallback 3: task.toml repo_approx_loc field
            if approx_loc is None:
                try:
                    import tomllib
                    with open(task_path / "task.toml", "rb") as f:
                        toml = tomllib.load(f)
                    approx_loc = toml.get("task", {}).get("repo_approx_loc")
                except Exception:
                    pass

            # Try to infer n_repos from Dockerfile clone count
            if n_repos == 1:
                dockerfile = task_path / "environment" / "Dockerfile"
                if dockerfile.exists():
                    try:
                        content = dockerfile.read_text()
                        n_repos = max(1, content.count("git clone"))
                    except Exception:
                        pass

            vq = vq_labels.get(task_name, {}).get("label", "conditional")

            eligible.append({
                "task_id": task_name,
                "suite": suite_dir,
                "task_type": task_type,
                "repo_approx_loc": approx_loc,
                "n_repos": n_repos,
                "loc_band": loc_band(approx_loc),
                "vq": vq,
                "language": meta.get("language", meta.get("repo_primary_language", "unknown")),
            })

    return eligible


def select_for_type(candidates, target_n):
    """Select target_n tasks from candidates, maximizing diversity.

    Priority order:
    1. LOC band coverage (one per band)
    2. Multi-repo representation
    3. Suite diversity (cap per suite)
    4. core_ready preference
    """
    if len(candidates) <= target_n:
        return candidates

    selected = []
    selected_ids = set()

    def add(task):
        if task["task_id"] not in selected_ids:
            selected.append(task)
            selected_ids.add(task["task_id"])

    # Group by various dimensions
    by_band = defaultdict(list)
    by_suite = defaultdict(list)
    for t in candidates:
        by_band[t["loc_band"]].append(t)
        by_suite[t["suite"]].append(t)

    # Pass 1: One task per LOC band (prefer core_ready, then multi-repo)
    for band in LOC_BANDS:
        tasks = by_band.get(band, [])
        if not tasks or len(selected) >= target_n:
            continue
        # Prefer core_ready + multi-repo
        tasks_sorted = sorted(tasks, key=lambda t: (
            0 if t["vq"] == "core_ready" else 1,
            0 if t["n_repos"] > 1 else 1,
        ))
        add(tasks_sorted[0])

    # Pass 2: Ensure multi-repo coverage (at least 20% multi-repo)
    multi_target = max(target_n // 5, 3)
    multi_count = sum(1 for t in selected if t["n_repos"] > 1)
    if multi_count < multi_target:
        multi_candidates = sorted(
            [t for t in candidates if t["n_repos"] > 1 and t["task_id"] not in selected_ids],
            key=lambda t: (0 if t["vq"] == "core_ready" else 1, -(t.get("repo_approx_loc") or 0)),
        )
        for t in multi_candidates:
            if multi_count >= multi_target or len(selected) >= target_n:
                break
            add(t)
            multi_count += 1

    # Pass 3: Suite diversity — cap per suite to prevent domination
    max_per_suite = max(target_n // len(by_suite), 3) if by_suite else target_n
    suite_counts = Counter(t["suite"] for t in selected)

    # Fill remaining, round-robin across suites
    remaining_by_suite = {}
    for suite, tasks in by_suite.items():
        remaining = sorted(
            [t for t in tasks if t["task_id"] not in selected_ids],
            key=lambda t: (0 if t["vq"] == "core_ready" else 1, -(t.get("repo_approx_loc") or 0)),
        )
        if remaining:
            remaining_by_suite[suite] = remaining

    # Round-robin fill
    while len(selected) < target_n and remaining_by_suite:
        suites_to_remove = []
        for suite in sorted(remaining_by_suite.keys()):
            if len(selected) >= target_n:
                break
            if suite_counts.get(suite, 0) >= max_per_suite:
                continue
            tasks = remaining_by_suite[suite]
            if tasks:
                t = tasks.pop(0)
                add(t)
                suite_counts[suite] = suite_counts.get(suite, 0) + 1
            if not tasks:
                suites_to_remove.append(suite)
        for s in suites_to_remove:
            del remaining_by_suite[s]
        # If all suites hit cap, raise cap
        if len(selected) < target_n and remaining_by_suite:
            if all(suite_counts.get(s, 0) >= max_per_suite for s in remaining_by_suite):
                max_per_suite += 2

    return selected[:target_n]


def main():
    # Load reference data
    taxonomy = json.loads(TAXONOMY_FILE.read_text())
    suite_to_type = taxonomy["suite_to_task_type"]

    vq_labels = {}
    if LABELS_FILE.exists():
        vq_labels = json.loads(LABELS_FILE.read_text()).get("labels", {})

    selected_metadata = []
    if SELECTED_FILE.exists():
        data = json.loads(SELECTED_FILE.read_text())
        selected_metadata = data.get("tasks", data) if isinstance(data, dict) else data

    # Discover all eligible tasks
    eligible = discover_eligible_tasks(suite_to_type, vq_labels, selected_metadata)
    print(f"Eligible tasks: {len(eligible)}")

    by_type = defaultdict(list)
    for t in eligible:
        by_type[t["task_type"]].append(t)

    for tt, tasks in sorted(by_type.items()):
        print(f"  {tt}: {len(tasks)} eligible")

    # Select per task_type
    manifest_tasks = []
    type_actual = {}
    for task_type, target in TYPE_TARGETS.items():
        candidates = by_type.get(task_type, [])
        selected = select_for_type(candidates, target)
        type_actual[task_type] = len(selected)
        manifest_tasks.extend(selected)

        if len(selected) < target:
            print(f"  WARN: {task_type} has {len(selected)}/{target} (pool: {len(candidates)})")

    actual_total = len(manifest_tasks)
    print(f"\nManifest: {actual_total}/{TARGET_TOTAL} tasks")

    # Build clean output
    manifest_entries = []
    for t in manifest_tasks:
        manifest_entries.append({
            "task_id": t["task_id"],
            "suite": t["suite"],
            "task_type": t["task_type"],
            "repo_approx_loc": t.get("repo_approx_loc"),
            "n_repos": t["n_repos"],
            "loc_band": t["loc_band"],
            "verifier_quality": t["vq"],
            "language": t.get("language", "unknown"),
        })

    # Sort by task_type, then suite, then task_id
    manifest_entries.sort(key=lambda t: (t["task_type"], t["suite"], t["task_id"]))

    # Compute distribution stats
    type_dist = Counter(t["task_type"] for t in manifest_entries)
    loc_dist = Counter(t["loc_band"] for t in manifest_entries)
    repo_dist = Counter(t["n_repos"] for t in manifest_entries)
    vq_dist = Counter(t["verifier_quality"] for t in manifest_entries)
    suite_dist = Counter(t["suite"] for t in manifest_entries)
    lang_dist = Counter(t["language"] for t in manifest_entries)

    multi_repo_pct = sum(1 for t in manifest_entries if t["n_repos"] > 1) / len(manifest_entries) * 100
    large_loc_pct = sum(1 for t in manifest_entries if t["loc_band"] in ("2M-8M", "8M-40M", ">40M")) / len(manifest_entries) * 100

    # Per-type stats
    type_stats = {}
    for tt in TYPE_TARGETS:
        tt_tasks = [t for t in manifest_entries if t["task_type"] == tt]
        tt_suites = Counter(t["suite"] for t in tt_tasks)
        tt_bands = Counter(t["loc_band"] for t in tt_tasks)
        tt_multi = sum(1 for t in tt_tasks if t["n_repos"] > 1)
        type_stats[tt] = {
            "count": len(tt_tasks),
            "target": TYPE_TARGETS[tt],
            "suites": len(tt_suites),
            "suite_distribution": dict(tt_suites.most_common()),
            "loc_bands": dict(tt_bands),
            "multi_repo_count": tt_multi,
            "multi_repo_pct": round(tt_multi / len(tt_tasks) * 100, 1) if tt_tasks else 0,
        }

    output = {
        "schema_version": "2.0",
        "description": "Unified benchmark manifest: task-type-centric, no SDLC/Org split. Every task has deterministic reward + IR retrieval scoring.",
        "target_total": TARGET_TOTAL,
        "actual_total": actual_total,
        "type_allocation": {
            tt: {"target": TYPE_TARGETS[tt], "actual": type_actual[tt]}
            for tt in TYPE_TARGETS
        },
        "summary": {
            "task_type_distribution": dict(type_dist.most_common()),
            "loc_band_distribution": dict(loc_dist.most_common()),
            "n_repos_distribution": {str(k): v for k, v in sorted(repo_dist.items())},
            "verifier_quality": dict(vq_dist.most_common()),
            "multi_repo_pct": round(multi_repo_pct, 1),
            "large_codebase_pct": round(large_loc_pct, 1),
            "suites_represented": len(suite_dist),
            "languages_represented": len(lang_dist),
        },
        "per_type_stats": type_stats,
        "tasks": manifest_entries,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2) + "\n")
    print(f"\nWritten to {OUTPUT_FILE}")

    # Print summary
    print(f"\n=== Distribution Summary ===")
    print(f"Task types: {dict(type_dist.most_common())}")
    print(f"LOC bands: {dict(loc_dist.most_common())}")
    print(f"n_repos: {dict(sorted(repo_dist.items()))}")
    print(f"VQ: {dict(vq_dist.most_common())}")
    print(f"Multi-repo: {multi_repo_pct:.1f}%")
    print(f"Large codebase (2M+): {large_loc_pct:.1f}%")
    print(f"Suites: {len(suite_dist)}")
    print(f"Languages: {len(lang_dist)}")

    for tt, stats in type_stats.items():
        print(f"\n  {tt} ({stats['count']}/{stats['target']}):")
        print(f"    Suites: {stats['suites']}, Multi-repo: {stats['multi_repo_pct']}%")
        print(f"    LOC bands: {stats['loc_bands']}")
        print(f"    Suite dist: {stats['suite_distribution']}")


if __name__ == "__main__":
    main()

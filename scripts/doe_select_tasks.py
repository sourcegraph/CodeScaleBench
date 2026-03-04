#!/usr/bin/env python3
"""DOE-driven task selection: rank tasks by information value and produce keep/move lists.

For each SDLC suite, ranks tasks by a composite "information value" score that reflects
how much each task contributes to estimating the MCP treatment effect:

  info_value = w_delta * |delta_norm| + w_var * var_norm + w_ceiling * ceiling_penalty

Where:
  - |delta|: absolute MCP-baseline reward difference (larger = more informative for treatment)
  - rep_var: within-task replicate variance (larger = more agent stochasticity, more info)
  - ceiling_penalty: 1 if task is at floor (all 0) or ceiling (all 1) in BOTH configs, else 0

Tasks are ranked by info_value and the top-N (per Neyman allocation) are kept.

Usage:
    python3 scripts/doe_select_tasks.py                    # Preview keep/move lists
    python3 scripts/doe_select_tasks.py --budget 150       # With custom budget
    python3 scripts/doe_select_tasks.py --execute          # Actually move task dirs
    python3 scripts/doe_select_tasks.py --json             # Machine-readable output
"""

import json
import statistics
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "runs" / "official" / "MANIFEST.json"
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
BACKUPS_DIR = BENCHMARKS_DIR / "backups"
SELECTION_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

SDLC_SUITES = [
    "csb_sdlc_feature", "csb_sdlc_refactor", "csb_sdlc_debug", "csb_sdlc_design", "csb_sdlc_document",
    "csb_sdlc_fix", "csb_sdlc_secure", "csb_sdlc_test", "csb_sdlc_understand",
]

MCP_UNIQUE_SUITES = [
    "csb_org_compliance", "csb_org_crossorg", "csb_org_crossrepo",
    "csb_org_crossrepo_tracing", "csb_org_domain", "csb_org_incident",
    "csb_org_migration", "csb_org_onboarding", "csb_org_org",
    "csb_org_platform", "csb_org_security",
]

BASELINE_CONFIGS = {"baseline", "baseline-local-direct", "baseline-local-artifact"}
MCP_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact"}

# Weights for information value composite score
W_DELTA = 0.5      # weight on |MCP - baseline delta|
W_VARIANCE = 0.3   # weight on within-task replicate variance
W_CEILING = 0.2    # weight on ceiling/floor penalty (inverted: non-ceiling tasks get bonus)

# Neyman-optimal targets at budget=150 (from doe_variance_analysis.py)
# These are recalculated dynamically but kept as reference
DEFAULT_TARGETS = {
    "csb_sdlc_fix": 25, "csb_sdlc_test": 23, "csb_sdlc_feature": 22,
    "csb_sdlc_debug": 18, "csb_sdlc_refactor": 15, "csb_sdlc_design": 14,
    "csb_sdlc_document": 12, "csb_sdlc_secure": 11, "csb_sdlc_understand": 10,
}


def load_run_history(manifest: dict) -> dict:
    """Extract per-task reward vectors from run_history, grouped by suite and config."""
    run_history = manifest.get("run_history", {})
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for run_key, tasks in run_history.items():
        parts = run_key.split("/")
        if len(parts) != 2:
            continue
        suite, config = parts

        if config in BASELINE_CONFIGS:
            config_type = "baseline"
        elif config in MCP_CONFIGS:
            config_type = "mcp"
        else:
            continue

        for task_name, task_info in tasks.items():
            runs = task_info.get("runs", [])
            rewards = [
                r["reward"] for r in runs
                if r.get("reward") is not None and r.get("status") != "errored"
            ]
            if rewards:
                data[suite][config_type][task_name] = rewards

    return dict(data)


def compute_task_info_value(
    bl_rewards: list, mcp_rewards: list
) -> dict:
    """Compute information value for a single task.

    Returns dict with component scores and composite info_value.
    """
    bl_mean = statistics.mean(bl_rewards) if bl_rewards else 0.0
    mcp_mean = statistics.mean(mcp_rewards) if mcp_rewards else 0.0
    delta = mcp_mean - bl_mean

    # Within-task replicate variance (pooled across both arms)
    bl_var = statistics.variance(bl_rewards) if len(bl_rewards) > 1 else 0.0
    mcp_var = statistics.variance(mcp_rewards) if len(mcp_rewards) > 1 else 0.0
    n_bl = len(bl_rewards)
    n_mcp = len(mcp_rewards)
    # Pooled variance weighted by degrees of freedom
    if n_bl + n_mcp > 2:
        pooled_var = ((n_bl - 1) * bl_var + (n_mcp - 1) * mcp_var) / (n_bl + n_mcp - 2)
    else:
        pooled_var = max(bl_var, mcp_var)

    # Ceiling/floor detection: task is uninformative if both arms consistently
    # hit 0.0 or 1.0 (with tiny variance)
    is_ceiling = (bl_mean >= 0.95 and mcp_mean >= 0.95 and pooled_var < 0.005)
    is_floor = (bl_mean <= 0.05 and mcp_mean <= 0.05 and pooled_var < 0.005)
    is_uninformative = is_ceiling or is_floor

    return {
        "bl_mean": bl_mean,
        "mcp_mean": mcp_mean,
        "delta": delta,
        "abs_delta": abs(delta),
        "bl_var": bl_var,
        "mcp_var": mcp_var,
        "pooled_var": pooled_var,
        "n_bl": n_bl,
        "n_mcp": n_mcp,
        "is_ceiling": is_ceiling,
        "is_floor": is_floor,
        "is_uninformative": is_uninformative,
    }


def rank_tasks_in_suite(
    suite: str, suite_data: dict, min_reps: int = 2
) -> list:
    """Rank tasks by information value within a suite.

    Returns list of (task_name, info_dict) sorted by info_value descending.
    """
    bl_data = suite_data.get("baseline", {})
    mcp_data = suite_data.get("mcp", {})

    # Only consider tasks with data in at least one arm (preferably both)
    all_tasks = set(bl_data.keys()) | set(mcp_data.keys())
    paired_tasks = set(bl_data.keys()) & set(mcp_data.keys())

    task_infos = []
    for task_name in all_tasks:
        bl_rewards = bl_data.get(task_name, [])
        mcp_rewards = mcp_data.get(task_name, [])

        # Skip tasks with too few replicates
        if len(bl_rewards) < min_reps and len(mcp_rewards) < min_reps:
            continue

        info = compute_task_info_value(bl_rewards, mcp_rewards)
        info["task_name"] = task_name
        info["is_paired"] = task_name in paired_tasks
        task_infos.append(info)

    if not task_infos:
        return []

    # Normalize components to [0, 1] for composite score
    max_delta = max(t["abs_delta"] for t in task_infos) or 1.0
    max_var = max(t["pooled_var"] for t in task_infos) or 1.0

    for info in task_infos:
        delta_norm = info["abs_delta"] / max_delta
        var_norm = info["pooled_var"] / max_var
        ceiling_bonus = 0.0 if info["is_uninformative"] else 1.0

        info["delta_norm"] = delta_norm
        info["var_norm"] = var_norm
        info["ceiling_bonus"] = ceiling_bonus
        info["info_value"] = (
            W_DELTA * delta_norm +
            W_VARIANCE * var_norm +
            W_CEILING * ceiling_bonus
        )

    # Sort by info_value descending (highest information first)
    task_infos.sort(key=lambda x: x["info_value"], reverse=True)
    return task_infos


def load_task_languages() -> dict:
    """Load task language info from selected_benchmark_tasks.json."""
    try:
        with open(SELECTION_PATH) as f:
            sel = json.load(f)
        tasks = sel.get("tasks", sel) if isinstance(sel, dict) else sel
        return {
            t.get("task_id", t.get("task_name", "")): t.get("language", "unknown")
            for t in tasks
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def check_language_diversity(kept_tasks: list, lang_map: dict, suite: str) -> dict:
    """Check language diversity in the kept set."""
    langs = defaultdict(int)
    for task_info in kept_tasks:
        lang = lang_map.get(task_info["task_name"], "unknown")
        langs[lang] += 1
    return dict(langs)


def _load_doe_module():
    """Import doe_variance_analysis.py dynamically."""
    import importlib.util
    doe_spec = importlib.util.spec_from_file_location(
        "doe_variance_analysis",
        PROJECT_ROOT / "scripts" / "doe_variance_analysis.py"
    )
    doe_mod = importlib.util.module_from_spec(doe_spec)
    doe_spec.loader.exec_module(doe_mod)
    return doe_mod


def compute_neyman_allocation(manifest: dict, budget: int,
                              target_suites: list = None,
                              include_staging: bool = False) -> dict:
    """Compute Neyman-optimal allocation using the validated DOE variance decomposition.

    Delegates to doe_variance_analysis.py's ANOVA-based variance decomposition and
    Neyman allocation, which uses effective_var = sigma2_task + sigma2_rep/n_reps.

    Args:
        manifest: loaded MANIFEST.json dict
        budget: total task budget across all target_suites
        target_suites: list of suite names to allocate across (default: SDLC_SUITES)
        include_staging: also load results from runs/staging/

    Returns {suite: target_n}.
    """
    doe_mod = _load_doe_module()

    if target_suites is None:
        target_suites = SDLC_SUITES

    run_data = doe_mod.load_run_history(manifest)

    # Merge staging data if requested
    if include_staging:
        staging_data = doe_mod.load_staging_results(target_suites)
        run_data = doe_mod.merge_run_data(run_data, staging_data)

    config_arms = ["baseline", "mcp"]

    # Combined decomposition (same method as doe_variance_analysis main)
    combined_decomps = {}
    for suite in target_suites:
        suite_data = run_data.get(suite, {})
        if not suite_data:
            continue
        all_task_data = {}
        for config_type in config_arms:
            arm_data = suite_data.get(config_type, {})
            for task, rewards in arm_data.items():
                key = f"{task}_{config_type}"
                all_task_data[key] = rewards
        decomp = doe_mod.variance_decomposition_per_suite(all_task_data, min_reps=2)
        if decomp:
            combined_decomps[suite] = decomp

    # Effective variance for Neyman allocation: sigma2_task + sigma2_rep/n_reps
    n_reps = 3  # planned replicates
    effective_vars = {}
    for suite in target_suites:
        decomp = combined_decomps.get(suite)
        if decomp:
            effective_vars[suite] = decomp["sigma2_task"] + decomp["sigma2_rep"] / n_reps
        else:
            effective_vars[suite] = 0.05

    return doe_mod.neyman_allocation(effective_vars, budget)


def get_existing_tasks_on_disk(suite: str) -> set:
    """Get task names that exist on disk for a given suite."""
    suite_dir = BENCHMARKS_DIR / suite
    if not suite_dir.is_dir():
        return set()
    return {d.name for d in suite_dir.iterdir() if d.is_dir() and not d.name.startswith(".")}


def get_backup_tasks(suite: str) -> dict:
    """Get backup tasks available for promotion. Returns {task_name: backup_dir}."""
    # Backup dirs that are known-incompatible (require external servers, etc.)
    INCOMPATIBLE_BACKUP_DIRS = {"ccb_test_tac"}

    backups = {}
    # Look for suite-specific backup dirs
    for backup_dir in BACKUPS_DIR.iterdir():
        if not backup_dir.is_dir():
            continue
        if backup_dir.name in INCOMPATIBLE_BACKUP_DIRS:
            continue
        # Match backup dirs like csb_sdlc_fix_extra, ccb_fix_doe_trim, etc.
        suite_short = suite.replace("csb_sdlc_", "").replace("ccb_", "")
        if backup_dir.name.startswith(suite_short + "_") or \
           backup_dir.name.startswith(suite + "_"):
            for task_dir in backup_dir.iterdir():
                if task_dir.is_dir() and not task_dir.name.startswith("."):
                    backups[task_dir.name] = task_dir
    return backups


def generate_rebalance_plan(manifest: dict, budget: int, min_reps: int = 2,
                            target_suites: list = None,
                            include_staging: bool = False) -> dict:
    """Generate the full rebalance plan.

    Returns dict with per-suite keep/move/promote lists and summary.

    Args:
        target_suites: which suites to rebalance (default: SDLC_SUITES)
        include_staging: merge runs/staging/ data (needed for MCP-unique suites)
    """
    if target_suites is None:
        target_suites = SDLC_SUITES

    doe_mod = _load_doe_module()
    run_data = load_run_history(manifest)

    if include_staging:
        staging_data = doe_mod.load_staging_results(target_suites)
        run_data = doe_mod.merge_run_data(run_data, staging_data)

    allocation = compute_neyman_allocation(
        manifest, budget,
        target_suites=target_suites,
        include_staging=include_staging,
    )
    lang_map = load_task_languages()

    plan = {
        "budget": budget,
        "allocation": allocation,
        "suites": {},
    }

    for suite in target_suites:
        target_n = allocation.get(suite, 20)
        on_disk = get_existing_tasks_on_disk(suite)
        current_n = len(on_disk)
        delta_n = target_n - current_n

        suite_plan = {
            "current_n": current_n,
            "target_n": target_n,
            "delta": delta_n,
            "action": "grow" if delta_n > 0 else ("shrink" if delta_n < 0 else "unchanged"),
        }

        # Rank tasks by information value
        if suite in run_data:
            ranked = rank_tasks_in_suite(suite, run_data[suite], min_reps)
        else:
            ranked = []

        # Build case-insensitive mapping: lowercase(run_name) -> on_disk_name
        # Handles MANIFEST names like CCX-compliance-118 vs on-disk ccx-compliance-118
        on_disk_lower = {name.lower(): name for name in on_disk}
        for t in ranked:
            disk_name = on_disk_lower.get(t["task_name"].lower())
            if disk_name and disk_name != t["task_name"]:
                t["task_name"] = disk_name  # normalize to on-disk name

        # Map ranked tasks to on-disk tasks
        ranked_names = {t["task_name"] for t in ranked}
        unranked_on_disk = on_disk - ranked_names  # tasks without enough run data

        if delta_n < 0:
            # SHRINK: keep top target_n, move the rest
            # Prefer keeping tasks with data; unranked tasks are moved first
            n_to_keep_from_ranked = min(target_n, len(ranked))
            n_to_keep_from_unranked = target_n - n_to_keep_from_ranked

            keep_ranked = ranked[:n_to_keep_from_ranked]
            # If we need unranked tasks to fill (unlikely), keep some
            keep_unranked = sorted(unranked_on_disk)[:max(0, n_to_keep_from_unranked)]

            move_ranked = ranked[n_to_keep_from_ranked:]
            move_unranked = sorted(unranked_on_disk - set(keep_unranked))

            suite_plan["keep"] = [t["task_name"] for t in keep_ranked] + list(keep_unranked)
            suite_plan["move_to_backup"] = (
                [t["task_name"] for t in move_ranked] + move_unranked
            )
            suite_plan["ranked_tasks"] = [
                {
                    "task": t["task_name"],
                    "info_value": round(t["info_value"], 4),
                    "delta": round(t["delta"], 4),
                    "bl_mean": round(t["bl_mean"], 4),
                    "mcp_mean": round(t["mcp_mean"], 4),
                    "pooled_var": round(t["pooled_var"], 4),
                    "is_paired": t["is_paired"],
                    "action": "keep" if t["task_name"] in suite_plan["keep"] else "move",
                }
                for t in ranked
            ]

        elif delta_n > 0:
            # GROW: keep all current, add from backups or flag for scaffolding
            backups_available = get_backup_tasks(suite)
            n_to_add = delta_n
            promote = []
            scaffold = 0

            if backups_available:
                for task_name, backup_path in sorted(backups_available.items()):
                    if n_to_add <= 0:
                        break
                    promote.append({
                        "task_name": task_name,
                        "source": str(backup_path),
                    })
                    n_to_add -= 1

            scaffold = n_to_add  # remaining tasks need scaffolding

            suite_plan["keep"] = sorted(on_disk)
            suite_plan["move_to_backup"] = []
            suite_plan["promote_from_backup"] = promote
            suite_plan["scaffold_needed"] = scaffold
            suite_plan["ranked_tasks"] = [
                {
                    "task": t["task_name"],
                    "info_value": round(t["info_value"], 4),
                    "delta": round(t["delta"], 4),
                    "bl_mean": round(t["bl_mean"], 4),
                    "mcp_mean": round(t["mcp_mean"], 4),
                    "pooled_var": round(t["pooled_var"], 4),
                    "is_paired": t["is_paired"],
                    "action": "keep",
                }
                for t in ranked
            ]

        else:
            # UNCHANGED
            suite_plan["keep"] = sorted(on_disk)
            suite_plan["move_to_backup"] = []

        # Language diversity check
        kept_tasks = [t for t in ranked if t["task_name"] in set(suite_plan.get("keep", []))]
        suite_plan["language_diversity"] = check_language_diversity(kept_tasks, lang_map, suite)

        plan["suites"][suite] = suite_plan

    # Summary
    total_keep = sum(len(s["keep"]) for s in plan["suites"].values())
    total_move = sum(len(s["move_to_backup"]) for s in plan["suites"].values())
    total_promote = sum(len(s.get("promote_from_backup", [])) for s in plan["suites"].values())
    total_scaffold = sum(s.get("scaffold_needed", 0) for s in plan["suites"].values())

    plan["summary"] = {
        "total_keep": total_keep,
        "total_move_to_backup": total_move,
        "total_promote_from_backup": total_promote,
        "total_scaffold_needed": total_scaffold,
        "final_total": total_keep + total_promote + total_scaffold,
    }

    return plan


def print_plan(plan: dict):
    """Pretty-print the rebalance plan."""
    suite_list = sorted(plan["suites"].keys())

    print("=" * 80)
    print(f"DOE TASK REBALANCE PLAN (budget={plan['budget']})")
    print("=" * 80)
    print()

    # Allocation table
    print(f"{'Suite':<30} {'Current':>8} {'Target':>8} {'Delta':>8} {'Action':<12}")
    print("-" * 70)
    for suite in suite_list:
        sp = plan["suites"].get(suite, {})
        print(f"{suite:<30} {sp.get('current_n',0):>8} {sp.get('target_n',0):>8} "
              f"{sp.get('delta',0):>+8} {sp.get('action','?'):<12}")
    print("-" * 70)
    s = plan["summary"]
    print(f"Total: keep={s['total_keep']}, move={s['total_move_to_backup']}, "
          f"promote={s['total_promote_from_backup']}, scaffold={s['total_scaffold_needed']}")
    print()

    # Per-suite details
    for suite in suite_list:
        sp = plan["suites"].get(suite, {})
        if sp.get("action") == "unchanged":
            continue

        print(f"\n--- {suite} ({sp['action'].upper()}: {sp['current_n']} -> {sp['target_n']}) ---")

        if sp.get("move_to_backup"):
            print(f"\n  MOVE to backup ({len(sp['move_to_backup'])} tasks):")
            ranked = sp.get("ranked_tasks", [])
            moved_info = {t["task"]: t for t in ranked if t.get("action") == "move"}
            for task_name in sp["move_to_backup"]:
                info = moved_info.get(task_name)
                if info:
                    print(f"    {task_name:<50} iv={info['info_value']:.4f} "
                          f"delta={info['delta']:+.4f} bl={info['bl_mean']:.3f} mcp={info['mcp_mean']:.3f}")
                else:
                    print(f"    {task_name:<50} (no run data)")

        if sp.get("promote_from_backup"):
            print(f"\n  PROMOTE from backup ({len(sp['promote_from_backup'])} tasks):")
            for p in sp["promote_from_backup"]:
                print(f"    {p['task_name']:<50} from {p['source']}")

        if sp.get("scaffold_needed", 0) > 0:
            print(f"\n  SCAFFOLD: {sp['scaffold_needed']} new tasks needed")

        if sp.get("ranked_tasks"):
            print(f"\n  Task ranking (top to bottom by info value):")
            for i, t in enumerate(sp["ranked_tasks"][:sp["target_n"] + 5]):
                marker = "KEEP" if t["action"] == "keep" else "MOVE"
                print(f"    {i+1:3d}. [{marker}] {t['task']:<45} iv={t['info_value']:.4f} "
                      f"delta={t['delta']:+.4f}")

        if sp.get("language_diversity"):
            langs = sp["language_diversity"]
            print(f"\n  Language diversity (kept): {dict(sorted(langs.items()))}")


def execute_rebalance(plan: dict, dry_run: bool = True):
    """Execute the rebalance plan by moving task directories."""
    import shutil

    suite_list = sorted(plan["suites"].keys())
    actions = []
    for suite in suite_list:
        sp = plan["suites"].get(suite, {})

        # Move tasks to backup
        for task_name in sp.get("move_to_backup", []):
            src = BENCHMARKS_DIR / suite / task_name
            backup_subdir = f"{suite}_doe_trim"
            dst_parent = BACKUPS_DIR / backup_subdir
            dst = dst_parent / task_name

            if not src.is_dir():
                print(f"WARNING: {src} does not exist, skipping")
                continue

            actions.append(("move", src, dst, dst_parent))

        # Promote tasks from backup
        for promo in sp.get("promote_from_backup", []):
            src = Path(promo["source"])
            dst = BENCHMARKS_DIR / suite / promo["task_name"]

            if not src.is_dir():
                print(f"WARNING: {src} does not exist, skipping")
                continue

            actions.append(("promote", src, dst, None))

    if dry_run:
        print(f"\n{'='*60}")
        print(f"DRY RUN: {len(actions)} actions would be performed")
        print(f"{'='*60}")
        for action_type, src, dst, _ in actions:
            print(f"  {action_type.upper()}: {src} -> {dst}")
        return

    print(f"\nExecuting {len(actions)} actions...")
    for action_type, src, dst, dst_parent in actions:
        if dst_parent:
            dst_parent.mkdir(parents=True, exist_ok=True)
        print(f"  {action_type.upper()}: {src.name} -> {dst}")
        shutil.move(str(src), str(dst))

    print(f"\nDone. {len(actions)} tasks moved.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="DOE-driven task rebalance")
    parser.add_argument("--budget", type=int, default=150,
                        help="Total task budget (default: 150 for SDLC, 220 for MCP-unique)")
    parser.add_argument("--min-reps", type=int, default=2,
                        help="Minimum replicates for a task to be ranked (default: 2)")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON")
    parser.add_argument("--execute", action="store_true",
                        help="Actually move directories (default: dry run preview)")
    parser.add_argument("--mcp-unique-only", action="store_true",
                        help="Rebalance MCP-unique suites instead of SDLC (budget default: 220)")
    parser.add_argument("--include-staging", action="store_true",
                        help="Also load results from runs/staging/")
    args = parser.parse_args()

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    if args.mcp_unique_only:
        target_suites = MCP_UNIQUE_SUITES
        budget = args.budget if args.budget != 150 else 220  # default to 220 for MCP-unique
        include_staging = True  # always needed for MCP-unique
    else:
        target_suites = SDLC_SUITES
        budget = args.budget
        include_staging = args.include_staging

    plan = generate_rebalance_plan(
        manifest, budget, args.min_reps,
        target_suites=target_suites,
        include_staging=include_staging,
    )

    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print_plan(plan)

        if args.execute:
            print("\n" + "!" * 60)
            print("EXECUTING REBALANCE - moving task directories!")
            print("!" * 60)
            execute_rebalance(plan, dry_run=False)
        else:
            execute_rebalance(plan, dry_run=True)
            print("\nRun with --execute to actually move directories.")


if __name__ == "__main__":
    main()

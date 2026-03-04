#!/usr/bin/env python3
"""Generate minimal coverage gap-fill selection files for SDLC and Org suites.

Scans the actual filesystem (official + staging runs) to compute per-task,
per-config (baseline vs MCP) run counts, then generates the bare-minimum
selection files needed to reach 3 paired runs per task.

Output files go to configs/coverage_gap_20260302/ with separate files for:
  - Daytona vs Local (sweap-image tasks)
  - baseline-only vs mcp-only vs both

Usage:
    python3 scripts/generate_coverage_gap_configs.py [--target 3] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_DIR = PROJECT_ROOT / "runs" / "official"
STAGING_DIR = PROJECT_ROOT / "runs" / "staging"
SELECTION_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"
OUTPUT_DIR = PROJECT_ROOT / "configs" / "coverage_gap_20260302"

# Sweap-image tasks that must use local Docker, not Daytona
SWEAP_TASKS = {
    "ansible-galaxy-tar-regression-prove-001",
    "flipt-auth-cookie-regression-prove-001",
    "qutebrowser-hsv-color-regression-prove-001",
    "qutebrowser-adblock-cache-regression-prove-001",
    "qutebrowser-darkmode-threshold-regression-prove-001",
    "qutebrowser-url-regression-prove-001",
    "teleport-ssh-regression-prove-001",
    "tutanota-search-regression-prove-001",
    "vuls-oval-regression-prove-001",
    "ansible-abc-imports-fix-001",
    "ansible-module-respawn-fix-001",
    "flipt-cockroachdb-backend-fix-001",
    "flipt-ecr-auth-oci-fix-001",
    "navidrome-windows-log-fix-001",
    "nodebb-notif-dropdown-fix-001",
    "nodebb-plugin-validate-fix-001",
    "openlibrary-solr-boolean-fix-001",
    "openlibrary-search-query-fix-001",
    "flipt-otlp-exporter-fix-001",
    "flipt-trace-sampling-fix-001",
    "openlibrary-fntocli-adapter-fix-001",
}


def normalize_task_name(raw_name: str) -> str:
    """Strip mcp_/bl_/sgonly_ prefix and _[random] Harbor suffix, lowercase."""
    name = raw_name
    for prefix in ("mcp_", "bl_", "sgonly_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"_[a-zA-Z0-9]{4,8}$", "", name)
    return name.lower()


def extract_task_name(config_path: Path) -> str | None:
    """Extract normalized task name from a Harbor config.json."""
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        tasks = cfg.get("tasks", [])
        if tasks:
            path = tasks[0] if isinstance(tasks[0], str) else tasks[0].get("path", "")
            if not path:
                return None
            return normalize_task_name(path.rstrip("/").split("/")[-1])
    except Exception:
        return None


def is_baseline(config_name: str) -> bool:
    return "baseline" in config_name.lower()


def is_mcp(config_name: str) -> bool:
    return "mcp" in config_name.lower() or "sg" in config_name.lower()


def scan_runs(base_dir: Path, prefix_filters: list[str]) -> dict[str, dict[str, set]]:
    """Scan run directories and return {task_lower: {baseline: set(runs), mcp: set(runs)}}."""
    results: dict[str, dict[str, set]] = defaultdict(lambda: {"baseline": set(), "mcp": set()})
    if not base_dir.exists():
        return results

    for run_dir in base_dir.iterdir():
        if not run_dir.is_dir() or run_dir.name.startswith("__"):
            continue
        if not any(run_dir.name.startswith(p) for p in prefix_filters):
            continue

        for config_dir in run_dir.iterdir():
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name

            for ts_dir in config_dir.iterdir():
                if not ts_dir.is_dir():
                    continue
                config_file = ts_dir / "config.json"
                if not config_file.exists():
                    continue
                task = extract_task_name(config_file)
                if not task:
                    continue
                if is_baseline(config_name):
                    results[task]["baseline"].add(run_dir.name)
                elif is_mcp(config_name):
                    results[task]["mcp"].add(run_dir.name)

    return results


def main():
    parser = argparse.ArgumentParser(description="Generate coverage gap-fill configs")
    parser.add_argument("--target", type=int, default=3, help="Target paired runs per task")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    args = parser.parse_args()

    # Load canonical tasks
    with open(SELECTION_PATH) as f:
        data = json.load(f)

    canonical_tasks: dict[str, dict] = {}  # task_lower -> full task entry
    for t in data["tasks"]:
        canonical_tasks[t["task_id"].lower()] = t

    # Scan all runs
    all_results: dict[str, dict[str, set]] = defaultdict(lambda: {"baseline": set(), "mcp": set()})
    for prefix_list in [
        ["csb_sdlc_", "ccb_",        # SDLC (including old prefix and build suite)
         "feature_", "refactor_", "debug_", "design_", "document_",
         "fix_", "secure_", "test_", "understand_"],  # bare legacy SDLC prefixes
        ["csb_org_", "ccb_mcp_"],    # Org
    ]:
        for base in [OFFICIAL_DIR, STAGING_DIR]:
            results = scan_runs(base, prefix_list)
            for task, configs in results.items():
                all_results[task]["baseline"] |= configs["baseline"]
                all_results[task]["mcp"] |= configs["mcp"]

    # Compute gaps
    gap_tasks: list[dict] = []  # entries with bl_need, mcp_need fields added
    for task_lower, task_entry in canonical_tasks.items():
        bl_count = len(all_results[task_lower]["baseline"])
        mcp_count = len(all_results[task_lower]["mcp"])
        bl_need = max(0, args.target - bl_count)
        mcp_need = max(0, args.target - mcp_count)

        if bl_need > 0 or mcp_need > 0:
            entry = dict(task_entry)
            entry["_bl_count"] = bl_count
            entry["_mcp_count"] = mcp_count
            entry["_bl_need"] = bl_need
            entry["_mcp_need"] = mcp_need
            gap_tasks.append(entry)

    # Classify tasks
    sdlc_daytona_bl_only = []
    sdlc_daytona_mcp_only = []
    sdlc_daytona_both = []
    sdlc_local_bl_only = []
    sdlc_local_mcp_only = []
    sdlc_local_both = []
    org_bl_only = []
    org_mcp_only = []
    org_both = []

    for entry in gap_tasks:
        task_id_lower = entry["task_id"].lower()
        benchmark = entry["benchmark"]
        bl_need = entry["_bl_need"]
        mcp_need = entry["_mcp_need"]
        is_sweap = task_id_lower in SWEAP_TASKS
        is_sdlc = benchmark.startswith("csb_sdlc_")
        is_org = benchmark.startswith("csb_org_")

        if is_sdlc:
            if is_sweap:
                if bl_need > 0 and mcp_need > 0:
                    sdlc_local_both.append(entry)
                elif bl_need > 0:
                    sdlc_local_bl_only.append(entry)
                else:
                    sdlc_local_mcp_only.append(entry)
            else:
                if bl_need > 0 and mcp_need > 0:
                    sdlc_daytona_both.append(entry)
                elif bl_need > 0:
                    sdlc_daytona_bl_only.append(entry)
                else:
                    sdlc_daytona_mcp_only.append(entry)
        elif is_org:
            if bl_need > 0 and mcp_need > 0:
                org_both.append(entry)
            elif bl_need > 0:
                org_bl_only.append(entry)
            else:
                org_mcp_only.append(entry)

    # Compute total agent runs needed per wave
    # Each wave runs tasks that need N more runs; max(bl_need, mcp_need) determines waves
    max_waves = max((max(e["_bl_need"], e["_mcp_need"]) for e in gap_tasks), default=0)

    # Print summary
    print(f"Target: {args.target} paired runs per task")
    print(f"Canonical tasks: {len(canonical_tasks)}")
    print(f"Tasks below target: {len(gap_tasks)}")
    print()

    # Per-suite summary
    suite_gaps = defaultdict(lambda: {"total": 0, "bl_runs": 0, "mcp_runs": 0})
    for e in gap_tasks:
        s = e["benchmark"]
        suite_gaps[s]["total"] += 1
        suite_gaps[s]["bl_runs"] += e["_bl_need"]
        suite_gaps[s]["mcp_runs"] += e["_mcp_need"]

    print(f"{'Suite':40s} {'Tasks':>6s} {'BL need':>8s} {'MCP need':>9s}")
    print("-" * 65)
    for suite in sorted(suite_gaps.keys()):
        g = suite_gaps[suite]
        print(f"{suite:40s} {g['total']:6d} {g['bl_runs']:8d} {g['mcp_runs']:9d}")
    total_bl = sum(g["bl_runs"] for g in suite_gaps.values())
    total_mcp = sum(g["mcp_runs"] for g in suite_gaps.values())
    print("-" * 65)
    print(f"{'TOTAL':40s} {len(gap_tasks):6d} {total_bl:8d} {total_mcp:9d}")
    print(f"\nTotal agent runs needed: {total_bl + total_mcp}")
    print()

    # Batch breakdown
    batches = [
        ("sdlc_daytona_both", sdlc_daytona_both, "both", "daytona"),
        ("sdlc_daytona_bl_only", sdlc_daytona_bl_only, "baseline-only", "daytona"),
        ("sdlc_daytona_mcp_only", sdlc_daytona_mcp_only, "mcp-only", "daytona"),
        ("sdlc_local_both", sdlc_local_both, "both", "local"),
        ("sdlc_local_bl_only", sdlc_local_bl_only, "baseline-only", "local"),
        ("sdlc_local_mcp_only", sdlc_local_mcp_only, "mcp-only", "local"),
        ("org_bl_only", org_bl_only, "baseline-only", "daytona"),
        ("org_mcp_only", org_mcp_only, "mcp-only", "daytona"),
        ("org_both", org_both, "both", "daytona"),
    ]

    print("=== BATCH FILES ===\n")
    files_to_write = {}
    commands = []

    for batch_name, tasks_list, config_mode, env in batches:
        if not tasks_list:
            continue

        # For "both" batches, we need multiple waves
        # Wave N includes tasks that need N or more runs
        max_need = max(max(e["_bl_need"], e["_mcp_need"]) for e in tasks_list)

        for wave in range(1, max_need + 1):
            # Include tasks that need >= wave runs
            wave_tasks = [e for e in tasks_list if (
                (config_mode == "both" and (e["_bl_need"] >= wave or e["_mcp_need"] >= wave)) or
                (config_mode == "baseline-only" and e["_bl_need"] >= wave) or
                (config_mode == "mcp-only" and e["_mcp_need"] >= wave)
            )]
            if not wave_tasks:
                continue

            # For "both" mode, split into sub-batches per wave
            # Tasks that only need baseline this wave go to bl_only, etc.
            if config_mode == "both":
                wave_bl = [e for e in wave_tasks if e["_bl_need"] >= wave and e["_mcp_need"] >= wave]
                wave_bl_only = [e for e in wave_tasks if e["_bl_need"] >= wave and e["_mcp_need"] < wave]
                wave_mcp_only = [e for e in wave_tasks if e["_mcp_need"] >= wave and e["_bl_need"] < wave]

                for sub_name, sub_tasks, sub_mode in [
                    (f"{batch_name}_wave{wave}", wave_bl, ""),
                    (f"{batch_name}_wave{wave}_bl_extra", wave_bl_only, "--baseline-only"),
                    (f"{batch_name}_wave{wave}_mcp_extra", wave_mcp_only, "--full-only"),
                ]:
                    if not sub_tasks:
                        continue
                    fname = f"{sub_name}.json"
                    bl_runs = sum(1 for e in sub_tasks if e["_bl_need"] >= wave)
                    mcp_runs = sum(1 for e in sub_tasks if e["_mcp_need"] >= wave)
                    print(f"  {fname}: {len(sub_tasks)} tasks (bl={bl_runs}, mcp={mcp_runs}) [{env}]")

                    # Clean entries for output
                    clean_tasks = []
                    for e in sub_tasks:
                        clean = {k: v for k, v in e.items() if not k.startswith("_")}
                        clean_tasks.append(clean)
                    files_to_write[fname] = {"tasks": clean_tasks}

                    flag = sub_mode or ""
                    if env == "daytona":
                        cmd = f"./configs/run_selected_tasks.sh --selection-file configs/coverage_gap_20260302/{fname} --category staging {flag}".strip()
                    else:
                        cmd = f"HARBOR_ENV= ./configs/run_selected_tasks.sh --selection-file configs/coverage_gap_20260302/{fname} --category staging {flag}".strip()
                    commands.append((wave, env, cmd))
            else:
                fname = f"{batch_name}_wave{wave}.json"
                flag = "--baseline-only" if config_mode == "baseline-only" else "--full-only"
                print(f"  {fname}: {len(wave_tasks)} tasks [{env}] {flag}")

                clean_tasks = [{k: v for k, v in e.items() if not k.startswith("_")} for e in wave_tasks]
                files_to_write[fname] = {"tasks": clean_tasks}

                if env == "daytona":
                    cmd = f"./configs/run_selected_tasks.sh --selection-file configs/coverage_gap_20260302/{fname} --category staging {flag}"
                else:
                    cmd = f"HARBOR_ENV= ./configs/run_selected_tasks.sh --selection-file configs/coverage_gap_20260302/{fname} --category staging {flag}"
                commands.append((wave, env, cmd))

    print()
    print("=== EXECUTION PLAN ===\n")
    print("# Prerequisites:")
    print("source .env.local && export HARBOR_ENV=daytona && export DAYTONA_OVERRIDE_STORAGE=10240")
    print()

    # Group by wave
    for wave_num in sorted(set(w for w, _, _ in commands)):
        daytona_cmds = [c for w, e, c in commands if w == wave_num and e == "daytona"]
        local_cmds = [c for w, e, c in commands if w == wave_num and e == "local"]

        print(f"# === Wave {wave_num} ===")
        if daytona_cmds:
            print(f"# Daytona ({len(daytona_cmds)} batches):")
            for c in daytona_cmds:
                print(c)
            print()
        if local_cmds:
            print(f"# Local Docker ({len(local_cmds)} batches):")
            for c in local_cmds:
                print(c)
            print()

    # Write files
    if args.dry_run:
        print(f"[DRY RUN] Would write {len(files_to_write)} files to {OUTPUT_DIR}/")
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for fname, content in files_to_write.items():
            out_path = OUTPUT_DIR / fname
            with open(out_path, "w") as f:
                json.dump(content, f, indent=2)
            print(f"  Wrote {out_path}")
        print(f"\nWrote {len(files_to_write)} selection files to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()

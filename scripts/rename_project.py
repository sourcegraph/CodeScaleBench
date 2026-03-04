#!/usr/bin/env python3
"""Bulk rename migration: CodeContextBench → CodeScaleBench.

Handles:
1. Benchmark directory renames (git mv)
2. Backup directory renames (git mv)
3. Run output directory renames (git mv)
4. task.toml field updates (category, mcp_suite)
5. task_spec.json field updates (mcp_suite)
6. JSON config file updates (selected_benchmark_tasks.json, rerun configs, etc.)

Usage:
    python3 scripts/rename_project.py              # dry-run (default)
    python3 scripts/rename_project.py --execute     # actually perform renames
    python3 scripts/rename_project.py --dirs-only   # only rename directories
    python3 scripts/rename_project.py --metadata-only  # only update file contents
"""

import argparse
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# Suite Definitions
# ============================================================

SDLC_SUITES = [
    "debug", "design", "document", "feature", "fix",
    "refactor", "secure", "test", "understand",
]

MCP_SUITES = [
    "compliance", "crossorg", "crossrepo", "crossrepo_tracing",
    "domain", "incident", "migration", "onboarding", "org",
    "platform", "security",
]

# Directory rename mappings
DIR_RENAMES: dict[str, str] = {}

# SDLC: ccb_{suite} → csb_sdlc_{suite}
for s in SDLC_SUITES:
    DIR_RENAMES[f"ccb_{s}"] = f"csb_sdlc_{s}"

# MCP-unique: ccb_mcp_{suite} → csb_org_{suite}
for s in MCP_SUITES:
    DIR_RENAMES[f"ccb_mcp_{s}"] = f"csb_org_{s}"

# Legacy: ccb_build → csb_sdlc_build (exists in run dirs)
DIR_RENAMES["ccb_build"] = "csb_sdlc_build"

# Exclusions
SKIP_PATTERNS = {"ccb_contextbench"}


def _should_skip(name: str) -> bool:
    """Check if a directory name should be skipped."""
    # Strip decoration prefixes
    bare = name
    for prefix in ("__archived_", "__duplicate_", "__broken_verifier_"):
        if bare.startswith(prefix):
            bare = bare[len(prefix):]
            break
    return any(skip in bare for skip in SKIP_PATTERNS)


def _rename_dir_name(name: str) -> str | None:
    """Compute the new name for a directory. Returns None if no rename needed."""
    if _should_skip(name):
        return None

    # Handle decoration prefixes (__archived_, __duplicate_, etc.)
    decoration = ""
    bare = name
    for prefix in ("__archived_", "__duplicate_", "__broken_verifier_"):
        if bare.startswith(prefix):
            decoration = prefix
            bare = bare[len(prefix):]
            break

    # Try exact match first (benchmark/backup dirs)
    if bare in DIR_RENAMES:
        return decoration + DIR_RENAMES[bare]

    # Try prefix match (run dirs like ccb_fix_haiku_20260301_...)
    # Must match longest prefix first to avoid ccb_mcp_crossrepo matching before ccb_mcp_crossrepo_tracing
    sorted_prefixes = sorted(DIR_RENAMES.keys(), key=len, reverse=True)
    for old_prefix in sorted_prefixes:
        if bare.startswith(old_prefix + "_") or bare == old_prefix:
            suffix = bare[len(old_prefix):]
            return decoration + DIR_RENAMES[old_prefix] + suffix

    return None


def _rename_suite_in_text(text: str) -> str:
    """Replace ccb_ suite names in text content.

    Handles both ccb_mcp_ (longer prefix, matched first) and ccb_ (SDLC).
    Skips ccb_contextbench.
    """
    result = text

    # MCP suites first (longer prefix prevents partial matches)
    # Must do crossrepo_tracing before crossrepo
    for s in sorted(MCP_SUITES, key=len, reverse=True):
        result = result.replace(f"ccb_mcp_{s}", f"csb_org_{s}")

    # SDLC suites
    for s in SDLC_SUITES:
        result = result.replace(f"ccb_{s}", f"csb_sdlc_{s}")

    # Legacy ccb_build
    result = result.replace("ccb_build", "csb_sdlc_build")

    return result


def _rename_suite_in_json_value(value):
    """Recursively rename suite references in JSON values."""
    if isinstance(value, str):
        return _rename_suite_in_text(value)
    elif isinstance(value, list):
        return [_rename_suite_in_json_value(v) for v in value]
    elif isinstance(value, dict):
        new_dict = {}
        for k, v in value.items():
            new_key = _rename_suite_in_text(k)
            new_dict[new_key] = _rename_suite_in_json_value(v)
        return new_dict
    return value


# ============================================================
# Phase 1: Directory Renames
# ============================================================

def find_dirs_to_rename(base_dir: Path) -> list[tuple[Path, Path]]:
    """Find directories under base_dir that need renaming."""
    renames = []
    if not base_dir.exists():
        return renames

    for entry in sorted(base_dir.iterdir()):
        if not entry.is_dir():
            continue
        new_name = _rename_dir_name(entry.name)
        if new_name and new_name != entry.name:
            renames.append((entry, entry.parent / new_name))

    return renames


def _smart_rename(old: Path, new: Path) -> None:
    """Use git mv for tracked dirs, plain mv for untracked or problematic."""
    result = subprocess.run(
        ["git", "mv", str(old), str(new)],
        capture_output=True, cwd=REPO_ROOT
    )
    if result.returncode != 0:
        # Fallback: plain rename for untracked or partially-deleted dirs
        import shutil
        shutil.move(str(old), str(new))


def rename_directories(execute: bool) -> int:
    """Rename benchmark, backup, and run directories."""
    total = 0

    # Benchmark dirs
    bench_dir = REPO_ROOT / "benchmarks"
    renames = find_dirs_to_rename(bench_dir)
    if renames:
        print(f"\n  Benchmark directories ({len(renames)}):")
        for old, new in renames:
            print(f"    {old.name} → {new.name}")
            if execute:
                _smart_rename(old, new)
            total += 1

    # Backup dirs
    backup_dir = REPO_ROOT / "benchmarks" / "backups"
    renames = find_dirs_to_rename(backup_dir)
    if renames:
        print(f"\n  Backup directories ({len(renames)}):")
        for old, new in renames:
            print(f"    {old.name} → {new.name}")
            if execute:
                _smart_rename(old, new)
            total += 1

    # Run output dirs (official, staging, archive, backup_runs)
    for run_category in ["official", "staging", "archive", "backup_runs"]:
        run_dir = REPO_ROOT / "runs" / run_category
        renames = find_dirs_to_rename(run_dir)
        if renames:
            print(f"\n  Run dirs - {run_category} ({len(renames)}):")
            for old, new in renames:
                print(f"    {old.name} → {new.name}")
                if execute:
                    _smart_rename(old, new)
                total += 1

    return total


# ============================================================
# Phase 2: Task Metadata Updates
# ============================================================

def update_task_tomls(execute: bool) -> int:
    """Update mcp_suite and category fields in task.toml files."""
    count = 0
    bench_dir = REPO_ROOT / "benchmarks"

    for toml_path in sorted(bench_dir.rglob("task.toml")):
        # Skip ccb_contextbench
        if "ccb_contextbench" in str(toml_path):
            continue

        text = toml_path.read_text()
        new_text = text

        # Replace mcp_suite values: mcp_suite = "ccb_mcp_X" → mcp_suite = "csb_org_X"
        for s in sorted(MCP_SUITES, key=len, reverse=True):
            new_text = new_text.replace(
                f'mcp_suite = "ccb_mcp_{s}"',
                f'mcp_suite = "csb_org_{s}"'
            )

        # Replace category values that reference ccb_ suites
        # category = "ccb_swebenchpro" → leave as-is (legacy, not our renamed suites)
        # We only rename if category is exactly a suite we're renaming
        for s in SDLC_SUITES:
            new_text = new_text.replace(
                f'category = "ccb_{s}"',
                f'category = "csb_sdlc_{s}"'
            )

        if new_text != text:
            count += 1
            rel = toml_path.relative_to(REPO_ROOT)
            if execute:
                toml_path.write_text(new_text)
            else:
                print(f"    [toml] {rel}")

    return count


def update_task_specs(execute: bool) -> int:
    """Update mcp_suite field in task_spec.json files."""
    count = 0
    bench_dir = REPO_ROOT / "benchmarks"

    for spec_path in sorted(bench_dir.rglob("task_spec.json")):
        if "ccb_contextbench" in str(spec_path):
            continue

        try:
            data = json.loads(spec_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        changed = False
        if "mcp_suite" in data and isinstance(data["mcp_suite"], str):
            new_val = _rename_suite_in_text(data["mcp_suite"])
            if new_val != data["mcp_suite"]:
                data["mcp_suite"] = new_val
                changed = True

        if changed:
            count += 1
            rel = spec_path.relative_to(REPO_ROOT)
            if execute:
                spec_path.write_text(json.dumps(data, indent=2) + "\n")
            else:
                print(f"    [spec] {rel}")

    return count


# ============================================================
# Phase 3: JSON Config Updates
# ============================================================

def update_json_configs(execute: bool) -> int:
    """Update suite references in JSON config files."""
    count = 0
    configs_dir = REPO_ROOT / "configs"

    for json_path in sorted(configs_dir.glob("*.json")):
        try:
            text = json_path.read_text()
            data = json.loads(text)
        except (json.JSONDecodeError, OSError):
            continue

        # Skip if no ccb_ references
        if "ccb_" not in text:
            continue
        # Skip if ccb_contextbench only
        if text.replace("ccb_contextbench", "") == text.replace("ccb_", ""):
            continue

        new_data = _rename_suite_in_json_value(data)
        new_text = json.dumps(new_data, indent=2) + "\n"

        if new_text != text:
            count += 1
            if execute:
                json_path.write_text(new_text)
            else:
                print(f"    [json] {json_path.name}")

    return count


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Rename CodeContextBench → CodeScaleBench (directory + metadata migration)"
    )
    parser.add_argument("--execute", action="store_true",
                       help="Actually perform renames (default: dry-run)")
    parser.add_argument("--dirs-only", action="store_true",
                       help="Only rename directories, skip metadata updates")
    parser.add_argument("--metadata-only", action="store_true",
                       help="Only update file contents, skip directory renames")
    args = parser.parse_args()

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== CodeContextBench → CodeScaleBench Migration ({mode}) ===\n")

    dir_count = 0
    toml_count = 0
    spec_count = 0
    json_count = 0

    if not args.metadata_only:
        print("Phase 1: Directory renames")
        dir_count = rename_directories(args.execute)
        print(f"\n  Total directories: {dir_count}")

    if not args.dirs_only:
        print("\nPhase 2: Task TOML updates")
        toml_count = update_task_tomls(args.execute)
        print(f"  Total task.toml files: {toml_count}")

        print("\nPhase 3: Task spec updates")
        spec_count = update_task_specs(args.execute)
        print(f"  Total task_spec.json files: {spec_count}")

        print("\nPhase 4: JSON config updates")
        json_count = update_json_configs(args.execute)
        print(f"  Total JSON configs: {json_count}")

    print(f"\n=== Summary ===")
    print(f"  Directories:   {dir_count}")
    print(f"  task.toml:     {toml_count}")
    print(f"  task_spec.json:{spec_count}")
    print(f"  JSON configs:  {json_count}")
    print(f"  Mode:          {mode}")

    if not args.execute:
        print("\n  Run with --execute to apply changes.")


if __name__ == "__main__":
    main()

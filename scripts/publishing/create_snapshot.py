#!/usr/bin/env python3
"""Create a snapshot from completed run results.

Scans run directories, symlinks traces, computes summaries, and generates browse.html.

Usage:
    # From a suite + model + staging runs
    python3 scripts/publishing/create_snapshot.py \
        --suite benchmarks/suites/csb-v2-dual264.json \
        --model haiku45 \
        --tag 040101 \
        --scan-dirs runs/staging runs/official/_raw

    # List existing snapshots
    python3 scripts/publishing/create_snapshot.py --list
"""
import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "runs" / "snapshots"

MODEL_MAP = {
    "haiku45": "claude-haiku-4-5-20251001",
    "sonnet46": "claude-sonnet-4-6",
    "opus46": "claude-opus-4-6",
}

CONFIGS_SET = {
    "augment-local-direct", "github-remote-direct", "mcp-remote-direct",
    "baseline-local-direct", "mcp-remote-artifact", "baseline-local-artifact",
    "augment-remote-direct",
}


def norm_task(name: str) -> str:
    # Task IDs were renamed from CCX-* to ccx-*; fold case so both spellings
    # merge into one task instead of colliding on case-insensitive filesystems.
    for prefix in ("mcp_", "bl_", "sgonly_", "artifact_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = re.sub(r"__[A-Za-z0-9]{7}$", "", name)
    return re.sub(r"_+[A-Za-z0-9]{4,8}$", "", name).lower()


def scan_results(scan_dirs: list[Path], model_short: str) -> dict:
    """Scan directories for reward.txt files matching the model."""
    import subprocess

    results = defaultdict(lambda: defaultdict(lambda: (-999, "")))

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        proc = subprocess.run(
            ["find", str(scan_dir), "-name", "reward.txt", "-path", "*/verifier/*"],
            capture_output=True, text=True, timeout=60,
        )
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("/")
            config = model = None
            for p in parts:
                if p in CONFIGS_SET:
                    config = p
                for m in MODEL_MAP:
                    if m.replace("45", "").replace("46", "") in p and not model:
                        model = m.replace("45", "").replace("46", "")
            if not config or not model or model != model_short.replace("45", "").replace("46", ""):
                continue

            vi = parts.index("verifier")
            trial_dir = "/".join(parts[:vi])
            trial_name = parts[vi - 1]
            task = norm_task(trial_name)

            try:
                reward = float(open(line).read().strip())
            except (ValueError, OSError):
                continue

            if reward > results[config][task][0]:
                results[config][task] = (reward, trial_dir)

    return results


def create_snapshot(
    suite_path: Path,
    model_short: str,
    tag: str,
    scan_dirs: list[Path],
    description: str = "",
    expansion_of: str = None,
) -> Path:
    suite = json.load(open(suite_path))
    suite_id = suite["suite_id"]
    model_full = MODEL_MAP.get(model_short, model_short)
    snapshot_id = f"{suite_id}--{model_short}--{tag}"
    snap_dir = SNAPSHOTS_DIR / snapshot_id

    print(f"Creating snapshot: {snapshot_id}")
    print(f"  Suite: {suite_id} ({suite['task_count']} tasks)")
    print(f"  Model: {model_full}")
    print(f"  Scanning: {', '.join(str(d) for d in scan_dirs)}")

    results = scan_results(scan_dirs, model_short)

    traces_dir = snap_dir / "traces"
    summary_dir = snap_dir / "summary"
    traces_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    rewards_data = {}
    linked = 0
    configs_found = set()

    for config, tasks in sorted(results.items()):
        config_dir = traces_dir / config
        config_dir.mkdir(parents=True, exist_ok=True)
        configs_found.add(config)

        for task, (reward, trial_path) in sorted(tasks.items()):
            link = config_dir / task
            if link.exists() or link.is_symlink():
                link.unlink()

            trial_p = Path(trial_path)
            if trial_p.exists():
                link.symlink_to(trial_p.resolve())
                linked += 1

            if task not in rewards_data:
                rewards_data[task] = {}
            rewards_data[task][config] = reward

    # Summary
    with open(summary_dir / "rewards.json", "w") as f:
        json.dump({"snapshot_id": snapshot_id, "generated": datetime.utcnow().isoformat() + "Z",
                    "tasks": rewards_data}, f, indent=2)

    agg = {}
    for config in sorted(configs_found):
        rvals = [rewards_data[t][config] for t in rewards_data if config in rewards_data[t]]
        agg[config] = {
            "task_count": len(rvals),
            "mean_reward": round(statistics.mean(rvals), 4) if rvals else None,
        }

    with open(summary_dir / "aggregate.json", "w") as f:
        json.dump({"snapshot_id": snapshot_id, "generated": datetime.utcnow().isoformat() + "Z",
                    "configs": agg}, f, indent=2)

    manifest = {
        "snapshot_id": snapshot_id,
        "suite_id": suite_id,
        "model": model_full,
        "configs": sorted(configs_found),
        "created": datetime.utcnow().strftime("%Y-%m-%d"),
        "frozen": True,
        "description": description or f"{model_full} results on {suite_id}",
        "task_count": len(rewards_data),
        "aggregate": agg,
        "expansion_of": expansion_of,
    }
    with open(snap_dir / "SNAPSHOT.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Linked {linked} traces, {len(rewards_data)} unique tasks")
    for config, a in agg.items():
        print(f"    {config}: {a['task_count']} tasks, mean={a['mean_reward']}")

    return snap_dir


def main():
    parser = argparse.ArgumentParser(description="Create a results snapshot")
    parser.add_argument("--suite", help="Path to suite JSON")
    parser.add_argument("--model", help="Model short name (haiku45, sonnet46, opus46)")
    parser.add_argument("--tag", help="Snapshot tag (date or descriptive, e.g. 040101, mcp-comparison)")
    parser.add_argument("--scan-dirs", nargs="+", help="Directories to scan for results")
    parser.add_argument("--description", default="", help="Snapshot description")
    parser.add_argument("--expansion-of", default=None, help="Parent snapshot ID")
    parser.add_argument("--list", action="store_true", help="List existing snapshots")
    args = parser.parse_args()

    if args.list:
        for d in sorted(SNAPSHOTS_DIR.iterdir()):
            if d.is_dir() and (d / "SNAPSHOT.json").exists():
                m = json.load(open(d / "SNAPSHOT.json"))
                print(f"  {m['snapshot_id']}: {m['task_count']} tasks, {m['model']}")
        return

    if not all([args.suite, args.model, args.tag]):
        parser.error("--suite, --model, and --tag are required")

    scan_dirs = [Path(d) for d in (args.scan_dirs or ["runs/staging", "runs/official/_raw"])]
    create_snapshot(
        Path(args.suite), args.model, args.tag, scan_dirs,
        args.description, args.expansion_of,
    )


if __name__ == "__main__":
    main()

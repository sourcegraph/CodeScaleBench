#!/usr/bin/env python3
"""Replace repo_approx_loc with precise cloc code-line counts in all config JSONs.

Reads results/repo_cloc_counts.json and updates:
  - configs/selected_benchmark_tasks.json
  - All derivative config JSONs that contain repo_approx_loc
  - Also adds repo_cloc_languages (top 5 by code lines)

The field repo_approx_loc is replaced with the cloc value. A new field
repo_approx_loc_source is set to "cloc" to indicate provenance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
CLOC_FILE = PROJ_ROOT / "results" / "repo_cloc_counts.json"

# Config files to update
CONFIG_FILES = [
    PROJ_ROOT / "configs" / "selected_benchmark_tasks.json",
    PROJ_ROOT / "configs" / "rerun_2_failed_org.json",
    PROJ_ROOT / "configs" / "rerun_migration294.json",
    PROJ_ROOT / "configs" / "zero_run_org_artifact.json",
    PROJ_ROOT / "configs" / "zero_run_daytona.json",
    PROJ_ROOT / "configs" / "zero_run_local.json",
    PROJ_ROOT / "configs" / "zero_run_tasks.json",
    PROJ_ROOT / "configs" / "coverage_gap_tasks.json",
    PROJ_ROOT / "configs" / "subset_tasks_n80.json",
]

# Map sg-evals pinned repos to canonical names (same as collect_repo_cloc.py)
SG_EVALS_TO_CANONICAL = {
    "sg-evals/kubernetes--v1.30.0": "kubernetes/kubernetes",
    "sg-evals/kubernetes--v1.32.0": "kubernetes/kubernetes",
    "sg-evals/chromium--2d05e315": "chromium/src",
    "sg-evals/pytorch--d18007a1": "pytorch/pytorch",
    "sg-evals/cilium--v1.16.5": "cilium/cilium",
    "sg-evals/firefox--871325b8": "mozilla/gecko-dev",
    "sg-evals/envoy--v1.31.2": "envoyproxy/envoy",
    "sg-evals/envoy--v1.33.0": "envoyproxy/envoy",
    "sg-evals/pandas--v2.2.3": "pandas-dev/pandas",
    "sg-evals/llvm-project--a8f3c97d": "llvm/llvm-project",
    "sg-evals/django--674eda1c": "django/django",
    "sg-evals/terraform--v1.10.3": "hashicorp/terraform",
    "sg-evals/libreoffice-core--9c8b85f3": "libreoffice/core",
    "sg-evals/istio--f8af3cae": "istio/istio",
    "sg-evals/prometheus--ba14bc4": "prometheus/prometheus",
    "sg-evals/numpy--v2.2.2": "numpy/numpy",
    "sg-evals/scikit-learn--cb7e82dd": "scikit-learn/scikit-learn",
    "sg-evals/curl--09e25b9d": "curl/curl",
    "sg-evals/kafka--0753c489": "apache/kafka",
    "sg-evals/rust--01f6ddf7": "rust-lang/rust",
    "sg-evals/arangodb--a5cca0b8": "arangodb/arangodb",
    "sg-evals/jdk--742e735d": "openjdk/jdk",
    "sg-evals/grafana--26d36ec": "grafana/grafana",
    "sg-evals/Strata--66225ca9": "OpenGamma/Strata",
    "sg-evals/android-frameworks-base--d41da232": "android/frameworks-base",
    "sg-evals/tidb--v8.5.0": "pingcap/tidb",
    "sg-evals/godot--4.3-stable": "godotengine/godot",
    "sg-evals/beam--v2.62.0": "apache/beam",
    "sg-evals/cockroach--v24.3.0": "cockroachdb/cockroach",
    "sg-evals/roslyn--v4.12.0": "dotnet/roslyn",
    "sg-evals/node--v22.13.0": "nodejs/node",
    "sg-evals/bazel--8.0.0": "bazelbuild/bazel",
    "sg-evals/TypeScript--v5.7.2": "microsoft/TypeScript",
    "sg-evals/grpc--v1.68.0": "grpc/grpc",
    "sg-evals/elasticsearch--v8.17.0": "elastic/elasticsearch",
    "sg-evals/ceph--v19.2.1": "ceph/ceph",
    "sg-evals/ClickHouse--v24.12": "ClickHouse/ClickHouse",
    "sg-evals/expressjs-express": "expressjs/express",
    "sg-evals/scipy": "scipy/scipy",
}

# Special bare-name repos
BARE_NAME_MAP = {
    "linux": "linux",
    "pytorch": "pytorch/pytorch",
    "torvalds/linux": "linux",
    "chromium/chromium": "chromium/src",
}

REPO_ALIAS_MAP = {
    "sourcegraph-testing/prometheus-common": "prometheus/common",
}

# Multi-repo comma-separated entries -> list of cloc keys
MULTI_REPO_MAP = {
    "numpy,pandas,scikit-learn": ["numpy/numpy", "pandas-dev/pandas", "scikit-learn/scikit-learn"],
    "django,flask,requests": ["django/django", "pallets/flask", "psf/requests"],
}


def resolve_repo_to_cloc_key(repo_str: str) -> list[str]:
    """Return list of cloc keys to look up for a given repo string."""
    if not repo_str:
        return []
    if repo_str in REPO_ALIAS_MAP:
        return [REPO_ALIAS_MAP[repo_str]]
    if "," in repo_str:
        # Check explicit mapping first
        if repo_str in MULTI_REPO_MAP:
            return MULTI_REPO_MAP[repo_str]
        # Fallback: try each component
        keys = []
        for part in repo_str.split(","):
            part = part.strip()
            resolved = resolve_repo_to_cloc_key(part)
            keys.extend(resolved)
        return keys
    if repo_str.startswith("sg-evals/"):
        canonical = SG_EVALS_TO_CANONICAL.get(repo_str)
        return [canonical] if canonical else []
    if repo_str in BARE_NAME_MAP:
        return [BARE_NAME_MAP[repo_str]]
    if repo_str == "org/repo":
        return []
    return [repo_str]


def find_task_dir(task: dict) -> Path | None:
    """Resolve a task to its benchmark directory."""
    task_dir = task.get("task_dir")
    if task_dir:
        path = PROJ_ROOT / task_dir
        if path.is_dir():
            return path

    benchmark = task.get("benchmark")
    task_id = task.get("task_id")
    if not benchmark or not task_id:
        return None

    bench_dir = PROJ_ROOT / "benchmarks" / benchmark
    if not bench_dir.is_dir():
        return None

    direct = bench_dir / str(task_id)
    if direct.is_dir():
        return direct

    lower = bench_dir / str(task_id).lower()
    if lower.is_dir():
        return lower

    target = str(task_id).lower()
    for child in bench_dir.iterdir():
        if child.name.lower() == target:
            return child
    return None


def _collect_repos(value, repos: set[str]) -> None:
    """Recursively collect repo names from oracle structures."""
    if isinstance(value, dict):
        repo = value.get("repo")
        if isinstance(repo, str) and repo:
            repos.add(repo)
        for nested in value.values():
            _collect_repos(nested, repos)
    elif isinstance(value, list):
        for nested in value:
            _collect_repos(nested, repos)


def repos_from_task_spec(task: dict) -> list[str]:
    """Extract canonical repo identifiers from a task's oracle spec."""
    task_dir = find_task_dir(task)
    if task_dir is None:
        return []

    spec_path = task_dir / "tests" / "task_spec.json"
    if not spec_path.is_file():
        return []

    try:
        spec = json.loads(spec_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    repos: set[str] = set()
    oracle = spec.get("artifacts", {}).get("oracle", {})
    _collect_repos(oracle, repos)

    canonical = []
    for repo in sorted(repos):
        keys = resolve_repo_to_cloc_key(repo)
        if keys:
            canonical.extend(keys)
        else:
            canonical.append(repo)

    return sorted(dict.fromkeys(canonical))


def resolve_repos_for_task(task: dict) -> tuple[list[str], str | None]:
    """Resolve cloc keys for a task, falling back to task-spec repo metadata."""
    repo_str = task.get("repo", "")
    cloc_keys = resolve_repo_to_cloc_key(repo_str)
    if cloc_keys:
        return list(dict.fromkeys(cloc_keys)), None

    fallback_repos = repos_from_task_spec(task)
    if not fallback_repos:
        return [], None

    canonical_repo_str = ",".join(fallback_repos)
    cloc_keys = []
    for repo in fallback_repos:
        cloc_keys.extend(resolve_repo_to_cloc_key(repo))
    return list(dict.fromkeys(cloc_keys)), canonical_repo_str


def update_task(task: dict, cloc_data: dict) -> bool:
    """Update a single task's LOC fields from cloc data. Returns True if updated."""
    cloc_keys, canonical_repo_str = resolve_repos_for_task(task)

    if not cloc_keys:
        return False

    # Sum LOC across all repos for multi-repo tasks
    total_code = 0
    total_files = 0
    top_languages = {}
    found = False

    for key in cloc_keys:
        info = cloc_data.get(key)
        if not info or "error" in info:
            continue
        found = True
        total_code += info["total_code_lines"]
        total_files += info["total_files"]
        for lang, stats in info.get("languages", {}).items():
            if lang in top_languages:
                top_languages[lang] += stats["code"]
            else:
                top_languages[lang] = stats["code"]

    if not found:
        return False

    task["repo_approx_loc"] = total_code
    task["repo_approx_loc_source"] = "cloc"
    task["repo_cloc_total_files"] = total_files

    # Top 5 languages by code lines
    sorted_langs = sorted(top_languages.items(), key=lambda x: -x[1])[:5]
    task["repo_cloc_top_languages"] = [
        {"language": lang, "code_lines": lines} for lang, lines in sorted_langs
    ]
    if canonical_repo_str and task.get("repo") in ("", "org/repo"):
        task["repo"] = canonical_repo_str

    return True


def update_config_file(path: Path, cloc_data: dict, dry_run: bool = False) -> int:
    """Update a single config file. Returns count of updated tasks."""
    if not path.is_file():
        return 0

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(f"  SKIP (parse error): {path}")
        return 0

    # Find tasks list
    if isinstance(data, dict) and "tasks" in data:
        tasks = data["tasks"]
    elif isinstance(data, list):
        tasks = data
    else:
        return 0

    if not isinstance(tasks, list):
        return 0

    updated = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if update_task(task, cloc_data):
            updated += 1

    if updated > 0 and not dry_run:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    return updated


def main():
    dry_run = "--dry-run" in sys.argv

    if not CLOC_FILE.is_file():
        print(f"ERROR: {CLOC_FILE} not found. Run collect_repo_cloc.py first.")
        sys.exit(1)

    with open(CLOC_FILE) as f:
        cloc_data = json.load(f)

    print(f"Loaded cloc data for {len(cloc_data)} repos")
    if dry_run:
        print("DRY RUN — no files will be modified")

    total_updated = 0
    for config_path in CONFIG_FILES:
        n = update_config_file(config_path, cloc_data, dry_run=dry_run)
        if n > 0:
            print(f"  {config_path.name}: {n} tasks updated")
            total_updated += n
        elif config_path.is_file():
            print(f"  {config_path.name}: 0 tasks updated (no matching repos)")
        else:
            print(f"  {config_path.name}: SKIP (not found)")

    print(f"\nTotal: {total_updated} task entries updated across all configs")


if __name__ == "__main__":
    main()

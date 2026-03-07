#!/usr/bin/env python3
"""Shallow-clone each benchmark repo and run cloc to get precise LOC counts.

Clones one repo at a time to /tmp, runs cloc --json, saves results, deletes clone.
Deduplicates sg-evals/ mirrors to canonical GitHub repos.
Outputs results/repo_cloc_counts.json with per-repo breakdown.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SELECTED_TASKS = PROJ_ROOT / "configs" / "selected_benchmark_tasks.json"
OUTPUT_FILE = PROJ_ROOT / "results" / "repo_cloc_counts.json"

# Map sg-evals pinned names and other aliases to canonical GitHub repos
# sg-evals format: sg-evals/reponame--commit_or_tag
def canonical_repo(repo_str: str) -> str | None:
    """Return canonical 'owner/repo' or None if not cloneable."""
    if not repo_str or repo_str == "org/repo":
        return None
    if "," in repo_str:
        # Multi-repo entries like "numpy,pandas,scikit-learn" — skip, handle individually
        return None
    if repo_str.startswith("sg-evals/"):
        # e.g. sg-evals/kubernetes--v1.32.0 -> kubernetes
        # e.g. sg-evals/envoy--v1.31.2 -> envoyproxy/envoy
        # These don't have owner info, so we need a mapping
        return None  # We'll handle these via SG_EVALS_MAP
    if "/" not in repo_str:
        # e.g. "linux", "pytorch" — need special handling
        return None
    return repo_str


# Special repos that need explicit clone URLs
SPECIAL_CLONE_URLS = {
    "linux": "https://github.com/torvalds/linux.git",
    "pytorch": "https://github.com/pytorch/pytorch.git",
}

# sg-evals to canonical mapping (manually curated from task.toml files)
SG_EVALS_TO_CANONICAL = {
    "sg-evals/kubernetes--v1.30.0": "kubernetes/kubernetes",
    "sg-evals/kubernetes--v1.32.0": "kubernetes/kubernetes",
    "sg-evals/chromium--2d05e315": None,  # Too large, skip or handle separately
    "sg-evals/pytorch--d18007a1": "pytorch/pytorch",
    "sg-evals/cilium--v1.16.5": "cilium/cilium",
    "sg-evals/firefox--871325b8": "mozilla/gecko-dev",
    "sg-evals/envoy--v1.31.2": "envoyproxy/envoy",
    "sg-evals/envoy--v1.33.0": "envoyproxy/envoy",
    "sg-evals/pandas--v2.2.3": "pandas-dev/pandas",
    "sg-evals/llvm-project--a8f3c97d": "llvm/llvm-project",
    "sg-evals/django--674eda1c": "django/django",
    "sg-evals/terraform--v1.10.3": "hashicorp/terraform",
    "sg-evals/libreoffice-core--9c8b85f3": None,  # Not on GitHub standard
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
    "sg-evals/android-frameworks-base--d41da232": None,  # AOSP, not standard GitHub
}


def get_clone_url(repo: str) -> str:
    if repo in SPECIAL_CLONE_URLS:
        return SPECIAL_CLONE_URLS[repo]
    return f"https://github.com/{repo}.git"


def collect_unique_repos() -> set[str]:
    """Extract deduplicated set of canonical repos from selected_benchmark_tasks.json."""
    with open(SELECTED_TASKS) as f:
        data = json.load(f)

    repos = set()
    for task in data.get("tasks", []):
        repo_str = task.get("repo", "")
        if not repo_str:
            continue

        # Handle multi-repo entries
        if "," in repo_str:
            for r in repo_str.split(","):
                r = r.strip()
                if "/" in r:
                    repos.add(r)
            continue

        # Handle sg-evals
        if repo_str.startswith("sg-evals/"):
            canonical = SG_EVALS_TO_CANONICAL.get(repo_str)
            if canonical:
                repos.add(canonical)
            continue

        # Handle bare names
        if "/" not in repo_str:
            if repo_str in SPECIAL_CLONE_URLS:
                repos.add(repo_str)
            continue

        # Skip placeholder
        if repo_str == "org/repo":
            continue

        repos.add(repo_str)

    return repos


def run_cloc(clone_dir: str) -> dict | None:
    """Run cloc --json on a directory and return parsed results."""
    try:
        result = subprocess.run(
            ["cloc", "--json", "--quiet", clone_dir],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"  cloc error: {e}", file=sys.stderr)
    return None


def clone_and_count(repo: str, work_dir: str) -> dict | None:
    """Shallow clone repo, run cloc, return results, clean up."""
    url = get_clone_url(repo)
    clone_path = os.path.join(work_dir, repo.replace("/", "_"))

    print(f"  Cloning {url} (depth=1)...")
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", url, clone_path],
            capture_output=True, text=True, timeout=900
        )
    except subprocess.TimeoutExpired:
        print(f"  Clone timed out for {repo}", file=sys.stderr)
        shutil.rmtree(clone_path, ignore_errors=True)
        return None

    if not os.path.isdir(clone_path):
        print(f"  Clone failed for {repo}", file=sys.stderr)
        return None

    print(f"  Running cloc...")
    cloc_data = run_cloc(clone_path)

    # Clean up immediately
    print(f"  Cleaning up clone...")
    shutil.rmtree(clone_path, ignore_errors=True)

    return cloc_data


def main():
    repos = sorted(collect_unique_repos())
    print(f"Found {len(repos)} unique repos to process")

    # Load existing results to support resuming
    results = {}
    if OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            results = json.load(f)
        print(f"Loaded {len(results)} existing results (will skip)")

    work_dir = tempfile.mkdtemp(prefix="cloc_")
    print(f"Work directory: {work_dir}")

    try:
        for i, repo in enumerate(repos, 1):
            if repo in results:
                print(f"[{i}/{len(repos)}] {repo} — cached, skipping")
                continue

            print(f"[{i}/{len(repos)}] {repo}")
            cloc_data = clone_and_count(repo, work_dir)

            if cloc_data:
                # Extract summary
                summary = cloc_data.get("SUM", {})
                total_code = summary.get("code", 0)
                total_comment = summary.get("comment", 0)
                total_blank = summary.get("blank", 0)
                n_files = summary.get("nFiles", 0)

                # Per-language breakdown (top languages by code lines)
                languages = {}
                for lang, stats in cloc_data.items():
                    if lang in ("header", "SUM"):
                        continue
                    if isinstance(stats, dict) and "code" in stats:
                        languages[lang] = {
                            "code": stats["code"],
                            "comment": stats["comment"],
                            "blank": stats["blank"],
                            "nFiles": stats["nFiles"],
                        }

                # Sort languages by code lines descending
                top_languages = dict(
                    sorted(languages.items(), key=lambda x: x[1]["code"], reverse=True)
                )

                results[repo] = {
                    "total_code_lines": total_code,
                    "total_comment_lines": total_comment,
                    "total_blank_lines": total_blank,
                    "total_files": n_files,
                    "total_all_lines": total_code + total_comment + total_blank,
                    "languages": top_languages,
                }
                print(f"  => {total_code:,} code lines, {n_files:,} files, {len(languages)} languages")
            else:
                results[repo] = {"error": "clone or cloc failed"}
                print(f"  => FAILED")

            # Save after each repo (resume support)
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(results, f, indent=2)

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    print(f"\nDone. Results saved to {OUTPUT_FILE}")
    print(f"Successfully counted: {sum(1 for v in results.values() if 'error' not in v)}/{len(results)}")


if __name__ == "__main__":
    main()

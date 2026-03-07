#!/usr/bin/env python3
"""Backfill reviewers.json for all benchmark tasks.

Queries GitHub API (via `gh`) to discover PR authors, reviewers, and top
contributors for the code areas each task touches. Generates a unified
reviewers.json per task directory.

Usage:
    python3 scripts/backfill_reviewers.py                    # all tasks
    python3 scripts/backfill_reviewers.py --dry-run           # preview only
    python3 scripts/backfill_reviewers.py --task-dir benchmarks/csb_sdlc_fix/ansible-abc-imports-fix-001
    python3 scripts/backfill_reviewers.py --suite csb_sdlc_fix
    python3 scripts/backfill_reviewers.py --overwrite         # regenerate existing
"""

import argparse
import json
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

# Map short repo names (no owner) to owner/repo.
# Extend as needed; unknown short names fall back to GitHub search.
SHORT_NAME_MAP = {
    "kubernetes": "kubernetes/kubernetes",
    "pytorch": "pytorch/pytorch",
    "linux": "torvalds/linux",
    "envoy": "envoyproxy/envoy",
    "kafka": "apache/kafka",
    "terraform": "hashicorp/terraform",
    "vscode": "microsoft/vscode",
    "aspnetcore": "dotnet/aspnetcore",
    "curl": "curl/curl",
    "servo": "servo/servo",
    "tensorrt-llm": "NVIDIA/TensorRT-LLM",
    "Ghost": "TryGhost/Ghost",
    "cal.com": "calcom/cal.com",
    "qutebrowser": "qutebrowser/qutebrowser",
    "tutanota": "tutao/tutanota",
    "vuls": "future-architect/vuls",
    "bustub": "cmu-db/bustub",
    "openhands": "All-Hands-AI/OpenHands",
    "sklearn": "scikit-learn/scikit-learn",
}

# sg-evals mirror pattern: sg-evals/kubernetes--v1.32.0 -> kubernetes/kubernetes
SG_EVALS_MAP = {
    "ClickHouse": "ClickHouse/ClickHouse",
    "Strata": "OpenGamma/Strata",
    "TypeScript": "microsoft/TypeScript",
    "android-frameworks-base": "aosp-mirror/platform_frameworks_base",
    "arangodb": "arangodb/arangodb",
    "bazel": "bazelbuild/bazel",
    "beam": "apache/beam",
    "ceph": "ceph/ceph",
    "chromium": "chromium/chromium",
    "cockroach": "cockroachdb/cockroach",
    "django": "django/django",
    "elasticsearch": "elastic/elasticsearch",
    "envoy": "envoyproxy/envoy",
    "firefox": "mozilla-firefox/firefox",
    "godot": "godotengine/godot",
    "grafana": "grafana/grafana",
    "grpc": "grpc/grpc",
    "jdk": "openjdk/jdk",
    "kafka": "apache/kafka",
    "kubernetes": "kubernetes/kubernetes",
    "libreoffice-core": "LibreOffice/core",
    "llvm-project": "llvm/llvm-project",
    "node": "nodejs/node",
    "roslyn": "dotnet/roslyn",
    "rust": "rust-lang/rust",
    "tidb": "pingcap/tidb",
    "servo": "servo/servo",
    "grafana-loki": "grafana/loki",
    "grafana-mimir": "grafana/mimir",
    "prometheus": "prometheus/prometheus",
    "etcd-io-etcd": "etcd-io/etcd",
    "expressjs-express": "expressjs/express",
    "scikit-learn": "scikit-learn/scikit-learn",
    "numpy": "numpy/numpy",
    "pandas": "pandas-dev/pandas",
    "scipy": "scipy/scipy",
    "prometheus-common": "prometheus/common",
    "prometheus-prometheus": "prometheus/prometheus",
}

# Bot accounts to exclude from contributor lists
BOT_LOGINS = {
    "dependabot[bot]", "dependabot", "renovate[bot]", "renovate",
    "github-actions[bot]", "codecov[bot]", "mergify[bot]",
    "stale[bot]", "allcontributors[bot]", "snyk-bot",
    "greenkeeper[bot]", "depfu[bot]", "imgbot[bot]",
    "copybara-service[bot]", "k8s-ci-robot", "bors",
    "bors[bot]", "rust-timer", "rust-highfive",
}

# Cache: repo -> contributor data (avoid redundant API calls)
_repo_contributor_cache: dict[str, list[dict]] = {}
_gh_rate_limit_remaining = 5000
_gh_calls = 0


def gh_api(endpoint: str, params: dict | None = None) -> dict | list | None:
    """Call GitHub API via gh CLI. Returns parsed JSON or None on error."""
    global _gh_calls, _gh_rate_limit_remaining
    # Build URL with query params for GET requests
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        full_endpoint = f"{endpoint}?{qs}"
    else:
        full_endpoint = endpoint
    cmd = ["gh", "api", full_endpoint]

    _gh_calls += 1
    # Throttle if we're making many calls
    if _gh_calls % 50 == 0:
        time.sleep(1)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return None


def resolve_repo(raw_repo: str) -> str | None:
    """Resolve a task.toml repo value to owner/repo format."""
    if not raw_repo or raw_repo == "org/repo":
        return None

    # Already owner/repo format (but not sg-evals)
    if "/" in raw_repo and not raw_repo.startswith("sg-evals/"):
        return raw_repo

    # sg-evals mirror: sg-evals/kubernetes--v1.32.0
    if raw_repo.startswith("sg-evals/"):
        mirror_name = raw_repo.split("/", 1)[1]
        base_name = mirror_name.split("--")[0]
        if base_name in SG_EVALS_MAP:
            return SG_EVALS_MAP[base_name]
        return None

    # Short name lookup
    if raw_repo in SHORT_NAME_MAP:
        return SHORT_NAME_MAP[raw_repo]

    return None


def get_code_areas_sdlc(task_dir: Path) -> list[str]:
    """Extract code areas from SDLC task files."""
    areas = []

    # Strategy 1: config.json patch (SWE-bench Pro tasks)
    config_path = task_dir / "tests" / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            patch = config.get("patch", "")
            # Extract file paths from diff headers: --- a/path or +++ b/path
            for line in patch.split("\n"):
                m = re.match(r'^[+-]{3} [ab]/(.+)$', line)
                if m:
                    path = m.group(1)
                    # Get directory prefix
                    parts = path.split("/")
                    if len(parts) > 1:
                        areas.append("/".join(parts[:2]) + "/")
                    else:
                        areas.append(parts[0])
        except (json.JSONDecodeError, KeyError):
            pass

    # Strategy 2: ground_truth.json file_references
    gt_path = task_dir / "tests" / "ground_truth.json"
    if gt_path.exists() and not areas:
        try:
            with open(gt_path) as f:
                gt = json.load(f)
            if isinstance(gt, dict):
                for ref in gt.get("file_references", []):
                    if not isinstance(ref, dict):
                        continue
                    patterns = ref.get("patterns", [])
                    for p in patterns:
                        clean = p.strip("^$.*()[]")
                        if "/" in clean:
                            areas.append(clean.split("/")[0] + "/")
        except (json.JSONDecodeError, KeyError):
            pass

    return list(set(areas))[:10]


def _strip_sg_evals_prefix(path: str) -> str:
    """Strip sg-evals/repo--commit/ prefix from oracle paths."""
    # Pattern: sg-evals/repo--hash/actual/path or repo--hash/actual/path
    m = re.match(r'(?:sg-evals/)?[^/]+--[a-f0-9]+/(.+)', path)
    if m:
        return m.group(1)
    return path


def get_code_areas_org(task_dir: Path) -> list[str]:
    """Extract code areas from org-scale task oracle files."""
    areas = []
    oracle_path = task_dir / "tests" / "oracle_answer.json"
    if oracle_path.exists():
        try:
            with open(oracle_path) as f:
                oracle = json.load(f)
            for file_entry in oracle.get("files", []):
                if isinstance(file_entry, dict):
                    path = file_entry.get("path", "")
                elif isinstance(file_entry, str):
                    path = file_entry
                else:
                    continue
                # Strip sg-evals prefix to get real repo path
                path = _strip_sg_evals_prefix(path)
                if "/" in path:
                    parts = path.split("/")
                    areas.append("/".join(parts[:2]) + "/")
        except (json.JSONDecodeError, KeyError):
            pass

    return list(set(areas))[:10]


def _resolve_sg_evals_repo(clone_ref: str) -> str | None:
    """Resolve sg-evals/repo--commit to canonical owner/repo."""
    # e.g., sg-evals/rust--01f6ddf7 -> rust-lang/rust
    if not clone_ref.startswith("sg-evals/"):
        return clone_ref if "/" in clone_ref else None
    mirror_name = clone_ref.split("/", 1)[1]
    # Try double-dash split first (sg-evals/rust--01f6ddf7)
    base_name = mirror_name.split("--")[0]
    result = SG_EVALS_MAP.get(base_name)
    if result:
        return result
    # Fallback: try the full mirror name (sg-evals/prometheus-prometheus)
    return SG_EVALS_MAP.get(mirror_name)


def get_repos_from_dockerfile(task_dir: Path) -> list[str]:
    """Extract git clone URLs from Dockerfile for org tasks."""
    repos = []
    dockerfile = task_dir / "environment" / "Dockerfile"
    if not dockerfile.exists():
        return repos
    try:
        content = dockerfile.read_text()
        # Match: git clone ... https://github.com/owner/repo-or-mirror
        # Handle both standard repos and sg-evals mirrors (no trailing .git)
        for m in re.finditer(
            r'git clone\b.*?https://github\.com/([^\s]+)', content
        ):
            raw = m.group(1).rstrip("/").removesuffix(".git")
            # Normalize: ensure we have owner/repo format
            parts = raw.split("/")
            if len(parts) >= 2:
                raw_repo = "/".join(parts[:2])
            else:
                continue
            # Try to resolve sg-evals mirrors
            resolved = _resolve_sg_evals_repo(raw_repo)
            if resolved and resolved not in repos:
                repos.append(resolved)
            elif not resolved and raw_repo not in repos:
                repos.append(raw_repo)
    except Exception:
        pass
    return repos


def get_top_contributors(owner_repo: str, code_areas: list[str],
                         max_results: int = 5) -> list[dict]:
    """Get top contributors for a repo's code areas via GitHub API."""
    cache_key = f"{owner_repo}::{','.join(sorted(code_areas[:3]))}"
    if cache_key in _repo_contributor_cache:
        return _repo_contributor_cache[cache_key]

    contributors: Counter = Counter()

    if code_areas:
        # Query commits per code area (more targeted)
        for area in code_areas[:3]:  # Limit API calls
            data = gh_api(
                f"repos/{owner_repo}/commits",
                {"path": area, "per_page": "30"}
            )
            if isinstance(data, list):
                for commit in data:
                    author = commit.get("author")
                    if author and isinstance(author, dict):
                        login = author.get("login", "")
                        if login and login not in BOT_LOGINS:
                            contributors[login] += 1
    else:
        # Fallback: repo-level contributors
        data = gh_api(f"repos/{owner_repo}/contributors",
                      {"per_page": "10"})
        if isinstance(data, list):
            for c in data:
                login = c.get("login", "")
                contribs = c.get("contributions", 0)
                if login and login not in BOT_LOGINS:
                    contributors[login] = contribs

    result = [
        {"login": login, "commits": count}
        for login, count in contributors.most_common(max_results)
    ]
    _repo_contributor_cache[cache_key] = result
    return result


def get_pr_reviewers(owner_repo: str, pr_number: int) -> dict | None:
    """Get PR metadata including author, reviewers, merged_by."""
    data = gh_api(
        f"repos/{owner_repo}/pulls/{pr_number}",
    )
    if not data or not isinstance(data, dict):
        return None

    author = data.get("user", {}).get("login", "")
    merged_by = (data.get("merged_by") or {}).get("login", "")

    # Get reviewers from reviews endpoint
    reviews = gh_api(f"repos/{owner_repo}/pulls/{pr_number}/reviews")
    reviewer_logins = []
    if isinstance(reviews, list):
        seen = set()
        for review in reviews:
            login = review.get("user", {}).get("login", "")
            if login and login not in BOT_LOGINS and login not in seen:
                seen.add(login)
                reviewer_logins.append(login)

    return {
        "number": pr_number,
        "url": f"https://github.com/{owner_repo}/pull/{pr_number}",
        "author": author,
        "merged_by": merged_by,
        "reviewers": reviewer_logins,
    }


def find_source_pr(task_dir: Path) -> tuple[str | None, int | None]:
    """Try to find source PR number from task metadata."""
    # SWE-bench Pro: config.json has instance_id with PR-ish info
    config_path = task_dir / "tests" / "config.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            # Some SWE-bench instances encode the PR in problem_statement
            problem = config.get("problem_statement", "")
            # Look for PR/issue references
            m = re.search(r'(?:pull|issues?|PR)[/ #](\d+)', problem, re.I)
            if m:
                repo = config.get("repo", "")
                if "/" in repo:
                    return repo, int(m.group(1))
        except (json.JSONDecodeError, KeyError):
            pass

    # Check instruction.md for PR/issue links
    instruction = task_dir / "instruction.md"
    if instruction.exists():
        try:
            text = instruction.read_text()
            m = re.search(
                r'github\.com/([^/]+/[^/]+)/(?:pull|issues)/(\d+)', text
            )
            if m:
                return m.group(1), int(m.group(2))
        except Exception:
            pass

    return None, None


def parse_task_toml(task_dir: Path) -> dict:
    """Parse task.toml for basic metadata."""
    toml_path = task_dir / "task.toml"
    if not toml_path.exists():
        return {}

    result = {}
    try:
        content = toml_path.read_text()
        # Simple TOML parsing for the fields we need
        for m in re.finditer(r'^(\w+)\s*=\s*"([^"]*)"', content, re.M):
            result[m.group(1)] = m.group(2)
        # Also check for org_scale = true
        if re.search(r'org_scale\s*=\s*true', content):
            result["org_scale"] = "true"
    except Exception:
        pass
    return result


def generate_reviewers_json(task_dir: Path, dry_run: bool = False) -> dict | None:
    """Generate reviewers.json for a single task."""
    meta = parse_task_toml(task_dir)
    raw_repo = meta.get("repo", "")
    task_id = meta.get("id", task_dir.name)
    is_org = meta.get("org_scale") == "true"

    # Resolve primary repo
    owner_repo = resolve_repo(raw_repo)

    # Fallback: infer repo from task ID prefix
    if not owner_repo:
        task_name = task_dir.name.lower()
        # Try known prefixes from task names
        name_to_repo = {
            "ansible": "ansible/ansible",
            "flipt": "flipt-io/flipt",
            "qutebrowser": "qutebrowser/qutebrowser",
            "teleport": "gravitational/teleport",
            "tutanota": "tutao/tutanota",
            "vuls": "future-architect/vuls",
            "envoy": "envoyproxy/envoy",
            "etcd": "etcd-io/etcd",
            "k8s": "kubernetes/kubernetes",
            "bustub": "cmu-db/bustub",
            "numpy": "numpy/numpy",
            "pandas": "pandas-dev/pandas",
            "sklearn": "scikit-learn/scikit-learn",
            "openhands": "All-Hands-AI/OpenHands",
            "python-http": "python/cpython",
        }
        for prefix, repo in name_to_repo.items():
            if task_name.startswith(prefix):
                owner_repo = repo
                break

    # For org tasks, also check Dockerfile and oracle for additional repos
    all_repos = []
    if is_org:
        dockerfile_repos = get_repos_from_dockerfile(task_dir)
        for r in dockerfile_repos:
            resolved = resolve_repo(r)
            if resolved and resolved not in all_repos:
                all_repos.append(resolved)
        # Fallback: extract repos from oracle_answer.json
        if not all_repos:
            oracle_path = task_dir / "tests" / "oracle_answer.json"
            if oracle_path.exists():
                try:
                    with open(oracle_path) as f:
                        oracle = json.load(f)
                    for file_entry in oracle.get("files", []):
                        repo_name = ""
                        if isinstance(file_entry, dict):
                            repo_name = file_entry.get("repo", "")
                        elif isinstance(file_entry, str):
                            # Strip github.com/ prefix if present
                            path = file_entry.replace("github.com/", "")
                            m = re.match(r'(sg-evals/[^/]+)', path)
                            if m:
                                repo_name = m.group(1)
                            else:
                                m = re.match(r'([^/]+/[^/]+)', path)
                                if m:
                                    repo_name = m.group(1)
                        if repo_name:
                            resolved = resolve_repo(repo_name)
                            if resolved and resolved not in all_repos:
                                all_repos.append(resolved)
                except (json.JSONDecodeError, KeyError):
                    pass
        if owner_repo and owner_repo not in all_repos:
            all_repos.insert(0, owner_repo)
    else:
        if owner_repo:
            all_repos = [owner_repo]

    if not all_repos:
        # Can't determine repo — skip
        return None

    # Determine code areas
    if is_org:
        code_areas = get_code_areas_org(task_dir)
    else:
        code_areas = get_code_areas_sdlc(task_dir)

    # Try to find source PR
    pr_repo, pr_number = find_source_pr(task_dir)

    reviewers_data: dict = {
        "task_id": task_id,
        "repos": all_repos,
    }

    # If we have a source PR, get full PR metadata
    if pr_repo and pr_number:
        pr_info = get_pr_reviewers(pr_repo, pr_number)
        if pr_info:
            reviewers_data["source_pr"] = pr_info
            # Suggested reviewers: PR reviewers + author (prioritize actual reviewers)
            suggested = list(pr_info["reviewers"])
            if pr_info["author"] and pr_info["author"] not in suggested:
                suggested.append(pr_info["author"])
            if pr_info["merged_by"] and pr_info["merged_by"] not in suggested:
                suggested.append(pr_info["merged_by"])
            reviewers_data["suggested_reviewers"] = suggested[:5]
            reviewers_data["discovery_method"] = "source_pr"

    # Always add contributor data (supplements PR data or serves as primary)
    all_contributors: Counter = Counter()
    for repo in all_repos[:3]:  # Limit to avoid excessive API calls
        contribs = get_top_contributors(repo, code_areas)
        for c in contribs:
            all_contributors[c["login"]] += c["commits"]

    top_contribs = [
        {"login": login, "commits": count}
        for login, count in all_contributors.most_common(5)
    ]

    if top_contribs:
        reviewers_data["top_contributors"] = top_contribs

    if code_areas:
        reviewers_data["code_areas"] = code_areas

    # If no PR-based reviewers, use contributor-based
    if "suggested_reviewers" not in reviewers_data and top_contribs:
        reviewers_data["suggested_reviewers"] = [
            c["login"] for c in top_contribs[:3]
        ]
        reviewers_data["discovery_method"] = "git_log_frequency"

    if "discovery_method" not in reviewers_data:
        reviewers_data["discovery_method"] = "github_api"

    return reviewers_data


def discover_task_dirs(
    base_dir: Path,
    suite_filter: str | None = None,
    task_dir_filter: str | None = None,
) -> list[Path]:
    """Find all task directories under benchmarks/."""
    task_dirs = []

    if task_dir_filter:
        p = REPO_ROOT / task_dir_filter
        if p.exists() and (p / "task.toml").exists():
            return [p]
        return []

    for suite_dir in sorted(base_dir.iterdir()):
        if not suite_dir.is_dir():
            continue
        if suite_filter and suite_dir.name != suite_filter:
            continue
        for task_dir in sorted(suite_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            if (task_dir / "task.toml").exists():
                task_dirs.append(task_dir)

    return task_dirs


def main():
    parser = argparse.ArgumentParser(
        description="Backfill reviewers.json for benchmark tasks"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be generated without writing")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing reviewers.json files")
    parser.add_argument("--task-dir",
                        help="Process a single task directory")
    parser.add_argument("--suite",
                        help="Process only tasks in this suite")
    parser.add_argument("--skip-api", action="store_true",
                        help="Skip GitHub API calls, generate stubs only")
    args = parser.parse_args()

    task_dirs = discover_task_dirs(
        BENCHMARKS_DIR,
        suite_filter=args.suite,
        task_dir_filter=args.task_dir,
    )

    print(f"Found {len(task_dirs)} task directories")

    created = 0
    skipped = 0
    failed = 0
    no_repo = 0

    for i, task_dir in enumerate(task_dirs):
        rel = task_dir.relative_to(REPO_ROOT)
        out_path = task_dir / "reviewers.json"

        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        if args.skip_api:
            # Generate stub with just task metadata
            meta = parse_task_toml(task_dir)
            raw_repo = meta.get("repo", "")
            owner_repo = resolve_repo(raw_repo)
            if not owner_repo:
                no_repo += 1
                continue
            stub = {
                "task_id": meta.get("id", task_dir.name),
                "repos": [owner_repo],
                "discovery_method": "stub",
                "suggested_reviewers": [],
                "code_areas": [],
                "top_contributors": [],
            }
            if not args.dry_run:
                with open(out_path, "w") as f:
                    json.dump(stub, f, indent=2)
                    f.write("\n")
            created += 1
            print(f"  [{created}] STUB {rel}")
            continue

        # Rate-limit progress
        if (i + 1) % 20 == 0:
            print(f"  Progress: {i+1}/{len(task_dirs)} "
                  f"(created={created}, skipped={skipped}, "
                  f"failed={failed}, no_repo={no_repo})")

        try:
            data = generate_reviewers_json(task_dir, dry_run=args.dry_run)
        except Exception as e:
            print(f"  ERROR {rel}: {e}")
            failed += 1
            continue

        if data is None:
            no_repo += 1
            if no_repo <= 10:
                print(f"  SKIP (no resolvable repo) {rel}")
            continue

        if args.dry_run:
            print(f"  WOULD CREATE {rel}/reviewers.json")
            print(f"    repos: {data.get('repos', [])}")
            print(f"    method: {data.get('discovery_method')}")
            print(f"    suggested: {data.get('suggested_reviewers', [])}")
            created += 1
        else:
            with open(out_path, "w") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            created += 1
            if created <= 20 or created % 50 == 0:
                suggested = data.get("suggested_reviewers", [])
                print(f"  [{created}] {rel} -> {suggested}")

    print(f"\nDone! created={created}, skipped={skipped}, "
          f"failed={failed}, no_repo={no_repo}, gh_calls={_gh_calls}")


if __name__ == "__main__":
    main()

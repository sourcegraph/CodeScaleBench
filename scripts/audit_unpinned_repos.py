#!/usr/bin/env python3
"""Audit all Dockerfile.sg_only files to find repos that need sg-evals mirrors.

Identifies github.com/ repos (searched at HEAD = unpinned) and resolves the
commit pin by parsing git clone/checkout commands per-repo from the Dockerfiles.

Output: JSON manifest of repo→commit→mirror mappings ready for mirror creation.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

# Manual overrides for tasks where Dockerfile patterns are too complex for auto-parsing.
# Resolved by inspecting each Dockerfile individually (sweap-images tags, crossrepo base
# images, go.googlesource.com URLs, ~1 parent-commit notation, etc.)
MANUAL_OVERRIDES: dict[str, dict[str, tuple[str, str]]] = {
    # crossrepo base image — commits from instance_to_mirror.json
    "ccb_refactor/python-http-class-naming-refac-001": {
        "github.com/django/django": ("674eda1c03a3187905f48afee0f15226aa62fdf3", "crossrepo base image"),
        "github.com/pallets/flask": ("798e006f435887adceb6aab9b57cde8e20276793", "crossrepo base image"),
        "github.com/psf/requests": ("421b8733cf17e4dee8be237e7412b095772c2323", "crossrepo base image"),
    },
    # git checkout COMMIT~1 (parent of the PR merge commit)
    "ccb_debug/envoy-duplicate-headers-debug-001": {
        "github.com/envoyproxy/envoy": ("25f893b44c9ac785d57f21399fb5aff540f0bef7", "git checkout COMMIT~1 (parent)"),
    },
    # git fetch without github URL on same line as clone
    "ccb_debug/istio-xds-destrul-debug-001": {
        "github.com/istio/istio": ("f8c9b973900a13a898348c010ae3cad2de08693b", "git fetch (pre-fix state)"),
    },
    "ccb_debug/terraform-phantom-update-debug-001": {
        "github.com/hashicorp/terraform": ("9658f9df6b24bd6d2c267c07cffd4c97cf8b9b40", "git fetch (pre-fix state)"),
    },
    # sweap-images tag with non-standard format
    "ccb_debug/vuls-oval-regression-prove-001": {
        "github.com/future-architect/vuls": ("139f3a81b66c47e6d8f70ce6c4afe7a9196a6ea8", "FROM sweap-images tag"),
    },
    # crossrepo base — kubernetes commit from crossrepo manifest
    "ccb_design/etcd-grpc-api-upgrade-001": {
        "github.com/kubernetes/kubernetes": ("8c9c67c000104450cfc5a5f48053a9a84b73cf93", "crossrepo base image"),
    },
    # git fetch without github URL on same line
    "ccb_document/cilium-api-doc-gen-001": {
        "github.com/cilium/cilium": ("ad6b298dbdcb9b828a247c54a477a9cfa43eff00", "git fetch (main 2026-02-16)"),
    },
    "ccb_document/docgen-runbook-002": {
        "github.com/envoyproxy/envoy": ("1d0ba73ad200d28e86c0c23f76c55320f82a8fba", "git fetch"),
    },
    # go.googlesource.com URL maps to github.com/golang/net
    "ccb_secure/golang-net-cve-triage-001": {
        "github.com/golang/net": ("88194ad8ab44a02ea952c169883c3f57db6cf9f4", "git checkout (go.googlesource.com/net)"),
    },
    "ccb_understand/argocd-sync-reconcile-qa-001": {
        "github.com/argoproj/argo-cd": ("206a6eeca509bbf7f239301f3d3fa498c23251a4", "git fetch (v2.14.21)"),
    },
    "ccb_understand/cilium-ebpf-fault-qa-001": {
        "github.com/cilium/cilium": ("a2f97aa8d2de4bb360bee1e295e20556ce4166ce", "git fetch (v1.17.9)"),
    },
    "ccb_understand/istio-xds-serving-qa-001": {
        "github.com/istio/istio": ("44d0e58e49d0dc89e27fc4f8679c68132d46b887", "git fetch (v1.24.3)"),
    },
    # crossrepo base
    "ccb_understand/k8s-cri-containerd-reason-001": {
        "github.com/kubernetes/kubernetes": ("8c9c67c000104450cfc5a5f48053a9a84b73cf93", "crossrepo base image"),
    },
    # git fetch without github URL on same line
    "ccb_understand/kafka-message-lifecycle-qa-001": {
        "github.com/apache/kafka": ("0753c489afad403fb6e78fda4c4a380e46f500c0", "git fetch (v4.1.1 release)"),
    },
    "ccb_understand/terraform-plan-pipeline-qa-001": {
        "github.com/hashicorp/terraform": ("24236f4f0bd10ada71d70868abe15f9d88099747", "git fetch (v1.10.0)"),
    },
    "ccb_understand/vscode-ext-host-qa-001": {
        "github.com/microsoft/vscode": ("17baf841131aa23349f217ca7c570c76ee87b957", "git fetch (v1.99.3)"),
    },
}


def extract_sg_repos(dockerfile_path: Path) -> tuple[list[str], list[str]]:
    """Extract repos from Dockerfile.sg_only, split into pinned and unpinned.

    Returns (unpinned_github_repos, pinned_sg_repos)
    """
    text = dockerfile_path.read_text()
    unpinned = []
    pinned = []

    # Check SOURCEGRAPH_REPOS (multi-repo)
    m = re.search(r'ENV\s+SOURCEGRAPH_REPOS[= ]"?([^"\n]+)"?', text)
    if m:
        repos = [r.strip() for r in m.group(1).split(",") if r.strip()]
        for repo in repos:
            if repo.startswith("sg-evals/") or repo.startswith("sourcegraph-testing/"):
                pinned.append(repo)
            elif repo.startswith("github.com/"):
                unpinned.append(repo)
            else:
                unpinned.append(f"github.com/{repo}")
        return unpinned, pinned

    # Check SOURCEGRAPH_REPO_NAME (single-repo)
    m = re.search(r'ENV\s+SOURCEGRAPH_REPO_NAME[= ]"?([^"\n]+)"?', text)
    if m:
        repo = m.group(1).strip()
        if repo.startswith("sg-evals/") or repo.startswith("sourcegraph-testing/"):
            pinned.append(repo)
        elif repo.startswith("github.com/"):
            unpinned.append(repo)
        else:
            unpinned.append(f"github.com/{repo}")
        return unpinned, pinned

    return [], []


def _resolve_ccb_repo_hash(name: str, short_hash: str) -> str:
    """Resolve a short ccb-repo hash to full hash via base_images/ Dockerfiles."""
    base_df = REPO_ROOT / "base_images" / f"Dockerfile.{name}-{short_hash}"
    if base_df.exists():
        text = base_df.read_text()
        m = re.search(r'git checkout\s+([0-9a-f]{20,40})', text)
        if m:
            return m.group(1)
    return short_hash


def resolve_per_repo_pins(task_dir: Path) -> dict[str, tuple[str, str]]:
    """Extract per-repo commit pins from Dockerfiles.

    Parses git clone/checkout patterns and associates each commit with the
    specific repo it belongs to. Returns dict of github_url -> (commit, source).
    """
    pins = {}

    for df_name in ["Dockerfile", "Dockerfile.sg_only", "Dockerfile.artifact_only"]:
        df_path = task_dir / "environment" / df_name
        if not df_path.exists():
            continue
        text = df_path.read_text()

        # Pattern 1: git clone ... github.com/ORG/REPO.git ... && git checkout COMMIT
        # or: git clone ... github.com/ORG/REPO.git ... && git fetch ... origin COMMIT && git checkout ...
        # Multi-line RUN commands use \ continuations or &&
        lines = text.replace("\\\n", " ").split("\n")
        for line in lines:
            # Find git clone with github URL followed by checkout/fetch
            clone_match = re.search(
                r'git\s+clone\s+[^&]*?(?:https?://)?github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?\s',
                line
            )
            if clone_match:
                repo_slug = clone_match.group(1)
                full_repo = f"github.com/{repo_slug}"

                # Look for --branch TAG in the clone command
                branch_match = re.search(r'--branch\s+(\S+)', line)

                # Look for git checkout COMMIT or git fetch ... origin COMMIT
                checkout_match = re.search(
                    r'git\s+checkout\s+(?:FETCH_HEAD|([0-9a-f]{7,40}|v[\d.]+\S*|[\w.-]+))',
                    line
                )
                fetch_match = re.search(
                    r'git\s+fetch\s+.*?origin\s+([0-9a-f]{7,40})',
                    line
                )

                if fetch_match:
                    commit = fetch_match.group(1)
                    if full_repo not in pins:
                        pins[full_repo] = (commit, f"git fetch origin {commit[:12]} ({df_name})")
                elif checkout_match and checkout_match.group(1):
                    commit = checkout_match.group(1)
                    if full_repo not in pins:
                        pins[full_repo] = (commit, f"git checkout {commit} ({df_name})")
                elif branch_match:
                    tag = branch_match.group(1)
                    if full_repo not in pins:
                        pins[full_repo] = (tag, f"git clone --branch {tag} ({df_name})")

        # Pattern 2: FROM ccb-repo-{name}-{hash}
        for m in re.finditer(r'FROM\s+.*ccb-repo-(\w+)-([0-9a-f]{7,})', text):
            name = m.group(1).lower()
            short_hash = m.group(2)
            commit = _resolve_ccb_repo_hash(name, short_hash)
            pins[f"_ccb_repo_{name}"] = (commit, f"FROM ccb-repo-{name}-{short_hash}")

        # Pattern 3: FROM sweap-images with full commit in tag
        for m in re.finditer(
            r'FROM\s+.*sweap-images:\S*?(\w+\.\w+)-\w+__\w+-([0-9a-f]{40})',
            text
        ):
            org_repo = m.group(1).replace(".", "/")
            commit = m.group(2)
            full_repo = f"github.com/{org_repo}"
            if full_repo not in pins:
                pins[full_repo] = (commit, f"FROM sweap-images tag")

        # Only use first Dockerfile that has results (prefer baseline Dockerfile)
        if pins and df_name == "Dockerfile":
            break

    return pins


def resolve_pin_from_task_toml(task_dir: Path) -> str | None:
    """Try to extract pre_fix_rev from task.toml."""
    toml_path = task_dir / "task.toml"
    if not toml_path.exists():
        return None
    text = toml_path.read_text()
    m = re.search(r'pre_fix_rev\s*=\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    return None


def main():
    # Collect all tasks
    all_tasks = []
    for suite_dir in sorted(BENCHMARKS_DIR.iterdir()):
        if not suite_dir.is_dir() or suite_dir.name.startswith("."):
            continue
        for task_dir in sorted(suite_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            sg_only = task_dir / "environment" / "Dockerfile.sg_only"
            if not sg_only.exists():
                continue
            all_tasks.append(task_dir)

    # repo -> {commit -> [task_ids]}
    mirror_needs = defaultdict(lambda: defaultdict(list))
    # Track unresolved
    unresolved = []  # (repo, task_id)
    pinned_count = 0

    for task_dir in all_tasks:
        sg_only = task_dir / "environment" / "Dockerfile.sg_only"
        unpinned, pinned_list = extract_sg_repos(sg_only)
        pinned_count += len(pinned_list)

        if not unpinned:
            continue

        task_id = f"{task_dir.parent.name}/{task_dir.name}"
        pre_fix_rev = resolve_pin_from_task_toml(task_dir)
        dockerfile_pins = resolve_per_repo_pins(task_dir)

        for repo in unpinned:
            pin = None
            source = None

            # Priority 1: manual overrides for edge cases
            if task_id in MANUAL_OVERRIDES and repo in MANUAL_OVERRIDES[task_id]:
                pin, source = MANUAL_OVERRIDES[task_id][repo]

            # Priority 2: per-repo match from Dockerfile parsing
            if not pin and repo in dockerfile_pins:
                pin, source = dockerfile_pins[repo]

            # Priority 3: ccb-repo base image match by repo leaf name
            if not pin:
                repo_leaf = repo.split("/")[-1].lower()
                ccb_key = f"_ccb_repo_{repo_leaf}"
                if ccb_key in dockerfile_pins:
                    pin, source = dockerfile_pins[ccb_key]

            # Priority 4: single-repo tasks can use pre_fix_rev
            if not pin and pre_fix_rev and len(unpinned) == 1:
                pin = pre_fix_rev
                source = "task.toml pre_fix_rev"

            if pin:
                mirror_needs[repo][pin].append({"task": task_id, "source": source})
            else:
                unresolved.append((repo, task_id))

    # Print summary
    total_unpinned = sum(
        sum(len(tasks) for tasks in commits.values())
        for commits in mirror_needs.values()
    ) + len(unresolved)

    total_mirrors = sum(len(commits) for commits in mirror_needs.values())

    print(f"=== UNPINNED REPO AUDIT ===\n")
    print(f"Total SG repo references: {pinned_count + total_unpinned}")
    print(f"  Already pinned (sg-evals/): {pinned_count}")
    print(f"  Unpinned (github.com/): {total_unpinned}")
    print(f"  Unique upstream repos: {len(mirror_needs) + len(set(r for r, _ in unresolved))}")
    print(f"  Mirrors needed: {total_mirrors}")
    print(f"  Unresolved: {len(unresolved)}")

    # Detailed report
    print(f"\n{'='*80}")
    print(f"MIRRORS NEEDED (resolved)")
    print(f"{'='*80}")

    # Build raw entries, then deduplicate by mirror name
    # (short hash from ccb-repo tags and full hash from git checkout can collide)
    raw_entries = []

    for repo in sorted(mirror_needs.keys()):
        commits = mirror_needs[repo]
        for commit, task_list in sorted(commits.items()):
            repo_short = repo.replace("github.com/", "")
            repo_leaf = repo_short.split("/")[-1]
            pin_short = commit[:8] if len(commit) > 8 else commit
            mirror = f"sg-evals/{repo_leaf}--{pin_short}"

            raw_entries.append({
                "upstream": repo,
                "commit": commit,
                "mirror": mirror,
                "pin_source": task_list[0]["source"],
                "tasks": [t["task"] for t in task_list],
            })

    # Deduplicate: merge entries with same mirror name (prefer longer commit hash)
    manifest_entries = []
    seen_mirrors: dict[str, int] = {}
    for entry in raw_entries:
        key = entry["mirror"]
        if key in seen_mirrors:
            idx = seen_mirrors[key]
            existing = manifest_entries[idx]
            existing["tasks"].extend(entry["tasks"])
            # Keep the longer (more specific) commit hash
            if len(entry["commit"]) > len(existing["commit"]):
                existing["commit"] = entry["commit"]
        else:
            seen_mirrors[key] = len(manifest_entries)
            manifest_entries.append(entry)

    for entry in manifest_entries:
        print(f"  {entry['mirror']:<50} ← {entry['upstream'].replace('github.com/', '')} @ {entry['commit'][:40]}")
        tasks_str = ", ".join(t.split("/")[-1] for t in entry["tasks"])
        print(f"    Tasks: {tasks_str}")
        print(f"    Source: {entry['pin_source']}")

    if unresolved:
        print(f"\n{'='*80}")
        print(f"UNRESOLVED ({len(unresolved)} task-repo pairs)")
        print(f"{'='*80}")
        for repo, task_id in unresolved:
            print(f"  {repo:<50} ← {task_id}")

    # Write JSON manifest
    manifest = {
        "_description": "Mirrors needed for reproducible Sourcegraph indexing",
        "_generated": "2026-02-22",
        "_status": "PENDING — mirrors must be created on Sourcegraph before updating Dockerfile.sg_only files",
        "mirrors": manifest_entries,
        "unresolved": [{"repo": r, "task": t} for r, t in unresolved],
        "summary": {
            "total_mirrors_needed": len(manifest_entries),
            "unique_upstream_repos": len(mirror_needs),
            "tasks_affected": total_unpinned,
            "unresolved_count": len(unresolved),
        },
    }

    out_path = REPO_ROOT / "configs" / "mirror_creation_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nManifest written to {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()

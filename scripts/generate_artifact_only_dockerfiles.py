#!/usr/bin/env python3
"""Generate Dockerfile.artifact_only for ccb_test tasks.

Artifact-only evaluation: both configs produce a single artifact in one shot.
Verifier scores only the artifact applied to a clean repo copy.

Categories:
  - Code review (8): clone + inject defects → backup → clear workspace → marker
  - Performance (3): full build → backup → clear workspace → marker
  - Testing (6): minimal image → empty workspace → marker (verifier is regex-only)
  - Understanding (3): skip (no artifact mode needed)

Also copies artifact_verifier_lib.sh into each task's tests/ directory.

Usage:
  python3 scripts/generate_artifact_only_dockerfiles.py [--dry-run] [--verbose]
"""

import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = REPO_ROOT / "benchmarks" / "ccb_test"
LIB_SRC = REPO_ROOT / "scripts" / "artifact_verifier_lib.sh"

# Task classification — explicit for the 20-task pilot
CODE_REVIEW_TASKS = [
    "aspnetcore-code-review-001",
    "calcom-code-review-001",
    "curl-security-review-001",
    "envoy-code-review-001",
    "ghost-code-review-001",
    "kafka-security-review-001",
    "terraform-code-review-001",
    "vscode-code-review-001",
]

PERF_TASKS = [
    "numpy-array-sum-perf-001",
    "pandas-groupby-perf-001",
    "sklearn-kmeans-perf-001",
]

TESTING_TASKS = [
    "test-coverage-gap-001",
    "test-coverage-gap-002",
    "test-integration-001",
    "test-integration-002",
    "test-unitgen-py-001",
    "test-unitgen-go-001",
]

UNDERSTANDING_TASKS = [
    "llamacpp-context-window-search-001",
    "llamacpp-file-modify-search-001",
    "openhands-search-file-test-001",
]

# All tasks that get Dockerfile.artifact_only
ARTIFACT_TASKS = CODE_REVIEW_TASKS + PERF_TASKS + TESTING_TASKS

ARTIFACT_SECTION = """
# --- artifact_only: backup full repo, then clear workspace for agent ---
RUN cp -a {workdir} /repo_full
RUN rm -rf {workdir} && mkdir -p {workdir}
RUN touch /tmp/.artifact_only_mode && echo '{workdir}' > /tmp/.artifact_only_workdir

WORKDIR {workdir}

ENTRYPOINT []
"""


def detect_workdir(dockerfile_text: str) -> str:
    """Detect the last WORKDIR from a Dockerfile."""
    workdirs = re.findall(r"^WORKDIR\s+(\S+)", dockerfile_text, re.MULTILINE)
    return workdirs[-1] if workdirs else "/workspace"


def detect_base_image(dockerfile_text: str) -> str:
    """Detect the FROM image."""
    m = re.match(r"^FROM\s+(\S+)", dockerfile_text, re.MULTILINE)
    return m.group(1) if m else "ubuntu:22.04"


def generate_build_requiring(task_dir: Path, dockerfile_text: str) -> str:
    """Generate Dockerfile.artifact_only for build-requiring tasks.

    Keeps the full original Dockerfile (clone, build deps, inject_defects)
    then appends: backup → clear workspace → marker.
    """
    task_name = task_dir.name
    workdir = detect_workdir(dockerfile_text)
    lines = dockerfile_text.rstrip().split("\n")

    # Find insertion point: before last ENTRYPOINT/CMD, or at end
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("ENTRYPOINT") or stripped.startswith("CMD"):
            insert_idx = i
            break

    header = (
        f"# {task_name} — artifact_only variant\n"
        "# Full repo backed up to /repo_full, workspace cleared for agent.\n"
        "# Verifier applies agent patches to /repo_full copy for scoring.\n\n"
    )

    body = "\n".join(lines[:insert_idx])
    section = ARTIFACT_SECTION.format(workdir=workdir)

    return header + body + "\n" + section


def generate_testing_write_only(task_dir: Path, dockerfile_text: str) -> str:
    """Generate Dockerfile.artifact_only for testing tasks (write-only).

    Minimal image with language runtime. No repo clone.
    Verifier scores by regex on test file content.
    """
    task_name = task_dir.name
    base_image = detect_base_image(dockerfile_text)

    # Map base images to appropriate minimal variants
    if "golang" in base_image.lower() or "go:" in base_image.lower():
        runtime_image = "golang:1.22-bookworm"
        extra_pkgs = "python3"
    elif "python" in base_image.lower():
        runtime_image = "python:3.12-bookworm"
        extra_pkgs = ""
    elif "ccb-repo-envoy" in base_image or "ccb-repo-kafka" in base_image:
        # Pre-built repo images — use minimal ubuntu (verifier only needs python3)
        runtime_image = "ubuntu:22.04"
        extra_pkgs = "python3 ca-certificates"
    else:
        runtime_image = "ubuntu:22.04"
        extra_pkgs = "python3 ca-certificates"

    pkg_line = f"    {extra_pkgs} \\\n" if extra_pkgs else ""

    return f"""# {task_name} — artifact_only variant
# Minimal image: verifier scores test file by regex, no compilation needed.
# Agent uses Sourcegraph MCP for code discovery.

FROM {runtime_image}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    curl \\
{pkg_line}    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

# Mark artifact-only mode
RUN touch /tmp/.artifact_only_mode

ENTRYPOINT []
"""


def copy_lib(task_dir: Path, dry_run: bool = False) -> bool:
    """Copy artifact_verifier_lib.sh to the task's tests/ directory."""
    tests_dir = task_dir / "tests"
    if not tests_dir.exists():
        tests_dir.mkdir(parents=True, exist_ok=True)

    dest = tests_dir / "artifact_verifier_lib.sh"
    if not LIB_SRC.exists():
        print(f"  ERROR: {LIB_SRC} not found")
        return False

    if dry_run:
        if dest.exists():
            return False
        return True

    shutil.copy2(LIB_SRC, dest)
    dest.chmod(0o755)
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    generated = 0
    skipped = 0
    libs_copied = 0
    errors = []

    for task_id in ARTIFACT_TASKS:
        task_dir = BENCHMARKS / task_id
        if not task_dir.exists():
            errors.append((task_id, "task directory not found"))
            continue

        env_dir = task_dir / "environment"
        dockerfile = env_dir / "Dockerfile"
        artifact_only = env_dir / "Dockerfile.artifact_only"

        if artifact_only.exists():
            skipped += 1
            if verbose:
                print(f"  SKIP {task_id}: already has Dockerfile.artifact_only")
            continue

        if not dockerfile.exists():
            errors.append((task_id, "no Dockerfile"))
            continue

        dockerfile_text = dockerfile.read_text()

        try:
            if task_id in CODE_REVIEW_TASKS:
                content = generate_build_requiring(task_dir, dockerfile_text)
                label = "code-review"
            elif task_id in PERF_TASKS:
                content = generate_build_requiring(task_dir, dockerfile_text)
                label = "performance"
            elif task_id in TESTING_TASKS:
                content = generate_testing_write_only(task_dir, dockerfile_text)
                label = "testing"
            else:
                if verbose:
                    print(f"  SKIP {task_id}: understanding task")
                continue

            if dry_run:
                print(f"  {label.upper():>15} {task_id}")
            else:
                env_dir.mkdir(parents=True, exist_ok=True)
                artifact_only.write_text(content)
                generated += 1
                if verbose:
                    print(f"  GENERATED {task_id} ({label})")

            # Copy artifact_verifier_lib.sh
            if copy_lib(task_dir, dry_run=dry_run):
                libs_copied += 1

        except Exception as e:
            errors.append((task_id, str(e)))
            print(f"  ERROR {task_id}: {e}")

    print(f"\n{'DRY RUN — ' if dry_run else ''}Summary:")
    print(f"  Already existed: {skipped}")
    print(f"  Generated: {generated}")
    print(f"  Libs copied: {libs_copied}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for tid, err in errors:
            print(f"    {tid}: {err}")


if __name__ == "__main__":
    main()

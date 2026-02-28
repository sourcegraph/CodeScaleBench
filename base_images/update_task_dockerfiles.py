#!/usr/bin/env python3
"""Update task Dockerfiles to reference pre-built CCB base images.

For each task whose Dockerfile matches a known base pattern (same FROM image,
same repo clone at same commit), replaces the common layers with a single
FROM ccb-repo-xxx line, keeping only task-specific additions.

Usage:
    python3 base_images/update_task_dockerfiles.py [--dry-run]
"""

import os
import re
import sys
from pathlib import Path

BENCHMARKS_DIR = Path(__file__).parent.parent / "benchmarks"

# Base image definitions: tag -> fingerprint to match in Dockerfiles
# Each entry: (base_tag, from_image, clone_url_fragment, commit_fragment, extra_base_lines)
# extra_base_lines: lines that are part of the base (e.g. "pip install -e .") — skip these too
BASES = [
    {
        "tag": "ccb-repo-django-674eda1c",
        "from_image": "python:3.11-slim",
        "clone_url": "django/django",
        "commit": "674eda1c03a3187905f48afee0f15226aa62fdf3",
        "skip_patterns": [
            r"pip install -e \.",  # included in base
        ],
    },
    {
        "tag": "ccb-repo-k8s-11602f08",
        "from_image": "golang:1.23-bookworm",
        "clone_url": "kubernetes/kubernetes",
        "commit": "11602f083ca275dcfd4341641ae7fe338b7f6f69",
        "skip_patterns": [],
    },
    {
        "tag": "ccb-repo-k8s-8c9c67c0",
        "from_image": "golang:1.23-bookworm",
        "clone_url": "kubernetes/kubernetes",
        "commit": "8c9c67c000104450cfc5a5f48053a9a84b73cf93",
        "skip_patterns": [],
    },
    {
        "tag": "ccb-repo-flipt-3d5a345f",
        "from_image": "golang:1.23-bookworm",
        "clone_url": "flipt-io/flipt",
        "commit": "3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8",
        "skip_patterns": [
            r"go mod download",  # included in base
        ],
    },
    {
        "tag": "ccb-repo-flink-0cc95fcc",
        "from_image": "eclipse-temurin:17-jdk",
        "clone_url": "apache/flink",
        "commit": "0cc95fcc145eddcfc87fc1b4ddf96ddd0f2ee15f",
        "skip_patterns": [],
    },
    {
        "tag": "ccb-repo-kafka-0753c489",
        "from_image": "eclipse-temurin:17-jdk",
        "clone_url": "apache/kafka",
        "commit": "0753c489afad403fb6e78fda4c4a380e46f500c0",
        "skip_patterns": [],
    },
    {
        "tag": "ccb-repo-kafka-e678b4b",
        "from_image": "eclipse-temurin:21-jdk",
        "clone_url": "apache/kafka",
        "commit": "e678b4b",
        "skip_patterns": [],
    },
]


def parse_dockerfile(path: Path) -> list[str]:
    """Read Dockerfile and return list of logical blocks (multi-line RUN collapsed)."""
    return path.read_text().splitlines()


def matches_base(lines: list[str], base: dict) -> bool:
    """Check if a Dockerfile matches a base image pattern."""
    text = "\n".join(lines)

    # Must have matching FROM
    if f"FROM {base['from_image']}" not in text:
        return False

    # Must clone the right repo at the right commit
    if base["clone_url"] not in text:
        return False
    if base["commit"] not in text:
        return False

    # Must clone to WORKDIR (.) not a subdirectory — skip cross-repo tasks
    # Cross-repo tasks clone to named dirs like /workspace/kafka/ or /workspace/flink/
    clone_line_pattern = re.compile(
        rf"git clone.*{re.escape(base['clone_url'])}.*\s+\."
    )
    if not clone_line_pattern.search(text):
        # Check if it clones to "." (current dir) at end of line
        alt_pattern = re.compile(
            rf"git clone.*{re.escape(base['clone_url'])}\.git \."
        )
        if not alt_pattern.search(text):
            return False

    return True


def extract_task_specific_lines(lines: list[str], base: dict) -> list[str]:
    """Extract lines that are task-specific (not part of the base)."""
    result = []
    skip_until_next_command = False
    found_clone = False

    # Patterns to skip (base infrastructure)
    base_patterns = [
        r"^FROM ",
        r"^WORKDIR /workspace",
        r"^RUN apt-get",
        r"^RUN git clone",
        r"^RUN git config",  # standalone git config
        r"^\s+git checkout",
        r"^\s+git config",
        r"^\s+git clone",
        r"^\s+&&\s*rm -rf /var/lib/apt/lists",
        r"^\s+curl\b",  # curl lines in apt-get blocks
        r"^\s+python3",  # package names in apt-get blocks
        r"^\s+git\\?$",  # package names in apt-get blocks
        r"^\s+ripgrep",
        r"^\s+maven",
        r"^#.*[Ii]nstall.*depend",
        r"^#.*[Cc]lone",
        r"^#.*pinned commit",
        r"^#.*setup complete",
        r"^#.*baseline.*MCP",
        r"^#.*Sourcegraph",
    ]

    # Add base-specific skip patterns
    for pat in base.get("skip_patterns", []):
        base_patterns.append(rf"^RUN {pat}")

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines before we find the clone
        if not found_clone:
            if base["clone_url"] in line or base["commit"] in line:
                found_clone = True
                # Skip this line and any continuation lines
                while i < len(lines) - 1 and lines[i].rstrip().endswith("\\"):
                    i += 1
                i += 1
                continue

            # Skip base infrastructure lines
            is_base = False
            for pat in base_patterns:
                if re.match(pat, stripped) or re.match(pat, line):
                    is_base = True
                    break

            if is_base:
                # Skip continuation lines
                while i < len(lines) - 1 and lines[i].rstrip().endswith("\\"):
                    i += 1
                i += 1
                continue

            i += 1
            continue

        # After the clone, check for skip patterns
        is_skip = False
        for pat in base.get("skip_patterns", []):
            if re.search(pat, stripped):
                is_skip = True
                break

        # Skip comments about standard setup
        if stripped.startswith("#") and any(
            kw in stripped.lower()
            for kw in ["task setup complete", "baseline", "sourcegraph", "mcp agent"]
        ):
            is_skip = True

        # Skip empty RUN mkdir that just creates standard dirs
        if re.match(r"^RUN mkdir -p /workspace/tests /app$", stripped):
            is_skip = True

        if is_skip:
            while i < len(lines) - 1 and lines[i].rstrip().endswith("\\"):
                i += 1
            i += 1
            continue

        result.append(line)
        i += 1

    # Strip leading/trailing blank lines
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()

    return result


GHCR_PREFIX = "ghcr.io/sourcegraph"


def rewrite_dockerfile(path: Path, base: dict, task_lines: list[str], dry_run: bool) -> bool:
    """Rewrite a task Dockerfile to use a base image from GHCR."""
    new_lines = [f"FROM {GHCR_PREFIX}/{base['tag']}"]

    if task_lines:
        new_lines.append("")
        new_lines.extend(task_lines)

    new_lines.append("")  # trailing newline

    new_content = "\n".join(new_lines)

    if dry_run:
        return True

    path.write_text(new_content)
    return True


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("DRY RUN — no files will be modified\n")

    # Find all task Dockerfiles
    dockerfiles = sorted(BENCHMARKS_DIR.glob("ccb_*/*/environment/Dockerfile"))
    print(f"Scanning {len(dockerfiles)} task Dockerfiles...\n")

    stats = {base["tag"]: [] for base in BASES}
    skipped = []

    for df_path in dockerfiles:
        lines = parse_dockerfile(df_path)
        task_dir = df_path.parent.parent.name

        for base in BASES:
            if matches_base(lines, base):
                task_lines = extract_task_specific_lines(lines, base)
                rewrite_dockerfile(df_path, base, task_lines, dry_run)
                stats[base["tag"]].append((task_dir, len(task_lines)))
                break

    # Print summary
    total = 0
    print("=" * 70)
    print("BASE IMAGE ADOPTION SUMMARY")
    print("=" * 70)
    for base in BASES:
        tasks = stats[base["tag"]]
        if tasks:
            total += len(tasks)
            print(f"\n{base['tag']} ({len(tasks)} tasks):")
            for task_dir, extra_lines in tasks:
                marker = f" (+{extra_lines} task-specific lines)" if extra_lines else ""
                print(f"  - {task_dir}{marker}")

    print(f"\n{'=' * 70}")
    print(f"Total: {total} task Dockerfiles {'would be ' if dry_run else ''}updated")
    print(f"Remaining: {len(dockerfiles) - total} tasks unchanged (different base/repo/commit)")

    if dry_run:
        print("\nRe-run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build a structured registry of all benchmark tasks for the Daytona runner.

Scans every task under benchmarks/, parses task.toml and Dockerfiles, and
produces a JSON registry cataloging metadata, Docker image requirements,
test infrastructure, and Daytona readiness classification.

Usage:
    python3 scripts/build_daytona_registry.py [--output PATH] [--summary]

Output: scripts/daytona_task_registry.json (default)
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
BASE_IMAGES_DIR = REPO_ROOT / "base_images"

# ---------------------------------------------------------------------------
# TOML parsing (minimal, stdlib-only — handles flat tables and string arrays)
# ---------------------------------------------------------------------------

def parse_toml_simple(path: Path) -> Dict[str, Any]:
    """Parse a simple TOML file into nested dicts.

    Handles: [section], key = "value", key = number, key = bool,
    key = ["a", "b"], multi-line strings (triple-quoted).
    Does NOT handle inline tables or deeply nested structures.
    """
    result: Dict[str, Any] = {}
    current_section: Optional[Dict[str, Any]] = result
    section_path: List[str] = []

    try:
        lines = path.read_text().splitlines()
    except Exception:
        return {}

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            i += 1
            continue

        # Section header: [section] or [section.subsection]
        section_match = re.match(r"^\[([^\]]+)\]$", line)
        if section_match:
            section_path = section_match.group(1).split(".")
            current_section = result
            for part in section_path:
                if part not in current_section:
                    current_section[part] = {}
                current_section = current_section[part]
            i += 1
            continue

        # Key = value
        kv_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*)$', line)
        if kv_match and current_section is not None:
            key = kv_match.group(1)
            raw_value = kv_match.group(2).strip()

            # Multi-line string (triple-quoted)
            if raw_value.startswith('"""'):
                ml_lines = [raw_value[3:]]
                i += 1
                while i < len(lines):
                    if '"""' in lines[i]:
                        ml_lines.append(lines[i].split('"""')[0])
                        break
                    ml_lines.append(lines[i])
                    i += 1
                current_section[key] = "\n".join(ml_lines)
                i += 1
                continue

            # String
            if raw_value.startswith('"') and raw_value.endswith('"'):
                current_section[key] = raw_value[1:-1]
            # Boolean
            elif raw_value in ("true", "false"):
                current_section[key] = raw_value == "true"
            # Number (int or float)
            elif re.match(r'^-?\d+(\.\d+)?$', raw_value):
                current_section[key] = (
                    float(raw_value) if "." in raw_value else int(raw_value)
                )
            # Array of strings
            elif raw_value.startswith("["):
                array_str = raw_value
                # Handle multi-line arrays
                while not array_str.rstrip().endswith("]"):
                    i += 1
                    if i < len(lines):
                        array_str += " " + lines[i].strip()
                items = re.findall(r'"([^"]*)"', array_str)
                current_section[key] = items
            else:
                current_section[key] = raw_value

        i += 1

    return result


# ---------------------------------------------------------------------------
# Dockerfile analysis
# ---------------------------------------------------------------------------

def extract_from_lines(dockerfile_path: Path) -> List[str]:
    """Extract all FROM image references from a Dockerfile.

    Handles heredocs (skips FROM-like lines inside heredoc blocks) and
    multi-stage builds (filters out references to earlier stage aliases).
    """
    from_images = []
    stage_aliases: set = set()
    in_heredoc = False
    heredoc_delim = ""
    try:
        for line in dockerfile_path.read_text().splitlines():
            stripped = line.strip()

            # Track heredoc blocks to avoid matching FROM inside them
            if in_heredoc:
                if stripped == heredoc_delim:
                    in_heredoc = False
                continue

            # Detect heredoc start: << 'DELIM' or << DELIM or <<- DELIM
            heredoc_match = re.search(r"<<-?\s*'?(\w+)'?", line)
            if heredoc_match:
                heredoc_delim = heredoc_match.group(1)
                in_heredoc = True
                # Don't skip this line — it may also contain a RUN/etc command
                # but it won't contain a FROM, so no further action needed

            match = re.match(r"^FROM\s+(\S+)(\s+AS\s+(\S+))?", stripped, re.IGNORECASE)
            if match:
                image = match.group(1)
                alias = match.group(3)
                # Record stage alias for later filtering
                if alias:
                    stage_aliases.add(alias.lower())
                # Skip references to earlier build stages (e.g. FROM base AS final)
                if image.lower() not in stage_aliases:
                    from_images.append(image)
    except Exception:
        pass
    return from_images


def classify_base_image(image: str) -> str:
    """Classify a Docker base image for Daytona readiness.

    Returns one of:
      - "standard"    : Public registry images (ubuntu, python, golang, etc.)
      - "ccb_repo"    : CCB pre-built repo images (ccb-repo-*)
      - "sweap"       : SWE-bench Pro images (jefzda/sweap-images:*)
      - "tac"         : TheAgentCompany images (ghcr.io/theagentcompany/*)
      - "ccb_linux"   : CCB Linux kernel images (ccb-linux-base:*)
      - "dotnet"      : Microsoft .NET SDK images
      - "unknown"     : Unrecognized
    """
    if image.startswith("ccb-repo-") or "ccb-repo-" in image:
        return "ccb_repo"
    if image.startswith("ccb-linux-base:"):
        return "ccb_linux"
    if image.startswith("jefzda/sweap-images:"):
        return "sweap"
    if image.startswith("ghcr.io/theagentcompany/"):
        return "tac"
    if image.startswith("mcr.microsoft.com/"):
        return "dotnet"
    # Standard public images
    standard_prefixes = (
        "ubuntu:", "debian:", "python:", "golang:", "node:",
        "rust:", "gcc:", "eclipse-temurin:", "alpine:",
    )
    for prefix in standard_prefixes:
        if image.startswith(prefix):
            return "standard"
    return "unknown"


def daytona_readiness(image_classes: List[str]) -> str:
    """Determine overall Daytona readiness from image classifications.

    Returns:
      - "ready"             : All images are publicly pullable (standard, ccb_repo,
                              sweap on Docker Hub, tac on GHCR)
      - "needs_registry"    : Requires private registry access (dotnet/mcr)
      - "needs_custom_build": Requires custom kernel/special build steps
    """
    classes = set(image_classes)
    if "ccb_linux" in classes:
        return "needs_custom_build"
    # ccb_repo on GHCR, sweap on Docker Hub, tac on GHCR — all public
    if classes <= {"standard", "ccb_repo", "sweap", "tac"}:
        return "ready"
    if classes & {"dotnet"}:
        return "needs_registry"
    return "needs_custom_build"


# ---------------------------------------------------------------------------
# Task scanner
# ---------------------------------------------------------------------------

def scan_task(task_dir: Path) -> Optional[Dict[str, Any]]:
    """Scan a single task directory and extract registry metadata."""
    suite = task_dir.parent.name
    task_id = task_dir.name
    env_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"

    # Must have at least a Dockerfile
    dockerfile = env_dir / "Dockerfile"
    if not dockerfile.exists():
        return None

    # Parse task.toml
    task_toml = task_dir / "task.toml"
    toml_data = parse_toml_simple(task_toml) if task_toml.exists() else {}

    # Extract metadata from TOML (handle two schema variants)
    metadata = toml_data.get("metadata", {})
    task_section = toml_data.get("task", {})
    verification = toml_data.get("verification", {})
    environment = toml_data.get("environment", {})

    # Language: prefer task.language, fall back to metadata
    language = task_section.get("language", metadata.get("language", ""))

    # Category
    category = task_section.get("category", metadata.get("category", ""))

    # Difficulty
    difficulty = task_section.get("difficulty", metadata.get("difficulty", ""))

    # Repo
    repo = task_section.get("repo", "")

    # Timeouts
    agent_timeout = (
        task_section.get("time_limit_sec")
        or toml_data.get("agent", {}).get("timeout_sec")
        or 900
    )
    build_timeout = environment.get("build_timeout_sec", 300)

    # Reward type
    reward_type = (
        verification.get("reward_type")
        or task_section.get("reward_type", "")
    )

    # MCP-specific fields
    mcp_suite = task_section.get("mcp_suite", "")
    use_case_id = task_section.get("use_case_id", "")

    # Resource requirements
    cpus = environment.get("cpus", 2)
    memory_mb = environment.get("memory_mb", 4096)
    storage_mb = environment.get("storage_mb", 10240)

    # Tags
    tags = metadata.get("tags", [])

    # --- Dockerfiles ---
    dockerfiles = {}
    dockerfile_variants = [
        ("baseline", "Dockerfile"),
        ("sg_only", "Dockerfile.sg_only"),
        ("artifact_only", "Dockerfile.artifact_only"),
    ]

    all_image_classes = []

    for variant_name, filename in dockerfile_variants:
        df_path = env_dir / filename
        if df_path.exists():
            from_lines = extract_from_lines(df_path)
            classes = [classify_base_image(img) for img in from_lines]
            all_image_classes.extend(classes)
            dockerfiles[variant_name] = {
                "exists": True,
                "from_images": from_lines,
                "image_classes": classes,
            }
        else:
            dockerfiles[variant_name] = {"exists": False}

    # Check for nested repo/Dockerfile
    repo_dockerfile = env_dir / "repo" / "Dockerfile"
    if repo_dockerfile.exists():
        from_lines = extract_from_lines(repo_dockerfile)
        classes = [classify_base_image(img) for img in from_lines]
        all_image_classes.extend(classes)
        dockerfiles["repo_nested"] = {
            "exists": True,
            "from_images": from_lines,
            "image_classes": classes,
        }

    # --- Test infrastructure ---
    test_sh = tests_dir / "test.sh"
    eval_sh = tests_dir / "eval.sh"
    validators_py = tests_dir / "validators.py"
    instance_json = tests_dir / "instance.json"

    tests = {
        "test_sh": test_sh.exists(),
        "eval_sh": eval_sh.exists(),
        "validators_py": validators_py.exists(),
        "instance_json": instance_json.exists(),
    }

    # Extract instance.json metadata if present
    instance_meta = {}
    if instance_json.exists():
        try:
            instance_meta = json.loads(instance_json.read_text())
        except Exception:
            pass

    # --- Instructions ---
    instruction_md = task_dir / "instruction.md"
    instruction_mcp_md = task_dir / "instruction_mcp.md"

    instructions = {
        "baseline": instruction_md.exists(),
        "mcp": instruction_mcp_md.exists(),
    }

    # Infer verification command
    verify_command = verification.get("command", "")
    if not verify_command:
        if test_sh.exists():
            verify_command = "bash /tests/test.sh"
        elif eval_sh.exists():
            verify_command = "bash /tests/eval.sh"

    # --- Unique base images needed ---
    unique_images = sorted(set(
        img
        for variant in dockerfiles.values()
        if isinstance(variant, dict) and variant.get("exists")
        for img in variant.get("from_images", [])
    ))

    # Deduplicate image classes for readiness
    baseline_classes = [
        classify_base_image(img)
        for img in dockerfiles.get("baseline", {}).get("from_images", [])
    ]

    return {
        "task_id": task_id,
        "suite": suite,
        "language": language or instance_meta.get("language", ""),
        "category": category,
        "difficulty": difficulty,
        "repo": repo,
        "tags": tags,
        "mcp_suite": mcp_suite,
        "use_case_id": use_case_id,
        "timeouts": {
            "agent_sec": agent_timeout,
            "build_sec": build_timeout,
        },
        "resources": {
            "cpus": cpus,
            "memory_mb": memory_mb,
            "storage_mb": storage_mb,
        },
        "reward_type": reward_type,
        "dockerfiles": dockerfiles,
        "unique_base_images": unique_images,
        "daytona_readiness": daytona_readiness(baseline_classes),
        "tests": tests,
        "instructions": instructions,
        "verify_command": verify_command,
        "instance_meta": instance_meta if instance_meta else None,
    }


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

def build_registry() -> Dict[str, Any]:
    """Scan all benchmark suites and build the complete registry."""
    tasks = []
    suites = {}

    for suite_dir in sorted(BENCHMARKS_DIR.iterdir()):
        if not suite_dir.is_dir() or suite_dir.name.startswith("."):
            continue

        suite_name = suite_dir.name
        suite_tasks = []

        for task_dir in sorted(suite_dir.iterdir()):
            if not task_dir.is_dir() or task_dir.name.startswith("."):
                continue

            entry = scan_task(task_dir)
            if entry:
                tasks.append(entry)
                suite_tasks.append(entry["task_id"])

        if suite_tasks:
            suites[suite_name] = {
                "task_count": len(suite_tasks),
                "task_ids": suite_tasks,
            }

    # Build summary statistics
    readiness_counts = {}
    image_class_counts = {}
    language_counts = {}
    suite_readiness = {}

    for task in tasks:
        # Readiness
        r = task["daytona_readiness"]
        readiness_counts[r] = readiness_counts.get(r, 0) + 1

        # Image classes (from baseline Dockerfile)
        baseline_df = task["dockerfiles"].get("baseline", {})
        for cls in baseline_df.get("image_classes", []):
            image_class_counts[cls] = image_class_counts.get(cls, 0) + 1

        # Language
        lang = task["language"] or "unknown"
        language_counts[lang] = language_counts.get(lang, 0) + 1

        # Per-suite readiness
        suite = task["suite"]
        if suite not in suite_readiness:
            suite_readiness[suite] = {}
        suite_readiness[suite][r] = suite_readiness[suite].get(r, 0) + 1

    # Collect all ccb-repo-* images needed
    ccb_repo_images = sorted(set(
        img
        for task in tasks
        for img in task["unique_base_images"]
        if img.startswith("ccb-repo-")
    ))

    # Check which are available in base_images/
    available_base_images = []
    if BASE_IMAGES_DIR.exists():
        for df in BASE_IMAGES_DIR.glob("Dockerfile.*"):
            tag_suffix = df.name.replace("Dockerfile.", "")
            available_base_images.append(f"ccb-repo-{tag_suffix}")

    missing_base_images = sorted(
        set(ccb_repo_images) - set(available_base_images)
    )

    return {
        "version": "1.0",
        "generated_by": "scripts/build_daytona_registry.py",
        "benchmarks_dir": str(BENCHMARKS_DIR),
        "summary": {
            "total_tasks": len(tasks),
            "total_suites": len(suites),
            "readiness": readiness_counts,
            "image_classes": image_class_counts,
            "languages": language_counts,
            "suite_readiness": suite_readiness,
            "ccb_repo_images_needed": ccb_repo_images,
            "ccb_repo_images_available": available_base_images,
            "ccb_repo_images_missing": missing_base_images,
        },
        "suites": suites,
        "tasks": tasks,
    }


def print_summary(registry: Dict[str, Any]) -> None:
    """Print a human-readable summary of the registry."""
    summary = registry["summary"]
    suites = registry["suites"]

    print(f"\n{'='*70}")
    print(f"DAYTONA TASK REGISTRY")
    print(f"{'='*70}")
    print(f"\nTotal tasks: {summary['total_tasks']}")
    print(f"Total suites: {summary['total_suites']}")

    print(f"\n--- Daytona Readiness ---")
    for level, count in sorted(summary["readiness"].items()):
        pct = count / summary["total_tasks"] * 100
        print(f"  {level:<25} {count:>4} ({pct:5.1f}%)")

    print(f"\n--- Base Image Classes ---")
    for cls, count in sorted(
        summary["image_classes"].items(), key=lambda x: -x[1]
    ):
        print(f"  {cls:<25} {count:>4}")

    print(f"\n--- Languages ---")
    for lang, count in sorted(
        summary["languages"].items(), key=lambda x: -x[1]
    ):
        print(f"  {lang:<25} {count:>4}")

    print(f"\n--- Suites ---")
    print(f"  {'Suite':<40} {'Tasks':>6} {'Ready':>6} {'Base':>6} {'Reg':>6} {'Custom':>6}")
    print(f"  {'-'*40} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for suite_name in sorted(suites):
        s = suites[suite_name]
        sr = summary["suite_readiness"].get(suite_name, {})
        print(
            f"  {suite_name:<40} {s['task_count']:>6}"
            f" {sr.get('ready', 0):>6}"
            f" {sr.get('needs_base_build', 0):>6}"
            f" {sr.get('needs_registry', 0):>6}"
            f" {sr.get('needs_custom_build', 0):>6}"
        )

    print(f"\n--- CCB Repo Base Images ---")
    print(f"  Needed:    {len(summary['ccb_repo_images_needed'])}")
    print(f"  Available: {len(summary['ccb_repo_images_available'])}")
    print(f"  Missing:   {len(summary['ccb_repo_images_missing'])}")
    if summary["ccb_repo_images_missing"]:
        for img in summary["ccb_repo_images_missing"]:
            print(f"    MISSING: {img}")

    print(f"\n{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Build Daytona task registry from benchmarks"
    )
    parser.add_argument(
        "--output", "-o",
        default=str(REPO_ROOT / "scripts" / "daytona_task_registry.json"),
        help="Output JSON path (default: scripts/daytona_task_registry.json)",
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Print human-readable summary",
    )
    args = parser.parse_args()

    if not BENCHMARKS_DIR.exists():
        print(f"ERROR: Benchmarks directory not found: {BENCHMARKS_DIR}")
        sys.exit(1)

    print(f"Scanning {BENCHMARKS_DIR} ...")
    registry = build_registry()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, indent=2, default=str))
    print(f"Registry written to {output_path}")
    print(
        f"  {registry['summary']['total_tasks']} tasks across "
        f"{registry['summary']['total_suites']} suites"
    )

    if args.summary:
        print_summary(registry)


if __name__ == "__main__":
    main()

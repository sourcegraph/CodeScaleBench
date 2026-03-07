#!/usr/bin/env python3
"""Generate org-scale benchmark task directories from the use case registry.

Reads configs/use_case_registry.json and fixtures/repo_sets/*.json, fills
templates from templates/csb-org/, and writes task directories under
benchmarks/<mcp_suite>/<task_slug>/.

Usage:
    python3 scripts/generate_mcp_unique_tasks.py --use-case-ids 1 4 10
    python3 scripts/generate_mcp_unique_tasks.py --category A
    python3 scripts/generate_mcp_unique_tasks.py --family cross-repo-dep-trace
    python3 scripts/generate_mcp_unique_tasks.py --all --dry-run
    python3 scripts/generate_mcp_unique_tasks.py --category A --curate-oracle --verbose
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants and mappings
# ---------------------------------------------------------------------------

# Short family names for task IDs (CCX-<short_family>-<NNN>)
FAMILY_SHORT_NAME: Dict[str, str] = {
    "cross-repo-dep-trace": "dep-trace",
    "cross-repo-config-trace": "config-trace",
    "vuln-remediation": "vuln-remed",
    "migration-inventory": "migration",
    "incident-debug": "incident",
    "onboarding-comprehension": "onboard",
    "compliance-audit": "compliance",
    "cross-org-discovery": "crossorg",
    "agentic-correctness": "agentic",
    "domain-lineage": "domain",
    "platform-knowledge": "platform",
}

# apt packages for each primary language
LANGUAGE_PACKAGES: Dict[str, str] = {
    "Go": "golang-go",
    "Python": "python3 python3-pip",
    "JavaScript": "nodejs npm",
    "TypeScript": "nodejs npm",
    "Rust": "cargo",
    "Java": "default-jdk",
    "C": "gcc make",
    "C++": "g++ make",
}

# Default oracle check types per evaluation category
DEFAULT_CHECKS_BY_ORACLE_TYPE: Dict[str, List[Dict]] = {
    "deterministic_json": [
        {"type": "file_set_match", "params": {"search_pattern": "", "file_filter": ""}},
    ],
    "exit_code": [
        {"type": "file_set_match", "params": {"search_pattern": ""}},
    ],
    "unit_tests": [
        {"type": "test_ratio", "params": {"test_command": "python3 -m pytest", "workspace_dir": "/workspace"}},
    ],
    "hybrid": [
        {"type": "file_set_match", "params": {"search_pattern": ""}},
        {"type": "keyword_presence", "params": {"required_keywords": []}},
    ],
    "rubric_judge": [
        {"type": "keyword_presence", "params": {"required_keywords": []}},
        {"type": "provenance", "params": {"must_cite_paths": [], "must_cite_repos": []}},
    ],
    "tbd": [
        {"type": "file_set_match", "params": {"search_pattern": ""}},
    ],
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    """Find project root (contains benchmarks/ or fixtures/)."""
    for candidate in [start.resolve(), Path.cwd().resolve()]:
        current = candidate
        for _ in range(10):
            if (current / "benchmarks").is_dir() or (current / "fixtures").is_dir():
                return current
            current = current.parent
    return start.resolve()


def _registry_path(project_root: Path) -> Path:
    """Find use_case_registry.json — check project root and ralph-mcp-unique/."""
    candidates = [
        project_root / "configs" / "use_case_registry.json",
        project_root / "ralph-mcp-unique" / "configs" / "use_case_registry.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # return primary for error message


def _fixture_path(project_root: Path, repo_set_id: str) -> Path:
    return project_root / "fixtures" / "repo_sets" / f"{repo_set_id}.json"


def _templates_dir(project_root: Path) -> Path:
    return project_root / "templates" / "csb-org"


def _task_dir(project_root: Path, mcp_suite: str, task_slug: str) -> Path:
    return project_root / "benchmarks" / mcp_suite / task_slug


# ---------------------------------------------------------------------------
# Task ID and slug derivation
# ---------------------------------------------------------------------------

def derive_task_id(use_case: Dict) -> str:
    """Derive CCX-<short_family>-<NNN> task ID from use case registry entry."""
    family = use_case.get("task_family", "unknown")
    short = FAMILY_SHORT_NAME.get(family, family[:8])
    uid = use_case.get("use_case_id", 0)
    return f"CCX-{short}-{uid:03d}"


def derive_task_slug(task_id: str) -> str:
    """Convert CCX-dep-trace-001 to ccx-dep-trace-001 (directory name)."""
    return task_id.lower()


# ---------------------------------------------------------------------------
# Template variable construction
# ---------------------------------------------------------------------------

def build_template_vars(
    use_case: Dict,
    fixture: Optional[Dict],
    task_id: str,
) -> Dict[str, str]:
    """Build the full set of string.Template variables for all templates."""
    mcp_suite = use_case.get("mcp_suite", "ccb_mcp_unknown")
    task_family = use_case.get("task_family", "unknown")
    language = "unknown"
    primary_repo = "org/repo"
    local_repos: List[str] = []
    mcp_repos: List[str] = []

    if fixture:
        language = fixture.get("primary_language", "unknown")
        local_repos = fixture.get("local_checkout_repos", [])
        mcp_repos = fixture.get("mcp_only_repos", [])
        if local_repos:
            primary_repo = local_repos[0]

    # Language setup
    lang_pkgs = LANGUAGE_PACKAGES.get(language, "")

    # Clone commands for baseline Dockerfile
    clone_cmds = []
    if fixture and local_repos:
        for repo_entry in fixture.get("repos", []):
            if repo_entry.get("full_name") in local_repos:
                org_repo = repo_entry["full_name"]
                dest = f"/workspace/{org_repo.split('/')[-1]}"
                # sg-evals mirrors are orphan repos where HEAD = pinned commit;
                # --branch with a commit hash fails, so clone HEAD directly.
                clone_cmds.append(
                    f"RUN git clone --depth 1 "
                    f"https://github.com/{org_repo} {dest}"
                )
    clone_commands = "\n".join(clone_cmds) if clone_cmds else (
        "# No local checkout repos specified for this fixture"
    )

    # MCP repos description for instruction.md
    mcp_repos_desc_lines = []
    if fixture:
        for repo_entry in fixture.get("repos", []):
            if repo_entry.get("full_name") in mcp_repos:
                name = repo_entry.get("logical_name", repo_entry["full_name"])
                fn = repo_entry["full_name"]
                mcp_repos_desc_lines.append(f"- `{fn}` ({name})")
    mcp_repos_description = "\n".join(mcp_repos_desc_lines) or "*(none — all repos available locally)*"

    # Local repo description
    local_repo_description = (
        f"The local `/workspace/` directory contains: {', '.join(local_repos)}."
        if local_repos else "No local repositories are pre-checked out."
    )

    # Evaluation checks
    oracle_type = use_case.get("oracle_type", "deterministic_json")
    checks = DEFAULT_CHECKS_BY_ORACLE_TYPE.get(oracle_type, DEFAULT_CHECKS_BY_ORACLE_TYPE["tbd"])
    evaluation_checks_json = json.dumps(checks, indent=2)
    evaluation_modes = ["deterministic"] if oracle_type not in ("rubric_judge",) else ["deterministic", "rubric_judge"]
    evaluation_modes_json = json.dumps(evaluation_modes)

    # Evaluation criteria description
    check_types = [c["type"] for c in checks]
    eval_criteria_lines = []
    if "file_set_match" in check_types:
        eval_criteria_lines.append("- **File recall and precision**: Did you find all relevant files?")
    if "symbol_resolution" in check_types:
        eval_criteria_lines.append("- **Symbol resolution**: Correct repo, path, and symbol name?")
    if "dependency_chain" in check_types:
        eval_criteria_lines.append("- **Dependency chain**: Correct order of dependency steps?")
    if "keyword_presence" in check_types:
        eval_criteria_lines.append("- **Keyword presence**: Are required terms present in your explanation?")
    if "provenance" in check_types:
        eval_criteria_lines.append("- **Provenance**: Did you cite specific file paths and repo names?")
    if "test_ratio" in check_types:
        eval_criteria_lines.append("- **Test ratio**: Does the generated code pass the provided test suite?")
    evaluation_criteria = "\n".join(eval_criteria_lines) or "- Correctness of identified items"

    # Verification modes (dual-mode support)
    verification_modes = use_case.get("verification_modes", ["artifact"])
    supports_direct = "direct" in verification_modes
    if supports_direct and not clone_cmds:
        raise ValueError(
            f"Task {use_case.get('use_case_id')} has verification_modes=['artifact','direct'] "
            f"but fixture has no local_checkout_repos. Direct mode needs a full repo clone."
        )
    # TOML array format: ["artifact", "direct"]
    verification_modes_toml = json.dumps(verification_modes)

    # Customer prompt for user_story (PRD format)
    customer_prompt = use_case.get("customer_prompt", "Perform the requested analysis.")
    title = use_case.get("title", task_id)

    return {
        # Task identity
        "task_id": task_id,
        "task_description": title,
        "task_title": title,
        "task_family": task_family,
        "category": use_case.get("category", "A"),
        "use_case_id": str(use_case.get("use_case_id", 0)),
        "mcp_suite": mcp_suite,
        "repo_set_id": use_case.get("repo_set_id", ""),
        # Language / env
        "language": language.lower(),
        "language_packages": lang_pkgs,
        "difficulty": use_case.get("difficulty", "medium"),
        "time_limit_sec": "900",
        # Repo info
        "primary_repo": primary_repo,
        "clone_commands": clone_commands,
        "local_repo_description": local_repo_description,
        "mcp_repos_description": mcp_repos_description,
        # Instruction content
        "customer_prompt": customer_prompt,
        "context_description": (
            f"You are working on a codebase task involving repos from the "
            f"{mcp_suite.replace('csb_org_', '').replace('ccb_mcp_', '').replace('_', ' ')} domain."
        ),
        "evaluation_criteria": evaluation_criteria,
        # TaskSpec / PRD
        "user_story": f"As a developer, I want to: {customer_prompt}",
        "constraints_json": json.dumps([
            "Provide specific file paths and repository names in your answer.",
            "Write your findings to /workspace/answer.json.",
        ]),
        "success_definition": (
            f"Agent successfully identifies relevant files and symbols across "
            f"all repos in the {use_case.get('repo_set_id', 'fixture')} fixture."
        ),
        "seed_prompt": customer_prompt,
        # Oracle (empty until curate_oracle.py populates them)
        "required_files_json": "[]",
        "required_symbols_json": "[]",
        "dependency_chains_json": "[]",
        "evaluation_modes_json": evaluation_modes_json,
        "evaluation_checks_json": evaluation_checks_json,
        # Dual-mode support
        "verification_modes_json": verification_modes_toml,
        "supports_direct": "true" if supports_direct else "false",
    }


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_template(templates_dir: Path, template_name: str, variables: Dict[str, str]) -> str:
    """Load and render a template with the given variables."""
    path = templates_dir / template_name
    if not path.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    content = path.read_text()
    return Template(content).substitute(variables)


# ---------------------------------------------------------------------------
# Task generation
# ---------------------------------------------------------------------------

def generate_task(
    use_case: Dict,
    project_root: Path,
    out_root: Optional[Path] = None,
    dry_run: bool = False,
    verbose: bool = False,
    curate_oracle: bool = False,
) -> Optional[Path]:
    """Generate a single task directory from a use case registry entry.

    Returns the task directory path, or None if skipped.
    """
    task_id = derive_task_id(use_case)
    task_slug = derive_task_slug(task_id)
    mcp_suite = use_case.get("mcp_suite", "ccb_mcp_unknown")
    repo_set_id = use_case.get("repo_set_id", "")

    # Resolve output directory
    benchmarks_root = out_root or (project_root / "benchmarks")
    task_dir = benchmarks_root / mcp_suite / task_slug
    env_dir = task_dir / "environment"
    tests_dir = task_dir / "tests"

    # Load fixture if available
    fixture: Optional[Dict] = None
    if repo_set_id:
        fp = _fixture_path(project_root, repo_set_id)
        if fp.exists():
            with open(fp) as f:
                fixture = json.load(f)
        else:
            logging.warning("  Fixture '%s' not found — proceeding without fixture", repo_set_id)

    # Build template variables
    variables = build_template_vars(use_case, fixture, task_id)

    templates_dir = _templates_dir(project_root)

    if dry_run:
        logging.info("[DRY RUN] Would generate: %s", task_dir)
        logging.info("[DRY RUN]   mcp_suite: %s", mcp_suite)
        logging.info("[DRY RUN]   task_id:   %s", task_id)
        logging.info("[DRY RUN]   fixture:   %s", repo_set_id)
        logging.info("[DRY RUN]   checks:    %s", [c["type"] for c in json.loads(variables["evaluation_checks_json"])])
        return task_dir

    # Create directories
    env_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    def write_rendered(fname: str, out_path: Path) -> None:
        content = render_template(templates_dir, fname, variables)
        out_path.write_text(content)
        if verbose:
            logging.debug("  Wrote %s", out_path)

    # task.toml
    write_rendered("task.toml.j2", task_dir / "task.toml")

    # instruction.md
    write_rendered("instruction.md.j2", task_dir / "instruction.md")

    # environment/Dockerfile (baseline)
    write_rendered("Dockerfile.j2", env_dir / "Dockerfile")

    # environment/Dockerfile.sg_only
    write_rendered("Dockerfile.sg_only.j2", env_dir / "Dockerfile.sg_only")

    # tests/eval.sh
    eval_sh = tests_dir / "eval.sh"
    write_rendered("eval.sh.j2", eval_sh)
    eval_sh.chmod(0o755)

    # tests/task_spec.json
    write_rendered("task_spec.json.j2", tests_dir / "task_spec.json")

    # Copy oracle_checks.py to tests/ (so eval.sh can find it at /tests/oracle_checks.py)
    oracle_src = project_root / "scripts" / "csb_metrics" / "oracle_checks.py"
    oracle_dst = tests_dir / "oracle_checks.py"
    if oracle_src.exists():
        shutil.copy2(oracle_src, oracle_dst)
        if verbose:
            logging.debug("  Copied oracle_checks.py -> %s", oracle_dst)

    # Write direct_verifier.sh placeholder for dual-mode tasks
    verification_modes = use_case.get("verification_modes", ["artifact"])
    if "direct" in verification_modes:
        direct_sh = tests_dir / "direct_verifier.sh"
        direct_sh.write_text(
            "#!/bin/bash\n"
            "# PLACEHOLDER: Adapt from parent SDLC verifier or write task-specific direct verifier.\n"
            "# This script is called by test.sh when NOT in artifact mode.\n"
            "echo 'ERROR: direct_verifier.sh is a placeholder — needs manual curation'\n"
            "echo '0.0' > /logs/verifier/reward.txt\n"
            "exit 1\n"
        )
        direct_sh.chmod(0o755)
        if verbose:
            logging.debug("  Wrote direct_verifier.sh placeholder for dual-mode task")

    logging.info("Generated task: %s", task_dir)

    # Run oracle curation if requested
    if curate_oracle:
        curator = project_root / "scripts" / "curate_oracle.py"
        if curator.exists():
            logging.info("  Curating oracle for %s...", task_id)
            result = subprocess.run(
                [sys.executable, str(curator), "--task-dir", str(task_dir), "--verbose"],
                capture_output=not verbose,
                text=True,
            )
            if verbose and result.stdout:
                print(result.stdout, end="")
            if result.returncode != 0:
                logging.warning("  Oracle curation failed for %s", task_id)
            else:
                logging.info("  Oracle curation complete for %s", task_id)
        else:
            logging.warning("  curate_oracle.py not found — skipping oracle curation")

    return task_dir


def validate_generated_task(task_dir: Path) -> bool:
    """Syntactically validate all generated files in a task directory."""
    ok = True

    # task.toml — just check it's parseable (no TOML stdlib parser, check as text)
    toml_file = task_dir / "task.toml"
    if toml_file.exists():
        content = toml_file.read_text()
        if "mcp_suite" not in content or "org_scale = true" not in content:
            logging.error("task.toml missing required fields: %s", toml_file)
            ok = False
    else:
        logging.error("task.toml missing: %s", task_dir)
        ok = False

    # tests/task_spec.json — valid JSON
    spec_file = task_dir / "tests" / "task_spec.json"
    if spec_file.exists():
        try:
            json.load(open(spec_file))
        except json.JSONDecodeError as e:
            logging.error("task_spec.json invalid JSON: %s — %s", spec_file, e)
            ok = False
    else:
        logging.error("task_spec.json missing: %s", task_dir)
        ok = False

    # tests/eval.sh — bash -n syntax check
    eval_sh = task_dir / "tests" / "eval.sh"
    if eval_sh.exists():
        result = subprocess.run(["bash", "-n", str(eval_sh)], capture_output=True, text=True)
        if result.returncode != 0:
            logging.error("eval.sh syntax error: %s — %s", eval_sh, result.stderr)
            ok = False
    else:
        logging.error("eval.sh missing: %s", task_dir)
        ok = False

    # tests/oracle_checks.py — py_compile
    oracle_py = task_dir / "tests" / "oracle_checks.py"
    if oracle_py.exists():
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(oracle_py)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            logging.error("oracle_checks.py compile error: %s", oracle_py)
            ok = False

    return ok


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate org-scale benchmark task directories from the use case registry.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    filter_group = parser.add_mutually_exclusive_group()
    filter_group.add_argument(
        "--use-case-ids", nargs="+", type=int, metavar="ID",
        help="Generate tasks for specific use case IDs (e.g. --use-case-ids 1 4 10).",
    )
    filter_group.add_argument(
        "--category", metavar="CATEGORY",
        help="Generate all tasks for a category (A-J).",
    )
    filter_group.add_argument(
        "--family", metavar="FAMILY",
        help="Generate all tasks for a task family (e.g. 'cross-repo-dep-trace').",
    )
    filter_group.add_argument(
        "--all", action="store_true", dest="all_tasks",
        help="Generate tasks for all use cases in the registry.",
    )

    parser.add_argument(
        "--out", metavar="DIR",
        help="Output root directory (default: benchmarks/ in project root).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be generated without writing files.",
    )
    parser.add_argument(
        "--include-stubs", action="store_true",
        help="Include entries with oracle_type='tbd' (default: skip these).",
    )
    parser.add_argument(
        "--curate-oracle", action="store_true",
        help="After generating task files, run curate_oracle.py to auto-populate oracle_answer.json.",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="After generation, run syntactic validation on generated files.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print detailed output.",
    )

    args = parser.parse_args()

    if not any([args.use_case_ids, args.category, args.family, args.all_tasks]):
        parser.error("One of --use-case-ids, --category, --family, or --all is required.")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Resolve project root
    project_root = _find_project_root(Path(__file__).parent)
    logging.info("Project root: %s", project_root)

    # Load registry
    registry_path = _registry_path(project_root)
    if not registry_path.exists():
        logging.error("Registry not found: %s", registry_path)
        return 1
    with open(registry_path) as f:
        registry_data = json.load(f)
    all_use_cases: List[Dict] = registry_data.get("use_cases", [])
    logging.info("Registry loaded: %d use cases", len(all_use_cases))

    # Filter use cases
    if args.use_case_ids:
        id_set = set(args.use_case_ids)
        use_cases = [uc for uc in all_use_cases if uc.get("use_case_id") in id_set]
    elif args.category:
        use_cases = [uc for uc in all_use_cases if uc.get("category") == args.category.upper()]
    elif args.family:
        use_cases = [uc for uc in all_use_cases if uc.get("task_family") == args.family]
    else:
        use_cases = list(all_use_cases)

    # Skip stubs unless --include-stubs
    if not args.include_stubs:
        before = len(use_cases)
        use_cases = [uc for uc in use_cases if uc.get("oracle_type", "tbd") != "tbd"]
        skipped = before - len(use_cases)
        if skipped:
            logging.info("Skipped %d stub entries (oracle_type='tbd'). Use --include-stubs to generate.", skipped)

    if not use_cases:
        logging.warning("No use cases matched the filter (after stub exclusion).")
        return 0

    logging.info("Generating %d task(s)...", len(use_cases))

    # Resolve output directory
    out_root = Path(args.out) if args.out else None

    # Generate tasks
    generated = []
    failed = []

    for uc in use_cases:
        uid = uc.get("use_case_id")
        title = uc.get("title", f"use_case_{uid}")
        logging.info("Processing use_case_id=%s: %s", uid, title)

        try:
            task_dir = generate_task(
                use_case=uc,
                project_root=project_root,
                out_root=out_root,
                dry_run=args.dry_run,
                verbose=args.verbose,
                curate_oracle=args.curate_oracle,
            )
            if task_dir:
                generated.append(task_dir)
        except Exception as exc:
            logging.error("Failed to generate task for use_case_id=%s: %s", uid, exc)
            if args.verbose:
                import traceback
                traceback.print_exc()
            failed.append(uid)

    # Validate generated files
    if args.validate and not args.dry_run:
        logging.info("\nValidating %d generated task(s)...", len(generated))
        validation_failures = []
        for task_dir in generated:
            if not validate_generated_task(task_dir):
                validation_failures.append(task_dir)
        if validation_failures:
            logging.error("%d tasks failed validation", len(validation_failures))
        else:
            logging.info("All %d tasks passed validation", len(generated))

    # Summary
    print(f"\nSummary: {len(generated)} task(s) {'planned' if args.dry_run else 'generated'}", end="")
    if failed:
        print(f", {len(failed)} failed", end="")
    print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

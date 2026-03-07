#!/usr/bin/env python3
"""ABC Benchmark Auditor — audit benchmark suites against ABC framework criteria.

Runs automated checks per-benchmark and delegates to existing scripts where they
already cover a criterion. Reports Task Validity, Outcome Validity, and Reporting
results with letter grades.

Usage:
  python3 scripts/abc_audit.py --suite ccb_pytorch [--format json|table]
  python3 scripts/abc_audit.py --all [--format json|table]
  python3 scripts/abc_audit.py --suite ccb_pytorch --dimension task_validity
  python3 scripts/abc_audit.py --suite ccb_pytorch --critical-only
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
RUNS_DIR = PROJECT_ROOT / "runs" / "official"
SELECTED_TASKS_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from abc_criteria import (
    CRITERIA_BY_ID,
    AuditReport,
    CriterionResult,
    Dimension,
    Severity,
    Status,
    get_criteria_for_suite,
)


# ---------------------------------------------------------------------------
# TOML parser (reused pattern)
# ---------------------------------------------------------------------------

def parse_task_toml_simple(path: Path) -> dict:
    """Minimal TOML parser for task.toml (no external deps)."""
    result = {}
    section = ""
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]").strip()
            continue
        if "=" in line:
            if '"""' in line:
                break
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            full_key = f"{section}.{key}" if section else key
            result[full_key] = val
    return result


# ---------------------------------------------------------------------------
# Task discovery
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".", "_", "template", "templates", "_shared", "jobs"}


def discover_tasks(suite: str) -> list[Path]:
    """Find all task directories for a benchmark suite."""
    suite_dir = BENCHMARKS_DIR / suite
    if not suite_dir.is_dir():
        return []
    tasks = []
    for child in sorted(suite_dir.iterdir()):
        if not child.is_dir() or child.name in _SKIP_DIRS or child.name.startswith((".", "_")):
            continue
        if (child / "task.toml").is_file() or (child / "instruction.md").is_file():
            tasks.append(child)
    return tasks


def discover_all_suites() -> list[str]:
    """Find all benchmark suite directories (csb_* and legacy ccb_*)."""
    return sorted(
        d.name for d in BENCHMARKS_DIR.iterdir()
        if d.is_dir() and d.name.startswith(("csb_", "ccb_"))
    )


# ---------------------------------------------------------------------------
# Automated check implementations
# ---------------------------------------------------------------------------

def check_t1_pinned_versions(tasks: list[Path]) -> CriterionResult:
    """T.1: Dockerfile pins versions (no :latest, unpinned apt)."""
    issues = []
    for task_dir in tasks:
        dockerfile = task_dir / "environment" / "Dockerfile"
        if not dockerfile.is_file():
            dockerfile = task_dir / "Dockerfile"
        if not dockerfile.is_file():
            continue

        content = dockerfile.read_text(errors="replace")
        task_name = task_dir.name

        # Check for :latest
        for match in re.finditer(r"FROM\s+(\S+:latest)", content, re.IGNORECASE):
            issues.append(f"{task_name}: FROM uses :latest ({match.group(1)})")

        # Check FROM with no tag at all (e.g., "FROM ubuntu" without ":22.04")
        for match in re.finditer(r"^FROM\s+(\S+)", content, re.MULTILINE):
            img = match.group(1)
            if ":" not in img and img.lower() not in ("scratch",) and " AS " not in match.group(0).upper():
                issues.append(f"{task_name}: FROM has no version tag ({img})")

        # Check for unpinned pip install (without ==)
        for match in re.finditer(r"pip3?\s+install\s+(?!-)[^=\n]*$", content, re.MULTILINE):
            line = match.group(0).strip()
            # Skip if it's installing from a requirements file
            if "-r " in line or "requirements" in line:
                continue
            # Check individual packages
            pkgs = line.split()
            for pkg in pkgs[2:]:  # Skip "pip install"
                if pkg.startswith("-"):
                    continue
                if "==" not in pkg and ">=" not in pkg and "<=" not in pkg and pkg != ".":
                    issues.append(f"{task_name}: unpinned pip install ({pkg})")
                    break

    if not issues:
        return CriterionResult(
            criterion_id="T.1", status=Status.PASS,
            evidence="All Dockerfiles pin versions",
        )
    return CriterionResult(
        criterion_id="T.1", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Pin all base images, apt packages, and pip dependencies to specific versions",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_t3_no_api_keys(tasks: list[Path]) -> CriterionResult:
    """T.3: No shared API keys in task.toml/Dockerfile."""
    key_patterns = [
        re.compile(r"(?:api[_-]?key|api[_-]?token|secret[_-]?key|password)\s*=\s*['\"]?\w{10,}", re.IGNORECASE),
        re.compile(r"sk-[a-zA-Z0-9]{20,}"),  # OpenAI-style
        re.compile(r"ghp_[a-zA-Z0-9]{30,}"),  # GitHub PAT
        re.compile(r"Bearer\s+[a-zA-Z0-9\-_.]{20,}"),
    ]
    issues = []
    allowlisted_hits = []
    allowlisted_synthetic_fixtures = {
        # Intentional synthetic-secret fixture for security tasks; these values are
        # test data used to verify that agents avoid reading sensitive files.
        ("django-sensitive-file-exclusion-001", "environment/Dockerfile"),
    }
    for task_dir in tasks:
        for fname in ["task.toml", "environment/Dockerfile", "Dockerfile"]:
            fpath = task_dir / fname
            if not fpath.is_file():
                continue
            content = fpath.read_text(errors="replace")
            for pat in key_patterns:
                for match in pat.finditer(content):
                    if (task_dir.name, fname) in allowlisted_synthetic_fixtures:
                        allowlisted_hits.append(
                            f"{task_dir.name}/{fname}: allowlisted synthetic fixture ({match.group(0)[:40]}...)"
                        )
                        continue
                    issues.append(f"{task_dir.name}/{fname}: potential key/secret ({match.group(0)[:40]}...)")

    if not issues:
        evidence = "No API keys or secrets found in task files"
        if allowlisted_hits:
            evidence += f" ({len(allowlisted_hits)} allowlisted synthetic fixture match(es) ignored)"
        return CriterionResult(
            criterion_id="T.3", status=Status.PASS,
            evidence=evidence,
            details={"allowlisted": allowlisted_hits[:20]} if allowlisted_hits else {},
        )
    return CriterionResult(
        criterion_id="T.3", status=Status.FAIL,
        evidence="\n".join(issues[:5]),
        remediation="Remove embedded credentials; use environment variables instead",
        details={"issues": issues},
    )


def check_t4_git_sha(tasks: list[Path]) -> CriterionResult:
    """T.4: Git checkouts use exact SHA (not HEAD/latest)."""
    issues = []
    for task_dir in tasks:
        dockerfile = task_dir / "environment" / "Dockerfile"
        if not dockerfile.is_file():
            dockerfile = task_dir / "Dockerfile"
        if not dockerfile.is_file():
            continue

        content = dockerfile.read_text(errors="replace")
        task_name = task_dir.name

        # Find git clone commands
        git_clones = re.findall(r"git\s+clone\b[^\n]*", content)
        if not git_clones:
            continue

        # Check if there's a subsequent git checkout with a SHA or version tag
        has_sha_checkout = bool(re.search(r"git\s+checkout\s+[0-9a-f]{7,40}", content))
        # Accept v1.0, tags/foo, or semver-like 1.96.0
        has_tag_checkout = bool(re.search(r"git\s+checkout\s+(v\d|tags/|\d+\.\d+)", content))

        if not has_sha_checkout and not has_tag_checkout:
            for clone in git_clones:
                if "--depth 1" in clone or "--branch" not in clone:
                    issues.append(f"{task_name}: git clone without SHA checkout ({clone.strip()[:80]})")

    if not issues:
        return CriterionResult(
            criterion_id="T.4", status=Status.PASS,
            evidence="All git checkouts use exact SHAs or tags",
        )
    return CriterionResult(
        criterion_id="T.4", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Add 'git checkout <sha>' after clone, or use '--branch <tag>'",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_t5_no_solution_leak(tasks: list[Path]) -> CriterionResult:
    """T.5: instruction.md doesn't leak solution content."""
    issues = []
    for task_dir in tasks:
        instruction = task_dir / "instruction.md"
        if not instruction.is_file():
            continue

        inst_text = instruction.read_text(errors="replace").lower()

        # Check against solve.sh
        solve_sh = task_dir / "solve.sh"
        if solve_sh.is_file():
            solve_text = solve_sh.read_text(errors="replace")
            # Extract meaningful code lines (not comments/blank)
            solve_lines = [
                l.strip() for l in solve_text.splitlines()
                if l.strip() and not l.strip().startswith("#") and len(l.strip()) > 15
            ]
            for line in solve_lines:
                if line.lower() in inst_text:
                    issues.append(f"{task_dir.name}: instruction contains solve.sh line: {line[:60]}")
                    break

        # Check against expected.diff
        for diff_path in [task_dir / "expected.diff", task_dir / "tests" / "expected.diff"]:
            if diff_path.is_file():
                diff_text = diff_path.read_text(errors="replace")
                # Extract added lines from diff
                added_lines = [
                    l[1:].strip() for l in diff_text.splitlines()
                    if l.startswith("+") and not l.startswith("+++") and len(l.strip()) > 20
                ]
                for line in added_lines[:20]:  # Sample first 20
                    if line.lower() in inst_text:
                        issues.append(f"{task_dir.name}: instruction contains diff content: {line[:60]}")
                        break

    if not issues:
        return CriterionResult(
            criterion_id="T.5", status=Status.PASS,
            evidence="No solution content found in instructions",
        )
    return CriterionResult(
        criterion_id="T.5", status=Status.WARN,
        evidence="\n".join(issues[:10]),
        remediation="Review instructions to ensure they don't contain solution code",
        details={"issues": issues},
    )


def check_t8_oracle_exists(tasks: list[Path]) -> CriterionResult:
    """T.8: Oracle/reference solution exists."""
    missing = []
    for task_dir in tasks:
        legacy_oracle_files = [
            task_dir / "solve.sh",
            task_dir / "expected.diff",
            task_dir / "tests" / "expected.diff",
            task_dir / "tests" / "golden",
            task_dir / "tests" / "expected",
        ]
        has_mcp_oracle_bundle = (
            (task_dir / "tests" / "oracle_answer.json").is_file()
            and (task_dir / "tests" / "oracle_checks.py").is_file()
        )
        if not any(p.exists() for p in legacy_oracle_files) and not has_mcp_oracle_bundle:
            missing.append(task_dir.name)

    if not missing:
        return CriterionResult(
            criterion_id="T.8", status=Status.PASS,
            evidence="All tasks have reference solutions",
        )
    return CriterionResult(
        criterion_id="T.8", status=Status.WARN,
        evidence=f"{len(missing)}/{len(tasks)} tasks lack oracle: {', '.join(missing[:10])}",
        remediation="Add solve.sh or expected.diff for validation",
        details={"missing": missing},
    )


def _is_eval_wrapper_script(content: str) -> bool:
    """Heuristic: test.sh is a thin wrapper that delegates to eval.sh."""
    if not content:
        return False
    has_eval_ref = "eval.sh" in content
    has_exec = bool(re.search(r"\bexec\b", content))
    # Common artifact wrappers are tiny and mention eval.sh in comments + exec line.
    line_count = len([l for l in content.splitlines() if l.strip()])
    return has_eval_ref and has_exec and line_count <= 30


def _uses_shared_verifier_delegate(content: str) -> bool:
    """Heuristic: test.sh delegates scoring to a shared verifier script."""
    if not content:
        return False
    return bool(re.search(r"source\s+/tests/(?:find_and_prove_verifier|verifier_lib)\.sh", content))


def _get_primary_verifier(task_dir: Path) -> Optional[Path]:
    """Pick the verifier file that contains the real scoring logic."""
    test_sh = task_dir / "tests" / "test.sh"
    eval_sh = task_dir / "tests" / "eval.sh"
    verify_py = task_dir / "tests" / "verify.py"

    if test_sh.is_file():
        content = test_sh.read_text(errors="replace")
        if eval_sh.is_file() and _is_eval_wrapper_script(content):
            return eval_sh
        return test_sh
    if verify_py.is_file():
        return verify_py
    if eval_sh.is_file():
        return eval_sh
    return None


def _get_verifier_candidates(task_dir: Path) -> list[Path]:
    """Return all plausible verifier files (including eval.sh for artifact tasks)."""
    candidates = []
    for rel in ("tests/test.sh", "tests/eval.sh", "tests/verify.py"):
        p = task_dir / rel
        if p.is_file():
            candidates.append(p)
    return candidates


def check_oc_empty_solution_rejected(tasks: list[Path]) -> CriterionResult:
    """O.c: Empty/no-op solution gets reward=0 (real assertions in test.sh)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier or verifier.suffix != ".sh":
            continue

        content = verifier.read_text(errors="replace")
        task_name = task_dir.name

        # Check for real assertion patterns
        assertion_patterns = [
            r"\btest\s+",
            r"\bassert\b",
            r"\bdiff\b",
            r"\bgrep\s+-[qc]",
            r"\bif\s+\[",
            r"\bpytest\b",
            r"assertEqual",
            r"\bcompare\b",
            r"\bpython.*assert",
        ]
        has_assertion = any(re.search(p, content) for p in assertion_patterns)

        # Suspicious: just echoes 1.0 without any checks
        just_echoes_reward = bool(re.search(r'echo\s+["\']?1\.0["\']?\s*>\s*.*reward', content))
        no_conditionals = not bool(re.search(r'\bif\b|\belse\b|\bthen\b|\bcase\b', content))

        if just_echoes_reward and no_conditionals and not has_assertion:
            issues.append(f"{task_name}: {verifier.name} unconditionally writes reward=1.0")

    if not issues:
        return CriterionResult(
            criterion_id="O.c", status=Status.PASS,
            evidence="All verifiers have real assertions",
        )
    return CriterionResult(
        criterion_id="O.c", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Add assertions that verify actual solution correctness",
        details={"issues": issues},
    )


def check_od_error_handling(tasks: list[Path]) -> CriterionResult:
    """O.d: test.sh has error handling (set -e or traps)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier:
            continue
        # Python verifiers use exceptions; no shell strict-mode check needed.
        if verifier.suffix == ".py":
            continue

        content = verifier.read_text(errors="replace")
        if verifier.name == "test.sh" and _uses_shared_verifier_delegate(content):
            continue
        has_set_e = bool(re.search(r"set\s+-e", content))
        has_pipefail = bool(re.search(r"set\s+-eo?\s+pipefail", content))
        has_trap = bool(re.search(r"\btrap\b", content))

        if not (has_set_e or has_pipefail or has_trap):
            issues.append(f"{task_dir.name}: {verifier.name} lacks set -e / pipefail / trap")

    if not issues:
        return CriterionResult(
            criterion_id="O.d", status=Status.PASS,
            evidence="All verifier shell scripts have error handling",
        )
    return CriterionResult(
        criterion_id="O.d", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Add 'set -eo pipefail' at the top of the verifier shell script",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_oe_multiple_assertions(tasks: list[Path]) -> CriterionResult:
    """O.e: test.sh covers multiple aspects (>1 assertion/check)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier:
            continue

        content = verifier.read_text(errors="replace")
        assertion_patterns = [
            r"\btest\s+", r"\bassert\b", r"\bdiff\b", r"\bgrep\b",
            r"\bif\s+\[", r"\bpytest\b", r"assertEqual", r"\bcompare\b",
        ]
        count = sum(1 for p in assertion_patterns if re.search(p, content))
        if count < 2:
            issues.append(f"{task_dir.name}: only {count} assertion pattern(s) found")

    if not issues:
        return CriterionResult(
            criterion_id="O.e", status=Status.PASS,
            evidence="All verifiers have multiple assertion types",
        )
    return CriterionResult(
        criterion_id="O.e", status=Status.WARN,
        evidence="\n".join(issues[:10]),
        remediation="Add more diverse checks to verifier",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_oh_reward_format(tasks: list[Path]) -> CriterionResult:
    """O.h: reward.txt output format is consistent."""
    issues = []
    for task_dir in tasks:
        candidates = _get_verifier_candidates(task_dir)
        found_reward = False
        for verifier in candidates:
            content = verifier.read_text(errors="replace")
            if re.search(r"reward\.txt|/logs/verifier/reward", content):
                found_reward = True
                break
            if verifier.name == "test.sh" and _uses_shared_verifier_delegate(content):
                # Shared verifier scripts handle reward writing, but the implementation
                # is not available in the task directory for static inspection.
                found_reward = True
                break

        if not found_reward and candidates:
            issues.append(f"{task_dir.name}: verifier doesn't write to reward.txt")

    if not issues:
        return CriterionResult(
            criterion_id="O.h", status=Status.PASS,
            evidence="All verifiers write to reward.txt",
        )
    return CriterionResult(
        criterion_id="O.h", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Ensure verifier writes result to /logs/verifier/reward.txt",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_oi_partial_credit(tasks: list[Path]) -> CriterionResult:
    """O.i: Verifier supports partial credit (0.0-1.0 range)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier:
            continue

        content = verifier.read_text(errors="replace")
        partial_patterns = [
            r"0\.\d+",  # Float literal
            r"bc\s+-l",
            r"\bweights?\b",
            r"partial",
            r"score\s*[+\-*/]=",
            r"float\(",
        ]
        has_partial = any(re.search(p, content) for p in partial_patterns)
        if not has_partial:
            issues.append(f"{task_dir.name}: binary reward only (no partial credit)")

    if not issues:
        return CriterionResult(
            criterion_id="O.i", status=Status.PASS,
            evidence="All verifiers support partial credit",
        )
    # This is RECOMMENDED, so WARN not FAIL
    return CriterionResult(
        criterion_id="O.i", status=Status.WARN,
        evidence=f"{len(issues)}/{len(tasks)} verifiers are binary-only",
        remediation="Consider weighted scoring for nuanced evaluation",
        details={"binary_only": [i.split(":")[0] for i in issues]},
    )


def check_r1_files_exist(tasks: list[Path]) -> CriterionResult:
    """R.1: All tasks have instruction.md + test.sh."""
    issues = []
    for task_dir in tasks:
        if not (task_dir / "instruction.md").is_file():
            issues.append(f"{task_dir.name}: missing instruction.md")
        if not (task_dir / "tests" / "test.sh").is_file() and not (task_dir / "tests" / "verify.py").is_file():
            issues.append(f"{task_dir.name}: missing tests/test.sh or tests/verify.py")

    if not issues:
        return CriterionResult(
            criterion_id="R.1", status=Status.PASS,
            evidence="All tasks have instruction.md and verifier",
        )
    return CriterionResult(
        criterion_id="R.1", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Add missing instruction.md or test.sh files",
        details={"issues": issues},
    )


def check_r2_no_contamination(tasks: list[Path]) -> CriterionResult:
    """R.2: No MCP/Sourcegraph contamination in instruction.md."""
    contamination_pattern = re.compile(
        r"sourcegraph\s+mcp|sourcegraph\s+tools?|mcp\s+tools?|"
        r"\bdeep\s*search\b|deepsearch|\bsg_[a-z_]+\b|\bcody\b|"
        r"\bindexed in sourcegraph\b|\bappear in sourcegraph\b",
        re.IGNORECASE,
    )
    issues = []
    for task_dir in tasks:
        instruction = task_dir / "instruction.md"
        if not instruction.is_file():
            continue
        content = instruction.read_text(errors="replace")
        matches = contamination_pattern.findall(content)
        if matches:
            unique = list(set(m.lower() for m in matches))
            issues.append(f"{task_dir.name}: found {', '.join(unique[:5])}")

    if not issues:
        return CriterionResult(
            criterion_id="R.2", status=Status.PASS,
            evidence="No MCP/Sourcegraph tool guidance in baseline instructions",
        )
    return CriterionResult(
        criterion_id="R.2", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Remove MCP/Sourcegraph tool guidance from baseline instructions",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_r3_readme(suite: str) -> CriterionResult:
    """R.3: Benchmark describes what it measures (README or CLAUDE.md)."""
    suite_dir = BENCHMARKS_DIR / suite
    has_readme = (suite_dir / "README.md").is_file()
    has_claude_md = (suite_dir / "CLAUDE.md").is_file()

    if has_readme or has_claude_md:
        return CriterionResult(
            criterion_id="R.3", status=Status.PASS,
            evidence=f"{'README.md' if has_readme else 'CLAUDE.md'} exists in {suite}",
        )
    return CriterionResult(
        criterion_id="R.3", status=Status.WARN,
        evidence=f"No README.md or CLAUDE.md in {suite}/",
        remediation="Add a README describing what this benchmark measures",
    )


def check_r4_sdlc_phase(suite: str) -> CriterionResult:
    """R.4: sdlc_phase populated in selected_benchmark_tasks.json."""
    if not SELECTED_TASKS_PATH.is_file():
        return CriterionResult(
            criterion_id="R.4", status=Status.ERROR,
            evidence="selected_benchmark_tasks.json not found",
        )

    data = json.loads(SELECTED_TASKS_PATH.read_text())
    tasks = data.get("tasks", data) if isinstance(data, dict) else data
    if isinstance(tasks, dict):
        tasks = list(tasks.values())

    missing = []
    total = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        task_benchmark = t.get("benchmark", "")
        if task_benchmark != suite:
            continue
        total += 1
        if not t.get("sdlc_phase"):
            missing.append(t.get("task_id", "unknown"))

    if total == 0:
        return CriterionResult(
            criterion_id="R.4", status=Status.SKIP,
            evidence=f"No tasks for {suite} in selection registry",
        )
    if not missing:
        return CriterionResult(
            criterion_id="R.4", status=Status.PASS,
            evidence=f"All {total} tasks have sdlc_phase",
        )
    return CriterionResult(
        criterion_id="R.4", status=Status.WARN,
        evidence=f"{len(missing)}/{total} tasks missing sdlc_phase: {', '.join(missing[:5])}",
        remediation="Add sdlc_phase to selected_benchmark_tasks.json",
        details={"missing": missing},
    )


def check_r5_error_catalog() -> CriterionResult:
    """R.5: ERROR_CATALOG.md covers all fingerprinted errors."""
    catalog = PROJECT_ROOT / "docs" / "ERROR_CATALOG.md"
    if not catalog.is_file():
        return CriterionResult(
            criterion_id="R.5", status=Status.WARN,
            evidence="docs/ERROR_CATALOG.md not found",
            remediation="Create an error catalog documenting known error patterns",
        )
    return CriterionResult(
        criterion_id="R.5", status=Status.PASS,
        evidence="ERROR_CATALOG.md exists",
    )


def check_r7_baseline_results(suite: str) -> CriterionResult:
    """R.7: Baseline config results exist."""
    if not RUNS_DIR.is_dir():
        return CriterionResult(
            criterion_id="R.7", status=Status.WARN,
            evidence="runs/official/ directory not found",
        )

    # Look for baseline run directories for this suite
    found_baseline = False
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        if "baseline" in run_dir.name and not any(
            skip in run_dir.name for skip in ["archive", "__broken_verifier"]
        ):
            # Check if it contains tasks for this suite
            for task_dir in run_dir.iterdir():
                if task_dir.is_dir() and (task_dir / "result.json").is_file():
                    found_baseline = True
                    break
        if found_baseline:
            break

    if found_baseline:
        return CriterionResult(
            criterion_id="R.7", status=Status.PASS,
            evidence=f"Baseline results found for {suite}",
        )
    return CriterionResult(
        criterion_id="R.7", status=Status.WARN,
        evidence=f"No baseline results found for {suite}",
        remediation="Run baseline configuration for this benchmark",
    )


def check_r8_task_selection_docs() -> CriterionResult:
    """R.8: TASK_SELECTION.md documents methodology."""
    doc = PROJECT_ROOT / "docs" / "TASK_SELECTION.md"
    if doc.is_file():
        return CriterionResult(
            criterion_id="R.8", status=Status.PASS,
            evidence="TASK_SELECTION.md exists",
        )
    return CriterionResult(
        criterion_id="R.8", status=Status.WARN,
        evidence="docs/TASK_SELECTION.md not found",
        remediation="Document task selection methodology",
    )


def check_r9_difficulty_distribution(suite: str) -> CriterionResult:
    """R.9: Difficulty distribution is documented and balanced."""
    if not SELECTED_TASKS_PATH.is_file():
        return CriterionResult(
            criterion_id="R.9", status=Status.ERROR,
            evidence="selected_benchmark_tasks.json not found",
        )

    data = json.loads(SELECTED_TASKS_PATH.read_text())
    tasks = data.get("tasks", data) if isinstance(data, dict) else data
    if isinstance(tasks, dict):
        tasks = list(tasks.values())

    difficulties: dict[str, int] = {}
    total = 0
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if t.get("benchmark") != suite:
            continue
        total += 1
        diff = t.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1

    if total == 0:
        return CriterionResult(
            criterion_id="R.9", status=Status.SKIP,
            evidence=f"No tasks for {suite} in selection registry",
        )

    dist_str = ", ".join(f"{k}: {v}" for k, v in sorted(difficulties.items()))

    if len(difficulties) >= 2:
        return CriterionResult(
            criterion_id="R.9", status=Status.PASS,
            evidence=f"Difficulty distribution ({total} tasks): {dist_str}",
            details={"distribution": difficulties},
        )
    return CriterionResult(
        criterion_id="R.9", status=Status.WARN,
        evidence=f"Only 1 difficulty level ({dist_str})",
        remediation="Include tasks at multiple difficulty levels",
        details={"distribution": difficulties},
    )


def check_r10_token_data() -> CriterionResult:
    """R.10: Token/cost data captured per run."""
    if not RUNS_DIR.is_dir():
        return CriterionResult(
            criterion_id="R.10", status=Status.WARN,
            evidence="runs/official/ not found",
        )

    # Sample a few result.json files for token data
    sampled = 0
    has_tokens = 0
    for run_dir in RUNS_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        if any(skip in run_dir.name for skip in ["archive", "__broken_verifier"]):
            continue
        for task_dir in run_dir.iterdir():
            result_json = task_dir / "result.json"
            if result_json.is_file():
                try:
                    result = json.loads(result_json.read_text())
                    sampled += 1
                    if result.get("token_usage") or result.get("tokens") or result.get("usage"):
                        has_tokens += 1
                except (json.JSONDecodeError, OSError):
                    pass
            if sampled >= 20:
                break
        if sampled >= 20:
            break

    if sampled == 0:
        return CriterionResult(
            criterion_id="R.10", status=Status.SKIP,
            evidence="No result.json files found to check",
        )
    pct = has_tokens / sampled * 100
    if pct >= 50:
        return CriterionResult(
            criterion_id="R.10", status=Status.PASS,
            evidence=f"Token data present in {has_tokens}/{sampled} sampled runs ({pct:.0f}%)",
        )
    return CriterionResult(
        criterion_id="R.10", status=Status.WARN,
        evidence=f"Token data in only {has_tokens}/{sampled} sampled runs ({pct:.0f}%)",
        remediation="Ensure token usage is logged in result.json",
    )


def check_r11_fingerprint_coverage() -> CriterionResult:
    """R.11: Error fingerprinting covers >=10 patterns."""
    fp_script = PROJECT_ROOT / "scripts" / "status_fingerprints.py"
    if not fp_script.is_file():
        return CriterionResult(
            criterion_id="R.11", status=Status.WARN,
            evidence="status_fingerprints.py not found",
        )

    content = fp_script.read_text(errors="replace")
    # Count fingerprint entries (tuples in ERROR_FINGERPRINTS list)
    count = len(re.findall(r'^\s*\(\s*"[^"]+",', content, re.MULTILINE))

    if count >= 10:
        return CriterionResult(
            criterion_id="R.11", status=Status.PASS,
            evidence=f"Error fingerprinting has {count} patterns (>=10)",
        )
    return CriterionResult(
        criterion_id="R.11", status=Status.WARN,
        evidence=f"Only {count} error fingerprint patterns (<10)",
        remediation="Add more error classification patterns",
    )


def check_r12_repro_instructions() -> CriterionResult:
    """R.12: Reproducibility instructions in CLAUDE.md."""
    claude_md = PROJECT_ROOT / "CLAUDE.md"
    if not claude_md.is_file():
        return CriterionResult(
            criterion_id="R.12", status=Status.WARN,
            evidence="CLAUDE.md not found",
        )
    content = claude_md.read_text(errors="replace")
    has_run_instructions = bool(re.search(r"running\s+tasks|run.*benchmark|how.*to.*run", content, re.IGNORECASE))
    if has_run_instructions:
        return CriterionResult(
            criterion_id="R.12", status=Status.PASS,
            evidence="CLAUDE.md contains run instructions",
        )
    return CriterionResult(
        criterion_id="R.12", status=Status.WARN,
        evidence="CLAUDE.md lacks reproducibility instructions",
        remediation="Add a 'Running Tasks' section to CLAUDE.md",
    )


def check_r13_manifest() -> CriterionResult:
    """R.13: MANIFEST.json tracks run results."""
    manifest = RUNS_DIR / "MANIFEST.json"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text())
            count = len(data) if isinstance(data, list) else len(data.get("results", []))
            return CriterionResult(
                criterion_id="R.13", status=Status.PASS,
                evidence=f"MANIFEST.json exists with {count} entries",
            )
        except json.JSONDecodeError:
            return CriterionResult(
                criterion_id="R.13", status=Status.WARN,
                evidence="MANIFEST.json exists but is invalid JSON",
                remediation="Regenerate with: python3 scripts/generate_manifest.py",
            )
    return CriterionResult(
        criterion_id="R.13", status=Status.WARN,
        evidence="MANIFEST.json not found",
        remediation="Generate with: python3 scripts/generate_manifest.py",
    )


def check_t10_shared_state(tasks: list[Path]) -> CriterionResult:
    """T.10: Tasks don't share mutable state (no hardcoded ports, shared /tmp, named volumes)."""
    issues = []
    for task_dir in tasks:
        task_name = task_dir.name
        task_issues = []

        # Scan Dockerfiles
        env_dir = task_dir / "environment"
        if env_dir.is_dir():
            for df in env_dir.iterdir():
                if df.name.startswith("Dockerfile") and df.is_file():
                    content = df.read_text(errors="replace")
                    # Check for EXPOSE (binds to host ports)
                    exposed = re.findall(r"^\s*EXPOSE\s+(\d+)", content, re.MULTILINE)
                    if exposed:
                        task_issues.append(f"{df.name}: EXPOSE {', '.join(exposed)}")

        # Scan test.sh / eval.sh for shared state
        for rel in ("tests/test.sh", "tests/eval.sh"):
            script = task_dir / rel
            if not script.is_file():
                continue
            content = script.read_text(errors="replace")

            # Hardcoded ports (e.g., localhost:8080, 0.0.0.0:3000, -p 8080:8080)
            port_binds = re.findall(r"-p\s+(\d+:\d+)", content)
            if port_binds:
                task_issues.append(f"{rel}: host port binding {', '.join(port_binds)}")

            # Fixed /tmp paths (e.g., /tmp/mytest, /tmp/results) — skip dynamic like /tmp/$$ or mktemp
            fixed_tmp = re.findall(r"/tmp/([a-zA-Z][a-zA-Z0-9_.-]+)", content)
            # Filter out common safe patterns (mktemp results, variable expansions)
            fixed_tmp = [t for t in fixed_tmp if not re.match(r"tmp\.", t)]
            if fixed_tmp:
                task_issues.append(f"{rel}: fixed /tmp paths: /tmp/{', /tmp/'.join(fixed_tmp[:3])}")

            # Named Docker volumes
            named_vols = re.findall(r"docker\s+.*-v\s+([a-zA-Z]\w+):/", content)
            if named_vols:
                task_issues.append(f"{rel}: named Docker volumes: {', '.join(named_vols)}")

        if task_issues:
            issues.append(f"{task_name}: {'; '.join(task_issues)}")

    if not issues:
        return CriterionResult(
            criterion_id="T.10", status=Status.PASS,
            evidence=f"No shared-state concerns found across {len(tasks)} tasks",
        )
    return CriterionResult(
        criterion_id="T.10", status=Status.FAIL,
        evidence="\n".join(issues[:10]),
        remediation="Remove hardcoded ports, use mktemp for temp paths, avoid named Docker volumes",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_oa_equivalent_solutions(tasks: list[Path]) -> CriterionResult:
    """O.a: Verifiers accept functionally equivalent solutions (no overly-strict matching)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier:
            continue

        content = verifier.read_text(errors="replace")
        task_name = task_dir.name
        task_issues = []

        if verifier.suffix == ".sh":
            # Flag grep -Fx (exact fixed-string line match)
            if re.search(r"\bgrep\s+.*-[A-Za-z]*F[A-Za-z]*x|grep\s+.*-[A-Za-z]*x[A-Za-z]*F", content):
                task_issues.append("grep -Fx (exact fixed-string match)")

            # Flag direct string equality tests: [ "$var" = "hardcoded" ] or == "hardcoded"
            strict_eq = re.findall(r'\[\s*"\$\w+"\s*==?\s*"([^"]+)"\s*\]', content)
            if strict_eq:
                task_issues.append(f"exact string comparison against: {', '.join(strict_eq[:3])}")

            # Flag diff without any tolerance flags (allow diff -w, diff -b, diff --ignore)
            diff_calls = re.finditer(r"\bdiff\s+([^\n|;&]+)", content)
            for m in diff_calls:
                args = m.group(1)
                if re.search(r"-[A-Za-z]*[wbBi]|--ignore|--strip", args):
                    continue
                if "<(" in args:
                    continue
                task_issues.append("diff without tolerance flags (-w/-b/--ignore)")
                break

        if task_issues:
            issues.append(f"{task_name}: {'; '.join(task_issues)}")

    if not issues:
        return CriterionResult(
            criterion_id="O.a", status=Status.PASS,
            evidence=f"No overly-strict matching found across {len(tasks)} verifiers",
        )
    return CriterionResult(
        criterion_id="O.a", status=Status.WARN,
        evidence="\n".join(issues[:10]),
        remediation="Consider using flexible matching (regex, -i flag, tolerance) in verifiers",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_ob_negated_solutions(tasks: list[Path]) -> CriterionResult:
    """O.b: Verifiers reject negated/inverted solutions (no keyword-only matching)."""
    issues = []
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier or verifier.suffix != ".sh":
            continue

        content = verifier.read_text(errors="replace")
        task_name = task_dir.name
        task_issues = []

        # Find bare grep for a single short keyword without robust flags.
        # These could match "NOT keyword" or "the answer is definitely not keyword".
        # Exclude greps with flags: -E (regex), -P (perl), -w (word boundary),
        # -c (count), -r/-R (recursive code search), -l (file list), -q (boolean),
        # -n (line numbers).
        bare_greps = re.finditer(
            r"""grep\s+(?:-[A-Za-z]*\s+)*['"]([^'"]{1,20})['"]\s+(\S+)""",
            content,
        )
        for m in bare_greps:
            keyword = m.group(1).strip()
            target = m.group(2)
            prefix = m.group(0).split(keyword)[0]

            # Skip multi-word or regex patterns (inherently more specific)
            if re.search(r"[.*+?^${}()|\\[\]]", keyword) or " " in keyword:
                continue

            # Skip if grep has flags that make matching more robust
            if re.search(r"-[A-Za-z]*[cEPrlRwqn]", prefix):
                continue

            # Skip if grepping source code files (not agent output)
            if re.search(r"\.(py|js|ts|go|java|rs|c|cpp|sh|rb|yaml|yml|toml|json|md)$", target):
                continue

            # Skip if target is log/reward/result paths (structured output)
            if re.search(r"/logs/|reward\.|result\.|\.log", target):
                continue

            task_issues.append(f"bare grep for '{keyword}' could match negated answer")

        if task_issues:
            issues.append(f"{task_name}: {'; '.join(task_issues[:3])}")

    if not issues:
        return CriterionResult(
            criterion_id="O.b", status=Status.PASS,
            evidence=f"No keyword-only matching vulnerable to negation across {len(tasks)} verifiers",
        )
    return CriterionResult(
        criterion_id="O.b", status=Status.WARN,
        evidence="\n".join(issues[:10]),
        remediation="Use multi-word patterns, regex with context, or structured JSON validation instead of bare keyword grep",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


def check_og_determinism(tasks: list[Path]) -> CriterionResult:
    """O.g: Verifiers produce deterministic results (no unseeded randomness)."""
    issues = []
    # Non-deterministic commands that affect scoring when used in comparisons
    NONDETERMINISTIC_CMDS = re.compile(
        r'\$RANDOM|\buuidgen\b|\bshuf\b'
    )
    # date command substitution used in comparisons/assertions (not just logging)
    DATE_IN_COMPARISON = re.compile(
        r'(?:\[\s*.*\$\(date\b|==\s*.*\$\(date\b|!=\s*.*\$\(date\b)'
    )
    # mktemp used in assertions/comparisons (not just for scratch files)
    MKTEMP_IN_ASSERT = re.compile(
        r'(?:diff|cmp|==|!=|grep|assert).*\$\(mktemp|mktemp.*(?:diff|cmp|==|!=|grep|assert)'
    )
    for task_dir in tasks:
        verifier = _get_primary_verifier(task_dir)
        if not verifier:
            continue

        content = verifier.read_text(errors="replace")
        task_name = task_dir.name
        task_issues = []

        if verifier.suffix == ".sh":
            if NONDETERMINISTIC_CMDS.search(content):
                matches = NONDETERMINISTIC_CMDS.findall(content)
                task_issues.append(f"non-deterministic command: {matches[0]}")

            if DATE_IN_COMPARISON.search(content):
                task_issues.append("date output used in comparison/assertion")

            if MKTEMP_IN_ASSERT.search(content):
                task_issues.append("mktemp path used in assertion/comparison")

        elif verifier.suffix == ".py":
            # Flag unseeded random usage
            if re.search(r'\brandom\.\w+\(', content):
                # Check if random is seeded
                if not re.search(r'random\.seed\(', content):
                    task_issues.append("unseeded random module usage")
            # Flag uuid usage in assertions
            if re.search(r'\buuid\.\w+\(', content):
                task_issues.append("uuid generation in verifier")

        if task_issues:
            issues.append(f"{task_name}: {'; '.join(task_issues)}")

    if not issues:
        return CriterionResult(
            criterion_id="O.g", status=Status.PASS,
            evidence=f"No non-deterministic patterns found across {len(tasks)} verifiers",
        )
    return CriterionResult(
        criterion_id="O.g", status=Status.WARN,
        evidence="\n".join(issues[:10]),
        remediation="Remove non-deterministic commands from verifier scoring logic, or seed random generators",
        details={"issue_count": len(issues), "issues": issues[:20]},
    )


# ---------------------------------------------------------------------------
# Main auditor
# ---------------------------------------------------------------------------

# Map criterion IDs to check functions
# Functions that take tasks: list[Path]
TASK_CHECKS = {
    "T.1": check_t1_pinned_versions,
    "T.3": check_t3_no_api_keys,
    "T.4": check_t4_git_sha,
    "T.5": check_t5_no_solution_leak,
    "T.8": check_t8_oracle_exists,
    "O.a": check_oa_equivalent_solutions,
    "O.b": check_ob_negated_solutions,
    "O.c": check_oc_empty_solution_rejected,
    "O.g": check_og_determinism,
    "O.d": check_od_error_handling,
    "O.e": check_oe_multiple_assertions,
    "O.h": check_oh_reward_format,
    "O.i": check_oi_partial_credit,
    "R.1": check_r1_files_exist,
    "R.2": check_r2_no_contamination,
    "T.10": check_t10_shared_state,
}

# Functions that take suite: str
SUITE_CHECKS = {
    "R.3": check_r3_readme,
    "R.4": check_r4_sdlc_phase,
    "R.7": check_r7_baseline_results,
    "R.9": check_r9_difficulty_distribution,
}

# Functions that take no args (project-level)
PROJECT_CHECKS = {
    "R.5": check_r5_error_catalog,
    "R.8": check_r8_task_selection_docs,
    "R.10": check_r10_token_data,
    "R.11": check_r11_fingerprint_coverage,
    "R.12": check_r12_repro_instructions,
    "R.13": check_r13_manifest,
}

# Semi-automated / manual checks (skip with note)
SKIP_CHECKS = {"T.2", "T.9", "O.f", "R.6"}


def audit_suite(suite: str, dimension: Optional[Dimension] = None) -> AuditReport:
    """Run all applicable criteria checks against a benchmark suite."""
    tasks = discover_tasks(suite)
    criteria = get_criteria_for_suite(suite)
    report = AuditReport(target=suite)

    for criterion in criteria:
        # Filter by dimension if specified
        if dimension and criterion.dimension != dimension:
            continue

        cid = criterion.id

        # Skip semi-automated/manual checks
        if cid in SKIP_CHECKS:
            report.results.append(CriterionResult(
                criterion_id=cid, status=Status.SKIP,
                evidence=f"Requires {criterion.automation.value} review",
            ))
            continue

        # R.2 doesn't apply to MCP-unique suites: instructions intentionally
        # reference Sourcegraph MCP tools (that's the point of these tasks).
        if cid == "R.2" and suite.startswith(("csb_org_", "ccb_mcp_")):
            report.results.append(CriterionResult(
                criterion_id=cid, status=Status.SKIP,
                evidence="MCP-unique suite: MCP tool references in instructions are by design",
            ))
            continue

        # Run automated check
        if cid in TASK_CHECKS:
            result = TASK_CHECKS[cid](tasks)
        elif cid in SUITE_CHECKS:
            result = SUITE_CHECKS[cid](suite)
        elif cid in PROJECT_CHECKS:
            result = PROJECT_CHECKS[cid]()
        elif criterion.delegated_to:
            # Delegated checks — mark as SKIP with delegation note
            report.results.append(CriterionResult(
                criterion_id=cid, status=Status.SKIP,
                evidence=f"Delegated to {criterion.delegated_to}",
            ))
            continue
        else:
            report.results.append(CriterionResult(
                criterion_id=cid, status=Status.SKIP,
                evidence="No automated check implemented",
            ))
            continue

        report.results.append(result)

    report.compute_grade()
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit benchmark suites against ABC framework criteria."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--suite", help="Benchmark suite name (e.g., ccb_pytorch)")
    group.add_argument("--all", action="store_true", help="Audit all benchmark suites")

    parser.add_argument("--dimension", choices=["task_validity", "outcome_validity", "reporting"],
                        help="Filter to a single dimension")
    parser.add_argument("--critical-only", action="store_true",
                        help="Only show critical criteria results")
    parser.add_argument("--format", choices=["json", "table"], default="table",
                        help="Output format (default: table)")

    args = parser.parse_args()

    dim = Dimension(args.dimension) if args.dimension else None

    reports: list[AuditReport] = []

    if args.suite:
        suite_dir = BENCHMARKS_DIR / args.suite
        if not suite_dir.is_dir():
            print(f"ERROR: Suite directory not found: {suite_dir}", file=sys.stderr)
            sys.exit(1)
        reports.append(audit_suite(args.suite, dim))
    elif args.all:
        for suite in discover_all_suites():
            reports.append(audit_suite(suite, dim))

    # Filter to critical-only if requested
    if args.critical_only:
        for report in reports:
            report.results = [
                r for r in report.results
                if CRITERIA_BY_ID.get(r.criterion_id, None) is None
                or CRITERIA_BY_ID[r.criterion_id].severity == Severity.CRITICAL
            ]
            report.compute_grade()

    # Output
    if args.format == "json":
        if len(reports) == 1:
            print(reports[0].to_json())
        else:
            output = {
                "suites_audited": len(reports),
                "reports": [r.to_dict() for r in reports],
            }
            print(json.dumps(output, indent=2))
    else:
        for report in reports:
            print(report.to_table())
            print()

    # Exit code: 0 if all critical pass, 1 if any critical fail
    has_critical_fail = any(not r.overall_pass for r in reports)
    sys.exit(1 if has_critical_fail else 0)


if __name__ == "__main__":
    main()

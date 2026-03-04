#!/usr/bin/env python3
"""ABC Task Quality Scorer — scores individual tasks on 3 weighted dimensions.

Dimensions:
  - Instruction Clarity (0.30): length, structure, no placeholders, metadata
  - Verifier Quality (0.40): test.sh exists, error handling, assertions, partial credit
  - Reproducibility (0.30): Dockerfile, pinned versions, deterministic checkout, time limit

Usage:
  python3 scripts/abc_score_task.py --task benchmarks/ccb_pytorch/sgt-005
  python3 scripts/abc_score_task.py --suite ccb_pytorch [--threshold 0.7]
  python3 scripts/abc_score_task.py --all --format table
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
SELECTED_TASKS_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DimensionScore:
    name: str
    weight: float
    score: float  # 0.0 - 1.0
    sub_checks: dict[str, float] = field(default_factory=dict)


@dataclass
class TaskScore:
    task_id: str
    suite: str
    task_dir: str
    overall: float = 0.0
    needs_review: bool = False
    dimensions: list[DimensionScore] = field(default_factory=list)

    def compute_overall(self) -> None:
        if not self.dimensions:
            self.overall = 0.0
            return
        self.overall = round(
            sum(d.weight * d.score for d in self.dimensions), 3
        )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "suite": self.suite,
            "task_dir": self.task_dir,
            "overall": self.overall,
            "needs_review": self.needs_review,
            "dimensions": [
                {
                    "name": d.name,
                    "weight": d.weight,
                    "score": d.score,
                    "sub_checks": d.sub_checks,
                }
                for d in self.dimensions
            ],
        }


# ---------------------------------------------------------------------------
# TOML parser (reused pattern from validate_tasks_preflight.py)
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
# Dimension scorers
# ---------------------------------------------------------------------------

def score_instruction_clarity(task_dir: Path, toml_data: dict) -> DimensionScore:
    """Score instruction.md quality (weight 0.30)."""
    sub = {}

    instruction_path = task_dir / "instruction.md"
    if not instruction_path.is_file():
        return DimensionScore(
            name="instruction_clarity", weight=0.30, score=0.0,
            sub_checks={"exists": 0.0},
        )

    text = instruction_path.read_text(errors="replace")

    # Length check: >500 chars = 1.0, 200-500 = 0.5, <200 = 0.0
    length = len(text)
    if length > 500:
        sub["length"] = 1.0
    elif length > 200:
        sub["length"] = 0.5
    else:
        sub["length"] = 0.0

    # Markdown structure: headers or lists present
    has_headers = bool(re.search(r"^#{1,3}\s", text, re.MULTILINE))
    has_lists = bool(re.search(r"^[\-\*]\s", text, re.MULTILINE))
    sub["structure"] = 1.0 if (has_headers or has_lists) else 0.0

    # No template placeholders like {{PLACEHOLDER}} or TODO
    placeholders = re.findall(r"\{\{[A-Z_]+\}\}", text)
    todos = re.findall(r"\bTODO\b", text, re.IGNORECASE)
    sub["no_placeholders"] = 0.0 if (placeholders or todos) else 1.0

    # task.toml completeness: has name + difficulty
    has_name = bool(toml_data.get("name") or toml_data.get("task.name"))
    has_difficulty = bool(toml_data.get("difficulty") or toml_data.get("metadata.difficulty"))
    sub["metadata_complete"] = 1.0 if (has_name and has_difficulty) else (0.5 if has_name else 0.0)

    score = round(sum(sub.values()) / len(sub), 3) if sub else 0.0
    return DimensionScore(name="instruction_clarity", weight=0.30, score=score, sub_checks=sub)


def score_verifier_quality(task_dir: Path) -> DimensionScore:
    """Score test.sh / verify.py quality (weight 0.40)."""
    sub = {}

    test_sh = task_dir / "tests" / "test.sh"
    verify_py = task_dir / "tests" / "verify.py"

    # Existence check
    has_test_sh = test_sh.is_file()
    has_verify_py = verify_py.is_file()
    sub["exists"] = 1.0 if (has_test_sh or has_verify_py) else 0.0

    if not (has_test_sh or has_verify_py):
        return DimensionScore(
            name="verifier_quality", weight=0.40, score=0.0, sub_checks=sub,
        )

    # Read the primary verifier
    verifier_text = ""
    if has_test_sh:
        verifier_text = test_sh.read_text(errors="replace")
    elif has_verify_py:
        verifier_text = verify_py.read_text(errors="replace")

    # Error handling: set -e, set -eo pipefail, or trap
    has_set_e = bool(re.search(r"set\s+-e", verifier_text))
    has_pipefail = bool(re.search(r"set\s+-eo?\s+pipefail", verifier_text))
    has_trap = bool(re.search(r"\btrap\b", verifier_text))
    # Python verifiers get automatic credit (exceptions are built-in)
    if has_verify_py and not has_test_sh:
        sub["error_handling"] = 1.0
    else:
        sub["error_handling"] = 1.0 if (has_set_e or has_pipefail or has_trap) else 0.0

    # Reward output: writes to reward.txt or /logs/verifier/reward.txt
    reward_patterns = [
        r"reward\.txt",
        r"/logs/verifier/reward",
        r"echo\s+.*>\s*.*reward",
        r"print.*reward",
    ]
    has_reward = any(re.search(p, verifier_text) for p in reward_patterns)
    sub["reward_output"] = 1.0 if has_reward else 0.0

    # Nontrivial logic: has real assertions (not just echo "1.0")
    assertion_patterns = [
        r"\btest\s+",
        r"\bassert\b",
        r"\bdiff\b",
        r"\bgrep\b",
        r"\bif\s+\[",
        r"\bpytest\b",
        r"\bunittest\b",
        r"assertEqual",
        r"assert_",
        r"\bmake\s+test",
        r"\bcompare\b",
    ]
    assertion_count = sum(
        1 for p in assertion_patterns if re.search(p, verifier_text)
    )
    sub["nontrivial_logic"] = min(1.0, assertion_count / 2.0)

    # Ground truth present: expected.diff, solve.sh, golden/, expected/
    ground_truth_files = [
        task_dir / "solve.sh",
        task_dir / "expected.diff",
        task_dir / "tests" / "expected.diff",
        task_dir / "tests" / "golden",
        task_dir / "tests" / "expected",
    ]
    has_ground_truth = any(p.exists() for p in ground_truth_files)
    sub["ground_truth"] = 1.0 if has_ground_truth else 0.0

    # Partial credit: float arithmetic or weighted scoring
    partial_patterns = [
        r"0\.\d+",  # float literal
        r"bc\s+-l",  # bc calculator
        r"python.*float",
        r"awk.*printf",
        r"\bweights?\b",
        r"partial",
        r"score\s*[+\-*/]=",
    ]
    has_partial = any(re.search(p, verifier_text) for p in partial_patterns)
    sub["partial_credit"] = 1.0 if has_partial else 0.0

    score = round(sum(sub.values()) / len(sub), 3) if sub else 0.0
    return DimensionScore(name="verifier_quality", weight=0.40, score=score, sub_checks=sub)


def score_reproducibility(task_dir: Path, toml_data: dict) -> DimensionScore:
    """Score reproducibility quality (weight 0.30)."""
    sub = {}

    # Dockerfile exists
    env_dir = task_dir / "environment"
    dockerfile = env_dir / "Dockerfile"
    if not dockerfile.is_file():
        # Some benchmarks use Harbor registry (no local Dockerfile)
        dockerfile = task_dir / "Dockerfile"

    has_dockerfile = dockerfile.is_file()
    sub["dockerfile_exists"] = 1.0 if has_dockerfile else 0.0

    if has_dockerfile:
        df_text = dockerfile.read_text(errors="replace")

        # Pinned versions: no :latest in FROM
        latest_from = re.findall(r"FROM\s+\S+:latest", df_text, re.IGNORECASE)
        unpinned_from = re.findall(r"FROM\s+\S+\s", df_text)
        # FROM that has no tag at all is also unpinned
        no_tag_from = [
            m for m in unpinned_from
            if ":" not in m.split()[1] and m.split()[1].lower() != "scratch"
        ]
        sub["pinned_versions"] = 0.0 if (latest_from or no_tag_from) else 1.0

        # Deterministic checkout: no unpinned git clone
        git_clones = re.findall(r"git\s+clone\b.*", df_text)
        unpinned_clones = []
        for clone in git_clones:
            # Check if there's a subsequent checkout to a SHA
            has_sha_checkout = bool(re.search(
                r"git\s+checkout\s+[0-9a-f]{7,40}", df_text
            ))
            if not has_sha_checkout and "--depth 1" in clone:
                unpinned_clones.append(clone.strip())
        sub["deterministic_checkout"] = 0.0 if unpinned_clones else 1.0
    else:
        sub["pinned_versions"] = 0.5  # Can't verify, neutral
        sub["deterministic_checkout"] = 0.5

    # Time limit set in task.toml
    time_limit = toml_data.get("time_limit_sec") or toml_data.get("task.time_limit_sec")
    sub["time_limit_set"] = 1.0 if time_limit else 0.0

    # Resource limits (memory_limit or cpu_limit in task.toml)
    has_mem = bool(toml_data.get("memory_limit") or toml_data.get("task.memory_limit"))
    has_cpu = bool(toml_data.get("cpu_limit") or toml_data.get("task.cpu_limit"))
    sub["resource_limits"] = 1.0 if (has_mem or has_cpu) else 0.0

    score = round(sum(sub.values()) / len(sub), 3) if sub else 0.0
    return DimensionScore(name="reproducibility", weight=0.30, score=score, sub_checks=sub)


# ---------------------------------------------------------------------------
# Main scorer
# ---------------------------------------------------------------------------

def score_task(task_dir: Path) -> TaskScore:
    """Score a single task directory."""
    task_dir = task_dir.resolve()
    task_id = task_dir.name
    suite = task_dir.parent.name if task_dir.parent != BENCHMARKS_DIR else "unknown"

    toml_path = task_dir / "task.toml"
    toml_data = parse_task_toml_simple(toml_path)

    ts = TaskScore(
        task_id=task_id,
        suite=suite,
        task_dir=str(task_dir.relative_to(PROJECT_ROOT)) if str(task_dir).startswith(str(PROJECT_ROOT)) else str(task_dir),
    )

    ts.dimensions = [
        score_instruction_clarity(task_dir, toml_data),
        score_verifier_quality(task_dir),
        score_reproducibility(task_dir, toml_data),
    ]
    ts.compute_overall()
    return ts


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
# Output formatting
# ---------------------------------------------------------------------------

def format_table(scores: list[TaskScore], threshold: float) -> str:
    """Format task scores as ASCII table."""
    lines = []
    lines.append(f"{'Task':<40} {'Suite':<20} {'Instr':>6} {'Verif':>6} {'Repro':>6} {'Overall':>8} {'Flag':>6}")
    lines.append(f"{'─' * 40} {'─' * 20} {'─' * 6} {'─' * 6} {'─' * 6} {'─' * 8} {'─' * 6}")

    for s in scores:
        dim_scores = {d.name: d.score for d in s.dimensions}
        flag = " *" if s.needs_review else ""
        lines.append(
            f"{s.task_id:<40} {s.suite:<20} "
            f"{dim_scores.get('instruction_clarity', 0):.2f}  "
            f"{dim_scores.get('verifier_quality', 0):.2f}  "
            f"{dim_scores.get('reproducibility', 0):.2f}  "
            f"{s.overall:>7.3f} {flag}"
        )

    flagged = sum(1 for s in scores if s.needs_review)
    lines.append("")
    lines.append(f"Tasks: {len(scores)}  |  Flagged (< {threshold}): {flagged}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score benchmark tasks on instruction clarity, verifier quality, and reproducibility."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=Path, help="Path to a single task directory")
    group.add_argument("--suite", help="Benchmark suite name (e.g., ccb_pytorch)")
    group.add_argument("--all", action="store_true", help="Score all benchmark suites")

    parser.add_argument("--threshold", type=float, default=0.7,
                        help="Flag tasks below this score (default: 0.7)")
    parser.add_argument("--format", choices=["json", "table"], default="table",
                        help="Output format (default: table)")

    args = parser.parse_args()

    scores: list[TaskScore] = []

    if args.task:
        task_path = args.task.resolve()
        if not task_path.is_dir():
            print(f"ERROR: Not a directory: {task_path}", file=sys.stderr)
            sys.exit(1)
        scores.append(score_task(task_path))
    elif args.suite:
        tasks = discover_tasks(args.suite)
        if not tasks:
            print(f"ERROR: No tasks found for suite '{args.suite}'", file=sys.stderr)
            sys.exit(1)
        for t in tasks:
            scores.append(score_task(t))
    elif args.all:
        for suite in discover_all_suites():
            for t in discover_tasks(suite):
                scores.append(score_task(t))

    # Apply threshold flagging
    for s in scores:
        s.needs_review = s.overall < args.threshold

    # Output
    if args.format == "json":
        output = {
            "threshold": args.threshold,
            "tasks_scored": len(scores),
            "tasks_flagged": sum(1 for s in scores if s.needs_review),
            "scores": [s.to_dict() for s in scores],
        }
        print(json.dumps(output, indent=2))
    else:
        print(format_table(scores, args.threshold))

    # Exit code
    flagged = sum(1 for s in scores if s.needs_review)
    sys.exit(1 if flagged > 0 else 0)


if __name__ == "__main__":
    main()

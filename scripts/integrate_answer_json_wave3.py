#!/usr/bin/env python3
"""Wave 3 integration: Add answer.json support to ccb_fix, ccb_secure, and ccb_build suites.

Categories handled:
  ccb_fix:
    - test_ratio (12): SWE-bench Pro tests — source block + cd replacement
    - diff_similarity (4): PyTorch verify_diff.py — source block + cd replacement
    - ir_checklist (3): IR metrics — source block + solution.md redirect + cd replacement
    - checklist (2+): weighted code checks — source block + cd replacement

  ccb_secure:
    - triage (8): CVE triage checklist — source block + triage.md redirect
    - ir_checklist (4): IR metrics — source block + solution.md redirect + cd replacement
    - code_change (8): code modification — source block + cd replacement

  ccb_build:
    - tac (1): external evaluator — SKIP
    - dibench (7): dependency validators — source block only
    - ir_checklist (8): compilation + IR metrics — source block + cd replacement
    - checklist (5): weighted code checks — source block + cd replacement
    - f1_scorer (2): F1 JSON scoring — source block only
    - semantic_similarity (1): patch validation — source block only

Each task gets:
1. answer_json_verifier_lib.sh copied to tests/
2. Source block added to test.sh
3. cd /workspace (or /app) replaced with VERIFY_REPO-aware version (code-change tasks)
4. ANALYSIS_TEXT_FILE redirect for text-output tasks
"""

import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_SRC = os.path.join(ROOT, "scripts", "answer_json_verifier_lib.sh")

# Source block to insert
SOURCE_BLOCK = """\

# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi
"""

# Tasks to skip entirely
SKIP_TASKS = {
    # ccb_build TAC: external evaluator (/utils/eval.py)
    "bustub-hyperloglog-impl-001",
}


# ── Category detection ───────────────────────────────────────────────────

def detect_category(content, task_name):
    """Auto-detect verifier category from test.sh content."""
    # TAC external evaluator
    if "/utils/eval.py" in content or "TAC evaluator" in content:
        return "tac"

    # DIBench dependency validators
    if "validate_task" in content and "validators" in content:
        return "dibench"

    # PyTorch diff similarity (verify_diff.py)
    if "verify_diff.py" in content:
        return "diff_similarity"

    # F1 scorer (structured JSON matching)
    if "key_fields" in content and "F1" in content and "true_positives" in content:
        return "f1_scorer"

    # Semantic similarity (expected_changes.json patch validation)
    if "expected_changes.json" in content:
        return "semantic_similarity"

    # CVE triage checklist (reads from triage.md)
    if 'REPORT_PATH' in content and 'triage.md' in content and 'required_findings' in content:
        return "triage"

    # IR checklist with verifier_lib.sh
    if "verifier_lib.sh" in content and ("ir_pipeline" in content or "run_ir_pipeline" in content
                                          or "compute_ir_metrics" in content):
        return "ir_checklist"

    # SWE-bench Pro test_ratio (test patch + pytest/go test/npm test)
    if "TEST_PATCH_EOF" in content:
        return "test_ratio"

    # Weighted checklist on code changes (various score variable names)
    if "SCORE_NUMERATOR" in content:
        return "checklist_code"
    if "FUNC_SCORE" in content or "POLICY_SCORE" in content:
        return "checklist_code"
    # SCORE=$((SCORE + N)) pattern with git diff checks
    if re.search(r'SCORE=\$\(\(\s*\$?SCORE\s*\+', content) and "git diff" in content:
        return "checklist_code"

    # Checklist reading from REPORT_PATH (text output)
    if 'REPORT_PATH' in content and 'required_findings' in content:
        return "checklist_text"

    return "unknown"


# ── Insertion point helpers ──────────────────────────────────────────────

def find_insertion_point(lines):
    """Find where to insert source block — after sg_only line or after set -e."""
    sg_only_idx = None
    set_e_idx = None

    for i, line in enumerate(lines):
        if "sg_only_mode" in line and "sgonly_verifier_wrapper" in line:
            sg_only_idx = i
        if line.strip() in ("set -e", "set -euo pipefail", "set -uo pipefail",
                            "set -eo pipefail"):
            set_e_idx = i

    if sg_only_idx is not None:
        return sg_only_idx + 1
    elif set_e_idx is not None:
        return set_e_idx + 1
    return 2  # fallback: after shebang


def detect_output_path(content, task_name):
    """Detect expected text output path from test.sh content."""
    # REPORT_PATH="${REPORT_PATH:-/logs/agent/triage.md}"
    m = re.search(r'REPORT_PATH="\$\{REPORT_PATH:-([^}]+)\}"', content)
    if m:
        return m.group(1)

    # SOLUTION_FILE="/logs/agent/solution.md"
    m = re.search(r'SOLUTION_FILE="([^"]+)"', content)
    if m:
        return m.group(1)

    # Check for solution.md reference
    if '/logs/agent/solution.md' in content:
        return '/logs/agent/solution.md'

    return None


def build_redirect_block(output_path):
    """Build conditional copy block for text-based redirects."""
    parent_dir = os.path.dirname(output_path)
    mkdir_cmd = ""
    if parent_dir and parent_dir not in ("/workspace", ""):
        mkdir_cmd = f'    mkdir -p "{parent_dir}"\n'

    return (
        f'\n# In artifact mode, populate expected output from answer.json analysis\n'
        f'if [ "${{ARTIFACT_ONLY:-false}}" = "true" ] && [ -f "${{ANALYSIS_TEXT_FILE:-}}" ]; then\n'
        f'{mkdir_cmd}'
        f'    cp "$ANALYSIS_TEXT_FILE" "{output_path}"\n'
        f'    echo "[answer_json] Copied analysis text to {output_path}"\n'
        f'fi\n'
    )


def find_redirect_point(lines, output_path):
    """Find where to insert redirect block — after the output file variable."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if output_path in stripped:
            if re.match(r'(REPORT_PATH|OUTPUT_FILE|SOLUTION_FILE|DOCUMENTATION_FILE)=', stripped):
                return i + 1
    # Fallback: after the source block
    for i, line in enumerate(lines):
        if "answer_json_verifier_lib.sh" in line:
            for j in range(i, min(i + 5, len(lines))):
                if lines[j].strip() == "fi":
                    return j + 1
    return None


# ── cd replacement ───────────────────────────────────────────────────────

def replace_cd_commands(lines):
    """Replace cd /workspace (and /app variants) with VERIFY_REPO-aware versions.

    Only replaces the first occurrence of each pattern, and only standalone
    cd commands (not in comments or the verifier wrapper line).
    """
    replaced = False
    result = []
    for line in lines:
        stripped = line.strip()
        # Skip comments and the sgonly/artifact source lines
        if stripped.startswith("#") or "verifier_wrapper" in stripped or "verifier_lib" in stripped:
            result.append(line)
            continue

        # Pattern: cd /app || cd /testbed || cd /workspace
        if not replaced and "cd /app" in stripped and ("cd /testbed" in stripped or "cd /workspace" in stripped):
            new_line = line.replace("cd /app", 'cd "${VERIFY_REPO:-/app}"', 1)
            result.append(new_line)
            replaced = True
            continue

        # Pattern: cd /app/repo (standalone)
        if not replaced and stripped == "cd /app/repo":
            new_line = line.replace("cd /app/repo", 'cd "${VERIFY_REPO:-/app/repo}"')
            result.append(new_line)
            replaced = True
            continue

        # Pattern: cd /workspace (standalone, not part of || chain already handled)
        if not replaced and re.match(r'^cd /workspace\s*$', stripped):
            new_line = line.replace("cd /workspace", 'cd "${VERIFY_REPO:-/workspace}"')
            result.append(new_line)
            replaced = True
            continue

        result.append(line)

    return result, replaced


# ── Integration functions ────────────────────────────────────────────────

def integrate_source_only(task_dir, task_name, category, dry_run=False):
    """Add source block only (DIBench, F1 scorer, semantic similarity).

    The lib handles setup gracefully; verifier operates as-is.
    """
    tests_dir = os.path.join(task_dir, "tests")
    test_sh = os.path.join(tests_dir, "test.sh")

    with open(test_sh) as f:
        content = f.read()

    if "answer_json_verifier_lib.sh" in content:
        return f"SKIP {task_name}: already integrated"

    lines = content.split("\n")
    source_idx = find_insertion_point(lines)
    source_lines = SOURCE_BLOCK.strip().split("\n")
    for j, sl in enumerate(source_lines):
        lines.insert(source_idx + j, sl)

    if dry_run:
        return f"WOULD modify {task_name} ({category})"

    shutil.copy2(LIB_SRC, os.path.join(tests_dir, "answer_json_verifier_lib.sh"))
    with open(test_sh, "w") as f:
        f.write("\n".join(lines))
    return f"OK {task_name}: integrated ({category})"


def integrate_code_change(task_dir, task_name, category, dry_run=False):
    """Add source block + replace cd commands for code-change verifiers.

    After sourcing, VERIFY_REPO is set. Replacing cd /workspace (or /app)
    with cd "${VERIFY_REPO:-/workspace}" makes verifiers work in artifact mode
    while remaining backward compatible for normal/sg_only runs.
    """
    tests_dir = os.path.join(task_dir, "tests")
    test_sh = os.path.join(tests_dir, "test.sh")

    with open(test_sh) as f:
        content = f.read()

    if "answer_json_verifier_lib.sh" in content:
        return f"SKIP {task_name}: already integrated"

    lines = content.split("\n")

    # Insert source block
    source_idx = find_insertion_point(lines)
    source_lines = SOURCE_BLOCK.strip().split("\n")
    for j, sl in enumerate(source_lines):
        lines.insert(source_idx + j, sl)

    # Replace cd commands
    lines, cd_replaced = replace_cd_commands(lines)

    if dry_run:
        cd_note = " + cd replaced" if cd_replaced else ""
        return f"WOULD modify {task_name} ({category}{cd_note})"

    shutil.copy2(LIB_SRC, os.path.join(tests_dir, "answer_json_verifier_lib.sh"))
    with open(test_sh, "w") as f:
        f.write("\n".join(lines))

    cd_note = " + cd replaced" if cd_replaced else ""
    return f"OK {task_name}: integrated ({category}{cd_note})"


def integrate_text_output(task_dir, task_name, category, dry_run=False):
    """Add source block + output redirect for text-based verifiers.

    Copies ANALYSIS_TEXT_FILE to the expected output path (triage.md, solution.md, etc).
    """
    tests_dir = os.path.join(task_dir, "tests")
    test_sh = os.path.join(tests_dir, "test.sh")

    with open(test_sh) as f:
        content = f.read()

    if "answer_json_verifier_lib.sh" in content:
        return f"SKIP {task_name}: already integrated"

    output_path = detect_output_path(content, task_name)
    if output_path is None:
        return f"SKIP {task_name}: could not detect output path"

    lines = content.split("\n")

    # Insert source block
    source_idx = find_insertion_point(lines)
    source_lines = SOURCE_BLOCK.strip().split("\n")
    for j, sl in enumerate(source_lines):
        lines.insert(source_idx + j, sl)

    # Insert redirect block
    redirect_idx = find_redirect_point(lines, output_path)
    if redirect_idx is None:
        redirect_idx = source_idx + len(source_lines) + 1

    redirect_block = build_redirect_block(output_path)
    redirect_lines = redirect_block.strip().split("\n")
    for j, rl in enumerate(redirect_lines):
        lines.insert(redirect_idx + j, rl)

    if dry_run:
        return f"WOULD modify {task_name} ({category} → {output_path})"

    shutil.copy2(LIB_SRC, os.path.join(tests_dir, "answer_json_verifier_lib.sh"))
    with open(test_sh, "w") as f:
        f.write("\n".join(lines))
    return f"OK {task_name}: integrated ({category} → {output_path})"


def integrate_ir_checklist(task_dir, task_name, category, dry_run=False):
    """Add source block + output redirect + cd replacement for IR checklist verifiers.

    These tasks check both code changes AND solution.md text. In artifact mode:
    - ANALYSIS_TEXT_FILE is copied to /logs/agent/solution.md
    - cd is redirected to VERIFY_REPO for git operations
    """
    tests_dir = os.path.join(task_dir, "tests")
    test_sh = os.path.join(tests_dir, "test.sh")

    with open(test_sh) as f:
        content = f.read()

    if "answer_json_verifier_lib.sh" in content:
        return f"SKIP {task_name}: already integrated"

    output_path = detect_output_path(content, task_name)
    if output_path is None:
        output_path = "/logs/agent/solution.md"  # default for IR tasks

    lines = content.split("\n")

    # Insert source block
    source_idx = find_insertion_point(lines)
    source_lines = SOURCE_BLOCK.strip().split("\n")
    for j, sl in enumerate(source_lines):
        lines.insert(source_idx + j, sl)

    # Insert redirect block
    redirect_idx = find_redirect_point(lines, output_path)
    if redirect_idx is None:
        redirect_idx = source_idx + len(source_lines) + 1

    redirect_block = build_redirect_block(output_path)
    redirect_lines = redirect_block.strip().split("\n")
    for j, rl in enumerate(redirect_lines):
        lines.insert(redirect_idx + j, rl)

    # Replace cd commands
    lines, cd_replaced = replace_cd_commands(lines)

    if dry_run:
        cd_note = " + cd replaced" if cd_replaced else ""
        return f"WOULD modify {task_name} ({category} → {output_path}{cd_note})"

    shutil.copy2(LIB_SRC, os.path.join(tests_dir, "answer_json_verifier_lib.sh"))
    with open(test_sh, "w") as f:
        f.write("\n".join(lines))

    cd_note = " + cd replaced" if cd_replaced else ""
    return f"OK {task_name}: integrated ({category} → {output_path}{cd_note})"


# ── Task routing ─────────────────────────────────────────────────────────

def integrate_task(task_dir, task_name, dry_run=False):
    """Detect category and route to appropriate integration function."""
    test_sh = os.path.join(task_dir, "tests", "test.sh")
    if not os.path.isfile(test_sh):
        return f"SKIP {task_name}: no test.sh"

    with open(test_sh) as f:
        content = f.read()

    if "answer_json_verifier_lib.sh" in content:
        return f"SKIP {task_name}: already integrated"

    category = detect_category(content, task_name)

    if category == "tac":
        return f"SKIP {task_name}: TAC external evaluator"

    if category == "dibench":
        return integrate_source_only(task_dir, task_name, "dibench", dry_run)

    if category == "f1_scorer":
        return integrate_source_only(task_dir, task_name, "f1_scorer", dry_run)

    if category == "semantic_similarity":
        return integrate_source_only(task_dir, task_name, "semantic_similarity", dry_run)

    if category == "triage":
        return integrate_text_output(task_dir, task_name, "triage", dry_run)

    if category == "checklist_text":
        return integrate_text_output(task_dir, task_name, "checklist_text", dry_run)

    if category == "ir_checklist":
        return integrate_ir_checklist(task_dir, task_name, "ir_checklist", dry_run)

    if category == "test_ratio":
        return integrate_code_change(task_dir, task_name, "test_ratio", dry_run)

    if category == "diff_similarity":
        return integrate_code_change(task_dir, task_name, "diff_similarity", dry_run)

    if category == "checklist_code":
        return integrate_code_change(task_dir, task_name, "checklist_code", dry_run)

    return f"SKIP {task_name}: unknown category"


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv

    suites = ["ccb_fix", "ccb_secure", "ccb_build"]
    benchmarks_dir = os.path.join(ROOT, "benchmarks")

    results = {"ok": 0, "skip": 0, "error": 0}
    categories_seen = {}

    for suite in suites:
        suite_dir = os.path.join(benchmarks_dir, suite)
        if not os.path.isdir(suite_dir):
            print(f"WARNING: Suite dir not found: {suite_dir}")
            continue

        print(f"\n=== {suite} ===")
        for task_name in sorted(os.listdir(suite_dir)):
            task_dir = os.path.join(suite_dir, task_name)
            if not os.path.isdir(task_dir):
                continue
            if task_name in SKIP_TASKS:
                print(f"  SKIP {task_name} (excluded)")
                results["skip"] += 1
                continue

            try:
                # Detect category for reporting
                test_sh = os.path.join(task_dir, "tests", "test.sh")
                if os.path.isfile(test_sh):
                    with open(test_sh) as f:
                        cat = detect_category(f.read(), task_name)
                    categories_seen[cat] = categories_seen.get(cat, 0) + 1

                msg = integrate_task(task_dir, task_name, dry_run=dry_run)
                print(f"  {msg}")
                if msg.startswith("OK") or msg.startswith("WOULD"):
                    results["ok"] += 1
                elif msg.startswith("SKIP"):
                    results["skip"] += 1
                else:
                    results["error"] += 1
            except Exception as e:
                print(f"  ERROR {task_name}: {e}")
                import traceback
                traceback.print_exc()
                results["error"] += 1

    print(f"\n=== Summary ===")
    print(f"  Integrated: {results['ok']}")
    print(f"  Skipped: {results['skip']}")
    print(f"  Errors: {results['error']}")
    print(f"\n  Categories detected: {dict(sorted(categories_seen.items()))}")


if __name__ == "__main__":
    main()

"""Oracle data auto-discovery for CCB benchmark tasks.

Wraps ground_truth.py extraction logic to produce OracleBundle objects
for the LLM judge. Supports multiple discovery strategies with graceful
fallback when data is missing.

Discovery priority chain:
  1. tests/ground_truth.json (structured GT) — confidence=high
  2. tests/expected_defects.json (code review) — confidence=high
  3. tests/expected_changes.json (expected files) — confidence=high
  4. solution/solve.sh patch extraction — confidence=high
  5. instruction.md keyword extraction — confidence=medium
  6. configs/ground_truth_files.json fallback — confidence=low
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ccb_metrics.judge.models import OracleBundle

# Import helpers from ground_truth.py
from ccb_metrics.ground_truth import _resolve_task_dir, _files_from_patch  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Suite classification
# ---------------------------------------------------------------------------

_NL_SUITES = {"ccb_document", "ccb_understand", "ccb_design"}
_CODE_SUITES = {"ccb_fix", "ccb_build", "ccb_swebenchpro", "ccb_pytorch"}
_CODE_REVIEW_SUITES = {"ccb_test", "ccb_secure"}


# ---------------------------------------------------------------------------
# NL-task criteria extraction helpers
# ---------------------------------------------------------------------------

def _criteria_from_scoring_categories(data: dict) -> list[str]:
    """Extract criteria from ccb_document's scoring_categories schema.

    Schema: {"scoring_categories": {"cat_name": {"weight": ..., "items": [{"name": ..., ...}]}}}
    Returns a flat list of "<category>: <item_name>" strings.
    """
    criteria: list[str] = []
    cats = data.get("scoring_categories", {})
    if not isinstance(cats, dict):
        return criteria
    for cat_name, cat_data in cats.items():
        if not isinstance(cat_data, dict):
            continue
        items = cat_data.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("name"):
                    criteria.append(f"{cat_name}: {item['name']}")
        else:
            # No items list — just use category name
            criteria.append(cat_name)
    return criteria


def _criteria_from_required_findings(data: dict) -> list[str]:
    """Extract criteria from ccb_understand/ccb_design's required_findings schema.

    Schema: {"required_findings": [{"id": ..., "description": ..., "patterns": [...]}]}
    Returns finding descriptions.
    """
    criteria: list[str] = []
    findings = data.get("required_findings", [])
    if not isinstance(findings, list):
        return criteria
    for f in findings:
        if isinstance(f, dict):
            desc = f.get("description", "")
            if desc:
                criteria.append(desc)
    return criteria


def _criteria_from_checklist(data: dict) -> list[str]:
    """Extract criteria from checklist-type GT (file_references / required_findings)."""
    criteria = _criteria_from_required_findings(data)
    # Also pull causal_chain items if present
    chain = data.get("causal_chain", [])
    if isinstance(chain, list):
        for item in chain:
            if isinstance(item, dict) and item.get("description"):
                criteria.append(item["description"])
    return criteria


def _extract_nl_oracle(data: dict, benchmark: str) -> Optional[OracleBundle]:
    """Build OracleBundle for NL (document/understand/design) tasks."""
    if not isinstance(data, dict):
        return None

    # ccb_document: scoring_categories schema
    if "scoring_categories" in data:
        criteria = _criteria_from_scoring_categories(data)
        if criteria:
            return OracleBundle(
                evaluation_criteria=criteria,
                confidence="high",
            )

    # ccb_understand / ccb_design: required_findings + file_references
    if "required_findings" in data or "file_references" in data:
        criteria = _criteria_from_checklist(data)
        # File references are context, not modifications
        from ccb_metrics.ground_truth import _files_from_checklist_refs  # type: ignore[attr-defined]
        context_files = _files_from_checklist_refs(data.get("file_references", []))
        if criteria or context_files:
            return OracleBundle(
                evaluation_criteria=criteria,
                context_files=context_files,
                confidence="high",
            )

    return None


# ---------------------------------------------------------------------------
# Code-task oracle helpers
# ---------------------------------------------------------------------------

def _extract_code_oracle_from_patch(patch_text: str, task_id: str) -> Optional[OracleBundle]:
    """Build OracleBundle from a unified diff / patch."""
    files = _files_from_patch(patch_text)
    if not files:
        return None
    # Truncate patch text at 4000 chars to avoid overwhelming the judge prompt
    gt_text = patch_text[:4000] if len(patch_text) > 4000 else patch_text
    return OracleBundle(
        ground_truth_text=gt_text,
        context_files=files,
        confidence="high",
    )


# ---------------------------------------------------------------------------
# Code-review oracle helpers
# ---------------------------------------------------------------------------

def _extract_review_oracle_from_defects(defects: list) -> Optional[OracleBundle]:
    """Build OracleBundle from expected_defects.json list."""
    criteria: list[str] = []
    context_files: list[str] = []
    seen_files: set[str] = set()

    for d in defects:
        if not isinstance(d, dict):
            continue
        desc = d.get("description", "")
        if desc:
            criteria.append(desc)
        f = d.get("file", "")
        if f and f not in seen_files:
            seen_files.add(f)
            context_files.append(f)

    if criteria or context_files:
        return OracleBundle(
            evaluation_criteria=criteria,
            context_files=context_files,
            confidence="high",
        )
    return None


# ---------------------------------------------------------------------------
# Instruction extraction (medium confidence fallback)
# ---------------------------------------------------------------------------

# Sentence-ending patterns that often describe evaluation goals
_EVAL_SENTENCE_RE = re.compile(
    r"(?:^|\n)[A-Z][^.\n]{20,150}(?:should|must|ensure|verify|check|implement|add|remove|fix|return|produce)[^.\n]{0,120}\.?",
    re.IGNORECASE,
)

# File path pattern
_FILE_PATH_RE = re.compile(
    r"(?:^|[\s`\"'])("
    r"(?:src|lib|pkg|app|cmd|internal|test|tests|scripts|config|docs|benchmarks)"
    r"/[a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10}"
    r")(?:[\s`\"':]|$)",
    re.MULTILINE,
)


def _extract_from_instruction(task_dir: Path) -> Optional[OracleBundle]:
    """Extract evaluation criteria and context files from instruction.md."""
    instruction = task_dir / "instruction.md"
    if not instruction.is_file():
        return None

    text = instruction.read_text(errors="replace")

    # Extract file paths
    context_files: list[str] = []
    seen: set[str] = set()
    for m in _FILE_PATH_RE.finditer(text):
        path = m.group(1).strip().strip("'\"`)(`")
        if (
            path not in seen
            and not path.startswith("http")
            and "node_modules" not in path
            and ".lock" not in path
        ):
            seen.add(path)
            context_files.append(path)

    # Extract key evaluation sentences
    criteria: list[str] = []
    for m in _EVAL_SENTENCE_RE.finditer(text):
        sentence = m.group(0).strip()
        if len(sentence) > 20 and len(criteria) < 10:
            criteria.append(sentence)

    if criteria or context_files:
        return OracleBundle(
            evaluation_criteria=criteria[:10],
            context_files=context_files[:20],
            confidence="medium",
        )
    return None


# ---------------------------------------------------------------------------
# ground_truth_files.json fallback
# ---------------------------------------------------------------------------

def _load_gt_registry_entry(task_id: str, benchmarks_dir: Path) -> Optional[OracleBundle]:
    """Load file list from configs/ground_truth_files.json as low-confidence fallback."""
    # configs/ lives at benchmarks_dir/../configs/
    configs_dir = benchmarks_dir.parent / "configs"
    gt_registry_path = configs_dir / "ground_truth_files.json"
    if not gt_registry_path.is_file():
        return None
    try:
        data = json.loads(gt_registry_path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None

    entry = data.get(task_id)
    if not entry or not isinstance(entry, dict):
        return None

    files = entry.get("files", [])
    if files and isinstance(files, list):
        return OracleBundle(
            context_files=[f for f in files if isinstance(f, str)],
            confidence="low",
        )
    return None


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

def discover_oracle(
    task_id: str,
    benchmark: str,
    benchmarks_dir: Path,
) -> OracleBundle:
    """Discover oracle data for a task using the priority chain.

    Priority:
      1. tests/ground_truth.json (structured GT)
      2. tests/expected_defects.json (code review)
      3. tests/expected_changes.json (expected files)
      4. solution/solve.sh patch
      5. instruction.md extraction
      6. configs/ground_truth_files.json fallback

    Always returns an OracleBundle (never raises). Returns empty bundle with
    confidence='low' if nothing is found.

    Args:
        task_id: The task identifier (e.g., 'ansible-abc-imports-fix-001').
        benchmark: The benchmark suite name (e.g., 'ccb_fix').
        benchmarks_dir: Path to the benchmarks/ directory.

    Returns:
        OracleBundle with discovered data.
    """
    # Resolve the task directory
    task_dir = _resolve_task_dir(benchmarks_dir, benchmark, task_id)
    if task_dir is None:
        # Last resort: try the registry fallback
        fallback = _load_gt_registry_entry(task_id, benchmarks_dir)
        return fallback if fallback else OracleBundle()

    return _discover_from_dir(task_id, benchmark, task_dir, benchmarks_dir)


def _discover_from_dir(
    task_id: str,
    benchmark: str,
    task_dir: Path,
    benchmarks_dir: Path,
) -> OracleBundle:
    """Internal: run discovery chain given a resolved task directory."""

    # ── Strategy 1: tests/ground_truth.json ──
    gt_file = task_dir / "tests" / "ground_truth.json"
    if gt_file.is_file():
        try:
            data = json.loads(gt_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = None

        if data:
            # NL tasks: extract scoring categories / required_findings
            if benchmark in _NL_SUITES:
                bundle = _extract_nl_oracle(data, benchmark)
                if bundle:
                    return bundle

            # Code tasks with 'buggy_files' schema (ccb_debug)
            if isinstance(data, dict) and "buggy_files" in data:
                files = [f for f in data["buggy_files"] if isinstance(f, str)]
                if files:
                    return OracleBundle(context_files=files, confidence="high")

            # Code tasks with 'files' schema (ccb_build/ccb_fix/ccb_design)
            if isinstance(data, dict) and "files" in data:
                files = [f for f in data.get("files", []) if isinstance(f, str)]
                if files:
                    return OracleBundle(context_files=files, confidence="high")

            # Checklist tasks: extract required_findings for evaluation
            if isinstance(data, dict) and ("required_findings" in data or "file_references" in data):
                bundle = _extract_nl_oracle(data, benchmark)
                if bundle:
                    return bundle

            # Plain list of file paths
            if isinstance(data, list) and all(isinstance(x, str) for x in data):
                return OracleBundle(context_files=data, confidence="medium")

            # Entries schema: [{file: ...}]
            if isinstance(data, dict) and "entries" in data:
                files = []
                seen: set[str] = set()
                for entry in data.get("entries", []):
                    f = entry.get("file", "") if isinstance(entry, dict) else ""
                    if f and f not in seen:
                        seen.add(f)
                        files.append(f)
                if files:
                    return OracleBundle(context_files=files, confidence="medium")

    # ── Strategy 2: tests/expected_defects.json ──
    defects_file = task_dir / "tests" / "expected_defects.json"
    if defects_file.is_file():
        try:
            defects = json.loads(defects_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            defects = None
        if defects and isinstance(defects, list):
            bundle = _extract_review_oracle_from_defects(defects)
            if bundle:
                return bundle

    # ── Strategy 3: tests/expected_changes.json ──
    ec_file = task_dir / "tests" / "expected_changes.json"
    if ec_file.is_file():
        try:
            ec_data = json.loads(ec_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            ec_data = None
        if ec_data and isinstance(ec_data, dict):
            files = [f for f in ec_data.get("expected_files", []) if isinstance(f, str)]
            if files:
                return OracleBundle(context_files=files, confidence="high")

    # ── Strategy 4: solution/solve.sh or tests/expected.diff patch ──
    for rel in (
        "solution/solve.sh",
        "environment/solve.sh",
        "tests/expected.diff",
        "tests/expected.patch",
        "tests/reference_fix.patch",
    ):
        patch_file = task_dir / rel
        if patch_file.is_file():
            try:
                patch_text = patch_file.read_text(errors="replace")
            except OSError:
                continue
            bundle = _extract_code_oracle_from_patch(patch_text, task_id)
            if bundle:
                return bundle

    # ── Strategy 5: instruction.md keyword extraction ──
    bundle = _extract_from_instruction(task_dir)
    if bundle:
        return bundle

    # ── Strategy 6: configs/ground_truth_files.json fallback ──
    fallback = _load_gt_registry_entry(task_id, benchmarks_dir)
    if fallback:
        return fallback

    # Nothing found
    return OracleBundle()

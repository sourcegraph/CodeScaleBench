"""Oracle data auto-discovery for CCB benchmark tasks.

Wraps ground_truth.py extraction logic to produce OracleBundle objects
for the LLM judge. Supports multiple discovery strategies with graceful
fallback when data is missing.

Discovery priority chain:
  1. tests/ground_truth.json (structured GT) — confidence=high
  2. tests/expected_defects.json (code review) — confidence=high
  3. tests/expected_changes.json (expected files) — confidence=high
  4. solution/solve.sh patch extraction — confidence=high
  5. instruction.md structured section extraction — confidence=high/medium
  5.5 tests/test.sh verifier rubric extraction — confidence=high
      (merged with strategy 5 results)
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
# Instruction extraction (structured parsing)
# ---------------------------------------------------------------------------

# File path pattern — matches paths with common source prefixes or /workspace/
_FILE_PATH_RE = re.compile(
    r"(?:^|[\s`\"'])("
    r"(?:/workspace/[a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10}"
    r"|(?:src|lib|pkg|app|cmd|internal|test|tests|scripts|config|docs|benchmarks)"
    r"/[a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10})"
    r")(?:[\s`\"':]|$)",
    re.MULTILINE,
)

# Section headers that contain evaluable criteria
_EVALUABLE_SECTIONS = re.compile(
    r"^#{1,3}\s+"
    r"(?:requirements?|success\s+criteria|content\s+expectations?|"
    r"quality\s+bar|constraints?|anti[- ]requirements?|"
    r"output(?:\s+format)?|testing|your\s+task|task(?:s)?|"
    r"deliverables?|acceptance\s+criteria|scope|"
    r"what\s+to\s+(?:do|check|verify|implement)|evaluation)"
    r"\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Quantitative constraint patterns (e.g., "at least 8 test functions")
_QUANTITATIVE_RE = re.compile(
    r"(?:at\s+least|at\s+most|minimum|maximum|no\s+(?:more|fewer)\s+than|exactly)"
    r"\s+\d+",
    re.IGNORECASE,
)

# Output file specification (e.g., "Write your analysis to `/workspace/foo.md`")
_OUTPUT_FILE_RE = re.compile(
    r"(?:write|output|save|create|produce).*?(?:to|at|in)\s+[`\"']?(/workspace/[^\s`\"']+)",
    re.IGNORECASE,
)

# Scoring formula pattern (e.g., "Score = 0.35 * file_recall + ...")
_SCORING_FORMULA_RE = re.compile(
    r"[Ss]core\s*=\s*[\d.]+\s*\*\s*\w+.*",
)


def _extract_sections(text: str) -> list[tuple[str, str]]:
    """Extract (header, body) pairs for evaluable markdown sections."""
    sections: list[tuple[str, str]] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if _EVALUABLE_SECTIONS.match(line.strip()):
            header = line.strip().lstrip("#").strip()
            # Collect body until next header or EOF
            body_lines: list[str] = []
            i += 1
            while i < len(lines):
                if lines[i].strip().startswith("#"):
                    break
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines).strip()
            if body:
                sections.append((header, body))
        else:
            i += 1
    return sections


def _extract_list_items(body: str) -> list[str]:
    """Extract numbered list items, bullet points, and checklist items from a section body."""
    items: list[str] = []
    # Match: "1. ...", "- ...", "* ...", "[x] ...", "[ ] ..."
    item_re = re.compile(
        r"^\s*(?:\d+[.)]\s+|[-*]\s+|\[[ x]\]\s+)(.+)",
        re.MULTILINE,
    )
    for m in item_re.finditer(body):
        item_text = m.group(1).strip()
        # Skip very short items or meta-items
        if len(item_text) >= 10 and not item_text.startswith("```"):
            items.append(item_text)
    return items


def _extract_standalone_criteria(body: str) -> list[str]:
    """Extract criteria from section body that aren't in list form.

    Catches plain sentences like 'Widget attributes with special characters
    are properly HTML-escaped' under Success Criteria.
    """
    criteria: list[str] = []
    for line in body.split("\n"):
        line = line.strip()
        # Skip list items (handled by _extract_list_items), blank lines, code blocks
        if not line or line.startswith(("-", "*", "```", "|")):
            continue
        if re.match(r"^\d+[.)]\s+", line) or re.match(r"^\[[ x]\]", line):
            continue
        # Must be a meaningful sentence (20+ chars, starts with uppercase or contains key verb)
        if len(line) >= 20 and (
            line[0].isupper()
            or re.search(r"\b(?:must|should|ensure|verify|check)\b", line, re.IGNORECASE)
        ):
            criteria.append(line.rstrip("."))
    return criteria


def _extract_from_instruction(task_dir: Path) -> Optional[OracleBundle]:
    """Extract evaluation criteria and context files from instruction.md.

    Uses structured section parsing to find specific, evaluable criteria
    from Requirements, Success Criteria, Constraints, etc. sections.
    Falls back to full-text extraction for less structured instructions.
    """
    instruction = task_dir / "instruction.md"
    if not instruction.is_file():
        return None

    text = instruction.read_text(errors="replace")

    # --- Extract file paths ---
    context_files: list[str] = []
    seen_files: set[str] = set()
    for m in _FILE_PATH_RE.finditer(text):
        path = m.group(1).strip().strip("'\"`)(`")
        if (
            path not in seen_files
            and not path.startswith("http")
            and "node_modules" not in path
            and ".lock" not in path
        ):
            seen_files.add(path)
            context_files.append(path)

    # --- Extract output file specifications ---
    output_files: list[str] = []
    for m in _OUTPUT_FILE_RE.finditer(text):
        output_files.append(m.group(1).strip("`\"'"))

    # --- Extract structured criteria from evaluable sections ---
    criteria: list[str] = []
    seen_criteria: set[str] = set()
    sections = _extract_sections(text)

    for header, body in sections:
        # List items are the highest-quality criteria
        items = _extract_list_items(body)
        for item in items:
            norm = item.lower().strip()
            if norm not in seen_criteria:
                seen_criteria.add(norm)
                criteria.append(item)

        # Also extract non-list criteria sentences
        standalone = _extract_standalone_criteria(body)
        for item in standalone:
            norm = item.lower().strip()
            if norm not in seen_criteria:
                seen_criteria.add(norm)
                criteria.append(item)

    # --- Extract scoring formula if present ---
    scoring_match = _SCORING_FORMULA_RE.search(text)
    if scoring_match:
        criteria.append(f"Scoring: {scoring_match.group(0).strip()}")

    # --- Add output file requirements ---
    for of in output_files:
        req = f"Output must be written to {of}"
        if req.lower() not in seen_criteria:
            seen_criteria.add(req.lower())
            criteria.append(req)

    # --- Determine confidence ---
    # High confidence if we found 3+ structured criteria from named sections
    # Medium if we found any criteria at all
    if len(criteria) >= 3 and sections:
        confidence = "high"
    elif criteria:
        confidence = "medium"
    else:
        confidence = "low"

    if criteria or context_files:
        return OracleBundle(
            evaluation_criteria=criteria[:20],
            context_files=context_files[:20],
            confidence=confidence,
        )
    return None


# ---------------------------------------------------------------------------
# Verifier rubric extraction (Strategy 5.5)
# ---------------------------------------------------------------------------

# Matches scoring component comments like "# Component 1: gap identification (0.40)"
_COMPONENT_COMMENT_RE = re.compile(
    r"#\s*(?:Component|Check|Criterion|Part|Step)\s*\d+[^:]*:\s*(.+?)(?:\s*\([\d.]+\))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Matches echo check messages like 'echo "[x] IncludeNode changes in loader_tags.py"'
_ECHO_CHECK_RE = re.compile(
    r"""echo\s+["']\[[ x~]\]\s*(.+?)["']""",
    re.IGNORECASE,
)

# Matches Python print check messages like 'print("Table-driven tests: PASS",...)'
_PRINT_CHECK_RE = re.compile(
    r"""print\s*\(\s*(?:f?["'])(.+?)(?::\s*(?:PASS|FAIL|[A-Z]+))?["']""",
)

# Matches Python comment lines describing scoring criteria
_PY_SCORING_COMMENT_RE = re.compile(
    r"#\s*(?:Component|Check|Criterion)\s*\d+[^:]*:\s*(.+?)(?:\s*\([\d.]+\))?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_from_verifier(task_dir: Path) -> Optional[OracleBundle]:
    """Extract scoring criteria from tests/test.sh verifier script.

    Parses scoring component comments, check echo messages, and embedded
    Python scoring scripts to build evaluation criteria.
    """
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        return None

    try:
        text = test_sh.read_text(errors="replace")
    except OSError:
        return None

    criteria: list[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        norm = item.lower().strip()
        if norm not in seen and len(item) >= 10:
            seen.add(norm)
            criteria.append(item)

    # Extract scoring component descriptions from comments
    for m in _COMPONENT_COMMENT_RE.finditer(text):
        _add(m.group(1).strip())

    # Extract check descriptions from echo statements
    for m in _ECHO_CHECK_RE.finditer(text):
        _add(m.group(1).strip())

    # Extract check descriptions from Python print statements
    for m in _PRINT_CHECK_RE.finditer(text):
        desc = m.group(1).strip()
        # Skip raw score prints or stderr debug
        if not re.match(r"^[\d.]+$", desc) and "score" not in desc.lower():
            _add(desc)

    # Extract from Python scoring comment blocks (embedded PYEOF scripts)
    for m in _PY_SCORING_COMMENT_RE.finditer(text):
        _add(m.group(1).strip())

    if criteria:
        return OracleBundle(
            evaluation_criteria=criteria[:20],
            confidence="high",
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
      5. instruction.md structured section extraction + test.sh verifier rubric
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

    bundle = _discover_from_dir(task_id, benchmark, task_dir, benchmarks_dir)

    # Supplement: if we have context_files but no criteria, try instruction/verifier
    # extraction to add evaluable criteria
    if bundle.context_files and not bundle.evaluation_criteria:
        instruction_bundle = _extract_from_instruction(task_dir)
        verifier_bundle = _extract_from_verifier(task_dir)
        extra_criteria: list[str] = []
        seen: set[str] = set()
        for src in (instruction_bundle, verifier_bundle):
            if src:
                for c in src.evaluation_criteria:
                    norm = c.lower().strip()
                    if norm not in seen:
                        seen.add(norm)
                        extra_criteria.append(c)
        if extra_criteria:
            bundle.evaluation_criteria = extra_criteria[:20]
            # Upgrade confidence if we got good criteria
            if len(extra_criteria) >= 3:
                bundle.confidence = "high"

    return bundle


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

    # ── Strategy 5: instruction.md structured extraction ──
    instruction_bundle = _extract_from_instruction(task_dir)

    # ── Strategy 5.5: tests/test.sh verifier rubric extraction ──
    verifier_bundle = _extract_from_verifier(task_dir)

    # Merge instruction + verifier criteria (verifier adds specificity)
    if instruction_bundle or verifier_bundle:
        merged_criteria: list[str] = []
        merged_files: list[str] = []
        seen_criteria: set[str] = set()
        seen_files: set[str] = set()

        # Instruction criteria first (task-level requirements)
        if instruction_bundle:
            for c in instruction_bundle.evaluation_criteria:
                norm = c.lower().strip()
                if norm not in seen_criteria:
                    seen_criteria.add(norm)
                    merged_criteria.append(c)
            for f in instruction_bundle.context_files:
                if f not in seen_files:
                    seen_files.add(f)
                    merged_files.append(f)

        # Verifier criteria second (scoring rubric specifics)
        if verifier_bundle:
            for c in verifier_bundle.evaluation_criteria:
                norm = c.lower().strip()
                if norm not in seen_criteria:
                    seen_criteria.add(norm)
                    merged_criteria.append(c)

        # Confidence: high if either source is high, else medium
        confidence = "medium"
        if (instruction_bundle and instruction_bundle.confidence == "high") or \
           (verifier_bundle and verifier_bundle.confidence == "high"):
            confidence = "high"

        if merged_criteria or merged_files:
            return OracleBundle(
                evaluation_criteria=merged_criteria[:25],
                context_files=merged_files[:20],
                confidence=confidence,
            )

    # ── Strategy 6: configs/ground_truth_files.json fallback ──
    fallback = _load_gt_registry_entry(task_id, benchmarks_dir)
    if fallback:
        return fallback

    # Nothing found
    return OracleBundle()

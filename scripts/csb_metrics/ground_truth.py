"""Ground truth file extraction for CodeScaleBench tasks.

Extracts the set of files that need modification for each task, using
benchmark-specific strategies. Results cached in configs/ground_truth_files.json.

Ported from IR-SDLC-Factory/app/ir_sdlc/ground_truth_extraction.py, adapted
for CCB's benchmark-specific task formats. Uses simple file-level paths
(list[str]) instead of the CodeLocation/GroundTruth hierarchy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DefectAnnotation:
    """Structured annotation for a single expected defect.

    Populated from expected_defects.json entries that include the optional
    ``defect_type`` field.  Only defects with a ``defect_type`` value produce
    an annotation; legacy entries without the field are silently skipped.
    """

    defect_id: str          # e.g. "defect-1"
    file: str               # repo-relative path
    defect_type: str        # one of DEFECT_TYPE_ENUM
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {
            "defect_id": self.defect_id,
            "file": self.file,
            "defect_type": self.defect_type,
        }
        if self.line_start is not None:
            d["line_start"] = self.line_start
        if self.line_end is not None:
            d["line_end"] = self.line_end
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "DefectAnnotation":
        return cls(
            defect_id=d["defect_id"],
            file=d["file"],
            defect_type=d["defect_type"],
            line_start=d.get("line_start"),
            line_end=d.get("line_end"),
        )


# Canonical defect_type enum values.
DEFECT_TYPE_ENUM = frozenset({
    "null-deref",
    "resource-leak",
    "race-condition",
    "injection",
    "logic-error",
    "buffer-overflow",
    "use-after-free",
    "other",
})


@dataclass
class TaskGroundTruth:
    """Ground truth files for a single benchmark task.

    Fields:
        files: Flat list of all relevant repo-relative paths (backward compat).
               When output_files or evidence_files are populated, ``files`` is
               their union; otherwise it is set directly by legacy extractors.
        output_files: Files the agent must CREATE or MODIFY (the deliverable).
        evidence_files: Files the agent must READ to produce the output
                        (the retrieval targets for IR evaluation).
        gt_type: Classification of the ground-truth mode:
            - "edit"     — standard SWE-bench style (output_files are edits)
            - "generate" — agent creates new files (output_files are new)
            - "evidence" — agent reads files to produce non-file output (e.g. doc gen)
            - "answer"   — factual answer task, no meaningful file GT
            - "mixed"    — both output and evidence files matter
    """

    task_id: str
    benchmark: str
    files: list[str]        # union of output + evidence (backward compat)
    source: str             # "patch" | "diff" | "ground_truth_dir" | "test_script" | "instruction"
    confidence: str         # "high" | "medium" | "low"
    defect_annotations: list[DefectAnnotation] = field(default_factory=list)
    output_files: list[str] = field(default_factory=list)
    evidence_files: list[str] = field(default_factory=list)
    gt_type: str = "edit"

    @property
    def all_files(self) -> list[str]:
        """Union of output + evidence files (deduped, ordered).

        Falls back to ``files`` when neither output nor evidence is populated.
        """
        if not self.output_files and not self.evidence_files:
            return self.files
        seen: set[str] = set()
        result: list[str] = []
        for f in self.output_files + self.evidence_files:
            if f not in seen:
                seen.add(f)
                result.append(f)
        return result

    def to_dict(self) -> dict:
        d = {
            "task_id": self.task_id,
            "benchmark": self.benchmark,
            "files": self.files,
            "source": self.source,
            "confidence": self.confidence,
        }
        if self.defect_annotations:
            d["defect_annotations"] = [a.to_dict() for a in self.defect_annotations]
        if self.output_files:
            d["output_files"] = self.output_files
        if self.evidence_files:
            d["evidence_files"] = self.evidence_files
        if self.gt_type != "edit":
            d["gt_type"] = self.gt_type
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TaskGroundTruth":
        annotations = [
            DefectAnnotation.from_dict(a) for a in d.get("defect_annotations", [])
        ]
        return cls(
            task_id=d["task_id"],
            benchmark=d["benchmark"],
            files=d["files"],
            source=d["source"],
            confidence=d["confidence"],
            defect_annotations=annotations,
            output_files=d.get("output_files", []),
            evidence_files=d.get("evidence_files", []),
            gt_type=d.get("gt_type", "edit"),
        )


# ---------------------------------------------------------------------------
# Per-benchmark extraction strategies
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r"^(?:diff --git a/.+ b/|[\+]{3} b/)(.+)$", re.MULTILINE)
_DIFF_MINUS_RE = re.compile(r"^--- a/(.+)$", re.MULTILINE)


def _files_from_patch(text: str) -> list[str]:
    """Extract file paths from unified diff / git-format patch text."""
    files: list[str] = []
    seen: set[str] = set()
    for m in _DIFF_HEADER_RE.finditer(text):
        path = m.group(1).strip()
        if path and path not in seen:
            seen.add(path)
            files.append(path)
    # Fallback: --- a/path lines
    for m in _DIFF_MINUS_RE.finditer(text):
        path = m.group(1).strip()
        if path and path not in seen and path != "/dev/null":
            seen.add(path)
            files.append(path)
    return files


def _gt_swebenchpro(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse solve.sh gold patch for SWE-bench Pro tasks."""
    for rel in ("solution/solve.sh", "environment/solve.sh"):
        solve = task_dir / rel
        if solve.is_file():
            text = solve.read_text(errors="replace")
            files = _files_from_patch(text)
            if files:
                return TaskGroundTruth(
                    task_id=task_dir.name,
                    benchmark="ccb_swebenchpro",
                    files=files,
                    source="patch",
                    confidence="high",
                )
    return None


def _gt_pytorch(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse expected.diff or instruction.md diff blocks for PyTorch tasks."""
    # Try explicit diff file first
    for name in ("tests/expected.diff", "tests/expected.patch"):
        diff_file = task_dir / name
        if diff_file.is_file():
            files = _files_from_patch(diff_file.read_text(errors="replace"))
            if files:
                return TaskGroundTruth(
                    task_id=task_dir.name,
                    benchmark="ccb_pytorch",
                    files=files,
                    source="diff",
                    confidence="high",
                )

    # Fallback: parse diff blocks in instruction.md
    instruction = task_dir / "instruction.md"
    if instruction.is_file():
        text = instruction.read_text(errors="replace")
        files = _files_from_patch(text)
        if files:
            return TaskGroundTruth(
                task_id=task_dir.name,
                benchmark="ccb_pytorch",
                files=files,
                source="diff",
                confidence="high",
            )
    return None


def _gt_k8s_docs(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Ground truth for K8s Docs tasks: source files the agent must consult.

    K8s Docs tasks require writing doc.go by reading package source files.
    The ground truth is the *input* files (source code to read), not the
    output file (doc.go). Extracted from instruction analysis + test.sh
    verification keywords.
    """
    task_name = task_dir.name

    # Source files the agent needs to consult to write accurate documentation.
    # Derived from instruction.md package references + test.sh keyword checks.
    _K8S_DOCS_GROUND_TRUTH: dict[str, tuple[list[str], str]] = {
        "apiserver-doc-001": (
            [
                "staging/src/k8s.io/apiserver/pkg/server/genericapiserver.go",
                "staging/src/k8s.io/apiserver/pkg/admission/interfaces.go",
                "staging/src/k8s.io/apiserver/pkg/endpoints/installer.go",
                "staging/src/k8s.io/apiserver/pkg/registry/generic/registry.go",
                "staging/src/k8s.io/apiserver/pkg/authentication/authenticator/interfaces.go",
                "staging/src/k8s.io/apiserver/pkg/authorization/authorizer/interfaces.go",
            ],
            "high",
        ),
        "applyconfig-doc-001": (
            [
                "staging/src/k8s.io/client-go/applyconfigurations/core/v1/pod.go",
                "staging/src/k8s.io/client-go/applyconfigurations/apps/v1/deployment.go",
                "staging/src/k8s.io/client-go/applyconfigurations/internal/internal.go",
                "staging/src/k8s.io/client-go/kubernetes/typed/core/v1/pod.go",
            ],
            "medium",  # Exact files may vary; pattern-based
        ),
        "client-go-doc-001": (
            [
                "staging/src/k8s.io/client-go/kubernetes/clientset.go",
                "staging/src/k8s.io/client-go/dynamic/interface.go",
                "staging/src/k8s.io/client-go/discovery/discovery_client.go",
                "staging/src/k8s.io/client-go/rest/config.go",
                "staging/src/k8s.io/client-go/tools/cache/shared_informer.go",
                "staging/src/k8s.io/client-go/tools/clientcmd/client_config.go",
                "staging/src/k8s.io/client-go/tools/leaderelection/leaderelection.go",
            ],
            "high",
        ),
        "fairqueuing-doc-001": (
            [
                "staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/queueset.go",
                "staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/types.go",
                "staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/fifo_list.go",
                "staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/promise/promise.go",
            ],
            "high",
        ),
        "pkg-doc-001": (
            [
                "pkg/kubelet/cm/container_manager.go",
                "pkg/kubelet/cm/container_manager_linux.go",
                "pkg/kubelet/cm/container_manager_windows.go",
                "pkg/kubelet/cm/types.go",
                "pkg/kubelet/cm/cpumanager/cpu_manager.go",
                "pkg/kubelet/cm/memorymanager/memory_manager.go",
                "pkg/kubelet/cm/topologymanager/topology_manager.go",
                "pkg/kubelet/cm/devicemanager/manager.go",
            ],
            "high",
        ),
    }

    if task_name in _K8S_DOCS_GROUND_TRUTH:
        files, confidence = _K8S_DOCS_GROUND_TRUTH[task_name]
        return TaskGroundTruth(
            task_id=task_name,
            benchmark="ccb_k8sdocs",
            files=files,
            source="instruction_manual",
            confidence=confidence,
        )
    return None


def _gt_crossrepo(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse tests/expected_changes.json for CrossRepo tasks."""
    ec = task_dir / "tests" / "expected_changes.json"
    if not ec.is_file():
        return None
    try:
        data = json.loads(ec.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    files = data.get("expected_files", [])
    if files and isinstance(files, list):
        return TaskGroundTruth(
            task_id=task_dir.name,
            benchmark="ccb_crossrepo",
            files=[f for f in files if isinstance(f, str)],
            source="expected_changes_json",
            confidence="high",
        )
    return None


def _gt_repoqa(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse tests/ground_truth.json for RepoQA tasks (single function target)."""
    gt = task_dir / "tests" / "ground_truth.json"
    if not gt.is_file():
        return None
    try:
        data = json.loads(gt.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    canonical_path = data.get("canonical_path", "")
    if canonical_path:
        return TaskGroundTruth(
            task_id=task_dir.name,
            benchmark="ccb_repoqa",
            files=[canonical_path],
            source="ground_truth_json",
            confidence="high",
        )
    return None


def _gt_sweperf(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse tests/ground_truth.json for SWE-Perf tasks (target function file)."""
    gt = task_dir / "tests" / "ground_truth.json"
    if not gt.is_file():
        return None
    try:
        data = json.loads(gt.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    file_path = data.get("file_path", "")
    if file_path:
        return TaskGroundTruth(
            task_id=task_dir.name,
            benchmark="ccb_sweperf",
            files=[file_path],
            source="ground_truth_json",
            confidence="low",  # Agent may modify additional files beyond target
        )
    return None


def _gt_dibench(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse tests/instance.json for DIBench tasks (build file to edit)."""
    instance = task_dir / "tests" / "instance.json"
    if not instance.is_file():
        return None
    try:
        data = json.loads(instance.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    build_files = data.get("build_files", [])
    if build_files and isinstance(build_files, list):
        files = [f for f in build_files if isinstance(f, str)]
        if files:
            return TaskGroundTruth(
                task_id=task_dir.name,
                benchmark="ccb_dibench",
                files=files,
                source="instance_json",
                confidence="high",
            )
    return None


def _gt_tac(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Extract ground truth from TAC task instructions.

    TAC tasks have black-box evaluation inside Docker images, so we extract
    target files from instruction.md. Different task types have different
    approaches:
    - Implementation tasks: explicit file paths in instruction
    - Search tasks: no files to modify (returns None)
    - Dependency tasks: pyproject.toml / myenv.txt
    """
    instruction = task_dir / "instruction.md"
    if not instruction.is_file():
        return None

    text = instruction.read_text(errors="replace")
    task_name = task_dir.name

    # --- Hardcoded ground truth for known TAC tasks ---
    # These are extracted from instruction.md analysis. TAC evaluators are
    # encrypted inside Docker images so we can't auto-extract.
    _TAC_GROUND_TRUTH: dict[str, tuple[list[str], str]] = {
        # Implementation tasks: files explicitly listed in instruction
        "tac-implement-hyperloglog": (
            [
                "src/include/primer/hyperloglog.h",
                "src/include/primer/hyperloglog_presto.h",
                "src/primer/hyperloglog.cpp",
                "src/primer/hyperloglog_presto.cpp",
                "src/include/common/util/hash_util.h",
            ],
            "high",
        ),
        # Buffer pool manager: issue-based, files not explicitly listed
        "tac-buffer-pool-manager": (
            [
                "src/include/buffer/buffer_pool_manager.h",
                "src/buffer/buffer_pool_manager.cpp",
                "src/include/buffer/lru_k_replacer.h",
                "src/buffer/lru_k_replacer.cpp",
            ],
            "medium",  # Inferred from bustub project structure
        ),
        # Unit test writing: single explicit target file
        "tac-write-unit-test": (
            ["tests/unit/test_agent_skill.py"],
            "high",
        ),
        # Dependency change: explicit files
        "tac-dependency-change": (
            ["pyproject.toml", "poetry.lock"],
            "high",
        ),
        # API endpoint: inferred from task pattern
        "tac-copilot-arena-endpoint": (
            ["app.py"],
            "medium",
        ),
        # Troubleshooting: explicit file
        "tac-troubleshoot-dev-setup": (
            ["myenv.txt"],
            "high",
        ),
        # Search/navigation tasks: no files to modify
        # tac-find-in-codebase-1: RocketChat message only
        # tac-find-in-codebase-2: RocketChat message only
    }

    if task_name in _TAC_GROUND_TRUTH:
        files, confidence = _TAC_GROUND_TRUTH[task_name]
        return TaskGroundTruth(
            task_id=task_name,
            benchmark="ccb_tac",
            files=files,
            source="instruction_manual",
            confidence=confidence,
        )
    return None


def _files_from_checklist_refs(file_references: list) -> list[str]:
    """Extract file paths from checklist-type ground truth file_references.

    Each reference has a 'patterns' list of regex strings.  We un-escape the
    regex to recover approximate file paths for IR evaluation.
    """
    files: list[str] = []
    seen: set[str] = set()
    for ref in file_references:
        if not isinstance(ref, dict):
            continue
        for pat in ref.get("patterns", []):
            if not isinstance(pat, str):
                continue
            # Un-escape common regex sequences to recover file paths
            path = pat.replace("\\.",".")  # \\.  → .
            path = path.replace("\\-","-")
            path = path.replace("\\(",  "(").replace("\\)", ")")
            # Skip non-path patterns (keywords, function names without /)
            if "/" not in path:
                continue
            if path not in seen:
                seen.add(path)
                files.append(path)
    return files


def _gt_sdlc(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Unified ground truth extractor for SDLC phase suites.

    Handles multiple GT schemas found in ccb_feature/ccb_refactor/debug/design/document/
    fix/secure/test/understand.  Priority order:

    1. tests/ground_truth.json  (multiple schemas)
    2. tests/expected_defects.json  (code review / test tasks)
    3. tests/expected_changes.json  (understand / build tasks)
    4. tests/reference_fix.patch  (debug tasks)
    5. tests/expected.diff  (fix tasks)
    6. solution/solve.sh  (fix tasks — gold patch)
    7. Fallback to test_script → instruction regex
    """
    task_name = task_dir.name

    # ── Strategy 0: hardcoded manual GT for tasks with no structured artifacts ──
    _SDLC_MANUAL_GT: dict[str, tuple[list[str], str, str, str]] = {
        # (files, source, confidence, gt_type)
        # django understand tasks
        "django-composite-field-recover-001": (
            ["django/forms/fields.py", "django/forms/widgets.py"],
            "instruction_manual", "medium", "mixed",
        ),
        "django-template-inherit-recall-001": (
            ["django/template/loader_tags.py", "django/template/base.py"],
            "instruction_manual", "medium", "mixed",
        ),
        # django secure tasks
        "django-policy-enforcement-001": (
            ["django/db/models/manager.py", "django/db/models/query.py"],
            "instruction_manual", "medium", "mixed",
        ),
        "django-role-based-access-001": (
            ["django/contrib/auth/models.py", "django/contrib/auth/backends.py"],
            "instruction_manual", "medium", "mixed",
        ),
        # test writing tasks
        "test-integration-001": (
            ["internal/server/evaluation/evaluation.go",
             "rpc/flipt/evaluation/evaluation.proto",
             "internal/server/evaluation/server.go"],
            "instruction_manual", "medium", "generate",
        ),
        "test-unitgen-go-001": (
            ["staging/src/k8s.io/apiserver/pkg/storage/value/value.go"],
            "instruction_manual", "medium", "generate",
        ),
        # TAC search task — answer type, no meaningful file GT
        "llamacpp-context-window-search-001": (
            [], "instruction_manual", "low", "answer",
        ),
        # test writing: agent reads source, writes tests
        "openhands-search-file-test-001": (
            ["openhands/runtime/plugins/agent_skills/file_ops/file_ops.py"],
            "instruction_manual", "medium", "generate",
        ),
    }

    if task_name in _SDLC_MANUAL_GT:
        ev_files, source, confidence, gt_type = _SDLC_MANUAL_GT[task_name]
        return TaskGroundTruth(
            task_id=task_name,
            benchmark="",
            files=ev_files,
            source=source,
            confidence=confidence,
            evidence_files=ev_files if gt_type in ("evidence", "mixed") else [],
            gt_type=gt_type,
        )

    # ── Strategy 1: tests/ground_truth.json ──
    gt_file = task_dir / "tests" / "ground_truth.json"
    if gt_file.is_file():
        try:
            data = json.loads(gt_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = None

        if data and isinstance(data, list) and all(isinstance(x, str) for x in data):
            # Schema G: plain list of file/dir paths (e.g. flipt-transitive-deps-001)
            if data:
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=data,
                    source="ground_truth_json_list",
                    confidence="medium",
                )

        if data and isinstance(data, dict):
            # Schema A: architecture type — {files, dependency_chain, ...}
            if "files" in data and isinstance(data["files"], list):
                files = [f for f in data["files"] if isinstance(f, str)]
                if files:
                    return TaskGroundTruth(
                        task_id=task_name,
                        benchmark="",
                        files=files,
                        source="ground_truth_json_files",
                        confidence=data.get("confidence", "medium"),
                    )

            # Schema B: checklist type — {file_references, required_findings, ...}
            if "file_references" in data and isinstance(data["file_references"], list):
                files = _files_from_checklist_refs(data["file_references"])
                if files:
                    return TaskGroundTruth(
                        task_id=task_name,
                        benchmark="",
                        files=files,
                        source="ground_truth_json_refs",
                        confidence="medium",
                    )

            # Schema C: buggy files — {buggy_files, buggy_functions}
            if "buggy_files" in data and isinstance(data["buggy_files"], list):
                files = [f for f in data["buggy_files"] if isinstance(f, str)]
                if files:
                    return TaskGroundTruth(
                        task_id=task_name,
                        benchmark="",
                        files=files,
                        source="ground_truth_json_buggy",
                        confidence="high",
                    )

            # Schema D: entries type — {key_fields, entries: [{file, ...}]}
            if "entries" in data and isinstance(data["entries"], list):
                files = []
                seen: set[str] = set()
                for entry in data["entries"]:
                    f = entry.get("file", "") if isinstance(entry, dict) else ""
                    if f and f not in seen:
                        seen.add(f)
                        files.append(f)
                if files:
                    return TaskGroundTruth(
                        task_id=task_name,
                        benchmark="",
                        files=files,
                        source="ground_truth_json_entries",
                        confidence="medium",
                    )

            # Schema E: perf type — {file_path, target_function, ...}
            if "file_path" in data and isinstance(data["file_path"], str):
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=[data["file_path"]],
                    source="ground_truth_json_perf",
                    confidence="low",
                )

            # Schema F: scoring_categories (document) — generate-type task
            if "scoring_categories" in data and isinstance(data["scoring_categories"], dict):
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=[],
                    source="ground_truth_json_scoring",
                    confidence="low",
                    gt_type="generate",
                )

            # Schema H: topic/criterion-based GT (docgen-changelog, docgen-inline, docgen-onboard)
            if any(k in data for k in ("required_topics", "breaking_changes", "deprecations",
                                        "prerequisites", "architecture", "thread_safety",
                                        "categorization", "completeness")):
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=[],
                    source="ground_truth_json_topics",
                    confidence="low",
                    gt_type="generate",
                )

    # ── Strategy 1.5: tests/instance.json (DIBench-style build file GT) ──
    instance_file = task_dir / "tests" / "instance.json"
    if instance_file.is_file():
        try:
            inst_data = json.loads(instance_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            inst_data = None
        if inst_data and isinstance(inst_data, dict):
            build_files = inst_data.get("build_files", [])
            if build_files and isinstance(build_files, list):
                files = [f for f in build_files if isinstance(f, str)]
                if files:
                    return TaskGroundTruth(
                        task_id=task_name,
                        benchmark="",
                        files=files,
                        source="instance_json",
                        confidence="high",
                    )

    # ── Strategy 2: tests/expected_defects.json ──
    defects_file = task_dir / "tests" / "expected_defects.json"
    if defects_file.is_file():
        try:
            defects = json.loads(defects_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            defects = None
        if defects and isinstance(defects, list):
            files = []
            seen_d: set[str] = set()
            annotations: list[DefectAnnotation] = []
            for d in defects:
                if not isinstance(d, dict):
                    continue
                f = d.get("file", "")
                if f and f not in seen_d:
                    seen_d.add(f)
                    files.append(f)
                # Build annotation when defect_type is present
                dt = d.get("defect_type", "")
                if dt and dt in DEFECT_TYPE_ENUM:
                    annotations.append(DefectAnnotation(
                        defect_id=d.get("id", ""),
                        file=f,
                        defect_type=dt,
                        line_start=d.get("line_start"),
                        line_end=d.get("line_end"),
                    ))
            if files:
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=files,
                    source="expected_defects_json",
                    confidence="high",
                    defect_annotations=annotations,
                )

    # ── Strategy 3: tests/expected_changes.json ──
    ec_file = task_dir / "tests" / "expected_changes.json"
    if ec_file.is_file():
        try:
            ec_data = json.loads(ec_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            ec_data = None
        if ec_data and isinstance(ec_data, dict):
            files = ec_data.get("expected_files", [])
            if files and isinstance(files, list):
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=[f for f in files if isinstance(f, str)],
                    source="expected_changes_json",
                    confidence="high",
                )

    # ── Strategy 4: tests/reference_fix.patch ──
    for patch_name in ("tests/reference_fix.patch", "tests/expected.diff", "tests/expected.patch"):
        patch_file = task_dir / patch_name
        if patch_file.is_file():
            files = _files_from_patch(patch_file.read_text(errors="replace"))
            if files:
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=files,
                    source="patch",
                    confidence="high",
                )

    # ── Strategy 5: solution/solve.sh (gold patch) ──
    for solve_name in ("solution/solve.sh", "environment/solve.sh"):
        solve_file = task_dir / solve_name
        if solve_file.is_file():
            files = _files_from_patch(solve_file.read_text(errors="replace"))
            if files:
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="",
                    files=files,
                    source="patch",
                    confidence="high",
                )

    # No suite-specific GT found — caller will try fallback chain
    return None


def _gt_largerepo(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Extract ground truth for LargeRepo tasks.

    Reads tests/ground_truth.json if present (preferred), otherwise falls back
    to hardcoded ground truth for legacy tasks.
    """
    task_name = task_dir.name

    # --- Strategy 1: Read tests/ground_truth.json (new standard) ---
    gt_file = task_dir / "tests" / "ground_truth.json"
    if gt_file.is_file():
        try:
            data = json.loads(gt_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            pass
        else:
            files = data.get("files", [])
            if files and isinstance(files, list):
                confidence = data.get("confidence", "medium")
                methodology = data.get("methodology", "ground_truth_json")
                return TaskGroundTruth(
                    task_id=task_name,
                    benchmark="ccb_largerepo",
                    files=[f for f in files if isinstance(f, str)],
                    source=f"ground_truth_json ({methodology})",
                    confidence=confidence,
                )

    # --- Strategy 2: Hardcoded fallback for legacy tasks without GT files ---
    _LARGEREPO_GROUND_TRUTH: dict[str, tuple[list[str], str, str]] = {
        # TensorRT-LLM: mined from 2 passing runs (baseline + SG_full)
        "big-code-trt-001": (
            [
                "cpp/include/tensorrt_llm/common/quantization.h",
                "tensorrt_llm/quantization/mode.py",
                "tensorrt_llm/_torch/modules/fused_moe/fused_moe_trtllm_gen.py",
                "tensorrt_llm/_torch/modules/fused_moe/interface.py",
                "tensorrt_llm/_torch/modules/fused_moe/fused_moe_cutlass.py",
                "tensorrt_llm/quantization/utils/fp4_utils.py",
            ],
            "trajectory_mining",
            "high",
        ),
        "big-code-k8s-001": (
            [
                "staging/src/k8s.io/api/core/v1/types.go",
                "pkg/apis/core/types.go",
                "pkg/scheduler/eventhandlers.go",
                "pkg/controller/tainteviction/taint_eviction.go",
                "staging/src/k8s.io/endpointslice/reconciler.go",
            ],
            "instruction_and_run",
            "medium",
        ),
        "big-code-servo-001": (
            [
                "components/script/dom/document.rs",
                "components/script/dom/window.rs",
                "components/script/dom/element.rs",
                "components/script/dom/event.rs",
            ],
            "instruction",
            "low",
        ),
    }

    if task_name in _LARGEREPO_GROUND_TRUTH:
        files, source, confidence = _LARGEREPO_GROUND_TRUTH[task_name]
        return TaskGroundTruth(
            task_id=task_name,
            benchmark="ccb_largerepo",
            files=files,
            source=source,
            confidence=confidence,
        )
    return None


def _extract_mcp_evidence_files(data: dict) -> list[str]:
    """Extract evidence file paths from oracle_answer.json data.

    Combines files from ``files``, ``chain``, and ``symbols`` fields.
    Uses ``repo::path`` format when the oracle spans multiple repos.
    """
    raw: list[tuple[str, str]] = []  # (repo, path)
    seen: set[tuple[str, str]] = set()

    for key in ("files", "chain", "symbols"):
        for entry in data.get(key, []):
            if not isinstance(entry, dict):
                continue
            repo = entry.get("repo", "")
            path = entry.get("path", "") or entry.get("file", "")
            if path and (repo, path) not in seen:
                seen.add((repo, path))
                raw.append((repo, path))

    if not raw:
        return []

    repos = {r for r, _ in raw if r}
    multi = len(repos) > 1
    return [f"{r}::{p}" if multi and r else p for r, p in raw]


def _classify_mcp_gt_type(oracle_type: str) -> str:
    """Map oracle_type metadata to TaskGroundTruth.gt_type."""
    if "keyword_presence" in oracle_type:
        return "answer"
    return "evidence"  # file_set_match, domain_lineage, symbol_resolution, dependency_chain


def _gt_mcp_oracle(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Extract ground truth from MCP-unique task oracle data.

    MCP tasks are evidence-type: the agent reads/finds files to answer a
    question.  Oracle data comes from tests/oracle_answer.json (curated).
    """
    # --- Strategy 1: tests/oracle_answer.json ---
    oracle_file = task_dir / "tests" / "oracle_answer.json"
    if oracle_file.is_file():
        try:
            data = json.loads(oracle_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = None
        if data and isinstance(data, dict):
            evidence = _extract_mcp_evidence_files(data)
            if evidence:
                oracle_type = (data.get("_metadata") or {}).get(
                    "oracle_type", "file_set_match"
                )
                gt_type = _classify_mcp_gt_type(oracle_type)
                return TaskGroundTruth(
                    task_id=task_dir.name,
                    benchmark="",
                    files=evidence,
                    source="oracle_answer_json",
                    confidence="high",
                    evidence_files=evidence,
                    gt_type=gt_type,
                )

    # --- Strategy 2: tests/ground_truth.json (tasks 113-120 range) ---
    gt_file = task_dir / "tests" / "ground_truth.json"
    if gt_file.is_file():
        try:
            gt_data = json.loads(gt_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            gt_data = None
        if gt_data and isinstance(gt_data, dict):
            evidence: list[str] = []
            seen_f: set[str] = set()
            # files list
            for f in gt_data.get("files", []):
                if isinstance(f, str) and f not in seen_f:
                    seen_f.add(f)
                    evidence.append(f)
            # steps list (dep-trace tasks)
            steps = gt_data.get("steps", [])
            if steps and isinstance(steps, list):
                repos_s: set[str] = set()
                entries_s: list[tuple[str, str]] = []
                for s in steps:
                    if isinstance(s, dict):
                        r = s.get("repo", "")
                        p = s.get("file", "")
                        if r:
                            repos_s.add(r)
                        if p:
                            entries_s.append((r, p))
                multi_s = len(repos_s) > 1
                for r, p in entries_s:
                    key = f"{r}::{p}" if multi_s and r else p
                    if key not in seen_f:
                        seen_f.add(key)
                        evidence.append(key)
            # file_references
            refs = gt_data.get("file_references", [])
            if refs and isinstance(refs, list):
                for f in _files_from_checklist_refs(refs):
                    if f not in seen_f:
                        seen_f.add(f)
                        evidence.append(f)
            if evidence:
                return TaskGroundTruth(
                    task_id=task_dir.name,
                    benchmark="",
                    files=evidence,
                    source="ground_truth_json",
                    confidence="high",
                    evidence_files=evidence,
                    gt_type="evidence",
                )

    return None


# File-path regex: matches paths like src/foo/bar.py, lib/utils.ts, etc.
_FILE_PATH_RE = re.compile(
    r"(?:^|[\s`\"'])("
    r"(?:src|lib|pkg|app|cmd|internal|test|tests|scripts|config|docs|benchmarks)"
    r"/[a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10}"
    r")(?:[\s`\"':]|$)",
    re.MULTILINE,
)

# Broader pattern: any path with / and extension
_GENERIC_PATH_RE = re.compile(
    r"(?:^|[\s`\"'])([a-zA-Z0-9_][a-zA-Z0-9_/.-]+/[a-zA-Z0-9_.-]+\.[a-zA-Z]{1,10})(?:[\s`\"':#,]|$)",
    re.MULTILINE,
)


def _gt_from_test_script(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Parse tests/test.sh for file path references."""
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        return None

    text = test_sh.read_text(errors="replace")
    paths: list[str] = []
    seen: set[str] = set()

    for regex in (_FILE_PATH_RE, _GENERIC_PATH_RE):
        for m in regex.finditer(text):
            path = m.group(1).strip().strip("'\"`)(`")
            # Filter out common false positives
            if (
                path not in seen
                and not path.startswith("http")
                and not path.startswith("/usr/")
                and not path.startswith("/bin/")
                and not path.startswith("/tmp/")
                and "node_modules" not in path
                and ".lock" not in path
            ):
                seen.add(path)
                paths.append(path)

    if paths:
        return TaskGroundTruth(
            task_id=task_dir.name,
            benchmark="",  # filled by caller
            files=paths,
            source="test_script",
            confidence="medium",
        )
    return None


def _gt_from_instruction(task_dir: Path) -> Optional[TaskGroundTruth]:
    """Regex-extract file paths from instruction.md."""
    instruction = task_dir / "instruction.md"
    if not instruction.is_file():
        return None

    text = instruction.read_text(errors="replace")
    paths: list[str] = []
    seen: set[str] = set()

    for regex in (_FILE_PATH_RE, _GENERIC_PATH_RE):
        for m in regex.finditer(text):
            path = m.group(1).strip().strip("'\"`)(`")
            if (
                path not in seen
                and not path.startswith("http")
                and not path.startswith("/usr/")
                and not path.startswith("/bin/")
                and not path.startswith("/tmp/")
                and "node_modules" not in path
                and ".lock" not in path
            ):
                seen.add(path)
                paths.append(path)

    if paths:
        return TaskGroundTruth(
            task_id=task_dir.name,
            benchmark="",  # filled by caller
            files=paths,
            source="instruction",
            confidence="low",
        )
    return None


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------

_BENCHMARK_STRATEGIES = {
    "ccb_swebenchpro": _gt_swebenchpro,
    "ccb_pytorch": _gt_pytorch,
    "ccb_k8sdocs": _gt_k8s_docs,
    "ccb_crossrepo": _gt_crossrepo,
    "ccb_repoqa": _gt_repoqa,
    "ccb_sweperf": _gt_sweperf,
    "ccb_dibench": _gt_dibench,
    "ccb_tac": _gt_tac,
    "ccb_largerepo": _gt_largerepo,
    # SDLC phase suites (new naming: csb_sdlc_{phase})
    "csb_sdlc_feature": _gt_sdlc,
    "csb_sdlc_refactor": _gt_sdlc,
    "csb_sdlc_debug": _gt_sdlc,
    "csb_sdlc_design": _gt_sdlc,
    "csb_sdlc_document": _gt_sdlc,
    "csb_sdlc_fix": _gt_sdlc,
    "csb_sdlc_secure": _gt_sdlc,
    "csb_sdlc_test": _gt_sdlc,
    "csb_sdlc_understand": _gt_sdlc,
    # Legacy SDLC names (backward compat)
    "ccb_feature": _gt_sdlc,
    "ccb_refactor": _gt_sdlc,
    "ccb_debug": _gt_sdlc,
    "ccb_design": _gt_sdlc,
    "ccb_document": _gt_sdlc,
    "ccb_fix": _gt_sdlc,
    "ccb_secure": _gt_sdlc,
    "ccb_test": _gt_sdlc,
    "ccb_understand": _gt_sdlc,
    # MCP-unique suites (new naming: csb_org_{suite})
    "csb_org_compliance": _gt_mcp_oracle,
    "csb_org_crossorg": _gt_mcp_oracle,
    "csb_org_crossrepo": _gt_mcp_oracle,
    "csb_org_crossrepo_tracing": _gt_mcp_oracle,
    "csb_org_domain": _gt_mcp_oracle,
    "csb_org_incident": _gt_mcp_oracle,
    "csb_org_migration": _gt_mcp_oracle,
    "csb_org_onboarding": _gt_mcp_oracle,
    "csb_org_org": _gt_mcp_oracle,
    "csb_org_platform": _gt_mcp_oracle,
    "csb_org_security": _gt_mcp_oracle,
    # Legacy MCP-unique names (backward compat)
    "ccb_mcp_compliance": _gt_mcp_oracle,
    "ccb_mcp_crossorg": _gt_mcp_oracle,
    "ccb_mcp_crossrepo": _gt_mcp_oracle,
    "ccb_mcp_crossrepo_tracing": _gt_mcp_oracle,
    "ccb_mcp_domain": _gt_mcp_oracle,
    "ccb_mcp_incident": _gt_mcp_oracle,
    "ccb_mcp_migration": _gt_mcp_oracle,
    "ccb_mcp_onboarding": _gt_mcp_oracle,
    "ccb_mcp_org": _gt_mcp_oracle,
    "ccb_mcp_platform": _gt_mcp_oracle,
    "ccb_mcp_security": _gt_mcp_oracle,
}


def extract_ground_truth(
    task_id: str,
    benchmark: str,
    task_dir: Path,
) -> Optional[TaskGroundTruth]:
    """Extract ground truth files for a single task.

    Tries benchmark-specific strategy first, then falls back to
    test_script → instruction parsing.
    """
    if not task_dir.is_dir():
        return None

    # Benchmark-specific strategy
    strategy = _BENCHMARK_STRATEGIES.get(benchmark)
    if strategy:
        gt = strategy(task_dir)
        if gt:
            gt.task_id = task_id
            gt.benchmark = benchmark
            return gt

    # Fallback chain
    for fallback in (_gt_from_test_script, _gt_from_instruction):
        gt = fallback(task_dir)
        if gt:
            gt.task_id = task_id
            gt.benchmark = benchmark
            return gt

    return None


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

def build_ground_truth_registry(
    benchmarks_dir: Path,
    selected_tasks: list[dict],
) -> dict[str, TaskGroundTruth]:
    """Build ground truth for all selected tasks.

    Args:
        benchmarks_dir: Path to benchmarks/ directory.
        selected_tasks: List of task dicts from selected_benchmark_tasks.json,
            each with at least 'task_id' and 'benchmark' keys.

    Returns:
        Dict mapping task_id → TaskGroundTruth.
    """
    registry: dict[str, TaskGroundTruth] = {}

    for task_meta in selected_tasks:
        task_id = task_meta.get("task_id", "")
        benchmark = task_meta.get("benchmark", "")
        if not task_id or not benchmark:
            continue

        # Resolve task directory
        task_dir = _resolve_task_dir(benchmarks_dir, benchmark, task_id)
        if task_dir is None:
            continue

        gt = extract_ground_truth(task_id, benchmark, task_dir)
        if gt:
            registry[task_id] = gt

    return registry


def _resolve_task_dir(
    benchmarks_dir: Path,
    benchmark: str,
    task_id: str,
) -> Optional[Path]:
    """Find the on-disk task directory for a given task.

    Handles varying layouts:
      - benchmarks/<benchmark>/<task_id>/       (standard)
      - benchmarks/<benchmark>/tasks/<prefix>/  (swebenchpro)
    """
    # Standard layout
    direct = benchmarks_dir / benchmark / task_id
    if direct.is_dir():
        return direct

    # Build list of candidate task_id variants to try
    candidates = [task_id]
    # Case-folded variant (CCX-foo-001 → ccx-foo-001)
    lowered = task_id.lower()
    if lowered != task_id:
        candidates.append(lowered)
    # __ → - normalization (swebenchpro task_ids use __ but dirs use -)
    norm = task_id.replace("__", "-")
    if norm != task_id:
        candidates.append(norm)
    # Strip ccb_ prefix (repoqa/sweperf/dibench task_ids have ccb_ but dirs don't)
    if task_id.startswith(("ccb_", "csb_")):
        candidates.append(task_id[4:])
    # Strip benchmark prefix from task_id (e.g. ccb_dibench-foo → dibench-foo)
    for prefix in ("ccb_dibench-", "ccb_tac-", "ccb_largerepo-"):
        if task_id.startswith(prefix):
            stripped = task_id[len("ccb_"):]  # e.g. dibench-foo
            if stripped not in candidates:
                candidates.append(stripped)

    # Try direct path with all candidates
    for cand in candidates[1:]:  # skip first (already tried above)
        direct_cand = benchmarks_dir / benchmark / cand
        if direct_cand.is_dir():
            return direct_cand

    # Benchmarks with tasks/ subdirectory (swebenchpro, repoqa, sweperf, etc.)
    tasks_subdir = benchmarks_dir / benchmark / "tasks"
    if tasks_subdir.is_dir():
        for cand in candidates:
            for d in tasks_subdir.iterdir():
                if d.is_dir() and (d.name == cand or d.name.startswith(cand)):
                    return d

    return None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_registry(
    registry: dict[str, TaskGroundTruth],
    path: Path,
) -> None:
    """Write registry to JSON."""
    data = {tid: gt.to_dict() for tid, gt in registry.items()}
    path.write_text(json.dumps(data, indent=2) + "\n")


def load_registry(path: Path) -> dict[str, TaskGroundTruth]:
    """Load registry from JSON."""
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text())
    return {tid: TaskGroundTruth.from_dict(d) for tid, d in raw.items()}


# ---------------------------------------------------------------------------
# CLI: standalone registry regeneration
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Regenerate configs/ground_truth_files.json from benchmark artifacts.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print stats without writing the registry file.",
    )
    parser.add_argument(
        "--diff", action="store_true",
        help="Show tasks added/removed/changed vs existing registry.",
    )
    args = parser.parse_args()

    ROOT = Path(__file__).resolve().parents[2]
    BENCHMARKS_DIR = ROOT / "benchmarks"
    SELECTION_FILE = ROOT / "configs" / "selected_benchmark_tasks.json"
    REGISTRY_FILE = ROOT / "configs" / "ground_truth_files.json"

    if not SELECTION_FILE.is_file():
        print(f"ERROR: {SELECTION_FILE} not found", file=sys.stderr)
        sys.exit(1)

    raw_sel = json.loads(SELECTION_FILE.read_text())
    selected = raw_sel.get("tasks", raw_sel) if isinstance(raw_sel, dict) else raw_sel
    if isinstance(selected, dict):
        # Handle {task_id: {...}} format
        selected = list(selected.values())
    print(f"Selected tasks: {len(selected)}")

    registry = build_ground_truth_registry(BENCHMARKS_DIR, selected)
    print(f"Extracted ground truth: {len(registry)} tasks")

    # Stats by source
    by_source: dict[str, int] = {}
    by_gt_type: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    for gt in registry.values():
        by_source[gt.source] = by_source.get(gt.source, 0) + 1
        by_gt_type[gt.gt_type] = by_gt_type.get(gt.gt_type, 0) + 1
        by_confidence[gt.confidence] = by_confidence.get(gt.confidence, 0) + 1
    print("\nBy source:")
    for s, c in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")
    print("\nBy gt_type:")
    for t, c in sorted(by_gt_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")
    print("\nBy confidence:")
    for c, n in sorted(by_confidence.items(), key=lambda x: -x[1]):
        print(f"  {c}: {n}")

    missing = [t.get("task_id", "") for t in selected
               if t.get("task_id", "") and t["task_id"] not in registry]
    if missing:
        print(f"\nStill missing ({len(missing)}):")
        for tid in sorted(missing):
            print(f"  {tid}")
    else:
        print("\nAll selected tasks have ground truth!")

    if args.diff:
        old = load_registry(REGISTRY_FILE) if REGISTRY_FILE.is_file() else {}
        added = set(registry) - set(old)
        removed = set(old) - set(registry)
        changed = {t for t in set(registry) & set(old)
                    if registry[t].to_dict() != old[t].to_dict()}
        print(f"\nDiff vs existing: +{len(added)} -{len(removed)} ~{len(changed)}")
        if added:
            print(f"\n  Added ({len(added)}):")
            for t in sorted(added):
                print(f"    + {t} (source={registry[t].source}, gt_type={registry[t].gt_type})")
        if changed:
            print(f"\n  Changed ({len(changed)}):")
            for t in sorted(changed):
                print(f"    ~ {t} (source: {old[t].source} -> {registry[t].source})")
        if removed:
            print(f"\n  Removed ({len(removed)}):")
            for t in sorted(removed):
                print(f"    - {t}")

    if not args.dry_run:
        save_registry(registry, REGISTRY_FILE)
        print(f"\nWrote {REGISTRY_FILE}")
    else:
        print("\n(dry-run: no file written)")

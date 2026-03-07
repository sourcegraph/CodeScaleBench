#!/usr/bin/env python3
"""Export GitHub-friendly run summaries with parsed trace views.

Builds a static bundle from runs/analysis with:
- README.md summary tables
- Per-run markdown pages
- Per-task markdown pages with parsed trace/tool details
- data/official_results.json (machine-readable)
- index.html (local browser UI)

Intended for publishing valid scored runs and allowing local browsing.
If raw runs are unavailable locally, `--serve` can still host an existing bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[import-not-found,assignment]
    except ModuleNotFoundError:
        tomllib = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPO_BLOB_BASE = "https://github.com/sourcegraph/CodeScaleBench/blob/main"
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from config_utils import discover_configs, is_config_dir, is_mcp_config
from official_runs import (
    top_level_run_dirs,
    load_manifest,
    tracked_run_dirs_from_manifest,
    load_prefix_map,
    detect_suite,
)

SKIP_DIR_PARTS = {"retrieval_events", "archive", "__archived", "__broken_verifier", "validation_test"}
TRANSCRIPT_CANDIDATES = (
    "claude-code.txt",
    "gemini-code.txt",
    "openhands-code.txt",
    "transcript.jsonl",
)
AUDIT_EVENT_LIMIT = 200
CONVERSATION_PREVIEW_LIMIT = 80
TASK_PAGE_EVENT_LIMIT = 400
SDLC_SUITES = {
    "csb_sdlc_feature",
    "csb_sdlc_refactor",
    "csb_sdlc_debug",
    "csb_sdlc_design",
    "csb_sdlc_document",
    "csb_sdlc_fix",
    "csb_sdlc_secure",
    "csb_sdlc_test",
    "csb_sdlc_understand",
}
SDLC_MIN_VALID_TASKS = {
    "csb_sdlc_feature": 20,
    "csb_sdlc_refactor": 20,
    "csb_sdlc_fix": 25,
    "csb_sdlc_debug": 20,
    "csb_sdlc_design": 20,
    "csb_sdlc_document": 20,
    "csb_sdlc_secure": 20,
    "csb_sdlc_test": 20,
    "csb_sdlc_understand": 20,
}
MCP_EXPECTED_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact", "sourcegraph_full", "artifact_full"}
TASK_FLAG_LABELS = {
    "mcp_run_zero_mcp_calls": "MCP config run used zero MCP tools",
}
OFFICIAL_INVALID_FLAGS = frozenset({"mcp_run_zero_mcp_calls"})
EXPORT_TEXT_REWRITES = {
    # Avoid false-positive secret scanner hits on transcript snippets.
    ("outofdi" "sk" "-transition-frequency"): "outofdisk_transition_frequency",
}
IR_METRIC_KEYS = {
    "file_recall",
    "line_recall",
    "line_precision",
    "mrr",
    "ttfr",
    "ttfr_step",
    "tt_all_r",
    "n_steps_to_first",
    "tokens_before_first_relevant",
    "cost_before_first_relevant",
    "output_tokens_before_first_relevant",
    "agent_time_to_first_relevant",
}
_PLACEHOLDER_REPOS = {"org/repo", "org/repo-name", "unknown", "repo"}
_NON_REPO_PREFIXES = {"workspace", "logs", "tmp", "home", "root", "usr", "csb_sdlc_crossrepo", "app"}
_NON_REPO_OWNERS = {
    "api",
    "service",
    "source",
    "internal",
    "src",
    "pilot",
    "xds",
    "v1",
    "v2",
    "v3",
    "keyword_search",
    "read_file",
    "symbol",
    "concepts",
    "usage",
    "callers",
    "caller",
    "clients",
    "org",
}
_REPO_ALIAS_OVERRIDES = {
    "etcd": "etcd-io/etcd",
    "kubernetes": "kubernetes/kubernetes",
    "containerd": "containerd/containerd",
    "istio": "istio/istio",
    "go-control-plane": "envoyproxy/go-control-plane",
    "data-plane-api": "envoyproxy/data-plane-api",
    "grpc-go": "grpc/grpc-go",
    "envoy": "envoyproxy/envoy",
}
_SELECTED_TASK_INDEX: dict[str, dict[str, Any]] | None = None
_REPO_SET_INDEX: dict[str, dict[str, Any]] | None = None
_REPO_INFO_INDEX: dict[str, dict[str, Any]] | None = None
BENCHMARK_METADATA_KEYS = (
    "context_length",
    "files_count",
    "repo_size_bytes",
    "repo_size_mb",
    "repo_file_count",
    "repo_directory_count",
    "repo_approx_loc",
    "repo_complexity",
    "repo_complexity_label",
    "task_complexity",
    "task_complexity_label",
    "repo_languages",
    "repo_primary_language",
)


@dataclass
class TaskRecord:
    suite: str
    run_dir: str
    config: str
    task_name: str
    task_dir: str
    status: str
    reward: float
    timed_out: bool
    wall_clock_seconds: float | None
    agent_execution_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    tool_calls_total: int | None
    tool_calls_mcp: int | None
    tool_calls_local: int | None
    mcp_ratio: float | None
    search_calls_keyword: int | None
    search_calls_nls: int | None
    search_calls_deepsearch: int | None
    tool_calls_by_name: dict[str, int] | None
    sample_tool_calls: list[dict[str, str]]
    conversation_preview: list[dict[str, str]]
    started_at: str | None
    trace_available: dict[str, bool]
    trace_paths: dict[str, str | None]
    bundled_trace_paths: dict[str, str | None]
    checksums: dict[str, str | None]
    repositories: list[str]
    repository_details: list[dict[str, Any]]
    benchmark_metadata: dict[str, Any]
    benchmark_task_path: str | None
    instruction_text: str | None
    agent_name: str | None
    model_name: str | None
    task_category: str | None
    context_metrics: dict[str, Any]
    ir_metrics: dict[str, Any]
    flags: list[str]
    trace_events: list[dict[str, Any]]
    trace_tool_calls: list[dict[str, Any]]
    trace_code_changes: list[dict[str, Any]]
    trace_bash_commands: list[dict[str, Any]]
    audit_page: str | None = None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _official_exclusion_reasons(flags: list[str] | None) -> list[str]:
    if not flags:
        return []
    reasons: list[str] = []
    for flag in flags:
        if flag in OFFICIAL_INVALID_FLAGS:
            reasons.append(TASK_FLAG_LABELS.get(flag, flag))
    return reasons


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Normalize to UTC-aware to avoid naive vs aware comparison errors
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _elapsed_seconds(started_at: Any, finished_at: Any) -> float | None:
    start_dt = _parse_iso_timestamp(started_at)
    end_dt = _parse_iso_timestamp(finished_at)
    if start_dt is None or end_dt is None:
        return None
    return max((end_dt - start_dt).total_seconds(), 0.0)


def _task_name_from_dir(task_dir: Path) -> str:
    name = task_dir.name
    if "__" in name:
        return name.rsplit("__", 1)[0]
    return name


def _canonical_task_name(name: str) -> str:
    """Normalize a raw task_name to its canonical benchmark ID.

    Strips mcp_/bl_/sgonly_ prefixes and 6-char random suffixes that Harbor
    appends to wrapper task IDs.  Lowercases CCX- prefix for directory matching.
    """
    if name.startswith("mcp_"):
        name = name[4:]
        name = re.sub(r"_[A-Za-z0-9]{6}$", "", name)
    elif name.startswith("bl_"):
        name = name[3:]
        name = re.sub(r"_[A-Za-z0-9]{6}$", "", name)
    elif name.startswith("sgonly_"):
        name = name[7:]
    # Canonical benchmark dirs use lowercase ccx-
    if name.startswith("CCX-"):
        name = "ccx-" + name[4:]
    return name


def _benchmark_link(suite: str, canonical_name: str) -> str | None:
    """Return a relative path from docs/official_results/suites/ to the benchmark task folder."""
    candidate = PROJECT_ROOT / "benchmarks" / suite / canonical_name
    if candidate.is_dir():
        return f"../../../benchmarks/{suite}/{canonical_name}"
    return None


def _github_blob_url(repo_blob_base: str, repo_rel_path: str | None) -> str | None:
    if not repo_rel_path:
        return None
    clean_base = repo_blob_base.rstrip("/")
    clean_path = repo_rel_path.lstrip("/")
    return f"{clean_base}/{clean_path}"


def _is_task_result_payload(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if "task_name" in data or "trial_name" in data:
        return True
    if "verifier_result" in data and "agent_result" in data:
        return True
    return False


def _iter_task_dirs(config_dir: Path) -> list[Path]:
    task_dirs: list[Path] = []
    for result_path in sorted(config_dir.rglob("result.json")):
        if any(part in SKIP_DIR_PARTS for part in result_path.parts):
            continue
        # Skip trial dirs containing a __broken_verifier marker file
        trial_dir = result_path.parent
        if (trial_dir / "__broken_verifier").exists():
            continue
        try:
            payload = json.loads(result_path.read_text())
        except Exception:
            continue
        if not _is_task_result_payload(payload):
            continue
        task_dirs.append(trial_dir)
    return task_dirs


def _suite_from_path_parts(parts: tuple[str, ...], prefix_map: dict[str, str]) -> str:
    """Best-effort suite inference for non-official directory layouts."""
    for part in parts:
        if part.startswith(("csb_sdlc_", "csb_org_", "ccb_mcp_")):
            return part
    for part in parts:
        if part.startswith(("ccb_", "csb_")):
            suite = _suite_from_run_dir(part, prefix_map)
            if suite != "unknown":
                return suite
    return "unknown"


def _iter_analysis_layout_tasks(
    runs_dir: Path,
    prefix_map: dict[str, str],
    run_filter: set[str] | None,
) -> list[tuple[str, str, str, Path]]:
    """Discover tasks in analysis-style layout:
    runs/analysis/.../<suite>/<config>/<task>/<trial>/result.json
    """
    discovered: list[tuple[str, str, str, Path]] = []
    for result_path in sorted(runs_dir.rglob("result.json")):
        if any(part in SKIP_DIR_PARTS for part in result_path.parts):
            continue
        task_dir = result_path.parent
        if (task_dir / "__broken_verifier").exists():
            continue
        try:
            payload = json.loads(result_path.read_text())
        except Exception:
            continue
        if not _is_task_result_payload(payload):
            continue

        rel_parts = result_path.relative_to(runs_dir).parts
        config_idx = next((i for i, part in enumerate(rel_parts) if is_config_dir(part)), None)
        if config_idx is None:
            continue

        config = rel_parts[config_idx]
        run_dir_name = "/".join(rel_parts[:config_idx]) if config_idx > 0 else "analysis"
        if run_filter and run_dir_name not in run_filter:
            continue

        suite = _suite_from_path_parts(rel_parts, prefix_map)
        discovered.append((suite, run_dir_name, config, task_dir))
    return discovered


def _extract_reward_and_status(result_payload: dict[str, Any]) -> tuple[float | None, str]:
    exception_info = result_payload.get("exception_info")
    verifier = result_payload.get("verifier_result") or {}
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else {}
    rewards = rewards if isinstance(rewards, dict) else {}
    reward = _safe_float(rewards.get("reward"))
    if reward is None:
        reward = _safe_float(rewards.get("score"))

    if exception_info is not None:
        return reward, "errored"
    if reward is None:
        return None, "unknown"
    if reward > 0:
        return reward, "passed"
    return reward, "failed"


def _load_task_metrics(task_dir: Path) -> dict[str, Any] | None:
    path = task_dir / "task_metrics.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _normalize_repo_name(repo: Any) -> str:
    if not isinstance(repo, str):
        return ""
    name = repo.strip()
    if name.startswith("github.com/"):
        name = name[len("github.com/"):]
    return name


def _repo_key(repo: Any) -> str:
    return _normalize_repo_name(repo).lower()


def _is_placeholder_repo(repo: Any) -> bool:
    return _repo_key(repo) in _PLACEHOLDER_REPOS


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if text.lower() in {"unknown", "null", "none", "tbd"}:
            continue
        return text
    return None


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_selected_task_index() -> dict[str, dict[str, Any]]:
    global _SELECTED_TASK_INDEX
    if _SELECTED_TASK_INDEX is not None:
        return _SELECTED_TASK_INDEX
    index: dict[str, dict[str, Any]] = {}
    selected_path = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"
    payload = _load_json_dict(selected_path)
    tasks = payload.get("tasks") if isinstance(payload, dict) else None
    if isinstance(tasks, list):
        for entry in tasks:
            if not isinstance(entry, dict):
                continue
            task_id = entry.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            index[_canonical_task_name(task_id)] = entry
    _SELECTED_TASK_INDEX = index
    return _SELECTED_TASK_INDEX


def _selected_task_metadata(task_name: str) -> dict[str, Any]:
    entry = _load_selected_task_index().get(_canonical_task_name(task_name))
    if not isinstance(entry, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in BENCHMARK_METADATA_KEYS:
        value = entry.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _canonicalize_benchmark_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    try:
        return str(candidate.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(candidate)


def _load_repo_fixture_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    global _REPO_SET_INDEX, _REPO_INFO_INDEX
    if _REPO_SET_INDEX is not None and _REPO_INFO_INDEX is not None:
        return _REPO_SET_INDEX, _REPO_INFO_INDEX

    repo_sets: dict[str, dict[str, Any]] = {}
    repo_info: dict[str, dict[str, Any]] = {}
    repo_sets_dir = PROJECT_ROOT / "fixtures" / "repo_sets"
    for fixture_path in sorted(repo_sets_dir.glob("*.json")):
        fixture = _load_json_dict(fixture_path)
        if not isinstance(fixture, dict):
            continue
        set_id = fixture.get("id") if isinstance(fixture.get("id"), str) else fixture_path.stem
        repo_sets[set_id] = fixture
        default_language = _first_non_empty(fixture.get("primary_language"))
        repos = fixture.get("repos")
        if not isinstance(repos, list):
            continue
        for repo in repos:
            if not isinstance(repo, dict):
                continue
            logical_name = _first_non_empty(repo.get("logical_name"))
            full_name = _first_non_empty(repo.get("full_name"))
            display_name = logical_name or full_name
            if not display_name:
                continue
            info = {
                "name": display_name,
                "language": _first_non_empty(repo.get("language"), default_language),
                "approx_loc": _safe_int(repo.get("loc_estimate")),
                "repo_set_id": set_id,
            }
            for alias in (display_name, logical_name, full_name):
                key = _repo_key(alias)
                if key and key not in repo_info:
                    repo_info[key] = info

    _REPO_SET_INDEX = repo_sets
    _REPO_INFO_INDEX = repo_info
    return _REPO_SET_INDEX, _REPO_INFO_INDEX


def _resolve_repo_candidate(raw: Any, repo_info: dict[str, dict[str, Any]]) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip("`\"'")
    if not text:
        return None

    github_match = re.search(r"github\.com/([^/\s]+)/([^/\s]+)", text)
    if github_match:
        org = github_match.group(1)
        repo = github_match.group(2)
        repo = repo[:-4] if repo.endswith(".git") else repo
        if org == "sg-evals":
            text = repo.split("--", 1)[0]
        else:
            text = f"{org}/{repo.split('--', 1)[0]}"
    else:
        text = text[:-4] if text.endswith(".git") else text
        if text.startswith("sg-evals/"):
            text = text.split("/", 1)[1].split("--", 1)[0]

    normalized = _normalize_repo_name(text)
    if not normalized:
        return None
    key = _repo_key(normalized)
    if key in _PLACEHOLDER_REPOS:
        return None

    if "/" in normalized:
        prefix = normalized.split("/", 1)[0].lower()
        if prefix in _NON_REPO_PREFIXES:
            return None

    info = repo_info.get(key)
    if info and isinstance(info.get("name"), str):
        return _normalize_repo_name(info["name"])

    if "/" not in normalized:
        if key in _REPO_ALIAS_OVERRIDES:
            return _REPO_ALIAS_OVERRIDES[key]
        suffix_matches = []
        for repo_key, info_payload in repo_info.items():
            if repo_key.endswith(f"/{key}") and isinstance(info_payload.get("name"), str):
                suffix_matches.append(_normalize_repo_name(info_payload["name"]))
        deduped_suffix = sorted({m for m in suffix_matches if m})
        if len(deduped_suffix) == 1:
            return deduped_suffix[0]

    if not _is_probable_repo_name(normalized):
        return None
    return normalized


def _is_probable_repo_name(value: str) -> bool:
    normalized = _normalize_repo_name(value)
    if not normalized or "/" not in normalized:
        return False
    owner, repo = normalized.split("/", 1)
    if owner.lower() in _NON_REPO_OWNERS:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._-]+", owner):
        return False
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repo):
        return False
    repo_lower = repo.lower()
    if repo_lower.endswith(
        (
            ".go",
            ".py",
            ".proto",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".js",
            ".ts",
            ".java",
            ".scala",
            ".rs",
            ".cc",
            ".cpp",
            ".h",
            ".hpp",
            ".c",
        )
    ):
        return False
    return True


def _extract_repo_candidates_from_instruction(instruction_text: str, repo_info: dict[str, dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for pattern in (r"`([^`]+)`", r'"([^"]+)"', r"'([^']+)'"):
        for match in re.finditer(pattern, instruction_text):
            token = match.group(1).strip()
            if not token:
                continue
            if "github.com/" not in token and not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", token):
                continue
            resolved = _resolve_repo_candidate(token, repo_info)
            if resolved:
                candidates.append(resolved)
    return candidates


def _extract_repo_candidates_from_task_yaml(task_path: Path, repo_info: dict[str, dict[str, Any]]) -> list[str]:
    path = task_path / "task.yaml"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except Exception:
        return []

    candidates: list[str] = []
    in_repos_block = False
    repos_indent = 0
    for line in lines:
        if not in_repos_block:
            if re.match(r"^\s*repos\s*:\s*$", line):
                in_repos_block = True
                repos_indent = len(line) - len(line.lstrip())
            continue
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= repos_indent:
            break
        match = re.match(r"^\s*-\s*([A-Za-z0-9._/\-]+)\s*$", line)
        if not match:
            continue
        resolved = _resolve_repo_candidate(match.group(1), repo_info)
        if resolved:
            candidates.append(resolved)
    return candidates


def _extract_repo_candidates_from_dockerfiles(task_path: Path, repo_info: dict[str, dict[str, Any]]) -> list[str]:
    env_dir = task_path / "environment"
    if not env_dir.is_dir():
        return []
    candidates: list[str] = []
    for dockerfile in sorted(env_dir.glob("Dockerfile*")):
        if not dockerfile.is_file():
            continue
        try:
            text = dockerfile.read_text(errors="replace")
        except Exception:
            continue

        for match in re.finditer(r"(?im)^\s*#\s*Clone\s+([A-Za-z0-9._-]+/[A-Za-z0-9._-]+)\s*$", text):
            resolved = _resolve_repo_candidate(match.group(1), repo_info)
            if resolved:
                candidates.append(resolved)
        for match in re.finditer(r"github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)", text):
            org = match.group(1)
            repo = match.group(2).split("--", 1)[0]
            raw = f"{org}/{repo}"
            resolved = _resolve_repo_candidate(raw, repo_info)
            if resolved:
                candidates.append(resolved)
    return candidates


def _extract_ir_fields(payload: dict[str, Any]) -> dict[str, Any]:
    ir: dict[str, Any] = {}
    for key in IR_METRIC_KEYS:
        value = payload.get(key)
        if value is not None:
            ir[key] = value
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        for key in IR_METRIC_KEYS:
            value = metrics.get(key)
            if value is not None and key not in ir:
                ir[key] = value
    expected_files = payload.get("expected_files")
    actual_files = payload.get("actual_files")
    if isinstance(expected_files, list):
        ir["expected_files_count"] = len(expected_files)
    if isinstance(actual_files, list):
        ir["actual_files_count"] = len(actual_files)
    return ir


def _load_ir_metrics(task_dir: Path, task_metrics: dict[str, Any] | None) -> dict[str, Any]:
    ir_metrics: dict[str, Any] = {}
    if isinstance(task_metrics, dict):
        ir_metrics.update(_extract_ir_fields(task_metrics))

    reward_payload = _load_json_dict(task_dir / "verifier" / "reward.json")
    if isinstance(reward_payload, dict):
        ir_metrics.update(_extract_ir_fields(reward_payload))

    for ir_path in (task_dir / "ir_metrics.json", task_dir / "verifier" / "ir_metrics.json"):
        payload = _load_json_dict(ir_path)
        if isinstance(payload, dict):
            extracted = _extract_ir_fields(payload)
            ir_metrics.update(extracted if extracted else {k: v for k, v in payload.items() if v is not None})
    return ir_metrics


def _extract_task_instruction(task_dir: Path, task_path_from_result: str | None) -> str | None:
    candidates = [
        task_dir / "instruction.txt",
        task_dir / "agent" / "instruction.txt",
    ]
    if task_path_from_result:
        benchmark_path = Path(task_path_from_result)
        candidates.extend([benchmark_path / "instruction.md", benchmark_path / "instruction.txt"])
    for path in candidates:
        if path.is_file():
            try:
                text = path.read_text(errors="replace").strip()
            except Exception:
                continue
            if text:
                return text
    return None


def _extract_repo_metadata(
    task_metrics: dict[str, Any] | None,
    task_path_from_result: str | None,
    task_name: str,
    suite: str,
) -> tuple[list[str], list[dict[str, Any]], str | None, str | None, int | None]:
    repos: list[str] = []
    repo_details: list[dict[str, Any]] = []
    benchmark_task_path: str | None = None
    task_category: str | None = None
    task_language: str | None = None
    task_context_length: int | None = None
    repo_set_id: str | None = None

    if task_metrics and isinstance(task_metrics.get("repo"), str) and task_metrics.get("repo"):
        repos.append(task_metrics["repo"])
    if task_metrics:
        task_category = _first_non_empty(task_metrics.get("category"), task_category)
        task_language = _first_non_empty(task_metrics.get("language"), task_language)
        task_context_length = _safe_int(task_metrics.get("task_context_length"))

    task_path_candidates: list[Path] = []
    if isinstance(task_path_from_result, str) and task_path_from_result:
        result_candidate = Path(task_path_from_result)
        if not result_candidate.is_absolute():
            result_candidate = PROJECT_ROOT / result_candidate
        task_path_candidates.append(result_candidate)
    canonical_name = _canonical_task_name(task_name)
    task_path_candidates.append(PROJECT_ROOT / "benchmarks" / suite / canonical_name)
    task_path_candidates.append(PROJECT_ROOT / "benchmarks" / suite / task_name)
    task_path = next((candidate for candidate in task_path_candidates if candidate.is_dir()), None)
    if task_path and task_path.is_dir():
        benchmark_task_path = _canonicalize_benchmark_path(task_path)
        if tomllib is not None:
            task_toml = task_path / "task.toml"
            if task_toml.is_file():
                try:
                    payload = tomllib.loads(task_toml.read_text())
                    task_section = payload.get("task", {})
                    repo_val = task_section.get("repo")
                    if isinstance(repo_val, str) and repo_val:
                        repos.append(repo_val)
                    repo_set_id = _first_non_empty(task_section.get("repo_set_id"), repo_set_id)
                    task_category = _first_non_empty(task_category, task_section.get("category"))
                    task_language = _first_non_empty(task_language, task_section.get("language"))
                except Exception:
                    pass
        task_spec = _load_json_dict(task_path / "tests" / "task_spec.json")
        if isinstance(task_spec, dict):
            task_category = _first_non_empty(task_category, task_spec.get("family"), task_spec.get("category"))
            artifacts = task_spec.get("artifacts")
            if isinstance(artifacts, dict):
                repo_set_id = _first_non_empty(repo_set_id, artifacts.get("repo_set_id"))
                oracle = artifacts.get("oracle")
                if isinstance(oracle, dict):
                    required_files = oracle.get("required_files")
                    if isinstance(required_files, list):
                        for file_entry in required_files:
                            if isinstance(file_entry, dict):
                                repo_val = file_entry.get("repo")
                                if isinstance(repo_val, str) and repo_val:
                                    repos.append(repo_val)

    selected_entry = _load_selected_task_index().get(_canonical_task_name(task_name))
    if isinstance(selected_entry, dict):
        selected_repo = selected_entry.get("repo")
        if isinstance(selected_repo, str) and selected_repo:
            repos.append(selected_repo)
        task_category = _first_non_empty(task_category, selected_entry.get("category"), selected_entry.get("sdlc_phase"))
        task_language = _first_non_empty(task_language, selected_entry.get("language"))
        if task_context_length is None:
            task_context_length = _safe_int(selected_entry.get("context_length"))
        repo_set_id = _first_non_empty(repo_set_id, selected_entry.get("repo_set_id"))

    repo_sets, repo_info = _load_repo_fixture_indexes()

    if task_path and task_path.is_dir():
        for instruction_name in ("instruction.md", "instruction_mcp.md", "instruction.txt"):
            instruction_path = task_path / instruction_name
            if not instruction_path.is_file():
                continue
            try:
                instruction_text = instruction_path.read_text(errors="replace")
            except Exception:
                continue
            repos.extend(_extract_repo_candidates_from_instruction(instruction_text, repo_info))
        repos.extend(_extract_repo_candidates_from_task_yaml(task_path, repo_info))
        repos.extend(_extract_repo_candidates_from_dockerfiles(task_path, repo_info))

    seen_detail_names: set[str] = set()

    def add_detail(name: str, language: str | None, approx_loc: int | None) -> None:
        clean_name = _normalize_repo_name(name)
        if not clean_name:
            return
        key = clean_name.lower()
        if key in seen_detail_names:
            return
        seen_detail_names.add(key)
        repo_details.append(
            {
                "name": clean_name,
                "language": language,
                "approx_loc": approx_loc,
            }
        )

    fixture = repo_sets.get(repo_set_id or "")
    if isinstance(fixture, dict):
        fixture_language = _first_non_empty(task_language, fixture.get("primary_language"))
        fixture_repos = fixture.get("repos")
        if isinstance(fixture_repos, list):
            for repo_entry in fixture_repos:
                if not isinstance(repo_entry, dict):
                    continue
                display_name = _first_non_empty(repo_entry.get("logical_name"), repo_entry.get("full_name"))
                if not display_name:
                    continue
                add_detail(
                    display_name,
                    _first_non_empty(repo_entry.get("language"), fixture_language),
                    _safe_int(repo_entry.get("loc_estimate")),
                )

    for repo in repos:
        normalized_repo = _normalize_repo_name(repo)
        if not normalized_repo:
            continue
        if _is_placeholder_repo(normalized_repo) and repo_details:
            continue
        info = repo_info.get(_repo_key(normalized_repo))
        if info:
            add_detail(
                str(info.get("name") or normalized_repo),
                _first_non_empty(task_language, info.get("language")),
                _safe_int(info.get("approx_loc")),
            )
        else:
            add_detail(normalized_repo, task_language, None)

    repositories = [d["name"] for d in repo_details if isinstance(d.get("name"), str) and d.get("name")]
    if not repositories:
        repositories = sorted(
            {
                _normalize_repo_name(repo)
                for repo in repos
                if _normalize_repo_name(repo) and not _is_placeholder_repo(repo)
            }
        )
    if not repositories:
        repositories = sorted({_normalize_repo_name(repo) for repo in repos if _normalize_repo_name(repo)})

    deduped = sorted({r for r in repos if r})
    if not repositories and deduped:
        repositories = sorted({_normalize_repo_name(r) for r in deduped if _normalize_repo_name(r)})

    return repositories, repo_details, benchmark_task_path, task_category, task_context_length


def _find_trace_paths(task_dir: Path) -> dict[str, str | None]:
    agent_dir = task_dir / "agent"
    trajectory = agent_dir / "trajectory.json"

    transcript: Path | None = None
    if agent_dir.is_dir():
        for name in TRANSCRIPT_CANDIDATES:
            candidate = agent_dir / name
            if candidate.is_file():
                transcript = candidate
                break

    rel_traj = str(trajectory.relative_to(PROJECT_ROOT)) if trajectory.is_file() else None
    rel_tx = str(transcript.relative_to(PROJECT_ROOT)) if transcript and transcript.is_file() else None
    return {
        "trajectory": rel_traj,
        "transcript": rel_tx,
    }


def _parse_transcript(
    transcript_path: Path,
    max_examples: int,
) -> tuple[dict[str, int], list[dict[str, str]], dict[str, Any], dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    line_count = 0
    json_line_count = 0
    tool_use_id_to_name: dict[str, str] = {}
    detailed_events: list[dict[str, Any]] = []
    detailed_tool_calls: list[dict[str, Any]] = []
    detailed_code_changes: list[dict[str, Any]] = []
    detailed_bash_commands: list[dict[str, Any]] = []
    token_input = 0
    token_output = 0
    token_cache_read = 0
    model_name: str | None = None
    if not transcript_path.is_file():
        return {}, examples, {
            "line_count": 0,
            "json_line_count": 0,
            "tool_event_count": 0,
            "message_event_count": 0,
            "messages": [],
            "tool_events": [],
        }, {}

    try:
        lines = transcript_path.read_text(errors="replace").splitlines()
    except Exception:
        return {}, examples, {
            "line_count": 0,
            "json_line_count": 0,
            "tool_event_count": 0,
            "message_event_count": 0,
            "messages": [],
            "tool_events": [],
        }, {}

    message_events: list[dict[str, Any]] = []
    sequence = 0
    pending_tool_calls: dict[str, dict[str, Any]] = {}

    def _append_message(
        msg_type: str,
        subtype: str,
        text: str | None = None,
        tool: str | None = None,
        payload: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> None:
        nonlocal sequence
        event_payload: dict[str, Any] = payload or {}
        detail = {
            "sequence": sequence,
            "timestamp": timestamp,
            "type": msg_type,
            "subtype": subtype,
            "tool": tool,
            "text": text or "",
            "payload": event_payload,
        }
        if len(detailed_events) < TASK_PAGE_EVENT_LIMIT:
            detailed_events.append(detail)
        if len(message_events) >= AUDIT_EVENT_LIMIT:
            sequence += 1
            return
        preview = (text or "").replace("\n", " ").strip()
        if len(preview) > 220:
            preview = preview[:220] + "..."
        message_events.append(
            {
                "sequence": sequence,
                "type": msg_type,
                "subtype": subtype,
                "tool": tool,
                "text": preview or None,
            }
        )
        sequence += 1

    def _tool_result_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    block_type = str(block.get("type") or "")
                    if block_type in {"text", "tool_result"}:
                        inner = block.get("text", block.get("content", ""))
                        if isinstance(inner, str):
                            parts.append(inner)
                        elif isinstance(inner, list):
                            for inner_block in inner:
                                if isinstance(inner_block, dict):
                                    inner_text = inner_block.get("text", inner_block.get("content", ""))
                                    if isinstance(inner_text, str):
                                        parts.append(inner_text)
                                elif isinstance(inner_block, str):
                                    parts.append(inner_block)
                    elif isinstance(block.get("content"), str):
                        parts.append(str(block.get("content")))
                elif isinstance(block, str):
                    parts.append(block)
            return "\n".join(p for p in parts if p)
        if isinstance(content, dict):
            raw = content.get("content")
            if raw is not None:
                extracted = _tool_result_to_text(raw)
                if extracted:
                    return extracted
            return json.dumps(content, sort_keys=True)
        return ""

    def _attach_tool_output(tool_use_id: str, output_payload: Any, output_text: str, timestamp: str | None) -> None:
        if not tool_use_id:
            return
        call = pending_tool_calls.get(tool_use_id)
        if call is None:
            return
        call["output"] = output_payload if output_payload is not None else output_text
        call["output_text"] = output_text
        if timestamp and not call.get("result_timestamp"):
            call["result_timestamp"] = timestamp

    for line in lines:
        line_count += 1
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        json_line_count += 1

        msg_type = str(payload.get("type") or "")
        ts = payload.get("timestamp")
        if not isinstance(ts, str):
            ts = None

        if msg_type == "assistant":
            message = payload.get("message")
            if not isinstance(message, dict):
                continue
            if model_name is None and isinstance(message.get("model"), str):
                model_name = message["model"]
            usage = message.get("usage")
            if isinstance(usage, dict):
                token_input += _safe_int(usage.get("input_tokens")) or 0
                token_output += _safe_int(usage.get("output_tokens")) or 0
                token_cache_read += _safe_int(usage.get("cache_read_input_tokens")) or 0
            content = message.get("content")
            if isinstance(content, str):
                _append_message("assistant", "text", content, timestamp=ts)
                continue
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "")
                if item_type == "text":
                    _append_message("assistant", "text", str(item.get("text") or ""), timestamp=ts)
                    continue
                if item_type != "tool_use":
                    continue
                tool_name = str(item.get("name") or "unknown")
                tool_input = item.get("input")
                tool_input_payload = tool_input if isinstance(tool_input, dict) else {}
                tool_call_id = str(item.get("id") or "")
                if tool_call_id:
                    tool_use_id_to_name[tool_call_id] = tool_name
                counts[tool_name] += 1
                _append_message(
                    "assistant",
                    "tool_use",
                    tool=tool_name,
                    payload=tool_input_payload,
                    timestamp=ts,
                )
                if len(events) < AUDIT_EVENT_LIMIT:
                    events.append(
                        {
                            "timestamp": ts if isinstance(ts, str) else None,
                            "tool": tool_name,
                        }
                    )
                if len(detailed_tool_calls) < TASK_PAGE_EVENT_LIMIT:
                    call_detail = {
                        "sequence": sequence - 1,
                        "timestamp": ts,
                        "tool": tool_name,
                        "tool_use_id": tool_call_id or None,
                        "input": tool_input_payload,
                        "output": None,
                        "output_text": "",
                    }
                    detailed_tool_calls.append(call_detail)
                    if tool_call_id:
                        pending_tool_calls[tool_call_id] = call_detail
                if tool_name == "Edit":
                    if len(detailed_code_changes) < TASK_PAGE_EVENT_LIMIT:
                        detailed_code_changes.append(
                            {
                                "sequence": sequence - 1,
                                "type": "edit",
                                "file_path": str(tool_input_payload.get("file_path") or ""),
                                "old_string": str(tool_input_payload.get("old_string") or ""),
                                "new_string": str(tool_input_payload.get("new_string") or ""),
                            }
                        )
                elif tool_name == "Write":
                    if len(detailed_code_changes) < TASK_PAGE_EVENT_LIMIT:
                        detailed_code_changes.append(
                            {
                                "sequence": sequence - 1,
                                "type": "write",
                                "file_path": str(tool_input_payload.get("file_path") or ""),
                                "content": str(tool_input_payload.get("content") or ""),
                            }
                        )
                elif tool_name == "Bash":
                    command = str(tool_input_payload.get("command") or "")
                    if command and len(detailed_bash_commands) < TASK_PAGE_EVENT_LIMIT:
                        detailed_bash_commands.append(
                            {
                                "sequence": sequence - 1,
                                "command": command,
                            }
                        )
                if len(examples) < max_examples:
                    examples.append({"tool": tool_name})
            continue

        if msg_type == "user":
            message = payload.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            top_level_tool_result = payload.get("tool_use_result")
            camel_tool_result = payload.get("toolUseResult")

            handled_tool_result = False
            if isinstance(content, list):
                tool_result_blocks = [
                    block for block in content if isinstance(block, dict) and str(block.get("type") or "") == "tool_result"
                ]
                if tool_result_blocks:
                    handled_tool_result = True
                    for block in tool_result_blocks:
                        tool_use_id = str(block.get("tool_use_id") or block.get("toolUseId") or "")
                        mapped_tool = tool_use_id_to_name.get(tool_use_id)
                        block_content = block.get("content")
                        block_text = _tool_result_to_text(block_content)
                        output_payload: Any = block_content
                        # Claude transcript commonly includes richer structured data here.
                        if top_level_tool_result is not None and len(tool_result_blocks) == 1:
                            output_payload = top_level_tool_result
                        elif isinstance(camel_tool_result, dict):
                            output_payload = camel_tool_result
                        if not block_text and output_payload is not None:
                            block_text = _tool_result_to_text(output_payload)
                        _append_message(
                            "user",
                            "tool_result",
                            block_text,
                            tool=mapped_tool,
                            payload=output_payload if isinstance(output_payload, dict) else None,
                            timestamp=ts,
                        )
                        _attach_tool_output(tool_use_id, output_payload, block_text, ts)
            if handled_tool_result:
                continue

            if isinstance(camel_tool_result, dict):
                tool_use_id = str(camel_tool_result.get("tool_use_id") or camel_tool_result.get("toolUseId") or "")
                mapped_tool = tool_use_id_to_name.get(tool_use_id)
                result_text = _tool_result_to_text(camel_tool_result.get("content"))
                _append_message(
                    "user",
                    "tool_result",
                    result_text,
                    tool=mapped_tool,
                    payload=camel_tool_result,
                    timestamp=ts,
                )
                _attach_tool_output(tool_use_id, camel_tool_result, result_text, ts)
                continue

            if top_level_tool_result is not None:
                result_text = _tool_result_to_text(top_level_tool_result)
                _append_message("user", "tool_result", result_text, payload=top_level_tool_result if isinstance(top_level_tool_result, dict) else None, timestamp=ts)
                continue

            if isinstance(content, str):
                _append_message("user", "text", content, timestamp=ts)
            elif isinstance(content, list):
                text_parts = [
                    str(block.get("text") or "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                _append_message("user", "text", "\n".join(text_parts), timestamp=ts)
            continue

        if msg_type == "system":
            subtype = str(payload.get("subtype") or "init")
            _append_message("system", subtype, timestamp=ts)

    return dict(counts), examples, {
        "line_count": line_count,
        "json_line_count": json_line_count,
        "tool_event_count": sum(counts.values()),
        "message_event_count": len(message_events),
        "messages": message_events,
        "tool_events": events,
    }, {
        "model_name": model_name,
        "token_input": token_input,
        "token_output": token_output,
        "token_cache_read": token_cache_read,
        "events": detailed_events,
        "tool_calls": detailed_tool_calls,
        "code_changes": detailed_code_changes,
        "bash_commands": detailed_bash_commands,
    }


def _parse_trajectory(trajectory_path: Path) -> dict[str, Any]:
    if not trajectory_path.is_file():
        return {
            "step_count": 0,
            "tool_event_count": 0,
            "tool_counts_by_name": {},
            "tool_events": [],
        }
    try:
        payload = json.loads(trajectory_path.read_text())
    except Exception:
        return {
            "step_count": 0,
            "tool_event_count": 0,
            "tool_counts_by_name": {},
            "tool_events": [],
        }
    steps = payload.get("steps")
    if not isinstance(steps, list):
        steps = []

    counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    code_changes: list[dict[str, Any]] = []
    bash_commands: list[dict[str, Any]] = []
    conversation_events: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("step_id")
        timestamp = step.get("timestamp")
        source = str(step.get("source") or "")
        message = str(step.get("message") or "")
        if message and len(conversation_events) < TASK_PAGE_EVENT_LIMIT:
            conversation_events.append(
                {
                    "sequence": step_id if isinstance(step_id, int) else len(conversation_events) + 1,
                    "timestamp": timestamp if isinstance(timestamp, str) else None,
                    "type": source or "unknown",
                    "subtype": "message",
                    "tool": None,
                    "text": message,
                    "payload": {},
                }
            )
        tool_calls = step.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        observation_payload = step.get("observation")
        observation_by_call_id: dict[str, Any] = {}
        if isinstance(observation_payload, dict):
            results = observation_payload.get("results")
            if isinstance(results, list):
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    source_call_id = str(result.get("source_call_id") or "")
                    if source_call_id:
                        observation_by_call_id[source_call_id] = result.get("content")
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool_name = str(
                call.get("function_name")
                or call.get("tool_name")
                or call.get("name")
                or "unknown"
            )
            tool_call_id = str(call.get("tool_call_id") or call.get("id") or "")
            arguments = call.get("arguments")
            arguments_payload = arguments if isinstance(arguments, dict) else {}
            call_output = observation_by_call_id.get(tool_call_id)
            counts[tool_name] += 1
            if len(events) < AUDIT_EVENT_LIMIT:
                events.append(
                    {
                        "step_id": step_id if isinstance(step_id, int) else None,
                        "timestamp": timestamp if isinstance(timestamp, str) else None,
                        "tool": tool_name,
                        "tool_use_id": tool_call_id or None,
                        "arguments": arguments_payload,
                        "input": arguments_payload,
                        "output": call_output,
                    }
                )
            if tool_name == "Edit" and len(code_changes) < TASK_PAGE_EVENT_LIMIT:
                code_changes.append(
                    {
                        "sequence": step_id if isinstance(step_id, int) else None,
                        "type": "edit",
                        "file_path": str(arguments_payload.get("file_path") or ""),
                        "old_string": str(arguments_payload.get("old_string") or ""),
                        "new_string": str(arguments_payload.get("new_string") or ""),
                    }
                )
            if tool_name == "Write" and len(code_changes) < TASK_PAGE_EVENT_LIMIT:
                code_changes.append(
                    {
                        "sequence": step_id if isinstance(step_id, int) else None,
                        "type": "write",
                        "file_path": str(arguments_payload.get("file_path") or ""),
                        "content": str(arguments_payload.get("content") or ""),
                    }
                )
            if tool_name == "Bash":
                command = str(arguments_payload.get("command") or "")
                if command and len(bash_commands) < TASK_PAGE_EVENT_LIMIT:
                    bash_commands.append(
                        {
                            "sequence": step_id if isinstance(step_id, int) else None,
                            "command": command,
                        }
                    )
    return {
        "step_count": len(steps),
        "tool_event_count": sum(counts.values()),
        "tool_counts_by_name": dict(counts),
        "tool_events": events,
        "conversation_events": conversation_events,
        "code_changes": code_changes,
        "bash_commands": bash_commands,
    }


def _extract_task_record(
    suite: str,
    run_dir_name: str,
    config_name: str,
    task_dir: Path,
    max_examples: int,
) -> tuple[TaskRecord, dict[str, Any]] | None:
    result_path = task_dir / "result.json"
    if not result_path.is_file():
        return None

    try:
        result_payload = json.loads(result_path.read_text())
    except Exception:
        return None

    reward, status = _extract_reward_and_status(result_payload)
    if reward is None or status not in {"passed", "failed"}:
        return None

    task_name = str(result_payload.get("task_name") or _task_name_from_dir(task_dir))
    started_at_raw = result_payload.get("started_at")
    started_at = started_at_raw if isinstance(started_at_raw, str) else None

    agent_result = result_payload.get("agent_result") or {}
    if not isinstance(agent_result, dict):
        agent_result = {}

    timed_out = bool(result_payload.get("timed_out") or result_payload.get("timeout"))

    wall_clock_seconds = _safe_float(result_payload.get("wall_clock_seconds"))
    if wall_clock_seconds is None:
        wall_clock_seconds = _elapsed_seconds(
            result_payload.get("started_at"),
            result_payload.get("finished_at"),
        )

    agent_exec = result_payload.get("agent_execution") or {}
    agent_execution_seconds = _safe_float(agent_exec.get("elapsed_seconds")) if isinstance(agent_exec, dict) else None
    if agent_execution_seconds is None and isinstance(agent_exec, dict):
        agent_execution_seconds = _elapsed_seconds(
            agent_exec.get("started_at"),
            agent_exec.get("finished_at"),
        )

    input_tokens = _safe_int(agent_result.get("n_input_tokens"))
    output_tokens = _safe_int(agent_result.get("n_output_tokens"))
    cache_tokens = _safe_int(
        agent_result.get("n_cache_tokens", agent_result.get("cache_creation_input_tokens"))
    )

    task_metrics = _load_task_metrics(task_dir)

    tool_calls_total = _safe_int(task_metrics.get("tool_calls_total")) if task_metrics else None
    tool_calls_mcp = _safe_int(task_metrics.get("tool_calls_mcp")) if task_metrics else None
    tool_calls_local = _safe_int(task_metrics.get("tool_calls_local")) if task_metrics else None
    mcp_ratio = _safe_float(task_metrics.get("mcp_ratio")) if task_metrics else None

    search_calls_keyword = _safe_int(task_metrics.get("search_calls_keyword")) if task_metrics else None
    search_calls_nls = _safe_int(task_metrics.get("search_calls_nls")) if task_metrics else None
    search_calls_deepsearch = _safe_int(task_metrics.get("search_calls_deepsearch")) if task_metrics else None

    tool_calls_by_name = None
    if task_metrics and isinstance(task_metrics.get("tool_calls_by_name"), dict):
        tool_calls_by_name = {
            str(k): int(v)
            for k, v in task_metrics["tool_calls_by_name"].items()
            if isinstance(v, (int, float))
        }

    trace_paths = _find_trace_paths(task_dir)
    trajectory_path = PROJECT_ROOT / trace_paths["trajectory"] if trace_paths["trajectory"] else None
    transcript_path = PROJECT_ROOT / trace_paths["transcript"] if trace_paths["transcript"] else None
    parsed_counts, sample_tool_calls, transcript_audit, transcript_detail = (
        _parse_transcript(transcript_path, max_examples)
        if transcript_path
        else ({}, [], {"line_count": 0, "json_line_count": 0, "tool_event_count": 0, "tool_events": []}, {})
    )
    trajectory_audit = _parse_trajectory(trajectory_path) if trajectory_path else {
        "step_count": 0,
        "tool_event_count": 0,
        "tool_counts_by_name": {},
        "tool_events": [],
        "conversation_events": [],
        "code_changes": [],
        "bash_commands": [],
    }

    # Fallback to transcript-derived tool counts when task_metrics is missing.
    if tool_calls_by_name is None and parsed_counts:
        tool_calls_by_name = parsed_counts
    if tool_calls_total is None and parsed_counts:
        tool_calls_total = sum(parsed_counts.values())
    if tool_calls_mcp is None and parsed_counts:
        tool_calls_mcp = sum(v for k, v in parsed_counts.items() if k.startswith("mcp__sourcegraph__"))
    if tool_calls_local is None and parsed_counts and tool_calls_mcp is not None and tool_calls_total is not None:
        tool_calls_local = max(tool_calls_total - tool_calls_mcp, 0)
    if mcp_ratio is None and tool_calls_total and tool_calls_mcp is not None and tool_calls_total > 0:
        mcp_ratio = tool_calls_mcp / tool_calls_total

    rel_task_dir = str(task_dir.relative_to(PROJECT_ROOT))
    task_id = result_payload.get("task_id") if isinstance(result_payload.get("task_id"), dict) else {}
    task_path_from_result = task_id.get("path") if isinstance(task_id, dict) else None
    instruction_text = _extract_task_instruction(task_dir, task_path_from_result)
    repositories, repository_details, benchmark_task_path, task_category, fallback_context_length = _extract_repo_metadata(
        task_metrics,
        task_path_from_result,
        task_name,
        suite,
    )
    benchmark_metadata = _selected_task_metadata(task_name)
    ir_metrics = _load_ir_metrics(task_dir, task_metrics)

    agent_info = result_payload.get("agent_info") if isinstance(result_payload.get("agent_info"), dict) else {}
    agent_name = None
    if isinstance(agent_info.get("name"), str):
        agent_name = agent_info.get("name")

    config_payload = result_payload.get("config") if isinstance(result_payload.get("config"), dict) else {}
    config_agent = config_payload.get("agent") if isinstance(config_payload.get("agent"), dict) else {}
    model_name = None
    model_info = agent_info.get("model_info") if isinstance(agent_info.get("model_info"), dict) else {}
    if isinstance(model_info.get("name"), str) and model_info.get("name"):
        model_name = model_info.get("name")
    elif isinstance(config_agent.get("model_name"), str) and config_agent.get("model_name"):
        model_name = config_agent.get("model_name")
    elif isinstance(transcript_detail.get("model_name"), str) and transcript_detail.get("model_name"):
        model_name = transcript_detail.get("model_name")

    context_metrics: dict[str, Any] = {}
    if task_metrics:
        for key in (
            "task_context_length",
            "context_window_peak_pct",
            "environment_setup_seconds",
            "verifier_seconds",
            "files_modified",
            "lines_added",
            "lines_removed",
        ):
            if key in task_metrics:
                context_metrics[key] = task_metrics.get(key)
    if context_metrics.get("task_context_length") is None and fallback_context_length is not None:
        context_metrics["task_context_length"] = fallback_context_length

    flags: list[str] = []
    if (
        config_name in MCP_EXPECTED_CONFIGS
        and tool_calls_total is not None
        and tool_calls_total > 0
        and (tool_calls_mcp or 0) == 0
    ):
        flags.append("mcp_run_zero_mcp_calls")

    trace_events = transcript_detail.get("events") if isinstance(transcript_detail.get("events"), list) else []
    trace_tool_calls = transcript_detail.get("tool_calls") if isinstance(transcript_detail.get("tool_calls"), list) else []
    trace_code_changes = transcript_detail.get("code_changes") if isinstance(transcript_detail.get("code_changes"), list) else []
    trace_bash_commands = transcript_detail.get("bash_commands") if isinstance(transcript_detail.get("bash_commands"), list) else []
    if not trace_events:
        trace_events = trajectory_audit.get("conversation_events") if isinstance(trajectory_audit.get("conversation_events"), list) else []
    if not trace_tool_calls:
        trace_tool_calls = trajectory_audit.get("tool_events") if isinstance(trajectory_audit.get("tool_events"), list) else []
    if not trace_code_changes:
        trace_code_changes = trajectory_audit.get("code_changes") if isinstance(trajectory_audit.get("code_changes"), list) else []
    if not trace_bash_commands:
        trace_bash_commands = trajectory_audit.get("bash_commands") if isinstance(trajectory_audit.get("bash_commands"), list) else []

    result_sha = _sha256_file(result_path)
    traj_sha = _sha256_file(trajectory_path) if trajectory_path else None
    tx_sha = _sha256_file(transcript_path) if transcript_path else None

    record = TaskRecord(
        suite=suite,
        run_dir=run_dir_name,
        config=config_name,
        task_name=task_name,
        task_dir=rel_task_dir,
        status=status,
        reward=reward,
        timed_out=timed_out,
        wall_clock_seconds=wall_clock_seconds,
        agent_execution_seconds=agent_execution_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_tokens=cache_tokens,
        tool_calls_total=tool_calls_total,
        tool_calls_mcp=tool_calls_mcp,
        tool_calls_local=tool_calls_local,
        mcp_ratio=mcp_ratio,
        search_calls_keyword=search_calls_keyword,
        search_calls_nls=search_calls_nls,
        search_calls_deepsearch=search_calls_deepsearch,
        tool_calls_by_name=tool_calls_by_name,
        sample_tool_calls=sample_tool_calls,
        conversation_preview=[
            {
                "type": str(event.get("type") or ""),
                "subtype": str(event.get("subtype") or ""),
                "tool": str(event.get("tool") or ""),
                "text": str(event.get("text") or ""),
            }
            for event in transcript_audit.get("messages", [])[:CONVERSATION_PREVIEW_LIMIT]
            if isinstance(event, dict)
        ],
        started_at=started_at,
        trace_available={
            "trajectory": trace_paths["trajectory"] is not None,
            "transcript": trace_paths["transcript"] is not None,
        },
        trace_paths=trace_paths,
        bundled_trace_paths={"trajectory": None, "transcript": None},
        checksums={
            "result_json_sha256": result_sha,
            "trajectory_sha256": traj_sha,
            "transcript_sha256": tx_sha,
        },
        repositories=repositories,
        repository_details=repository_details,
        benchmark_metadata=benchmark_metadata,
        benchmark_task_path=benchmark_task_path,
        instruction_text=instruction_text,
        agent_name=agent_name,
        model_name=model_name,
        task_category=task_category,
        context_metrics=context_metrics,
        ir_metrics=ir_metrics,
        flags=flags,
        trace_events=trace_events[:TASK_PAGE_EVENT_LIMIT],
        trace_tool_calls=trace_tool_calls[:TASK_PAGE_EVENT_LIMIT],
        trace_code_changes=trace_code_changes[:TASK_PAGE_EVENT_LIMIT],
        trace_bash_commands=trace_bash_commands[:TASK_PAGE_EVENT_LIMIT],
    )

    audit_payload = {
        "provenance": {
            "suite": suite,
            "run_dir": run_dir_name,
            "config": config_name,
            "task_name": task_name,
            "task_category": task_category,
            "task_dir": str(task_dir.relative_to(PROJECT_ROOT)),
            "result_path": str(result_path.relative_to(PROJECT_ROOT)),
            "trace_paths": trace_paths,
            "checksums": record.checksums,
        },
        "score": {
            "status": status,
            "reward": reward,
            "timed_out": timed_out,
        },
        "metrics": {
            "wall_clock_seconds": wall_clock_seconds,
            "agent_execution_seconds": agent_execution_seconds,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_tokens": cache_tokens,
            "tool_calls_total": tool_calls_total,
            "tool_calls_mcp": tool_calls_mcp,
            "tool_calls_local": tool_calls_local,
            "mcp_ratio": mcp_ratio,
            "search_calls_keyword": search_calls_keyword,
            "search_calls_nls": search_calls_nls,
            "search_calls_deepsearch": search_calls_deepsearch,
            "tool_calls_by_name": tool_calls_by_name,
            "context_metrics": context_metrics,
            "ir_metrics": ir_metrics,
            "repositories": repositories,
            "repository_details": repository_details,
            "flags": flags,
        },
        "parsed_trace": {
            "transcript": transcript_audit,
            "trajectory": trajectory_audit,
        },
    }
    return record, audit_payload


def _slug(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip())
    normalized = normalized.strip("-")
    return normalized or "item"


def _normalize_config_for_suite(suite: str, config: str) -> str:
    if suite in SDLC_SUITES:
        if config == "baseline":
            return "baseline-local-direct"
        if config == "mcp":
            return "mcp-remote-direct"
    elif suite.startswith(("csb_org_", "ccb_mcp_")):
        if config == "baseline":
            return "baseline-local-artifact"
        if config == "mcp":
            return "mcp-remote-artifact"
    return config


def _fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _suite_from_run_dir(run_dir_name: str, prefix_map: dict[str, str]) -> str:
    suite = detect_suite(run_dir_name, prefix_map)
    if suite and suite not in {"csb_org", "csb_sdlc", "ccb_mcp"}:
        return suite

    if run_dir_name.startswith(("ccb_", "csb_")):
        parts = run_dir_name.split("_")
        # csb_org_* or ccb_mcp_* suites
        if len(parts) >= 3 and parts[1] in ("mcp", "org"):
            return "_".join(parts[:3])
        # csb_sdlc_* suites
        if len(parts) >= 3 and parts[1] == "sdlc":
            return "_".join(parts[:3])
        if len(parts) >= 2:
            return "_".join(parts[:2])

    return "unknown"


def _to_task_dict(
    record: TaskRecord,
    task_page: str,
    output_dir: Path,
    repo_blob_base: str,
) -> dict[str, Any]:
    canonical_name = _canonical_task_name(record.task_name)
    benchmark_repo_path: str | None = None
    benchmark_dir = PROJECT_ROOT / "benchmarks" / record.suite / canonical_name
    if benchmark_dir.is_dir():
        benchmark_repo_path = _canonicalize_benchmark_path(benchmark_dir)

    task_page_repo_path: str | None = None
    try:
        task_page_repo_path = str((output_dir / task_page).relative_to(PROJECT_ROOT))
    except ValueError:
        task_page_repo_path = None

    audit_repo_path: str | None = None
    if record.audit_page:
        try:
            audit_repo_path = str((output_dir / record.audit_page).relative_to(PROJECT_ROOT))
        except ValueError:
            audit_repo_path = None

    trajectory_repo_path: str | None = None
    bundled_traj = record.bundled_trace_paths.get("trajectory")
    if bundled_traj:
        try:
            trajectory_repo_path = str((output_dir / bundled_traj).relative_to(PROJECT_ROOT))
        except ValueError:
            trajectory_repo_path = None

    return {
        "suite": record.suite,
        "run_dir": record.run_dir,
        "config": record.config,
        "task_name": record.task_name,
        "agent_name": record.agent_name,
        "model_name": record.model_name,
        "repositories": record.repositories,
        "repository_details": record.repository_details,
        "task_category": record.task_category,
        "benchmark_task_path": record.benchmark_task_path,
        **record.benchmark_metadata,
        "started_at": record.started_at,
        "task_dir": record.task_dir,
        "status": record.status,
        "reward": record.reward,
        "timed_out": record.timed_out,
        "wall_clock_seconds": record.wall_clock_seconds,
        "agent_execution_seconds": record.agent_execution_seconds,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cache_tokens": record.cache_tokens,
        "tool_calls_total": record.tool_calls_total,
        "tool_calls_mcp": record.tool_calls_mcp,
        "tool_calls_local": record.tool_calls_local,
        "mcp_ratio": record.mcp_ratio,
        "search_calls_keyword": record.search_calls_keyword,
        "search_calls_nls": record.search_calls_nls,
        "search_calls_deepsearch": record.search_calls_deepsearch,
        "tool_calls_by_name": record.tool_calls_by_name,
        "context_metrics": record.context_metrics,
        "ir_metrics": record.ir_metrics,
        "flags": record.flags,
        "sample_tool_calls": record.sample_tool_calls,
        "trace_available": record.trace_available,
        "trace_paths": record.trace_paths,
        "bundled_trace_paths": record.bundled_trace_paths,
        "checksums": record.checksums,
        "audit_page": record.audit_page,
        "task_page": task_page,
        "task_page_github": _github_blob_url(repo_blob_base, task_page_repo_path),
        "benchmark_path": benchmark_repo_path,
        "benchmark_github": _github_blob_url(repo_blob_base, benchmark_repo_path),
        "audit_github": _github_blob_url(repo_blob_base, audit_repo_path),
        "trajectory_github": _github_blob_url(repo_blob_base, trajectory_repo_path),
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for source, replacement in EXPORT_TEXT_REWRITES.items():
        content = content.replace(source, replacement)
    path.write_text(content)


def _build_task_page(record: TaskRecord) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "-"))

    def fmt_json(value: Any) -> str:
        try:
            return esc(json.dumps(value, indent=2, sort_keys=True))
        except Exception:
            return esc(str(value))

    def truncate_text(text: str, limit: int = 1800) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... (truncated)"

    repo_text = ", ".join(record.repositories) if record.repositories else "-"
    task_category_text = record.task_category or "-"
    benchmark_text = record.benchmark_task_path or "-"
    instruction_text = record.instruction_text or "No instruction found."
    audit_href = f"../{record.audit_page}" if record.audit_page else None
    trajectory_href = f"../{record.bundled_trace_paths['trajectory']}" if record.bundled_trace_paths.get("trajectory") else None
    transcript_href = f"../{record.bundled_trace_paths['transcript']}" if record.bundled_trace_paths.get("transcript") else None

    repo_rows = []
    for repo_meta in record.repository_details:
        if not isinstance(repo_meta, dict):
            continue
        repo_name = str(repo_meta.get("name") or "")
        if not repo_name:
            continue
        repo_language = str(repo_meta.get("language") or "-")
        repo_size = _safe_int(repo_meta.get("approx_loc"))
        repo_size_text = f"~{repo_size:,}" if repo_size is not None else "-"
        repo_rows.append(
            f"<tr><td><code>{esc(repo_name)}</code></td><td>{esc(repo_language)}</td><td>{esc(repo_size_text)}</td></tr>"
        )
    repo_rows_html = "".join(repo_rows) or "<tr><td colspan='3'>No repository metadata available</td></tr>"

    benchmark_rows = []
    metadata = record.benchmark_metadata
    if metadata.get("repo_primary_language") is not None:
        benchmark_rows.append(f"<tr><td>Primary Language</td><td>{esc(metadata.get('repo_primary_language'))}</td></tr>")
    if metadata.get("repo_size_mb") is not None:
        benchmark_rows.append(
            f"<tr><td>Repository Size (MB)</td><td>{esc(_fmt_float(_safe_float(metadata.get('repo_size_mb')), 3))}</td></tr>"
        )
    if metadata.get("repo_approx_loc") is not None:
        benchmark_rows.append(
            f"<tr><td>Lines of Code (cloc)</td><td>{esc(_fmt_int(_safe_int(metadata.get('repo_approx_loc'))))}</td></tr>"
        )
    if metadata.get("files_count") is not None:
        benchmark_rows.append(
            f"<tr><td>Files Count</td><td>{esc(_fmt_int(_safe_int(metadata.get('files_count'))))}</td></tr>"
        )
    if metadata.get("repo_file_count") is not None:
        benchmark_rows.append(
            f"<tr><td>Repo File Count</td><td>{esc(_fmt_int(_safe_int(metadata.get('repo_file_count'))))}</td></tr>"
        )
    if metadata.get("repo_directory_count") is not None:
        benchmark_rows.append(
            f"<tr><td>Repo Directory Count</td><td>{esc(_fmt_int(_safe_int(metadata.get('repo_directory_count'))))}</td></tr>"
        )
    if metadata.get("context_length") is not None:
        benchmark_rows.append(
            f"<tr><td>Context Length</td><td>{esc(_fmt_int(_safe_int(metadata.get('context_length'))))}</td></tr>"
        )
    if metadata.get("repo_complexity") is not None:
        benchmark_rows.append(
            f"<tr><td>Repo Complexity</td><td>{esc(_fmt_float(_safe_float(metadata.get('repo_complexity')), 3))} "
            f"({esc(metadata.get('repo_complexity_label') or '-')})</td></tr>"
        )
    if metadata.get("task_complexity") is not None:
        benchmark_rows.append(
            f"<tr><td>Task Complexity</td><td>{esc(_fmt_float(_safe_float(metadata.get('task_complexity')), 3))} "
            f"({esc(metadata.get('task_complexity_label') or '-')})</td></tr>"
        )
    repo_languages = metadata.get("repo_languages")
    if isinstance(repo_languages, list) and repo_languages:
        language_parts = []
        for item in repo_languages:
            if not isinstance(item, dict):
                continue
            language = item.get("language")
            files = _safe_int(item.get("files"))
            if not language:
                continue
            language_parts.append(f"{language} ({files})" if files is not None else str(language))
        if language_parts:
            benchmark_rows.append(f"<tr><td>Repo Languages</td><td>{esc(', '.join(language_parts))}</td></tr>")
    benchmark_rows_html = "".join(benchmark_rows) or "<tr><td colspan='2'>No benchmark metadata available</td></tr>"

    flag_items = [TASK_FLAG_LABELS.get(flag, flag) for flag in record.flags]
    flag_html = ""
    if flag_items:
        items = "".join(f"<li>{esc(flag)}</li>" for flag in flag_items)
        flag_html = (
            "<div class='panel' style='border-color:#6b3f2a;background:#231711'>"
            "<h2>Warnings</h2>"
            f"<ul>{items}</ul>"
            "</div>"
        )

    tool_rows = []
    for tool, count in sorted((record.tool_calls_by_name or {}).items(), key=lambda kv: (-kv[1], kv[0])):
        tool_rows.append(f"<tr><td><code>{esc(tool)}</code></td><td>{int(count)}</td></tr>")
    tool_rows_html = "".join(tool_rows) or "<tr><td colspan='2'>No tool counts available</td></tr>"

    context_rows = []
    for key, value in sorted(record.context_metrics.items()):
        context_rows.append(f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>")
    context_rows_html = "".join(context_rows) or "<tr><td colspan='2'>No context metrics available</td></tr>"

    ir_rows = []
    for key, value in sorted(record.ir_metrics.items()):
        ir_rows.append(f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>")
    ir_rows_html = "".join(ir_rows) or "<tr><td colspan='2'>No IR metrics available</td></tr>"

    trace_rows = []
    for idx, event in enumerate(record.trace_events[:TASK_PAGE_EVENT_LIMIT], start=1):
        text = truncate_text(str(event.get("text") or ""))
        tool = event.get("tool") or "-"
        trace_rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{esc(event.get('timestamp') or '-')}</td>"
            f"<td>{esc(event.get('type') or '-')}</td>"
            f"<td>{esc(event.get('subtype') or '-')}</td>"
            f"<td><code>{esc(tool)}</code></td>"
            f"<td><pre>{esc(text)}</pre></td>"
            "</tr>"
        )
    trace_rows_html = "".join(trace_rows) or "<tr><td colspan='6'>No conversation events parsed</td></tr>"

    tool_call_blocks = []
    for idx, call in enumerate(record.trace_tool_calls[:TASK_PAGE_EVENT_LIMIT], start=1):
        tool_name = call.get("tool") or "unknown"
        call_input = call.get("input", call.get("arguments", {}))
        call_output = call.get("output")
        if call_output is None and isinstance(call.get("output_text"), str) and call.get("output_text"):
            call_output = call.get("output_text")
        output_html = f"<h4>Output</h4><pre>{fmt_json(call_output)}</pre>" if call_output is not None else ""
        tool_call_blocks.append(
            "<details>"
            f"<summary>{idx}. <code>{esc(tool_name)}</code> @ {esc(call.get('timestamp') or '-')}</summary>"
            f"<h4>Input</h4><pre>{fmt_json(call_input)}</pre>"
            f"{output_html}"
            "</details>"
        )
    tool_call_html = "".join(tool_call_blocks) or "<p>No tool call payloads parsed.</p>"

    change_blocks = []
    for idx, change in enumerate(record.trace_code_changes[:TASK_PAGE_EVENT_LIMIT], start=1):
        change_type = str(change.get("type") or "change")
        file_path = str(change.get("file_path") or "")
        if change_type == "edit":
            before = truncate_text(str(change.get("old_string") or ""))
            after = truncate_text(str(change.get("new_string") or ""))
            body = (
                "<div class='split'>"
                f"<div><h4>Before</h4><pre>{esc(before)}</pre></div>"
                f"<div><h4>After</h4><pre>{esc(after)}</pre></div>"
                "</div>"
            )
        else:
            content = truncate_text(str(change.get("content") or ""))
            body = f"<pre>{esc(content)}</pre>"
        change_blocks.append(
            "<details>"
            f"<summary>{idx}. {esc(change_type.upper())} <code>{esc(file_path)}</code></summary>"
            f"{body}"
            "</details>"
        )
    change_html = "".join(change_blocks) or "<p>No code changes parsed.</p>"

    bash_blocks = []
    for idx, item in enumerate(record.trace_bash_commands[:TASK_PAGE_EVENT_LIMIT], start=1):
        command = str(item.get("command") or "")
        bash_blocks.append(f"<pre>{idx}. $ {esc(command)}</pre>")
    bash_html = "".join(bash_blocks) or "<p>No bash commands parsed.</p>"

    links = []
    if audit_href:
        links.append(f"<a href='{esc(audit_href)}'>audit.json</a>")
    if trajectory_href:
        links.append(f"<a href='{esc(trajectory_href)}'>trajectory.json</a>")
    if transcript_href:
        links.append(f"<a href='{esc(transcript_href)}'>transcript</a>")
    links_html = " | ".join(links) if links else "-"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(record.task_name)} - Official Results</title>
  <style>
    :root {{ --bg:#0b1117; --panel:#131d27; --border:#2a3a4a; --text:#e9f0f6; --muted:#9fb1c2; --accent:#4fd39b; }}
    body {{ margin:0; font-family: ui-sans-serif,system-ui,-apple-system,sans-serif; background:linear-gradient(180deg,#0b1117,#0f1720); color:var(--text); }}
    .wrap {{ max-width:1200px; margin:0 auto; padding:20px; }}
    h1,h2,h3,h4 {{ margin:0 0 10px; }}
    .panel {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:14px; margin-bottom:14px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; }}
    .metric {{ background:#0f1821; border:1px solid var(--border); border-radius:10px; padding:10px; }}
    .metric .k {{ color:var(--muted); font-size:12px; }}
    .metric .v {{ font-size:20px; margin-top:4px; }}
    .meta {{ color:var(--muted); font-size:13px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--border); padding:8px; text-align:left; vertical-align:top; font-size:13px; }}
    th {{ color:var(--muted); }}
    code,pre {{ font-family: ui-monospace,SFMono-Regular,Menlo,monospace; }}
    pre {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#0d151d; border:1px solid var(--border); border-radius:8px; padding:8px; margin:8px 0; }}
    details {{ border:1px solid var(--border); border-radius:10px; padding:8px 10px; margin:8px 0; background:#0f1821; }}
    summary {{ cursor:pointer; color:var(--accent); }}
    a {{ color:var(--accent); text-decoration:none; }}
    .split {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
    @media (max-width: 900px) {{ .split {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{esc(record.task_name)}</h1>
    <p class="meta">Suite <code>{esc(record.suite)}</code> | Run <code>{esc(record.run_dir)}</code> | Config <code>{esc(record.config)}</code></p>
    {flag_html}

    <div class="panel">
      <h2>Task Information</h2>
      <div class="grid">
        <div class="metric"><div class="k">Repositories</div><div class="v" style="font-size:14px">{esc(repo_text)}</div></div>
        <div class="metric"><div class="k">Task ID</div><div class="v" style="font-size:14px">{esc(record.task_name)}</div></div>
        <div class="metric"><div class="k">Task Category</div><div class="v" style="font-size:14px">{esc(task_category_text)}</div></div>
        <div class="metric"><div class="k">Agent</div><div class="v" style="font-size:16px">{esc(record.agent_name or "-")}</div></div>
        <div class="metric"><div class="k">Model</div><div class="v" style="font-size:16px">{esc(record.model_name or "-")}</div></div>
      </div>
      <p class="meta" style="margin-top:10px">Benchmark path: <code>{esc(benchmark_text)}</code></p>
      <details>
        <summary>Repository metadata</summary>
        <table>
          <thead><tr><th>Repository</th><th>Primary Language</th><th>Approx Size (LOC)</th></tr></thead>
          <tbody>{repo_rows_html}</tbody>
        </table>
      </details>
      <details>
        <summary>Benchmark metadata</summary>
        <table>
          <tbody>{benchmark_rows_html}</tbody>
        </table>
      </details>
      <details>
        <summary>Task instruction sent to agent</summary>
        <pre>{esc(instruction_text)}</pre>
      </details>
    </div>

    <div class="panel">
      <h2>Execution Metrics</h2>
      <div class="grid">
        <div class="metric"><div class="k">Reward</div><div class="v">{_fmt_float(record.reward, 4)}</div></div>
        <div class="metric"><div class="k">Status</div><div class="v">{esc(record.status)}</div></div>
        <div class="metric"><div class="k">Total Time</div><div class="v">{_fmt_float(record.wall_clock_seconds, 1)}s</div></div>
        <div class="metric"><div class="k">Agent Time</div><div class="v">{_fmt_float(record.agent_execution_seconds, 1)}s</div></div>
        <div class="metric"><div class="k">Input Tokens</div><div class="v">{_fmt_int(record.input_tokens)}</div></div>
        <div class="metric"><div class="k">Output Tokens</div><div class="v">{_fmt_int(record.output_tokens)}</div></div>
        <div class="metric"><div class="k">Cache Tokens</div><div class="v">{_fmt_int(record.cache_tokens)}</div></div>
        <div class="metric"><div class="k">Tool Calls</div><div class="v">{_fmt_int(record.tool_calls_total)}</div></div>
        <div class="metric"><div class="k">MCP Ratio</div><div class="v">{_fmt_float(record.mcp_ratio, 3)}</div></div>
      </div>
      <p class="meta">Raw traces: {links_html}</p>
      <details>
        <summary>Tool Breakdown</summary>
        <table><thead><tr><th>Tool</th><th>Calls</th></tr></thead><tbody>{tool_rows_html}</tbody></table>
      </details>
      <details>
        <summary>Context Metrics (task_metrics / IR analysis)</summary>
        <h3>Context</h3>
        <table><tbody>{context_rows_html}</tbody></table>
        <h3 style="margin-top:10px">IR</h3>
        <table><tbody>{ir_rows_html}</tbody></table>
      </details>
    </div>

    <div class="panel">
      <h2>Agent Trace</h2>
      <details open>
        <summary>Conversation History ({len(record.trace_events)})</summary>
        <table>
          <thead><tr><th>#</th><th>Timestamp</th><th>Type</th><th>Subtype</th><th>Tool</th><th>Text</th></tr></thead>
          <tbody>{trace_rows_html}</tbody>
        </table>
      </details>
      <details>
        <summary>Tool Calls ({len(record.trace_tool_calls)})</summary>
        {tool_call_html}
      </details>
      <details>
        <summary>Code Changes ({len(record.trace_code_changes)})</summary>
        {change_html}
      </details>
      <details>
        <summary>Bash Commands ({len(record.trace_bash_commands)})</summary>
        {bash_html}
      </details>
    </div>
  </div>
</body>
</html>
"""


def _build_run_page(run_dir: str, config_tasks: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    lines.append(f"# {run_dir}")
    lines.append("")

    for config, tasks in sorted(config_tasks.items()):
        rewards = [t["reward"] for t in tasks]
        passes = sum(1 for t in tasks if t["status"] == "passed")
        mean_reward = statistics.mean(rewards) if rewards else 0.0
        pass_rate = (passes / len(tasks)) if tasks else 0.0

        lines.append(f"## {config}")
        lines.append("")
        lines.append(f"- Valid tasks: `{len(tasks)}`")
        lines.append(f"- Mean reward: `{mean_reward:.3f}`")
        lines.append(f"- Pass rate: `{pass_rate:.3f}`")
        lines.append("")

        lines.append("| Task | Status | Reward | MCP Ratio | Tool Calls | Trace |")
        lines.append("|---|---|---:|---:|---:|---|")

        tasks_sorted = sorted(tasks, key=lambda x: (x["status"], x["task_name"]))
        for task in tasks_sorted:
            trace = []
            if task["trace_available"]["trajectory"]:
                trace.append("traj")
            if task["trace_available"]["transcript"]:
                trace.append("tx")
            trace_label = ", ".join(trace) if trace else "-"
            lines.append(
                "| "
                f"[{task['task_name']}]({task['task_page']}) | "
                f"`{task['status']}` | "
                f"{task['reward']:.3f} | "
                f"{_fmt_float(task['mcp_ratio'])} | "
                f"{_fmt_int(task['tool_calls_total'])} | "
                f"{trace_label} |"
            )
        lines.append("")

    return "\n".join(lines)


def _build_suite_page(
    suite: str,
    run_config_tasks: dict[tuple[str, str], list[dict[str, Any]]],
    all_suite_tasks: list[dict[str, Any]] | None = None,
    run_history: dict[str, dict] | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# {suite}")
    lines.append("")

    # ---- Run/Config summary (unchanged) ----
    lines.append("## Run/Config Summary")
    lines.append("")
    lines.append("| Run | Config | Valid Tasks | Mean Reward | Pass Rate |")
    lines.append("|---|---|---:|---:|---:|")
    for (run_dir, config), tasks in sorted(run_config_tasks.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        rewards = [t["reward"] for t in tasks]
        passes = sum(1 for t in tasks if t["status"] == "passed")
        mean_reward = statistics.mean(rewards) if rewards else 0.0
        pass_rate = (passes / len(tasks)) if tasks else 0.0
        lines.append(
            f"| [{run_dir}](../runs/{_slug(run_dir)}.md) | `{config}` | {len(tasks)} | {mean_reward:.3f} | {pass_rate:.3f} |"
        )
    lines.append("")

    # ---- Consolidated Tasks table (sorted by canonical task name) ----
    lines.append("## Tasks")
    lines.append("")

    # Collect all tasks from deduped view, grouped by (canonical_name, config)
    deduped_rows: list[dict[str, Any]] = []
    for _rc, tasks in run_config_tasks.items():
        deduped_rows.extend(tasks)

    # Count runs per (canonical_name, config) from all_suite_tasks if available
    run_counts: dict[tuple[str, str], int] = defaultdict(int)
    if all_suite_tasks:
        for t in all_suite_tasks:
            if t.get("suite") == suite:
                cn = _canonical_task_name(t["task_name"])
                run_counts[(cn, t["config"])] += 1

    lines.append("| Task | Benchmark | Config | Status | Reward | Runs | MCP Ratio |")
    lines.append("|---|---|---|---|---:|---:|---:|")

    for task in sorted(deduped_rows, key=lambda t: (_canonical_task_name(t["task_name"]), t["config"])):
        cn = _canonical_task_name(task["task_name"])
        bm_link = _benchmark_link(suite, cn)
        bm_cell = f"[source]({bm_link})" if bm_link else "—"
        n_runs = run_counts.get((cn, task["config"]), 1)
        runs_cell = str(n_runs) if n_runs > 1 else "1"

        lines.append(
            f"| [{task['task_name']}](../{task['task_page']}) | "
            f"{bm_cell} | "
            f"`{task['config']}` | "
            f"`{task['status']}` | "
            f"{task['reward']:.3f} | "
            f"{runs_cell} | "
            f"{_fmt_float(task['mcp_ratio'])} |"
        )
    lines.append("")

    # ---- Multi-Run Variance section ----
    # Use MANIFEST run_history if available
    rh = run_history or {}
    variance_rows: list[dict[str, Any]] = []
    for rh_key, tasks_data in rh.items():
        parts = rh_key.split("/")
        if len(parts) != 2:
            continue
        rh_suite, rh_config = parts
        if rh_suite != suite:
            continue
        for task_name, info in tasks_data.items():
            if info.get("n_runs", 1) <= 1:
                continue
            rewards = [r["reward"] for r in info.get("runs", [])]
            cn = task_name.lower() if task_name.startswith("CCX-") else task_name
            bm_link = _benchmark_link(suite, cn)
            variance_rows.append({
                "task_name": task_name,
                "canonical_name": cn,
                "config": rh_config,
                "n_runs": info["n_runs"],
                "mean_reward": info.get("mean_reward", 0.0),
                "std_reward": info.get("std_reward", 0.0),
                "rewards": rewards,
                "run_dirs": [r.get("run_dir", "?") for r in info.get("runs", [])],
                "bm_link": bm_link,
            })

    if variance_rows:
        variance_rows.sort(key=lambda r: (r["canonical_name"], r["config"]))
        lines.append("## Multi-Run Variance")
        lines.append("")
        lines.append(f"Tasks with multiple valid runs ({len(variance_rows)} task/config pairs).")
        lines.append("")
        lines.append("| Task | Benchmark | Config | Runs | Mean | Std | Individual Rewards |")
        lines.append("|---|---|---|---:|---:|---:|---|")
        for vr in variance_rows:
            bm_cell = f"[source]({vr['bm_link']})" if vr["bm_link"] else "—"
            rewards_str = ", ".join(f"{r:.3f}" for r in vr["rewards"])
            lines.append(
                f"| {vr['task_name']} | "
                f"{bm_cell} | "
                f"`{vr['config']}` | "
                f"{vr['n_runs']} | "
                f"{vr['mean_reward']:.3f} | "
                f"{vr['std_reward']:.3f} | "
                f"{rewards_str} |"
            )
        lines.append("")

    return "\n".join(lines)


def _build_root_readme(suite_summaries: list[dict[str, Any]], run_summaries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    generated = datetime.now(timezone.utc).isoformat()
    lines.append("# Official Results Browser")
    lines.append("")
    lines.append("This bundle is generated from `runs/analysis/` and includes only valid scored tasks (`passed`/`failed` with numeric reward) that pass config-specific validity checks.")
    lines.append("")
    lines.append(f"Generated: `{generated}`")
    lines.append("")
    lines.append("## Local Browse")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/export_official_results.py --serve")
    lines.append("```")
    lines.append("")
    lines.append("Suite-level views are deduplicated to the latest row per `suite + config + task_name`.")
    lines.append("Historical reruns/backfills remain available in `data/official_results.json` under `all_tasks`.")
    lines.append("")
    lines.append("## Suite/Config Summary")
    lines.append("")
    lines.append("| Suite | Config | Valid Tasks | Min Required | Mean Reward | Pass Rate | Coverage |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in suite_summaries:
        coverage_flag = "FLAG: below minimum" if row.get("below_minimum_valid_tasks") else "ok"
        lines.append(
            f"| [{row['suite']}](suites/{row['suite']}.md) | `{row['config']}` | "
            f"{row['task_count']} | {row.get('min_required_valid_tasks', '-')} | "
            f"{row['mean_reward']:.3f} | {row['pass_rate']:.3f} | {coverage_flag} |"
        )
    lines.append("")
    lines.append("<details>")
    lines.append("<summary>Run/Config Summary</summary>")
    lines.append("")
    lines.append("")
    lines.append("| Run | Suite | Config | Valid Tasks | Mean Reward | Pass Rate |")
    lines.append("|---|---|---|---:|---:|---:|")
    for row in run_summaries:
        lines.append(
            f"| [{row['run_dir']}](runs/{row['run_page']}) | `{row['suite']}` | `{row['config']}` | "
            f"{row['task_count']} | {row['mean_reward']:.3f} | {row['pass_rate']:.3f} |"
        )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append("`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.")
    return "\n".join(lines)


def _task_sort_key(task: dict[str, Any]) -> tuple[datetime, str, str]:
    started_at = task.get("started_at")
    started_dt = _parse_iso_timestamp(started_at)
    if started_dt is None:
        started_dt = datetime.fromtimestamp(0, tz=timezone.utc)
    return (started_dt, str(task.get("run_dir", "")), str(task.get("task_dir", "")))


def _dedupe_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep latest task result per suite+config+task_name for suite-level views."""
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for task in tasks:
        key = (str(task["suite"]), str(task["config"]), str(task["task_name"]))
        prev = best.get(key)
        if prev is None or _task_sort_key(task) > _task_sort_key(prev):
            best[key] = task
    return sorted(best.values(), key=lambda t: (t["suite"], t["config"], t["task_name"]))


def _suite_min_required_valid_tasks(suite: str, rows: list[dict[str, Any]]) -> int:
    explicit = SDLC_MIN_VALID_TASKS.get(suite)
    if explicit is not None:
        return explicit
    # For non-SDLC suites, require parity with the best-covered config in-suite.
    if not rows:
        return 0
    return max(int(r.get("task_count", 0)) for r in rows)


def _build_index_html() -> str:
    return """<!doctype html>
<html lang=\"en\"> 
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Official Results Browser</title>
  <style>
    :root { --bg:#0f1419; --panel:#182028; --text:#eef3f8; --muted:#9bb0c3; --accent:#47d18c; --warn:#ffcc66; }
    body { margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 20px; }
    .controls { display:flex; gap:12px; flex-wrap:wrap; margin-bottom: 14px; }
    .meta { color: var(--muted); font-size: 12px; margin: 4px 0 10px; }
    button { background: transparent; color: var(--text); border:1px solid #2e3d4a; border-radius:8px; padding:8px 10px; cursor:pointer; }
    select,input { background:var(--panel); color:var(--text); border:1px solid #2e3d4a; border-radius:8px; padding:8px; }
    table { width:100%; border-collapse: collapse; background:var(--panel); border-radius:10px; overflow:hidden; }
    th,td { border-bottom: 1px solid #2d3a45; padding: 8px 10px; text-align:left; font-size: 13px; }
    th { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    a { color: var(--accent); text-decoration: none; }
    .pill { padding:2px 8px; border-radius:999px; font-size:12px; }
    .passed { background: rgba(71,209,140,0.2); }
    .failed { background: rgba(255,204,102,0.2); }
    .task-meta { margin-top:4px; font-size:12px; color:var(--muted); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>Official Results Browser</h1>
    <div class=\"controls\">
      <select id=\"suiteFilter\"><option value=\"\">All suites</option></select>
      <select id=\"datasetFilter\">
        <option value=\"all\">All task runs</option>
        <option value=\"latest\">Latest per suite+config+task</option>
      </select>
      <select id=\"runFilter\"><option value=\"\">All runs</option></select>
      <select id=\"configFilter\"><option value=\"\">All configs</option></select>
      <select id=\"statusFilter\"><option value=\"\">All statuses</option><option>passed</option><option>failed</option></select>
      <input id=\"taskSearch\" placeholder=\"Search task\" />
      <button id=\"clearFilters\" type=\"button\">Clear filters</button>
    </div>
    <div id=\"stats\" class=\"meta\"></div>
    <table>
      <thead><tr><th>Suite</th><th>Run</th><th>Config</th><th>Task</th><th>Status</th><th>Reward</th><th>MCP ratio</th><th>Tools</th><th>Flags</th><th>Trace</th></tr></thead>
      <tbody id=\"rows\"></tbody>
    </table>
  </div>
  <script>
    const rowsEl = document.getElementById('rows');
    const suiteFilter = document.getElementById('suiteFilter');
    const datasetFilter = document.getElementById('datasetFilter');
    const runFilter = document.getElementById('runFilter');
    const configFilter = document.getElementById('configFilter');
    const statusFilter = document.getElementById('statusFilter');
    const taskSearch = document.getElementById('taskSearch');
    const clearFilters = document.getElementById('clearFilters');
    const statsEl = document.getElementById('stats');

    function fmt(v, d=3) { return (v===null || v===undefined) ? '-' : Number(v).toFixed(d); }
    function fmtInt(v) { return (v===null || v===undefined) ? '-' : Number(v).toLocaleString(); }
    function uniqueSorted(values) { return [...new Set(values)].sort(); }
    function resetOptions(selectEl, allLabel, values) {
      const previous = selectEl.value;
      selectEl.innerHTML = '';
      selectEl.add(new Option(allLabel, ''));
      values.forEach(v => selectEl.add(new Option(v, v)));
      if (previous && values.includes(previous)) {
        selectEl.value = previous;
      } else {
        selectEl.value = '';
      }
    }

    fetch('data/official_results.json').then(r => r.json()).then(data => {
      const allTasks = data.all_tasks || data.tasks || [];
      const dedupedTasks = data.tasks || [];
      const suites = uniqueSorted(allTasks.map(t => t.suite || 'unknown'));
      suites.forEach(s => suiteFilter.add(new Option(s, s)));
      resetOptions(runFilter, 'All runs', uniqueSorted(allTasks.map(t => t.run_dir)));
      resetOptions(configFilter, 'All configs', uniqueSorted(allTasks.map(t => t.config)));
      // Avoid browser form-state restoration narrowing results unexpectedly.
      suiteFilter.value = '';
      datasetFilter.value = 'all';
      runFilter.value = '';
      configFilter.value = '';
      statusFilter.value = '';
      taskSearch.value = '';

      const render = () => {
        const dataset = datasetFilter.value || 'all';
        const tasks = dataset === 'latest' ? dedupedTasks : allTasks;
        const suiteScoped = suiteFilter.value
          ? tasks.filter(t => (t.suite || 'unknown') === suiteFilter.value)
          : tasks;
        resetOptions(runFilter, 'All runs', uniqueSorted(suiteScoped.map(t => t.run_dir)));
        const runScoped = runFilter.value
          ? suiteScoped.filter(t => t.run_dir === runFilter.value)
          : suiteScoped;
        resetOptions(configFilter, 'All configs', uniqueSorted(runScoped.map(t => t.config)));
        const sfu = suiteFilter.value;
        const rf = runFilter.value;
        const cf = configFilter.value;
        const sf = statusFilter.value;
        const q = taskSearch.value.trim().toLowerCase();
        const filtered = tasks.filter(t =>
          (!sfu || (t.suite || 'unknown') === sfu) &&
          (!rf || t.run_dir === rf) &&
          (!cf || t.config === cf) &&
          (!sf || t.status === sf) &&
          (!q || t.task_name.toLowerCase().includes(q))
        );
        const limited = filtered.slice(0, 1200);
        const active = [];
        if (sfu) active.push(`suite=${sfu}`);
        if (rf) active.push(`run=${rf}`);
        if (cf) active.push(`config=${cf}`);
        if (sf) active.push(`status=${sf}`);
        if (q) active.push(`search=${q}`);

        rowsEl.innerHTML = '';
        limited.forEach(t => {
            const tr = document.createElement('tr');
            const trace = `${t.trace_available.trajectory ? 'traj ' : ''}${t.trace_available.transcript ? 'tx' : ''}`.trim() || '-';
            const repoLink = t.task_page_github ? `<a href=\"${t.task_page_github}\" target=\"_blank\" rel=\"noopener\">repo</a>` : '';
            const benchmarkLink = t.benchmark_github ? `<a href=\"${t.benchmark_github}\" target=\"_blank\" rel=\"noopener\">benchmark</a>` : '';
            const trajLink = t.trajectory_github ? `<a href=\"${t.trajectory_github}\" target=\"_blank\" rel=\"noopener\">trajectory</a>` : '';
            const auditLink = t.audit_github ? `<a href=\"${t.audit_github}\" target=\"_blank\" rel=\"noopener\">audit</a>` : '';
            const extras = [repoLink, benchmarkLink, trajLink, auditLink].filter(Boolean).join(' | ');
            const metadata = [];
            if (t.repo_primary_language) metadata.push(`lang=${t.repo_primary_language}`);
            if (t.repo_size_mb !== null && t.repo_size_mb !== undefined) metadata.push(`size=${fmt(t.repo_size_mb, 1)} MB`);
            if (t.repo_complexity !== null && t.repo_complexity !== undefined) metadata.push(`repo_complexity=${fmt(t.repo_complexity, 3)}`);
            if (t.task_complexity !== null && t.task_complexity !== undefined) metadata.push(`task_complexity=${fmt(t.task_complexity, 3)}`);
            if (t.files_count !== null && t.files_count !== undefined) metadata.push(`files=${fmtInt(t.files_count)}`);
            if (t.benchmark_task_path) metadata.push(`path=${t.benchmark_task_path}`);
            tr.innerHTML = `
              <td class=\"mono\">${t.suite || 'unknown'}</td>
              <td class=\"mono\">${t.run_dir}</td>
              <td class=\"mono\">${t.config}</td>
              <td><a href=\"${t.task_page}\">${t.task_name}</a>${extras ? `<div style=\"margin-top:4px;font-size:12px\">${extras}</div>` : ''}${metadata.length ? `<div class=\"task-meta\">${metadata.join(' | ')}</div>` : ''}</td>
              <td><span class=\"pill ${t.status}\">${t.status}</span></td>
              <td>${fmt(t.reward,3)}</td>
              <td>${fmt(t.mcp_ratio,3)}</td>
              <td>${t.tool_calls_total ?? '-'}</td>
              <td>${(t.flags || []).join(', ') || '-'}</td>
              <td>${trace}</td>
            `;
            rowsEl.appendChild(tr);
          });
        const modeLabel = dataset === 'latest' ? 'Latest per suite+config+task' : 'All task runs';
        const capNote = filtered.length > limited.length ? ` (capped to ${limited.length})` : '';
        const activeLabel = active.length ? ` | Active: ${active.join(', ')}` : '';
        statsEl.textContent = `Dataset: ${modeLabel} | Showing ${filtered.length} of ${tasks.length}${capNote}${activeLabel}`;
      };

      suiteFilter.addEventListener('change', render);
      datasetFilter.addEventListener('change', render);
      runFilter.addEventListener('change', render);
      configFilter.addEventListener('change', render);
      statusFilter.addEventListener('change', render);
      taskSearch.addEventListener('input', render);
      clearFilters.addEventListener('click', () => {
        suiteFilter.value = '';
        datasetFilter.value = 'all';
        runFilter.value = '';
        configFilter.value = '';
        statusFilter.value = '';
        taskSearch.value = '';
        render();
      });
      render();
    });
  </script>
</body>
</html>
"""


def _serve_directory(directory: Path, port: int) -> None:
    os.chdir(directory)
    server = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
    print(f"Serving {directory} at http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def build_export(
    runs_dir: Path,
    output_dir: Path,
    run_filter: set[str] | None,
    max_examples: int,
    repo_blob_base: str,
    manifest_only: bool,
) -> dict[str, Any]:
    prefix_map = load_prefix_map(PROJECT_ROOT)
    manifest_path = runs_dir / "MANIFEST.json"
    tracked: set[str] | None = None
    if manifest_path.is_file():
        manifest = load_manifest(manifest_path)
        tracked = tracked_run_dirs_from_manifest(manifest)

    run_dirs = top_level_run_dirs(runs_dir)
    if run_filter:
        run_dirs = [r for r in run_dirs if r.name in run_filter]
    if manifest_only and tracked is not None and tracked:
        run_dirs = [r for r in run_dirs if r.name in tracked]

    tasks_out: list[dict[str, Any]] = []
    excluded_tasks: list[dict[str, Any]] = []

    tasks_dir = output_dir / "tasks"
    runs_pages_dir = output_dir / "runs"
    suite_pages_dir = output_dir / "suites"
    audits_dir = output_dir / "audits"
    traces_dir = output_dir / "traces"

    def _append_task_record(suite: str, run_dir_name: str, config: str, task_dir: Path) -> None:
        normalized_config = _normalize_config_for_suite(suite, config)
        extracted = _extract_task_record(suite, run_dir_name, normalized_config, task_dir, max_examples)
        if extracted is None:
            return
        record, audit_payload = extracted

        exclusion_reasons = _official_exclusion_reasons(record.flags)
        if exclusion_reasons:
            excluded_tasks.append(
                {
                    "suite": suite,
                    "run_dir": run_dir_name,
                    "config": record.config,
                    "task_name": record.task_name,
                    "task_dir": record.task_dir,
                    "flags": list(record.flags),
                    "exclusion_reasons": exclusion_reasons,
                    "started_at": record.started_at,
                }
            )
            return

        base_slug = _slug(f"{run_dir_name}--{config}--{record.task_name}")
        try:
            rel_task_dir = str(task_dir.relative_to(runs_dir))
        except ValueError:
            rel_task_dir = str(task_dir)
        task_suffix = hashlib.sha1(rel_task_dir.encode("utf-8")).hexdigest()[:10]
        task_slug = f"{base_slug}--{task_suffix}"
        bundled_trace_paths: dict[str, str | None] = {"trajectory": None, "transcript": None}
        if record.trace_paths.get("trajectory"):
            src = PROJECT_ROOT / record.trace_paths["trajectory"]
            if src.is_file():
                rel = f"traces/{task_slug}/trajectory.json"
                dst = traces_dir / task_slug / "trajectory.json"
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                bundled_trace_paths["trajectory"] = rel
        if record.trace_paths.get("transcript"):
            src_tx = PROJECT_ROOT / record.trace_paths["transcript"]
            if src_tx.is_file():
                tx_name = src_tx.name
                rel_tx = f"traces/{task_slug}/{tx_name}"
                dst_tx = traces_dir / task_slug / tx_name
                dst_tx.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_tx, dst_tx)
                bundled_trace_paths["transcript"] = rel_tx
        record.bundled_trace_paths = bundled_trace_paths

        audit_page_rel = f"audits/{task_slug}.json"
        record.audit_page = audit_page_rel
        _write_text(audits_dir / f"{task_slug}.json", json.dumps(audit_payload, indent=2, sort_keys=True))
        task_page_rel = f"tasks/{task_slug}.html"
        task_page_path = tasks_dir / f"{task_slug}.html"
        _write_text(task_page_path, _build_task_page(record))

        task_dict = _to_task_dict(
            record,
            task_page_rel,
            output_dir,
            repo_blob_base,
        )
        tasks_out.append(task_dict)

    for run_dir in run_dirs:
        suite = _suite_from_run_dir(run_dir.name, prefix_map)
        configs = discover_configs(run_dir)
        for config in configs:
            config_dir = run_dir / config
            for task_dir in _iter_task_dirs(config_dir):
                _append_task_record(suite, run_dir.name, config, task_dir)

    # Fallback: analysis layout does not have official run-dir/config structure.
    if not tasks_out:
        for suite, run_dir_name, config, task_dir in _iter_analysis_layout_tasks(runs_dir, prefix_map, run_filter):
            _append_task_record(suite, run_dir_name, config, task_dir)

    run_summaries: list[dict[str, Any]] = []
    suite_summaries: list[dict[str, Any]] = []
    run_page_map: dict[str, str] = {}

    by_run: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for task in tasks_out:
        by_run[task["run_dir"]][task["config"]].append(task)

    for run_dir_name, config_map in sorted(by_run.items()):
        run_page_name = f"{_slug(run_dir_name)}.md"
        run_page_map[run_dir_name] = run_page_name
        run_page_path = runs_pages_dir / run_page_name
        run_suite = next((tasks[0]["suite"] for tasks in config_map.values() if tasks), "unknown")

        # Adjust task links in page scope.
        page_config_map: dict[str, list[dict[str, Any]]] = {}
        for config, tasks in config_map.items():
            adjusted = []
            for t in tasks:
                copy_t = dict(t)
                copy_t["task_page"] = f"../{t['task_page']}"
                adjusted.append(copy_t)
            page_config_map[config] = adjusted

        _write_text(run_page_path, _build_run_page(run_dir_name, page_config_map))

        for config, tasks in sorted(config_map.items()):
            rewards = [t["reward"] for t in tasks]
            pass_count = sum(1 for t in tasks if t["status"] == "passed")
            mean_reward = statistics.mean(rewards) if rewards else 0.0
            pass_rate = pass_count / len(tasks) if tasks else 0.0
            run_summaries.append(
                {
                    "run_dir": run_dir_name,
                    "suite": run_suite,
                    "run_page": run_page_name,
                    "config": config,
                    "task_count": len(tasks),
                    "mean_reward": mean_reward,
                    "pass_rate": pass_rate,
                    "is_mcp_config": is_mcp_config(config),
                }
            )

    run_summaries.sort(key=lambda x: (x["run_dir"], x["config"]))
    deduped_tasks = _dedupe_tasks(tasks_out)

    # Load MANIFEST run_history for multi-run variance data
    manifest_run_history: dict[str, dict] = {}
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text())
            manifest_run_history = manifest_data.get("run_history", {})
        except (json.JSONDecodeError, OSError):
            pass

    by_suite: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for task in deduped_tasks:
        by_suite[task["suite"]][(task["run_dir"], task["config"])].append(task)

    for suite, run_config_tasks in sorted(by_suite.items()):
        _write_text(
            suite_pages_dir / f"{suite}.md",
            _build_suite_page(suite, run_config_tasks, all_suite_tasks=tasks_out, run_history=manifest_run_history),
        )

        config_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (_run_dir, config), tasks in run_config_tasks.items():
            config_buckets[config].extend(tasks)
        for config, tasks in sorted(config_buckets.items()):
            rewards = [t["reward"] for t in tasks]
            passes = sum(1 for t in tasks if t["status"] == "passed")
            suite_summaries.append(
                {
                    "suite": suite,
                    "config": config,
                    "task_count": len(tasks),
                    "mean_reward": statistics.mean(rewards) if rewards else 0.0,
                    "pass_rate": (passes / len(tasks)) if tasks else 0.0,
                    "is_mcp_config": is_mcp_config(config),
                }
            )
    summary_rows_by_suite: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in suite_summaries:
        summary_rows_by_suite[str(row["suite"])].append(row)
    for suite, rows in summary_rows_by_suite.items():
        min_required = _suite_min_required_valid_tasks(suite, rows)
        for row in rows:
            row["min_required_valid_tasks"] = min_required
            row["below_minimum_valid_tasks"] = int(row["task_count"]) < min_required

    suite_summaries.sort(key=lambda x: (x["suite"], x["config"]))

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_dir": str(runs_dir),
        "repo_blob_base": repo_blob_base,
        "suite_count": len(by_suite),
        "run_count": len({r["run_dir"] for r in run_summaries}),
        "task_count": len(deduped_tasks),
        "all_task_count": len(tasks_out),
        "excluded_task_count": len(excluded_tasks),
        "suite_summaries": suite_summaries,
        "run_summaries": run_summaries,
        "tasks": deduped_tasks,
        "all_tasks": sorted(tasks_out, key=lambda t: (t["run_dir"], t["config"], t["task_name"])),
        "excluded_tasks": sorted(excluded_tasks, key=lambda t: (t["run_dir"], t["config"], t["task_name"])),
    }

    (output_dir / "data").mkdir(parents=True, exist_ok=True)
    _write_text(output_dir / "data" / "official_results.json", json.dumps(data, indent=2, sort_keys=True))
    _write_text(output_dir / "README.md", _build_root_readme(suite_summaries, run_summaries))
    _write_text(output_dir / "index.html", _build_index_html())

    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default="./runs/analysis",
        help="Path to runs directory (default: ./runs/analysis)",
    )
    parser.add_argument(
        "--output-dir",
        default="./docs/official_results",
        help="Directory to write static export bundle (default: ./docs/official_results)",
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Optional run directory name to include (repeatable)",
    )
    parser.add_argument(
        "--max-trace-examples",
        type=int,
        default=12,
        help="Max parsed tool-use examples per task page (default: 12)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve output directory locally after generation.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8008,
        help="Port for --serve (default: 8008)",
    )
    parser.add_argument(
        "--repo-blob-base",
        default=DEFAULT_REPO_BLOB_BASE,
        help="GitHub blob base URL for repo links (default: CodeScaleBench main branch).",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Limit export to run directories referenced by MANIFEST run_history.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not runs_dir.is_dir():
        existing_json = output_dir / "data" / "official_results.json"
        if args.serve and existing_json.is_file():
            print(f"[WARN] runs dir not found: {runs_dir}")
            print(f"[WARN] serving existing bundle without regeneration: {output_dir}")
            _serve_directory(output_dir, args.port)
            return 0
        print(f"[FAIL] runs dir not found: {runs_dir}")
        print("[HINT] Pass --runs-dir to a local analysis runs checkout, or run with --serve to host an existing docs bundle.")
        return 2

    run_filter = set(args.run) if args.run else None

    data = build_export(
        runs_dir=runs_dir,
        output_dir=output_dir,
        run_filter=run_filter,
        max_examples=max(0, args.max_trace_examples),
        repo_blob_base=args.repo_blob_base,
        manifest_only=args.manifest_only,
    )

    print(f"[OK] Wrote export bundle to: {output_dir}")
    print(f"      Runs: {data['run_count']}")
    print(f"      Valid scored tasks: {data['task_count']}")
    print(f"      Excluded tasks: {data.get('excluded_task_count', 0)}")
    print(f"      Root summary: {output_dir / 'README.md'}")
    print(f"      JSON data: {output_dir / 'data' / 'official_results.json'}")
    print(f"      Local UI: {output_dir / 'index.html'}")

    if args.serve:
        _serve_directory(output_dir, args.port)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

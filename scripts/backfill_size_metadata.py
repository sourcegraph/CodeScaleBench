#!/usr/bin/env python3
"""Backfill repo and task complexity metadata in selected_benchmark_tasks.json.

Populates per-task:
  - context_length
  - files_count
  - context_length_source
  - files_count_source
  - repo_size_bytes
  - repo_size_mb
  - repo_file_count
  - repo_directory_count
  - repo_approx_loc
  - repo_languages
  - repo_primary_language
  - repo_complexity
  - repo_complexity_label
  - repo_complexity_source
  - task_complexity
  - task_complexity_label
  - task_complexity_source

Extraction order:
1) task.toml metadata (exact)
2) git tree scan at pinned repo revision (exact files, byte-based token estimate)
3) environment/repo scan (approximate, where available)
4) MCP-breakdown proxy (estimated)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


_LANGUAGE_BY_EXTENSION = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".h": "c_cpp_headers",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    ".php": "php",
    ".proto": "protobuf",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
}

_TEXT_EXTENSIONS = set(_LANGUAGE_BY_EXTENSION) | {
    ".bazel",
    ".bzl",
    ".cfg",
    ".cmake",
    ".conf",
    ".css",
    ".env",
    ".gradle",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".properties",
    ".rst",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

_CLOC_COUNTS_PATH = Path("results/repo_cloc_counts.json")
_CLOC_COUNTS_CACHE: dict[str, int] | None = None

_REPO_SIZE_CACHE_PATH = Path("docs/analysis/github_repo_size_kb_cache.json")
_REPO_SIZE_KB_CACHE: dict[str, int] | None = None
_REPO_SIZE_API_CACHE_PATH = Path(".cache/repo_size_api_kb_cache.json")
_REPO_SIZE_API_CACHE: dict[str, int] | None = None
_REPO_ALIASES = {
    "linux": "torvalds/linux",
    "pytorch": "pytorch/pytorch",
    "tutanota/tutanota": "tutao/tutanota",
}


def _load_cloc_counts() -> dict[str, int]:
    """Load repo -> total_code_lines mapping from cloc results."""
    global _CLOC_COUNTS_CACHE
    if _CLOC_COUNTS_CACHE is not None:
        return _CLOC_COUNTS_CACHE
    if not _CLOC_COUNTS_PATH.is_file():
        _CLOC_COUNTS_CACHE = {}
        return _CLOC_COUNTS_CACHE
    try:
        data = json.loads(_CLOC_COUNTS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    _CLOC_COUNTS_CACHE = {
        repo: info["total_code_lines"]
        for repo, info in data.items()
        if isinstance(info, dict) and "total_code_lines" in info
    }
    return _CLOC_COUNTS_CACHE


def _get_cloc_loc(repo: str) -> int | None:
    """Look up precise LOC from cloc counts, handling aliases."""
    cache = _load_cloc_counts()
    if repo in cache:
        return cache[repo]
    alias = _REPO_ALIASES.get(repo)
    if alias and alias in cache:
        return cache[alias]
    return None


def _read_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _run(
    cmd: list[str], cwd: Path | None = None, timeout_sec: int | None = None
) -> subprocess.CompletedProcess[str]:
    cwd_s = str(cwd) if cwd else None
    if timeout_sec is None:
        return subprocess.run(
            cmd,
            cwd=cwd_s,
            text=True,
            capture_output=True,
            check=False,
        )
    proc = subprocess.Popen(
        cmd,
        cwd=cwd_s,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )
    try:
        out, err = proc.communicate(timeout=timeout_sec)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 15)
        except OSError:
            pass
        try:
            out, err = proc.communicate(timeout=2)
        except Exception:
            out, err = "", "timeout"
        return subprocess.CompletedProcess(
            cmd,
            returncode=124,
            stdout=out or "",
            stderr=err or "timeout",
        )


def _safe_slug(repo: str) -> str:
    return repo.replace("/", "__")


def _is_valid_repo_ref(repo: object) -> bool:
    if not isinstance(repo, str):
        return False
    repo = repo.strip()
    if not repo or repo.startswith("/") or "," in repo:
        return False
    if repo in {"org/repo", "owner/repo"}:
        return False
    return repo.count("/") == 1


def _normalize_repo_hint(repo: object) -> str | None:
    if not isinstance(repo, str):
        return None
    repo = repo.strip()
    if not repo:
        return None
    if repo in _REPO_ALIASES:
        return _REPO_ALIASES[repo]
    repo = repo.removeprefix("https://github.com/").removeprefix("http://github.com/")
    repo = repo.removesuffix(".git").strip("/")
    if repo.startswith("repos/"):
        tail = repo.removeprefix("repos/")
        if tail == "pytorch":
            return "pytorch/pytorch"
    if repo in _REPO_ALIASES:
        return _REPO_ALIASES[repo]
    if _is_valid_repo_ref(repo):
        return repo
    return None


def _parse_repo_and_rev(task_dir: Path) -> tuple[str | None, str | None]:
    """Extract (owner/repo, rev) from task.toml / repo_path / Dockerfile hints."""
    toml_path = task_dir / "task.toml"
    repo: str | None = None
    rev: str | None = None

    if toml_path.is_file():
        try:
            d = _read_toml(toml_path)
        except Exception:
            d = {}
        task = d.get("task", {}) or {}
        repo_raw = task.get("repo")
        rev_raw = task.get("pre_fix_rev")
        if isinstance(repo_raw, str) and repo_raw.strip():
            repo = repo_raw.strip()
        if isinstance(rev_raw, str) and rev_raw.strip():
            rev = rev_raw.strip()

    repo_path_file = task_dir / "repo_path"
    if repo_path_file.is_file() and (not repo or "/" not in repo):
        try:
            rp = repo_path_file.read_text(errors="ignore").strip()
        except OSError:
            rp = ""
        if "/" in rp:
            repo = rp

    dockerfile = task_dir / "environment" / "Dockerfile"
    if dockerfile.is_file() and (not repo or not rev):
        try:
            txt = dockerfile.read_text(errors="ignore")
        except OSError:
            txt = ""
        if not repo:
            m_repo = re.search(
                r"https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\\.git)?(?:\\s|$)",
                txt,
            )
            if m_repo:
                repo = m_repo.group(1)
        if not rev:
            m_rev = re.search(r"git checkout\\s+([0-9a-fA-F]{7,40}|v[0-9][A-Za-z0-9._-]*)", txt)
            if m_rev:
                rev = m_rev.group(1)

    if repo and "/" not in repo:
        repo = None
    return repo, rev


def _parse_dockerfile_repo_refs(task_dir: Path) -> list[str]:
    dockerfile = task_dir / "environment" / "Dockerfile"
    if not dockerfile.is_file():
        return []
    try:
        text = dockerfile.read_text(errors="ignore")
    except OSError:
        return []

    refs: list[str] = []
    for match in re.finditer(r"https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text):
        repo = _normalize_repo_hint(match.group(1))
        if repo and repo not in refs:
            refs.append(repo)
    return refs


def _resolve_repo_ref(task: dict, task_dir: Path) -> tuple[str | None, str | None]:
    parsed_repo, parsed_rev = _parse_repo_and_rev(task_dir)
    task_repo = _normalize_repo_hint(task.get("repo"))

    if parsed_repo and parsed_repo.startswith("sg-evals/") and task_repo:
        return task_repo, parsed_rev
    if parsed_repo in {"org/repo", "owner/repo"} and task_repo:
        return task_repo, parsed_rev

    normalized_parsed = _normalize_repo_hint(parsed_repo)
    if normalized_parsed:
        return normalized_parsed, parsed_rev
    if task_repo:
        return task_repo, parsed_rev
    return None, parsed_rev


def _resolve_repo_refs(task: dict, task_dir: Path) -> tuple[list[str], str | None]:
    primary_repo, rev = _resolve_repo_ref(task, task_dir)
    repos: list[str] = []
    if primary_repo:
        repos.append(primary_repo)
    for repo in _parse_dockerfile_repo_refs(task_dir):
        if repo not in repos:
            repos.append(repo)
    return repos, rev


def _looks_text_path(path_str: str) -> bool:
    path = Path(path_str)
    suffix = path.suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        return True
    return path.name.lower() in {"dockerfile", "makefile", "jenkinsfile"}


def _infer_language(path_str: str) -> str | None:
    path = Path(path_str)
    suffix = path.suffix.lower()
    if suffix in _LANGUAGE_BY_EXTENSION:
        return _LANGUAGE_BY_EXTENSION[suffix]
    name = path.name.lower()
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    return None


def _complexity_label(score: float) -> str:
    if score >= 0.86:
        return "expert"
    if score >= 0.62:
        return "hard"
    return "medium"


def _safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _normalize_log(value: float, cap: float) -> float:
    if value <= 0 or cap <= 1:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(cap))


def _normalize_linear(value: float, cap: float) -> float:
    if value <= 0 or cap <= 0:
        return 0.0
    return min(1.0, value / cap)


def _load_ground_truth_meta(task_dir: Path) -> dict:
    gt_meta_path = task_dir / "tests" / "ground_truth_meta.json"
    if not gt_meta_path.is_file():
        return {}
    try:
        with open(gt_meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_repo_size_kb_cache() -> dict[str, int]:
    global _REPO_SIZE_KB_CACHE
    if _REPO_SIZE_KB_CACHE is not None:
        return _REPO_SIZE_KB_CACHE
    if not _REPO_SIZE_CACHE_PATH.is_file():
        _REPO_SIZE_KB_CACHE = {}
        return _REPO_SIZE_KB_CACHE
    try:
        data = json.loads(_REPO_SIZE_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    _REPO_SIZE_KB_CACHE = {
        str(repo): int(size_kb)
        for repo, size_kb in data.items()
        if isinstance(repo, str) and isinstance(size_kb, (int, float)) and size_kb > 0
    }
    return _REPO_SIZE_KB_CACHE


def _load_repo_size_api_cache() -> dict[str, int]:
    global _REPO_SIZE_API_CACHE
    if _REPO_SIZE_API_CACHE is not None:
        return _REPO_SIZE_API_CACHE
    if not _REPO_SIZE_API_CACHE_PATH.is_file():
        _REPO_SIZE_API_CACHE = {}
        return _REPO_SIZE_API_CACHE
    try:
        data = json.loads(_REPO_SIZE_API_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
    _REPO_SIZE_API_CACHE = {
        str(repo): int(size_kb)
        for repo, size_kb in data.items()
        if isinstance(repo, str) and isinstance(size_kb, (int, float)) and size_kb > 0
    }
    return _REPO_SIZE_API_CACHE


def _save_repo_size_api_cache() -> None:
    cache = _load_repo_size_api_cache()
    _REPO_SIZE_API_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REPO_SIZE_API_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def _get_repo_size_kb(repo: str) -> int | None:
    cache = _load_repo_size_kb_cache()
    if repo in cache:
        return cache[repo]

    api_cache = _load_repo_size_api_cache()
    if repo in api_cache:
        return api_cache[repo]

    url = f"https://api.github.com/repos/{repo}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodeScaleBench-backfill-size-metadata",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None

    size_kb = payload.get("size")
    if isinstance(size_kb, (int, float)) and size_kb > 0:
        api_cache[repo] = int(size_kb)
        _save_repo_size_api_cache()
        return int(size_kb)
    return None


def _git_tree_metrics(repo: str, rev: str, cache_dir: Path, git_timeout_sec: int) -> dict[str, object]:
    """Return repo metrics for repo@rev from the git tree without blob checkout."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / _safe_slug(repo)
    remote = f"https://github.com/{repo}.git"

    if not local.exists():
        cp = _run(
            ["git", "-c", "gc.auto=0", "clone", "--filter=blob:none", "--no-checkout", remote, str(local)],
            timeout_sec=git_timeout_sec,
        )
        if cp.returncode != 0:
            return {}
        _run(["git", "-C", str(local), "config", "gc.auto", "0"], timeout_sec=git_timeout_sec)

    if rev == "HEAD":
        commit = "HEAD"
    else:
        cp = _run(
            ["git", "-c", "gc.auto=0", "-C", str(local), "rev-parse", "--verify", f"{rev}^{{commit}}"],
            timeout_sec=git_timeout_sec,
        )
        if cp.returncode != 0:
            cp_fetch = _run(
                ["git", "-c", "gc.auto=0", "-C", str(local), "fetch", "--quiet", "origin", rev, "--depth", "1"],
                timeout_sec=git_timeout_sec,
            )
            if cp_fetch.returncode != 0:
                return {}
            cp = _run(
                ["git", "-c", "gc.auto=0", "-C", str(local), "rev-parse", "--verify", f"{rev}^{{commit}}"],
                timeout_sec=git_timeout_sec,
            )
            if cp.returncode != 0:
                return {}

        commit = cp.stdout.strip().splitlines()[-1] if cp.stdout.strip() else None
        if not commit:
            return {}

    files_count = 0
    directories: set[str] = set()
    language_files: dict[str, int] = {}

    proc = subprocess.Popen(
        ["git", "-c", "gc.auto=0", "-C", str(local), "ls-tree", "-r", commit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            try:
                meta, path_str = line.split("\t", 1)
            except ValueError:
                continue
            parts = meta.split()
            if len(parts) < 3 or parts[1] != "blob":
                continue

            files_count += 1
            parent = str(Path(path_str).parent)
            if parent and parent != ".":
                directories.add(parent)

            language = _infer_language(path_str)
            if language:
                language_files[language] = language_files.get(language, 0) + 1
        proc.communicate(timeout=git_timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return {}

    if proc.returncode != 0:
        return {}

    if files_count <= 0:
        return {}

    repo_size_kb = _get_repo_size_kb(repo)
    repo_size_bytes = int(repo_size_kb * 1024) if repo_size_kb is not None else None
    repo_size_mb = round(repo_size_kb / 1024, 3) if repo_size_kb is not None else None
    # Prefer cloc-based LOC counts from results/repo_cloc_counts.json.
    # Fallback to bytes//30 heuristic only if cloc data unavailable.
    repo_approx_loc = _get_cloc_loc(repo)
    if repo_approx_loc is None:
        repo_approx_loc = int(repo_size_bytes // 30) if repo_size_bytes is not None else None

    repo_languages = [
        {
            "language": language,
            "files": file_count,
            "pct_files": round((file_count / files_count) * 100, 2) if files_count > 0 else 0.0,
        }
        for language, file_count in sorted(language_files.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "context_length": max(1, repo_size_bytes // 4) if repo_size_bytes is not None else None,
        "files_count": files_count,
        "repo_size_bytes": repo_size_bytes,
        "repo_size_mb": repo_size_mb,
        "repo_file_count": files_count,
        "repo_directory_count": len(directories),
        "repo_approx_loc": repo_approx_loc,
        "repo_languages": repo_languages,
        "repo_primary_language": repo_languages[0]["language"] if repo_languages else None,
    }


def _merge_repo_metrics(metrics_list: list[dict[str, object]]) -> dict[str, object]:
    usable = [m for m in metrics_list if m]
    if not usable:
        return {}

    total_size_bytes = 0
    total_size_mb = 0.0
    size_known = False
    total_file_count = 0
    total_dir_count = 0
    total_loc = 0
    loc_known = False
    total_context = 0
    context_known = False
    language_files: dict[str, int] = {}

    for metrics in usable:
        file_count = metrics.get("repo_file_count")
        dir_count = metrics.get("repo_directory_count")
        if isinstance(file_count, int):
            total_file_count += file_count
        if isinstance(dir_count, int):
            total_dir_count += dir_count

        size_bytes = metrics.get("repo_size_bytes")
        size_mb = metrics.get("repo_size_mb")
        if isinstance(size_bytes, int):
            total_size_bytes += size_bytes
            size_known = True
        if isinstance(size_mb, (int, float)):
            total_size_mb += float(size_mb)

        loc = metrics.get("repo_approx_loc")
        if isinstance(loc, int):
            total_loc += loc
            loc_known = True

        ctx = metrics.get("context_length")
        if isinstance(ctx, int):
            total_context += ctx
            context_known = True

        for item in metrics.get("repo_languages", []) or []:
            if not isinstance(item, dict):
                continue
            language = item.get("language")
            files = item.get("files")
            if isinstance(language, str) and isinstance(files, int):
                language_files[language] = language_files.get(language, 0) + files

    repo_languages = [
        {
            "language": language,
            "files": file_count,
            "pct_files": round((file_count / total_file_count) * 100, 2) if total_file_count > 0 else 0.0,
        }
        for language, file_count in sorted(language_files.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "context_length": total_context if context_known and total_context > 0 else None,
        "files_count": total_file_count if total_file_count > 0 else None,
        "repo_size_bytes": total_size_bytes if size_known and total_size_bytes > 0 else None,
        "repo_size_mb": round(total_size_mb, 3) if size_known and total_size_mb > 0 else None,
        "repo_file_count": total_file_count if total_file_count > 0 else None,
        "repo_directory_count": total_dir_count if total_dir_count > 0 else None,
        "repo_approx_loc": total_loc if loc_known and total_loc > 0 else None,
        "repo_languages": repo_languages,
        "repo_primary_language": repo_languages[0]["language"] if repo_languages else None,
    }


def _scan_env_repo(repo_dir: Path) -> tuple[int | None, int | None]:
    """Return (approx_context_tokens, files_count) from environment/repo."""
    if not repo_dir.is_dir():
        return None, None

    files_count = 0
    approx_tokens = 0

    for p in repo_dir.rglob("*"):
        if not p.is_file():
            continue
        files_count += 1
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not text:
            continue
        approx_tokens += max(1, len(text) // 4)

    return approx_tokens if approx_tokens > 0 else None, files_count if files_count > 0 else None


def _proxy_context_length(task: dict) -> int | None:
    mb = task.get("mcp_breakdown") or {}
    cc = mb.get("context_complexity") if isinstance(mb, dict) else None
    try:
        cc = float(cc) if cc is not None else None
    except (TypeError, ValueError):
        cc = None
    if cc is None:
        return None
    return int(round(cc * 1_000_000))


def _proxy_files_count(task: dict) -> int | None:
    mb = task.get("mcp_breakdown") or {}
    cfd = mb.get("cross_file_deps") if isinstance(mb, dict) else None
    try:
        cfd = float(cfd) if cfd is not None else None
    except (TypeError, ValueError):
        cfd = None
    if cfd is None:
        return None
    scale = 450 if task.get("benchmark") == "ccb_k8sdocs" else 20
    return max(1, int(round(cfd * scale)))


def _compute_repo_complexity(repo_metrics: dict[str, object]) -> float | None:
    repo_file_count = _safe_float(repo_metrics.get("repo_file_count"))
    repo_directory_count = _safe_float(repo_metrics.get("repo_directory_count"))
    repo_approx_loc = _safe_float(repo_metrics.get("repo_approx_loc"))
    repo_languages = repo_metrics.get("repo_languages")

    if repo_file_count is None and repo_directory_count is None and repo_approx_loc is None:
        return None

    file_score = _normalize_log(repo_file_count or 0.0, 100_000)
    dir_score = _normalize_log(repo_directory_count or 0.0, 10_000)
    loc_score = _normalize_log(repo_approx_loc or 0.0, 10_000_000)

    entropy_score = 0.0
    if isinstance(repo_languages, list):
        weights = [float(item.get("files", 0)) for item in repo_languages if isinstance(item, dict)]
        total = sum(weights)
        if total > 0 and len(weights) > 1:
            probs = [w / total for w in weights if w > 0]
            entropy = -sum(p * math.log2(p) for p in probs)
            entropy_score = min(1.0, entropy / math.log2(min(len(probs), 8)))

    return round((0.4 * loc_score) + (0.3 * file_score) + (0.15 * dir_score) + (0.15 * entropy_score), 3)


def _compute_task_complexity(task: dict, gt_meta: dict) -> float | None:
    retrieval_files = _safe_float(gt_meta.get("files_count"))
    edit_files = _safe_float(gt_meta.get("edit_files_count"))
    symbols_count = _safe_float(gt_meta.get("symbols_count"))
    chunks_count = _safe_float(gt_meta.get("chunks_count"))
    context_length = _safe_float(task.get("context_length"))

    mcp_breakdown = task.get("mcp_breakdown")
    if isinstance(mcp_breakdown, dict):
        cross_file_deps = _safe_float(mcp_breakdown.get("cross_file_deps")) or 0.0
        semantic_search = _safe_float(mcp_breakdown.get("semantic_search_potential")) or 0.0
    else:
        cross_file_deps = 0.0
        semantic_search = 0.0

    has_signal = any(
        value is not None and value > 0
        for value in (retrieval_files, edit_files, symbols_count, chunks_count, context_length)
    ) or cross_file_deps > 0 or semantic_search > 0
    if not has_signal:
        return None

    retrieval_score = _normalize_log(retrieval_files or 0.0, 40)
    edit_score = _normalize_log(edit_files or 0.0, 12)
    symbols_score = _normalize_log(symbols_count or 0.0, 80)
    chunks_score = _normalize_log(chunks_count or 0.0, 40)
    context_score = _normalize_log(context_length or 0.0, 2_000_000)

    score = (
        0.25 * retrieval_score
        + 0.25 * edit_score
        + 0.15 * symbols_score
        + 0.1 * chunks_score
        + 0.15 * context_score
        + 0.05 * _normalize_linear(cross_file_deps, 1.0)
        + 0.05 * _normalize_linear(semantic_search, 1.0)
    )
    return round(score, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill repo and task complexity metadata in selected_benchmark_tasks.json")
    parser.add_argument(
        "--selected-tasks",
        type=Path,
        default=Path("configs/selected_benchmark_tasks.json"),
        help="Path to selected_benchmark_tasks.json",
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=Path("benchmarks"),
        help="Path to benchmarks/ root",
    )
    parser.add_argument(
        "--git-cache-dir",
        type=Path,
        default=Path(".cache/repo_size"),
        help="Cache directory for blobless git clones used for size extraction",
    )
    parser.add_argument(
        "--disable-git-tree",
        action="store_true",
        help="Disable git tree exact extraction pass",
    )
    parser.add_argument(
        "--git-timeout-sec",
        type=int,
        default=90,
        help="Timeout per git operation/revision extraction in seconds",
    )
    parser.add_argument(
        "--task-ids-file",
        type=Path,
        help="Optional newline-delimited list of task_id values to limit processing",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write changes back to selected tasks file",
    )
    args = parser.parse_args()

    data = json.loads(args.selected_tasks.read_text())
    tasks = data.get("tasks", data) if isinstance(data, dict) else data
    task_id_filter: set[str] | None = None
    if args.task_ids_file:
        try:
            lines = [line.strip() for line in args.task_ids_file.read_text().splitlines() if line.strip()]
        except OSError:
            lines = []
        if lines:
            task_id_filter = set(lines)
            print(f"Filtering to {len(task_id_filter)} specified task_ids")

    n_total = 0
    n_ctx = 0
    n_files = 0
    n_ctx_exact = 0
    n_ctx_repo = 0
    n_ctx_proxy = 0
    n_ctx_git = 0
    n_files_exact = 0
    n_files_repo = 0
    n_files_proxy = 0
    n_files_git = 0
    n_repo_meta = 0
    n_task_complexity = 0
    git_cache: dict[tuple[str, str], dict[str, object]] = {}

    processed_ids: set[str] = set()
    for t in tasks:
        task_id = t.get("task_id")
        if task_id_filter is not None and task_id not in task_id_filter:
            continue
        if task_id:
            processed_ids.add(task_id)
        n_total += 1
        if n_total % 25 == 0:
            print(f"... processed {n_total}/{len(tasks)} tasks")

        task_dir = args.benchmarks_dir / t.get("task_dir", "")
        toml_path = task_dir / "task.toml"
        repo_dir = task_dir / "environment" / "repo"
        gt_meta = _load_ground_truth_meta(task_dir)

        context_length = t.get("context_length")
        files_count = t.get("files_count")
        context_src = t.get("context_length_source")
        files_src = t.get("files_count_source")

        ctx_is_proxy = context_src == "mcp_breakdown_proxy"
        files_is_proxy = files_src == "mcp_breakdown_proxy"

        if toml_path.is_file():
            try:
                d = _read_toml(toml_path)
                meta = d.get("metadata", {}) or {}
            except Exception:
                meta = {}
            ctx_meta = meta.get("context_length")
            files_meta = meta.get("files_count")
            try:
                if ctx_meta is not None and int(ctx_meta) > 0:
                    context_length = int(ctx_meta)
                    context_src = "task_toml_metadata"
            except (TypeError, ValueError):
                pass
            try:
                if files_meta is not None and int(files_meta) > 0:
                    files_count = int(files_meta)
                    files_src = "task_toml_metadata"
            except (TypeError, ValueError):
                pass

        repo_metrics: dict[str, object] = {}
        need_ctx = (not context_length or context_length <= 0 or ctx_is_proxy)
        need_files = (not files_count or files_count <= 0 or files_is_proxy)
        if (
            need_ctx
            or need_files
            or not t.get("repo_size_bytes")
            or not t.get("repo_languages")
            or not t.get("repo_primary_language")
            or not t.get("repo_complexity")
        ) and not args.disable_git_tree:
            repo_refs, rev_ref = _resolve_repo_refs(t, task_dir)
            repo_metrics_list: list[dict[str, object]] = []
            for repo_ref in repo_refs:
                rev_ref = rev_ref or "HEAD"
                key = (repo_ref, rev_ref)
                if key not in git_cache:
                    git_cache[key] = _git_tree_metrics(repo_ref, rev_ref, args.git_cache_dir, args.git_timeout_sec)
                repo_metrics_list.append(dict(git_cache[key]))

            repo_metrics = _merge_repo_metrics(repo_metrics_list)
            ctx_git = repo_metrics.get("context_length")
            files_git = repo_metrics.get("files_count")
            if need_ctx and ctx_git is not None:
                context_length = int(ctx_git)
                context_src = "git_tree_blob_bytes_div4"
            if need_files and files_git is not None:
                files_count = int(files_git)
                files_src = "git_tree_blob_count"

        if (not context_length or context_length <= 0) or (not files_count or files_count <= 0):
            ctx_repo, files_repo = _scan_env_repo(repo_dir)
            if (not context_length or context_length <= 0) and ctx_repo is not None:
                context_length = int(ctx_repo)
                context_src = "env_repo_scan_approx"
            if (not files_count or files_count <= 0) and files_repo is not None:
                files_count = int(files_repo)
                files_src = "env_repo_scan"

        if not context_length or context_length <= 0:
            ctx_proxy = _proxy_context_length(t)
            if ctx_proxy is not None:
                context_length = ctx_proxy
                context_src = "mcp_breakdown_proxy"
        if not files_count or files_count <= 0:
            files_proxy = _proxy_files_count(t)
            if files_proxy is not None:
                files_count = files_proxy
                files_src = "mcp_breakdown_proxy"

        if context_length and context_length > 0:
            t["context_length"] = int(context_length)
            t["context_length_source"] = context_src
            n_ctx += 1
            if context_src == "task_toml_metadata":
                n_ctx_exact += 1
            elif context_src == "git_tree_blob_bytes_div4":
                n_ctx_git += 1
            elif context_src == "env_repo_scan_approx":
                n_ctx_repo += 1
            elif context_src == "mcp_breakdown_proxy":
                n_ctx_proxy += 1
        else:
            t["context_length"] = None
            t["context_length_source"] = "unknown"

        if files_count and files_count > 0:
            t["files_count"] = int(files_count)
            t["files_count_source"] = files_src
            n_files += 1
            if files_src == "task_toml_metadata":
                n_files_exact += 1
            elif files_src == "git_tree_blob_count":
                n_files_git += 1
            elif files_src == "env_repo_scan":
                n_files_repo += 1
            elif files_src == "mcp_breakdown_proxy":
                n_files_proxy += 1
        else:
            t["files_count"] = None
            t["files_count_source"] = "unknown"

        if repo_metrics:
            t["repo_size_bytes"] = int(repo_metrics["repo_size_bytes"]) if repo_metrics.get("repo_size_bytes") is not None else None
            t["repo_size_mb"] = repo_metrics.get("repo_size_mb")
            t["repo_file_count"] = int(repo_metrics["repo_file_count"]) if repo_metrics.get("repo_file_count") is not None else None
            t["repo_directory_count"] = int(repo_metrics["repo_directory_count"]) if repo_metrics.get("repo_directory_count") is not None else None
            t["repo_approx_loc"] = int(repo_metrics["repo_approx_loc"]) if repo_metrics.get("repo_approx_loc") else None
            t["repo_languages"] = repo_metrics.get("repo_languages") or []
            t["repo_primary_language"] = repo_metrics.get("repo_primary_language")
            n_repo_meta += 1
        else:
            t.setdefault("repo_size_bytes", None)
            t.setdefault("repo_size_mb", None)
            t.setdefault("repo_file_count", None)
            t.setdefault("repo_directory_count", None)
            t.setdefault("repo_approx_loc", None)
            t.setdefault("repo_languages", [])
            t.setdefault("repo_primary_language", None)

        repo_complexity = _compute_repo_complexity({
            "repo_file_count": t.get("repo_file_count"),
            "repo_directory_count": t.get("repo_directory_count"),
            "repo_approx_loc": t.get("repo_approx_loc"),
            "repo_languages": t.get("repo_languages"),
        })
        if repo_complexity is not None:
            t["repo_complexity"] = repo_complexity
            t["repo_complexity_label"] = _complexity_label(repo_complexity)
            t["repo_complexity_source"] = "git_tree_scan" if repo_metrics else "cached_registry"
        else:
            t["repo_complexity"] = None
            t["repo_complexity_label"] = None
            t["repo_complexity_source"] = "unknown"

        task_complexity = _compute_task_complexity(t, gt_meta)
        if task_complexity is not None:
            t["task_complexity"] = task_complexity
            t["task_complexity_label"] = _complexity_label(task_complexity)
            t["task_complexity_source"] = "ground_truth_meta_plus_registry"
            n_task_complexity += 1
        else:
            t["task_complexity"] = None
            t["task_complexity_label"] = None
            t["task_complexity_source"] = "unknown"

    print(f"Tasks: {n_total}")
    if task_id_filter is not None:
        missing = task_id_filter - processed_ids
        print(f"Processed {len(processed_ids)} of {len(task_id_filter)} requested task_ids")
        if missing:
            print(f"Missing task_ids: {sorted(missing)}")
    print(
        "context_length populated: "
        f"{n_ctx} (task_toml={n_ctx_exact}, git_tree={n_ctx_git}, repo_scan={n_ctx_repo}, proxy={n_ctx_proxy})"
    )
    print(
        "files_count populated:   "
        f"{n_files} (task_toml={n_files_exact}, git_tree={n_files_git}, repo_scan={n_files_repo}, proxy={n_files_proxy})"
    )
    print(f"repo metadata populated: {n_repo_meta}")
    print(f"task_complexity populated: {n_task_complexity}")

    if args.write:
        if isinstance(data, dict) and "tasks" in data:
            data["tasks"] = tasks
        else:
            data = tasks
        args.selected_tasks.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Wrote {args.selected_tasks}")


if __name__ == "__main__":
    main()

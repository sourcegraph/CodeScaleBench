#!/usr/bin/env python3
"""Hybrid retrieval pipeline: DS broad discovery + Curator precise refinement.

Two-phase sequential pipeline:
  Phase 1: Deep Search (parallel) — broad file discovery via Sourcegraph DS API
  Phase 2: Curator Agent (sequential) — local refinement with DS seeds injected

DS file predictions are injected into the curator's user message as preliminary
candidates. The curator validates each against its edit-centric principle and
applies test classification rules, then adds any files it discovers locally.

Results are merged with provenance tracking (ds_only / curator_only / both).

Usage:
    # Full hybrid on 9-task hard subset
    python3 scripts/hybrid_retrieval_pipeline.py \\
        --instance-ids 157932b6,43d6d59b,2a93ee66,34826a6a,a42cace7,7df7e1c0,676e9486,0abc73df,61a7a81e

    # DS-only baseline (skip curator)
    python3 scripts/hybrid_retrieval_pipeline.py --instance-ids ... --ds-only

    # Curator-only baseline (skip DS)
    python3 scripts/hybrid_retrieval_pipeline.py --instance-ids ... --curator-only

    # With DS pruning before curator
    python3 scripts/hybrid_retrieval_pipeline.py --instance-ids ... --prune

    # Dry run
    python3 scripts/hybrid_retrieval_pipeline.py --instance-ids ... --dry-run

Environment:
    SRC_ACCESS_TOKEN or SOURCEGRAPH_ACCESS_TOKEN   Required for DS phase
    SOURCEGRAPH_URL                                SG instance (default: sourcegraph.sourcegraph.com)
    ANTHROPIC_API_KEY                              Required if --prune
    CCB_REPO_CACHE                                 Repo clone cache (default: ~/.cache/ccb_repos)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Add scripts/ to path for sibling imports
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from ds_hybrid_retrieval import (
    DS_PROMPT_TEMPLATE,
    _normalize_path,
    ds_create_conversation,
    ds_poll_conversation,
    extract_files_from_ds_response,
    load_tasks,
    prune_with_sonnet,
)
from context_retrieval_agent import (
    CURATOR_SYSTEM_PROMPT,
    _extract_json_from_text,
    _tool_description_for_backend,
    get_cache_dir,
    get_task_type_guidance,
)

log = logging.getLogger("hybrid_pipeline")

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results" / "contextbench"

# Cap DS seeds injected into curator message to avoid context bloat
MAX_DS_SEEDS = 25


# ---------------------------------------------------------------------------
# Phase 1: Deep Search Discovery
# ---------------------------------------------------------------------------


def run_ds_phase(
    task: Dict[str, Any],
    token: str,
    sg_url: str,
    prune: bool = False,
    anthropic_key: str = "",
) -> Dict[str, Any]:
    """Run DS retrieval for a single task.

    Returns dict with keys: files, raw_files, conv_id, elapsed_sec, error.
    Does NOT compute metrics (that happens at merge time).
    """
    iid = task["instance_id"]
    short = iid.split("__")[-1]
    repo = task["repo"]
    problem = task["problem_statement"]

    # Mirror repo name: sg-evals/{repo_short}--{commit8}
    repo_short = repo.split("/")[-1] if "/" in repo else repo
    commit = task.get("base_commit", "")
    commit8 = commit[:8]
    mirror_repo = f"github.com/sg-evals/{repo_short}--{commit8}"

    log.info("[DS][%s] Querying DS for %s (mirror: %s)", short, repo, mirror_repo)
    start = time.time()

    question = DS_PROMPT_TEMPLATE.format(
        search_repo=mirror_repo,
        repo=repo,
        problem_statement=problem[:4000],
    )

    conv_id = ds_create_conversation(question, token, sg_url)
    if conv_id is None:
        log.error("[DS][%s] Failed to create conversation", short)
        return {"instance_id": iid, "files": [], "raw_files": [],
                "conv_id": None, "elapsed_sec": round(time.time() - start, 1),
                "error": True}

    log.info("[DS][%s] Conversation %d created, polling...", short, conv_id)
    response_text = ds_poll_conversation(conv_id, token, sg_url)
    if response_text is None:
        log.error("[DS][%s] Query failed/timed out", short)
        return {"instance_id": iid, "files": [], "raw_files": [],
                "conv_id": conv_id, "elapsed_sec": round(time.time() - start, 1),
                "error": True}

    raw_files = extract_files_from_ds_response(response_text)
    log.info("[DS][%s] Returned %d files", short, len(raw_files))

    # Optional pruning
    if prune and len(raw_files) > 1 and anthropic_key:
        pruned_files = prune_with_sonnet(raw_files, problem, anthropic_key)
        log.info("[DS][%s] Pruned %d -> %d files", short, len(raw_files), len(pruned_files))
    else:
        pruned_files = raw_files

    # Normalize paths
    normalized = [_normalize_path(f) for f in pruned_files if f]
    normalized = [f for f in normalized if f]  # drop empties

    elapsed = round(time.time() - start, 1)
    log.info("[DS][%s] Done in %.1fs (%d files)", short, elapsed, len(normalized))

    return {
        "instance_id": iid,
        "files": normalized,
        "raw_files": raw_files,
        "conv_id": conv_id,
        "elapsed_sec": elapsed,
        "error": False,
        "pruned": prune and len(raw_files) > 1,
    }


# ---------------------------------------------------------------------------
# Phase 2: Curator Agent Refinement
# ---------------------------------------------------------------------------


def build_hybrid_user_message(
    problem_statement: str,
    repo_name: str,
    repo_path: Path,
    ds_seeds: List[str],
) -> str:
    """Build curator user message with DS seeds injected.

    Base message follows the daytona runner format. DS seeds are appended
    as preliminary candidates for the curator to validate.
    """
    parts = [
        f"## Task\n{problem_statement[:4000]}",
        f"\n## Repositories\n- **{repo_name}**: `{repo_path}`",
        f"\n**Use these repo names in Deep Search queries**: {repo_name}",
        "\n**IMPORTANT**: Search the local repository thoroughly using "
        "Bash, Read, Glob, Grep tools.",
    ]

    if ds_seeds:
        seed_list = ds_seeds[:MAX_DS_SEEDS]
        bullets = "\n".join(f"- `{f}`" for f in seed_list)
        truncated = ""
        if len(ds_seeds) > MAX_DS_SEEDS:
            truncated = f"\n\n*({len(ds_seeds) - MAX_DS_SEEDS} additional candidates omitted)*"

        parts.append(
            f"\n## Preliminary Candidates from Broad Code Search\n\n"
            f"The following {len(seed_list)} files were identified by automated "
            f"code search as potentially relevant to this task. Use them as "
            f"ADDITIONAL SEEDS for your exploration.\n\n"
            f"**IMPORTANT**:\n"
            f"- Do NOT blindly include all of these. Apply your edit-centric "
            f'principle ("Would this file appear in git diff?") to each.\n'
            f"- Some may be false positives (i18n translation variants, unrelated "
            f"test files, documentation). Filter using your test classification rules.\n"
            f"- Gold files may NOT be in this list. Continue your normal 5-step "
            f"exploration regardless.\n"
            f"- Read each candidate locally to verify relevance before including.\n\n"
            f"### Candidate Files ({len(seed_list)} files)\n"
            f"{bullets}{truncated}"
        )

    return "\n".join(parts)


def clone_repo_at_commit(
    repo_slug: str,
    commit: str,
    cache_dir: Optional[Path] = None,
) -> Path:
    """Clone a repo and checkout a specific commit.

    Uses shallow clone + fetch for the specific commit when needed.
    Returns path to the checked-out repo.
    """
    cache = cache_dir or get_cache_dir()
    commit8 = commit[:8] if commit else "HEAD"
    dir_name = repo_slug.replace("/", "__") + f"__{commit8}"
    repo_dir = cache / dir_name

    if repo_dir.exists() and (repo_dir / ".git").exists():
        # Verify we're at the right commit
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, cwd=str(repo_dir), timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip().startswith(commit8):
                log.debug("Cache hit: %s @ %s", repo_dir, commit8)
                return repo_dir
        except Exception:
            pass

    url = f"https://github.com/{repo_slug}.git"
    log.info("Cloning %s @ %s -> %s", url, commit8, repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Clone without checkout, then checkout the exact commit
        subprocess.run(
            ["git", "clone", "--no-checkout", url, str(repo_dir)],
            check=True, capture_output=True, text=True, timeout=600,
        )
        subprocess.run(
            ["git", "checkout", commit],
            check=True, capture_output=True, text=True,
            cwd=str(repo_dir), timeout=120,
        )
    except subprocess.CalledProcessError as e:
        log.error("Clone/checkout failed for %s @ %s: %s",
                  repo_slug, commit8, (e.stderr or "")[:500])
        raise

    return repo_dir


def run_curator_phase(
    task: Dict[str, Any],
    ds_seeds: List[str],
    model: str = "claude-opus-4-6",
    backend: str = "hybrid",
    verbose: bool = False,
    cache_dir: Optional[Path] = None,
    suite_name: str = "",
) -> Dict[str, Any]:
    """Run curator agent with DS seeds injected into user message.

    Clones the repo, builds hybrid user message, calls run_agent_cli.
    Returns dict with keys: files, cost_usd, elapsed_sec, error.
    """
    iid = task["instance_id"]
    short = iid.split("__")[-1]
    repo = task["repo"]
    commit = task.get("base_commit", "")

    log.info("[Curator][%s] Starting (repo=%s, seeds=%d)", short, repo, len(ds_seeds))
    start = time.time()

    # Clone repo at the right commit
    try:
        repo_path = clone_repo_at_commit(repo, commit, cache_dir)
    except Exception as e:
        log.error("[Curator][%s] Repo clone failed: %s", short, e)
        return {"instance_id": iid, "files": [], "cost_usd": 0,
                "elapsed_sec": round(time.time() - start, 1), "error": True}

    # Build user message with DS seeds
    user_msg = build_hybrid_user_message(
        problem_statement=task["problem_statement"],
        repo_name=repo,
        repo_path=repo_path,
        ds_seeds=ds_seeds,
    )

    # Build ctx dict for run_agent_cli
    ctx = {
        "task_name": short,
        "suite_name": "contextbench_hybrid",
        "seed_prompt": task["problem_statement"],
        "instruction": task["problem_statement"],
    }

    repo_paths = {repo: repo_path}

    # Monkey-patch build_user_message to use our hybrid message
    # We do this by directly calling the CLI with our custom message
    # instead of going through run_agent_cli's message building.
    import tempfile

    system = CURATOR_SYSTEM_PROMPT.format(
        tool_description=_tool_description_for_backend(backend, cli_mode=True),
        task_type_guidance=get_task_type_guidance(suite_name),
    )

    local_tools = ["Bash(read-only:true)", "Read", "Glob", "Grep"]
    sg_tools = ["mcp__sourcegraph__sg_keyword_search"]
    if backend == "local":
        allowed_tools = local_tools
    else:
        allowed_tools = local_tools + sg_tools

    # Write system prompt to temp file
    sys_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="hybrid_sys_", delete=False,
    )
    sys_file.write(system)
    sys_file.close()

    # Build MCP config if needed
    mcp_config_path = None
    if backend in ("deepsearch", "hybrid"):
        sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN", "")
        sg_url = os.environ.get("SOURCEGRAPH_URL",
                                "https://sourcegraph.sourcegraph.com").rstrip("/")
        if sg_token:
            mcp_config = {
                "mcpServers": {
                    "sourcegraph": {
                        "type": "http",
                        "url": f"{sg_url}/.api/mcp/v1",
                        "headers": {"Authorization": f"token {sg_token}"},
                    }
                }
            }
            mcp_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", prefix="hybrid_mcp_", delete=False,
            )
            json.dump(mcp_config, mcp_file)
            mcp_file.close()
            mcp_config_path = mcp_file.name
        else:
            log.warning("[Curator][%s] No SG token; falling back to local tools", short)
            allowed_tools = local_tools

    cmd = [
        "claude",
        "-p", user_msg,
        "--output-format", "json",
        "--model", model,
        "--append-system-prompt", system,
        "--allowedTools", ",".join(allowed_tools),
        "--dangerously-skip-permissions",
    ]
    if mcp_config_path:
        cmd.extend(["--mcp-config", mcp_config_path])

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    if "SRC_ACCESS_TOKEN" not in env:
        sg_token = env.get("SOURCEGRAPH_ACCESS_TOKEN", "")
        if sg_token:
            env["SRC_ACCESS_TOKEN"] = sg_token

    if verbose:
        log.info("[Curator][%s] CLI: model=%s tools=%s seeds=%d",
                 short, model, ",".join(allowed_tools), len(ds_seeds))

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            timeout=960,  # 15 min + 60s overhead
            cwd=str(repo_path),
        )
    except subprocess.TimeoutExpired:
        log.error("[Curator][%s] CLI timed out", short)
        return {"instance_id": iid, "files": [], "cost_usd": 0,
                "elapsed_sec": round(time.time() - start, 1), "error": True}
    finally:
        try:
            os.unlink(sys_file.name)
        except OSError:
            pass
        if mcp_config_path:
            try:
                os.unlink(mcp_config_path)
            except OSError:
                pass

    if result.returncode != 0:
        log.error("[Curator][%s] CLI failed (rc=%d): %s",
                  short, result.returncode,
                  (result.stderr or result.stdout or "")[:500])
        return {"instance_id": iid, "files": [], "cost_usd": 0,
                "elapsed_sec": round(time.time() - start, 1), "error": True}

    # Parse CLI JSON output
    try:
        cli_output = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as e:
        log.error("[Curator][%s] JSON parse failed: %s", short, e)
        return {"instance_id": iid, "files": [], "cost_usd": 0,
                "elapsed_sec": round(time.time() - start, 1), "error": True}

    # Extract oracle from result text
    result_text = cli_output.get("result", "")
    oracle = _extract_json_from_text(result_text)
    if oracle is None:
        log.warning("[Curator][%s] No oracle JSON in output", short)
        oracle = {"files": []}

    # Normalize file paths
    files_raw = oracle.get("files", [])
    if isinstance(files_raw, list):
        files = [_normalize_path(f) if isinstance(f, str) else "" for f in files_raw]
    else:
        files = []
    files = [f for f in files if f]

    elapsed = round(time.time() - start, 1)
    cost = cli_output.get("total_cost_usd", 0.0)
    log.info("[Curator][%s] Done in %.1fs ($%.4f) — %d files",
             short, elapsed, cost, len(files))

    return {
        "instance_id": iid,
        "files": files,
        "cost_usd": round(cost, 4),
        "elapsed_sec": elapsed,
        "error": False,
        "num_turns": cli_output.get("num_turns", 0),
    }


# ---------------------------------------------------------------------------
# Merge + Evaluate
# ---------------------------------------------------------------------------


def merge_predictions(
    ds_files: List[str],
    curator_files: List[str],
    strategy: str = "union",
) -> Tuple[Set[str], Dict[str, Any]]:
    """Merge DS and curator predictions with provenance tracking.

    Returns (merged_file_set, provenance_dict).
    """
    ds_set = {_normalize_path(f) for f in ds_files if f}
    cur_set = {_normalize_path(f) for f in curator_files if f}

    both = ds_set & cur_set
    ds_only = ds_set - cur_set
    cur_only = cur_set - ds_set

    if strategy == "union":
        merged = ds_set | cur_set
    elif strategy == "curator_refined":
        merged = cur_set  # curator is the authority; DS seeds were just input
    elif strategy == "intersection":
        merged = both
    else:
        raise ValueError(f"Unknown merge strategy: {strategy}")

    provenance = {
        "ds_only": sorted(ds_only),
        "curator_only": sorted(cur_only),
        "both": sorted(both),
        "n_ds_total": len(ds_set),
        "n_curator_total": len(cur_set),
        "n_merged": len(merged),
    }

    return merged, provenance


def evaluate_task(
    pred: Set[str],
    gold: Set[str],
) -> Dict[str, float]:
    """Compute precision, recall, F1."""
    matched = gold & pred
    missed = gold - pred
    extra = pred - gold
    recall = len(matched) / len(gold) if gold else 0
    precision = len(matched) / len(pred) if pred else 0
    f1 = (2 * recall * precision / (recall + precision)
          if (recall + precision) > 0 else 0)

    return {
        "n_gold": len(gold),
        "n_pred": len(pred),
        "n_matched": len(matched),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "matched": sorted(matched),
        "missed": sorted(missed),
        "extra": sorted(extra),
    }


def generate_report(
    task_results: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate the combined report JSON."""
    valid = [r for r in task_results if not r.get("error")]

    def _avg_metrics(results: List[Dict], key: str) -> Dict[str, float]:
        metrics_list = [r[key] for r in results if key in r and r[key]]
        if not metrics_list:
            return {"recall": 0, "precision": 0, "f1": 0}
        return {
            "recall": round(sum(m["recall"] for m in metrics_list) / len(metrics_list), 4),
            "precision": round(sum(m["precision"] for m in metrics_list) / len(metrics_list), 4),
            "f1": round(sum(m["f1"] for m in metrics_list) / len(metrics_list), 4),
        }

    # Provenance summary
    total_ds_only = sum(len(r.get("provenance", {}).get("ds_only", [])) for r in valid)
    total_cur_only = sum(len(r.get("provenance", {}).get("curator_only", [])) for r in valid)
    total_both = sum(len(r.get("provenance", {}).get("both", [])) for r in valid)

    # Hit rates: what fraction of each provenance category are gold matches?
    ds_only_hits = 0
    ds_only_total = 0
    cur_only_hits = 0
    cur_only_total = 0
    both_hits = 0
    both_total = 0
    for r in valid:
        gold = set(r.get("gold_files", []))
        prov = r.get("provenance", {})
        for f in prov.get("ds_only", []):
            ds_only_total += 1
            if _normalize_path(f) in gold:
                ds_only_hits += 1
        for f in prov.get("curator_only", []):
            cur_only_total += 1
            if _normalize_path(f) in gold:
                cur_only_hits += 1
        for f in prov.get("both", []):
            both_total += 1
            if _normalize_path(f) in gold:
                both_hits += 1

    total_cost = sum(r.get("curator_phase", {}).get("cost_usd", 0) for r in valid)
    total_elapsed = sum(
        r.get("ds_phase", {}).get("elapsed_sec", 0)
        + r.get("curator_phase", {}).get("elapsed_sec", 0)
        for r in valid
    )

    report = {
        "method": "hybrid_ds_curator",
        "merge_strategy": config.get("merge_strategy", "union"),
        "ds_pruned": config.get("prune", False),
        "curator_model": config.get("curator_model", "claude-opus-4-6"),
        "curator_backend": config.get("curator_backend", "hybrid"),
        "n_tasks": len(task_results),
        "n_valid": len(valid),
        "n_errors": len(task_results) - len(valid),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "file_metrics": _avg_metrics(valid, "merged_metrics"),
        "phase_metrics": {
            "ds_only": _avg_metrics(valid, "ds_metrics"),
            "curator_only": _avg_metrics(valid, "curator_metrics"),
        },
        "provenance_summary": {
            "total_ds_only_files": total_ds_only,
            "total_curator_only_files": total_cur_only,
            "total_both_files": total_both,
            "ds_only_hit_rate": round(ds_only_hits / ds_only_total, 4) if ds_only_total else 0,
            "curator_only_hit_rate": round(cur_only_hits / cur_only_total, 4) if cur_only_total else 0,
            "both_hit_rate": round(both_hits / both_total, 4) if both_total else 0,
        },
        "timing": {
            "total_elapsed_sec": round(total_elapsed, 1),
            "total_cost_usd": round(total_cost, 4),
        },
        "per_task": [
            {
                "instance_id": r["instance_id"],
                "error": r.get("error", False),
                "ds_phase": r.get("ds_phase", {}),
                "curator_phase": r.get("curator_phase", {}),
                "merged_metrics": r.get("merged_metrics", {}),
                "ds_metrics": r.get("ds_metrics", {}),
                "curator_metrics": r.get("curator_metrics", {}),
                "provenance": r.get("provenance", {}),
            }
            for r in task_results
        ],
    }

    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hybrid retrieval: DS broad discovery + Curator precise refinement"
    )
    parser.add_argument("--instance-ids", type=str, required=True,
                        help="Comma-separated instance ID suffixes")
    parser.add_argument("--merge-strategy", type=str, default="union",
                        choices=["union", "curator_refined", "intersection"],
                        help="How to merge DS + curator predictions (default: union)")
    parser.add_argument("--prune", action="store_true",
                        help="Apply DS pruning pass before curator")
    parser.add_argument("--parallel", type=int, default=5,
                        help="Concurrent DS queries (default: 5)")
    parser.add_argument("--curator-model", type=str, default="claude-opus-4-6",
                        help="Model for curator phase (default: claude-opus-4-6)")
    parser.add_argument("--curator-backend", type=str, default="hybrid",
                        choices=["local", "hybrid"],
                        help="Curator backend (default: hybrid)")
    parser.add_argument("--ds-only", action="store_true",
                        help="Skip curator phase (DS baseline)")
    parser.add_argument("--curator-only", action="store_true",
                        help="Skip DS phase (curator baseline)")
    parser.add_argument("--out", type=str, default="",
                        help="Output directory")
    parser.add_argument("--suite-name", type=str, default="",
                        help="Suite name for profile selection (e.g., csb_sdlc_fix)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Validate environment
    sg_token = (os.environ.get("SRC_ACCESS_TOKEN")
                or os.environ.get("SOURCEGRAPH_ACCESS_TOKEN", ""))
    sg_url = os.environ.get("SOURCEGRAPH_URL",
                            "https://sourcegraph.sourcegraph.com").rstrip("/")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if args.ds_only and args.curator_only:
        log.error("Cannot use --ds-only and --curator-only together")
        return 1

    # Load tasks
    suffixes = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
    tasks = load_tasks(suffixes)
    log.info("Loaded %d tasks", len(tasks))

    if not tasks:
        log.error("No tasks matched the given instance IDs")
        return 1

    if args.dry_run:
        mode = "hybrid"
        if args.ds_only:
            mode = "ds-only"
        elif args.curator_only:
            mode = "curator-only"
        print(f"\n{'=' * 60}")
        print(f"Hybrid Pipeline — {mode} mode")
        print(f"Merge strategy: {args.merge_strategy}")
        print(f"Curator model: {args.curator_model}")
        print(f"DS pruning: {args.prune}")
        print(f"{'=' * 60}")
        for t in tasks:
            print(f"  {t['instance_id']} ({t['repo']}) — {len(t['gold_files'])} gold files")
        print(f"\nTotal: {len(tasks)} tasks")
        return 0

    # Validate environment (after dry-run check)
    if not args.curator_only and not sg_token:
        log.error("SRC_ACCESS_TOKEN or SOURCEGRAPH_ACCESS_TOKEN required for DS phase")
        return 1

    if args.prune and not anthropic_key:
        log.warning("--prune requires ANTHROPIC_API_KEY; pruning disabled")
        args.prune = False

    cache_dir = get_cache_dir()

    # Output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    strategy_tag = args.merge_strategy
    if args.ds_only:
        strategy_tag = "ds_only"
    elif args.curator_only:
        strategy_tag = "curator_only"
    out_dir = Path(args.out) if args.out else RESULTS_DIR / f"hybrid_{strategy_tag}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Phase 1: DS Discovery (parallel)
    # -----------------------------------------------------------------------
    ds_results: Dict[str, Dict] = {}

    if not args.curator_only:
        log.info("=" * 60)
        log.info("PHASE 1: Deep Search Discovery (%d tasks, parallel=%d)",
                 len(tasks), args.parallel)
        log.info("=" * 60)

        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = {
                executor.submit(
                    run_ds_phase, task, sg_token, sg_url,
                    args.prune, anthropic_key
                ): task["instance_id"]
                for task in tasks
            }
            for future in as_completed(futures):
                iid = futures[future]
                try:
                    result = future.result(timeout=700)
                    ds_results[iid] = result
                except Exception as e:
                    log.error("[DS] Task %s failed: %s", iid, e)
                    ds_results[iid] = {
                        "instance_id": iid, "files": [], "raw_files": [],
                        "conv_id": None, "elapsed_sec": 0, "error": True,
                    }

        ds_ok = sum(1 for r in ds_results.values() if not r.get("error"))
        log.info("DS phase complete: %d/%d succeeded", ds_ok, len(tasks))
    else:
        log.info("Skipping DS phase (--curator-only)")

    # -----------------------------------------------------------------------
    # Phase 2: Curator Refinement (sequential)
    # -----------------------------------------------------------------------
    curator_results: Dict[str, Dict] = {}

    if not args.ds_only:
        log.info("=" * 60)
        log.info("PHASE 2: Curator Agent Refinement (%d tasks)", len(tasks))
        log.info("=" * 60)

        for i, task in enumerate(tasks, 1):
            iid = task["instance_id"]
            short = iid.split("__")[-1]

            # Get DS seeds for this task
            ds_data = ds_results.get(iid, {})
            ds_seeds = ds_data.get("files", []) if not ds_data.get("error") else []

            log.info("[%d/%d] Running curator for %s (DS seeds: %d)",
                     i, len(tasks), short, len(ds_seeds))

            result = run_curator_phase(
                task=task,
                ds_seeds=ds_seeds,
                model=args.curator_model,
                backend=args.curator_backend,
                verbose=args.verbose,
                cache_dir=cache_dir,
                suite_name=args.suite_name,
            )
            curator_results[iid] = result
    else:
        log.info("Skipping curator phase (--ds-only)")

    # -----------------------------------------------------------------------
    # Phase 3: Merge + Evaluate
    # -----------------------------------------------------------------------
    log.info("=" * 60)
    log.info("PHASE 3: Merge + Evaluate")
    log.info("=" * 60)

    task_results = []
    for task in tasks:
        iid = task["instance_id"]
        short = iid.split("__")[-1]
        gold = {_normalize_path(f) for f in task["gold_files"] if f}

        ds_data = ds_results.get(iid, {})
        cur_data = curator_results.get(iid, {})

        ds_files = ds_data.get("files", [])
        cur_files = cur_data.get("files", [])

        # Check for total failure
        ds_error = ds_data.get("error", True) if not args.curator_only else False
        cur_error = cur_data.get("error", True) if not args.ds_only else False
        total_error = (ds_error and not args.ds_only and not cur_files) and \
                      (cur_error and not args.curator_only and not ds_files)

        if args.ds_only:
            # DS-only mode: curator files empty
            cur_files = []
        elif args.curator_only:
            # Curator-only mode: DS files empty
            ds_files = []

        # Merge
        merged, provenance = merge_predictions(ds_files, cur_files, args.merge_strategy)

        # Evaluate all three views
        merged_metrics = evaluate_task(merged, gold)
        ds_metrics = evaluate_task({_normalize_path(f) for f in ds_files if f}, gold) if ds_files else {}
        cur_metrics = evaluate_task({_normalize_path(f) for f in cur_files if f}, gold) if cur_files else {}

        log.info("[%s] Merged: R=%.3f P=%.3f F1=%.3f | DS: R=%.3f F1=%.3f | Curator: R=%.3f F1=%.3f",
                 short,
                 merged_metrics["recall"], merged_metrics["precision"], merged_metrics["f1"],
                 ds_metrics.get("recall", 0), ds_metrics.get("f1", 0),
                 cur_metrics.get("recall", 0), cur_metrics.get("f1", 0))

        task_results.append({
            "instance_id": iid,
            "error": total_error,
            "gold_files": sorted(gold),
            "ds_phase": {
                "n_files": len(ds_files),
                "conv_id": ds_data.get("conv_id"),
                "elapsed_sec": ds_data.get("elapsed_sec", 0),
                "error": ds_data.get("error", True) if not args.curator_only else False,
            },
            "curator_phase": {
                "n_files": len(cur_files),
                "cost_usd": cur_data.get("cost_usd", 0),
                "elapsed_sec": cur_data.get("elapsed_sec", 0),
                "error": cur_data.get("error", True) if not args.ds_only else False,
                "num_turns": cur_data.get("num_turns", 0),
            },
            "merged_metrics": merged_metrics,
            "ds_metrics": ds_metrics,
            "curator_metrics": cur_metrics,
            "provenance": provenance,
        })

    # -----------------------------------------------------------------------
    # Phase 4: Report
    # -----------------------------------------------------------------------
    config = {
        "merge_strategy": args.merge_strategy,
        "prune": args.prune,
        "curator_model": args.curator_model,
        "curator_backend": args.curator_backend,
    }
    report = generate_report(task_results, config)

    report_path = out_dir / "hybrid_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    log.info("Report written to %s", report_path)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"HYBRID PIPELINE RESULTS ({report['merge_strategy']} merge)")
    print(f"{'=' * 60}")
    print(f"Tasks: {report['n_valid']}/{report['n_tasks']} valid")
    fm = report["file_metrics"]
    print(f"\nCombined:     R={fm['recall']:.3f}  P={fm['precision']:.3f}  F1={fm['f1']:.3f}")
    ds_m = report["phase_metrics"]["ds_only"]
    print(f"DS only:      R={ds_m['recall']:.3f}  P={ds_m['precision']:.3f}  F1={ds_m['f1']:.3f}")
    cur_m = report["phase_metrics"]["curator_only"]
    print(f"Curator only: R={cur_m['recall']:.3f}  P={cur_m['precision']:.3f}  F1={cur_m['f1']:.3f}")
    prov = report["provenance_summary"]
    print(f"\nProvenance: DS-only={prov['total_ds_only_files']} "
          f"Curator-only={prov['total_curator_only_files']} "
          f"Both={prov['total_both_files']}")
    print(f"Hit rates:  DS-only={prov['ds_only_hit_rate']:.2f} "
          f"Curator-only={prov['curator_only_hit_rate']:.2f} "
          f"Both={prov['both_hit_rate']:.2f}")
    print(f"\nCost: ${report['timing']['total_cost_usd']:.2f}")
    print(f"Time: {report['timing']['total_elapsed_sec']:.0f}s")
    print(f"\nReport: {report_path}")
    print(f"{'=' * 60}")

    # Per-task summary table
    print(f"\n{'Task':<12} {'Merged F1':>10} {'DS F1':>8} {'Cur F1':>8} {'DS#':>4} {'Cur#':>5} {'Gold#':>6}")
    print("-" * 60)
    for r in report["per_task"]:
        short = r["instance_id"].split("__")[-1][:10]
        mm = r.get("merged_metrics", {})
        dm = r.get("ds_metrics", {})
        cm = r.get("curator_metrics", {})
        print(f"{short:<12} {mm.get('f1', 0):>10.3f} {dm.get('f1', 0):>8.3f} "
              f"{cm.get('f1', 0):>8.3f} {r['ds_phase'].get('n_files', 0):>4} "
              f"{r['curator_phase'].get('n_files', 0):>5} "
              f"{mm.get('n_gold', 0):>6}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

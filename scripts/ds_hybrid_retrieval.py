#!/usr/bin/env python3
"""Deep Search hybrid retrieval: DS discovery → haiku precision filter.

Sends task problem statements to Sourcegraph Deep Search API, extracts
predicted file lists, optionally prunes with haiku, then evaluates against
ContextBench gold sets.

Usage:
    # Run on hard subset (9 tasks)
    python3 scripts/ds_hybrid_retrieval.py --instance-ids 157932b6,43d6d59b,2a93ee66,34826a6a,a42cace7,7df7e1c0,676e9486,0abc73df,61a7a81e

    # With haiku pruning
    python3 scripts/ds_hybrid_retrieval.py --instance-ids ... --prune

    # Dry run (show tasks, don't query)
    python3 scripts/ds_hybrid_retrieval.py --instance-ids ... --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

log = logging.getLogger("ds_hybrid")

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "results" / "contextbench"

DS_PROMPT_TEMPLATE = """\
I need to identify all files that would need to be modified in the {search_repo} repository to implement the following change. List ONLY file paths that would appear in the git diff of the fix — files that would be EDITED, CREATED, or DELETED.

IMPORTANT: Search ONLY in the repo:{search_repo} repository. This is a mirror of {repo} pinned at a specific commit.

{problem_statement}

Output your answer as a JSON object with a single key "files" containing a list of repo-relative file paths:
```json
{{"files": ["path/to/file1.ext", "path/to/file2.ext"]}}
```

Be thorough — include source files, test files that need updating, configuration files, schema files, lock files (go.mod, go.sum, Cargo.lock, etc.), documentation that would change, and any build/CI artifacts."""


def _normalize_path(p: str) -> str:
    """Normalize a file path: strip /workspace/repo__X.Y/ prefixes and leading /."""
    p = p.strip()
    # Strip /workspace/reponame__version/ prefix (SWE-bench workspace paths)
    if p.startswith("/workspace/"):
        parts = p.split("/", 3)  # ['', 'workspace', 'repo__ver', 'rest']
        if len(parts) >= 4 and "__" in parts[2]:
            p = parts[3]
        else:
            p = p[len("/workspace/"):]
    return p.lstrip("/")


def _extract_gold_files_from_row(row) -> List[str]:
    """Extract gold files using same logic as validate_on_contextbench.py.

    Uses both 'files' column and patch-derived file paths, then normalizes.
    """
    gold = set()

    # From gold_context annotations
    gc = row.get("gold_context", "[]")
    if isinstance(gc, str):
        try:
            gc = json.loads(gc)
        except (json.JSONDecodeError, TypeError):
            gc = []
    if isinstance(gc, list):
        for item in gc:
            if isinstance(item, dict) and "file" in item:
                gold.add(item["file"])

    # From patch diff (same as _extract_gold_files in validate_on_contextbench)
    patch = row.get("patch", "")
    if isinstance(patch, str):
        for line in patch.split("\n"):
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                path = line[6:].strip()
                if path and path != "/dev/null":
                    gold.add(path)

    # From test_patch
    test_patch = row.get("test_patch", "")
    if isinstance(test_patch, str):
        for line in test_patch.split("\n"):
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                path = line[6:].strip()
                if path and path != "/dev/null":
                    gold.add(path)

    # Normalize all paths
    normalized = set()
    for f in gold:
        n = _normalize_path(f)
        if n:
            normalized.add(n)

    return sorted(normalized)


def load_tasks(instance_suffixes: List[str]) -> List[Dict]:
    """Load ContextBench tasks matching the given instance ID suffixes."""
    import pandas as pd
    parquet = REPO_ROOT / "data" / "contextbench" / "full.parquet"
    df = pd.read_parquet(parquet)
    tasks = []
    for _, row in df.iterrows():
        iid = row["instance_id"]
        if any(iid.endswith(s) for s in instance_suffixes):
            gold_files = _extract_gold_files_from_row(row)
            tasks.append({
                "instance_id": iid,
                "repo": row.get("repo", ""),
                "base_commit": row.get("base_commit", ""),
                "problem_statement": row.get("problem_statement", ""),
                "gold_files": gold_files,
            })
    return tasks


def ds_create_conversation(question: str, token: str, sg_url: str) -> Optional[int]:
    """Create a Deep Search conversation and return its ID."""
    resp = requests.post(
        f"{sg_url}/.api/deepsearch/v1",
        headers={
            "Authorization": f"token {token}",
            "Content-Type": "application/json",
            "X-Requested-With": "ds-hybrid-retrieval",
        },
        json={"question": question},
        timeout=30,
    )
    if resp.status_code not in (200, 201, 202):
        log.error("DS create failed (%d): %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    return data.get("id")


def ds_poll_conversation(conv_id: int, token: str, sg_url: str,
                         poll_interval: int = 30, max_wait: int = 600) -> Optional[str]:
    """Poll a Deep Search conversation until completed. Returns the final reasoning text."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        resp = requests.get(
            f"{sg_url}/.api/deepsearch/v1/{conv_id}",
            headers={"Authorization": f"token {token}"},
            timeout=30,
        )
        if resp.status_code not in (200, 202):
            log.warning("DS poll failed (%d)", resp.status_code)
            time.sleep(poll_interval)
            continue
        data = resp.json()
        q = data["questions"][0]
        status = q["status"]
        if status == "completed":
            # Last turn has the answer in reasoning
            turns = q.get("turns", [])
            if turns:
                return turns[-1].get("reasoning", "")
            return ""
        elif status == "error":
            log.error("DS query errored for conv %d", conv_id)
            return None
        # Still processing
        tool_calls = q["stats"].get("tool_calls", 0)
        tokens = q["stats"].get("total_tokens", 0)
        log.debug("  conv %d: %s (tools=%d, tokens=%d)", conv_id, status, tool_calls, tokens)
        time.sleep(poll_interval)
    log.warning("DS query timed out for conv %d", conv_id)
    return None


def extract_files_from_ds_response(text: str) -> List[str]:
    """Extract file paths from Deep Search response text."""
    files = set()

    # Try JSON block extraction
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if isinstance(data.get("files"), list):
                return sorted(data["files"])
        except json.JSONDecodeError:
            pass

    # Try extracting from markdown table or bullet lists
    # Look for backtick-quoted file paths
    for match in re.finditer(r'`([a-zA-Z][\w/._-]+\.\w+)`', text):
        path = match.group(1)
        # Filter out obvious non-paths
        if "/" in path and not path.startswith("http"):
            files.add(path)

    # Look for file paths in numbered/bulleted lists
    for match in re.finditer(r'(?:^|\n)\s*(?:\d+\.|\-|\*)\s+\[?`?([a-zA-Z][\w/._-]+\.\w+)', text):
        path = match.group(1)
        if "/" in path:
            files.add(path)

    # Look for file paths in table rows
    for match in re.finditer(r'\|\s*`?([a-zA-Z][\w/._-]+\.\w+)`?\s*\|', text):
        path = match.group(1)
        if "/" in path:
            files.add(path)

    # Look for ### N. `path` pattern (Deep Search's common format)
    for match in re.finditer(r'###?\s+\d+\.\s+\[?`([a-zA-Z][\w/._-]+\.\w+)`', text):
        path = match.group(1)
        if "/" in path:
            files.add(path)

    return sorted(files)


def prune_with_sonnet(files: List[str], problem_statement: str,
                      token: str) -> List[str]:
    """Use Sonnet to prune false positives from file list."""
    import anthropic
    client = anthropic.Anthropic(api_key=token)

    file_list = "\n".join(f"- {f}" for f in files)
    prompt = f"""You are a precision filter for a code retrieval system. Given a task
description and a list of candidate files, identify which files would actually
appear in the git diff of a correct implementation.

## Task Description
{problem_statement[:3000]}

## Candidate Files
{file_list}

## Instructions
For each file, decide KEEP or DROP.

KEEP files that would be EDITED, CREATED, or DELETED by the change.
DROP files that:
- Are only READ for context but not modified
- Test a DIFFERENT feature/module than described
- Are documentation/changelog files NOT mentioned in the task
- Are lock files (go.sum, package-lock.json) unless a new dependency is explicitly needed

Output a JSON object:
```json
{{"keep": ["file1.py", "file2.py"], "drop": ["file3.py"]}}
```"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text

    # Extract JSON
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            keep = data.get("keep", [])
            if keep:
                return keep
        except json.JSONDecodeError:
            pass

    # Fallback: try raw JSON parse
    try:
        data = json.loads(text)
        return data.get("keep", files)
    except json.JSONDecodeError:
        pass

    log.warning("Pruning failed, keeping all %d files", len(files))
    return files


def process_task(task: Dict, token: str, sg_url: str,
                 prune: bool = False, anthropic_key: str = "") -> Dict:
    """Run DS retrieval + optional pruning for a single task."""
    iid = task["instance_id"]
    short = iid.split("__")[-1]
    repo = task["repo"]
    problem = task["problem_statement"]
    gold = set(task["gold_files"])

    # Compute mirror repo name: sg-evals/{repo_short}--{commit8}
    repo_short = repo.split("/")[-1] if "/" in repo else repo
    commit = task.get("base_commit", "")
    commit8 = commit[:8]
    mirror_repo = f"github.com/sg-evals/{repo_short}--{commit8}"

    log.info("[%s] Querying Deep Search for %s (mirror: %s)...", short, repo, mirror_repo)

    question = DS_PROMPT_TEMPLATE.format(
        search_repo=mirror_repo,
        repo=repo,
        problem_statement=problem[:4000],
    )

    conv_id = ds_create_conversation(question, token, sg_url)
    if conv_id is None:
        log.error("[%s] Failed to create DS conversation", short)
        return {"instance_id": iid, "error": True}

    log.info("[%s] DS conversation %d created, polling...", short, conv_id)
    response_text = ds_poll_conversation(conv_id, token, sg_url)
    if response_text is None:
        log.error("[%s] DS query failed/timed out", short)
        return {"instance_id": iid, "error": True}

    # Extract file predictions
    raw_files = extract_files_from_ds_response(response_text)
    log.info("[%s] DS returned %d files", short, len(raw_files))

    # Optional pruning
    if prune and len(raw_files) > 1 and anthropic_key:
        pruned_files = prune_with_sonnet(raw_files, problem, anthropic_key)
        log.info("[%s] Pruned %d → %d files", short, len(raw_files), len(pruned_files))
    else:
        pruned_files = raw_files

    pred = {_normalize_path(f) for f in pruned_files if f}

    # Evaluate (normalize gold too for consistency)
    gold = {_normalize_path(f) for f in gold if f}
    matched = gold & pred
    missed = gold - pred
    extra = pred - gold
    recall = len(matched) / len(gold) if gold else 0
    precision = len(matched) / len(pred) if pred else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0

    result = {
        "instance_id": iid,
        "error": False,
        "n_gold": len(gold),
        "n_raw": len(raw_files),
        "n_pred": len(pruned_files),
        "n_matched": len(matched),
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "matched": sorted(matched),
        "missed": sorted(missed),
        "extra": sorted(extra),
        "raw_files": raw_files,
        "pruned": prune,
        "ds_conversation_id": conv_id,
    }

    log.info("[%s] R=%.3f P=%.3f F1=%.3f (gold=%d, pred=%d, matched=%d)",
             short, recall, precision, f1, len(gold), len(pred), len(matched))

    return result


def main():
    parser = argparse.ArgumentParser(description="Deep Search hybrid retrieval")
    parser.add_argument("--instance-ids", type=str, required=True,
                        help="Comma-separated instance ID suffixes")
    parser.add_argument("--prune", action="store_true",
                        help="Apply haiku pruning pass")
    parser.add_argument("--parallel", type=int, default=5,
                        help="Concurrent DS queries")
    parser.add_argument("--out", type=str, default="",
                        help="Output directory")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sg_token = os.environ.get("SRC_ACCESS_TOKEN") or os.environ.get("SOURCEGRAPH_ACCESS_TOKEN", "")
    sg_url = os.environ.get("SOURCEGRAPH_URL", "https://sourcegraph.sourcegraph.com").rstrip("/")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if not sg_token:
        log.error("SRC_ACCESS_TOKEN or SOURCEGRAPH_ACCESS_TOKEN required")
        return 1

    if args.prune and not anthropic_key:
        log.warning("--prune requires ANTHROPIC_API_KEY; pruning disabled")
        args.prune = False

    suffixes = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
    tasks = load_tasks(suffixes)
    log.info("Loaded %d tasks", len(tasks))

    if args.dry_run:
        for t in tasks:
            print(f"  {t['instance_id']} ({t['repo']}) — {len(t['gold_files'])} gold files")
        return 0

    # Run queries in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(process_task, task, sg_token, sg_url,
                            args.prune, anthropic_key): task["instance_id"]
            for task in tasks
        }
        for future in as_completed(futures):
            try:
                result = future.result(timeout=700)
                results.append(result)
            except Exception as e:
                iid = futures[future]
                log.error("Task %s failed: %s", iid, e)
                results.append({"instance_id": iid, "error": True})

    # Aggregate metrics
    valid = [r for r in results if not r.get("error")]
    if not valid:
        log.error("No tasks completed successfully")
        return 1

    avg_recall = sum(r["recall"] for r in valid) / len(valid)
    avg_precision = sum(r["precision"] for r in valid) / len(valid)
    avg_f1 = sum(r["f1"] for r in valid) / len(valid)
    total_extra = sum(len(r["extra"]) for r in valid)
    total_missed = sum(len(r["missed"]) for r in valid)

    print("\n" + "=" * 80)
    print(f"DS HYBRID RETRIEVAL RESULTS ({len(valid)}/{len(results)} tasks)")
    print("=" * 80)
    print(f"  Avg Recall:    {avg_recall:.3f}")
    print(f"  Avg Precision: {avg_precision:.3f}")
    print(f"  Avg F1:        {avg_f1:.3f}")
    print(f"  Total extra:   {total_extra}")
    print(f"  Total missed:  {total_missed}")
    print(f"  Pruning:       {'yes' if args.prune else 'no'}")

    print(f"\n{'Task':>12} | {'Gold':>4} | {'Raw':>4} | {'Pred':>4} | {'R':>5} | {'P':>5} | {'F1':>5} | {'Extra':>5} | {'Miss':>5}")
    print("-" * 80)
    for r in sorted(valid, key=lambda x: x["instance_id"]):
        short = r["instance_id"].split("__")[-1]
        print(f"{short:>12} | {r['n_gold']:>4} | {r['n_raw']:>4} | {r['n_pred']:>4} | "
              f"{r['recall']:.3f} | {r['precision']:.3f} | {r['f1']:.3f} | "
              f"{len(r['extra']):>5} | {len(r['missed']):>5}")

    # Save results
    out_dir = Path(args.out) if args.out else RESULTS_DIR / f"ds_hybrid_{'pruned' if args.prune else 'raw'}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "method": "ds_hybrid",
        "pruned": args.prune,
        "n_tasks": len(valid),
        "file_metrics": {
            "recall": round(avg_recall, 4),
            "precision": round(avg_precision, 4),
            "f1": round(avg_f1, 4),
        },
        "per_task": valid,
    }
    report_path = out_dir / "ds_hybrid_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)

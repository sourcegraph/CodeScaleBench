#!/usr/bin/env python3
"""Oracle curation tool for MCP-unique benchmark tasks.

Uses the Sourcegraph search API to automatically generate exhaustive
closed-world oracle_answer.json files by searching repos for files,
symbols, and dependency chains.

Reads:  task_spec.json + repo-set fixture
Writes: oracle_answer.json, oracle_curation_log.json

Environment variables:
    SOURCEGRAPH_URL          SG instance URL (default: https://sourcegraph.sourcegraph.com)
    SOURCEGRAPH_ACCESS_TOKEN SG API token
    SRC_ENDPOINT             Fallback for SOURCEGRAPH_URL
    SRC_ACCESS_TOKEN         Fallback for SOURCEGRAPH_ACCESS_TOKEN

Usage:
    python3 scripts/curate_oracle.py --task-dir benchmarks/ccb_mcp_crossrepo_tracing/dep-trace-001
    python3 scripts/curate_oracle.py --task-spec task_spec.json --verify --verbose
    python3 scripts/curate_oracle.py --task-dir <dir> --verify --verbose
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Sourcegraph API client (stdlib-only: urllib)
# ---------------------------------------------------------------------------

class SourcegraphClient:
    """Thin wrapper around the Sourcegraph GraphQL search API."""

    DEFAULT_URL = "https://sourcegraph.sourcegraph.com"
    GRAPHQL_PATH = "/.api/graphql"

    def __init__(self, url: str, token: str, verbose: bool = False):
        self.url = url.rstrip("/")
        self.token = token
        self.verbose = verbose
        self.queries_made = 0
        self._request_log: List[Dict] = []
        self._rate_limit_delay = 1.0  # seconds between requests

    def graphql(
        self,
        query: str,
        variables: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Dict:
        """Execute a GraphQL query against the SG API with retry/backoff."""
        endpoint = f"{self.url}{self.GRAPHQL_PATH}"
        payload = json.dumps({"query": query, "variables": variables or {}}).encode()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"token {self.token}",
        }
        req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

        # Polite rate limiting
        if self.queries_made > 0:
            time.sleep(self._rate_limit_delay)
        self.queries_made += 1

        log_entry: Dict[str, Any] = {
            "query_index": self.queries_made,
            "variables": variables or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        last_exc: Optional[Exception] = None
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                if "errors" in data and data["errors"]:
                    logging.warning("GraphQL errors: %s", data["errors"])
                result = data.get("data", {})
                log_entry["status"] = "ok"
                self._request_log.append(log_entry)
                if self.verbose:
                    logging.debug("SG query #%d: ok", self.queries_made)
                return result
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code == 429:
                    wait = min(2 ** (attempt + 1), 120)  # cap at 120s
                    logging.warning("Rate limited (429), waiting %ds", wait)
                    time.sleep(wait)
                else:
                    logging.error("HTTP %d from SG API", exc.code)
                    break
            except urllib.error.URLError as exc:
                last_exc = exc
                logging.warning("URLError (attempt %d): %s", attempt, exc)
                time.sleep(1)

        log_entry["status"] = "error"
        log_entry["error"] = str(last_exc)
        self._request_log.append(log_entry)
        return {}

    def search_files(self, sg_query: str, max_results: int = 200) -> List[Dict]:
        """Return list of {repo, path, line_matches} from a file search."""
        gql = """
        query CurateFiles($query: String!) {
          search(query: $query, version: V2) {
            results {
              results {
                ... on FileMatch {
                  repository { name }
                  file { path }
                  lineMatches { lineNumber preview }
                }
              }
            }
          }
        }
        """
        full_query = f"{sg_query} count:{max_results}"
        resp = self.graphql(gql, {"query": full_query})
        items = []
        for r in (resp.get("search") or {}).get("results", {}).get("results", []):
            repo = (r.get("repository") or {}).get("name", "")
            path = (r.get("file") or {}).get("path", "")
            if repo and path:
                items.append({
                    "repo": repo,
                    "path": path,
                    "line_matches": r.get("lineMatches", []),
                })
        return items

    def search_symbols(self, sg_query: str, max_results: int = 100) -> List[Dict]:
        """Return list of {repo, path, symbol, kind} from a symbol search."""
        gql = """
        query CurateSymbols($query: String!) {
          search(query: $query, version: V2) {
            results {
              results {
                ... on FileMatch {
                  repository { name }
                  file { path }
                  symbols {
                    name
                    kind
                    location {
                      resource { path }
                      range { start { line character } }
                    }
                  }
                }
              }
            }
          }
        }
        """
        full_query = f"type:symbol {sg_query} count:{max_results}"
        resp = self.graphql(gql, {"query": full_query})
        symbols = []
        for r in (resp.get("search") or {}).get("results", {}).get("results", []):
            repo = (r.get("repository") or {}).get("name", "")
            path = (r.get("file") or {}).get("path", "")
            for sym in r.get("symbols", []):
                symbols.append({
                    "repo": repo,
                    "path": path,
                    "symbol": sym.get("name", ""),
                    "kind": sym.get("kind", ""),
                    "line": (sym.get("location") or {}).get("range", {}).get("start", {}).get("line", 0),
                })
        return symbols

    def get_request_log(self) -> List[Dict]:
        return list(self._request_log)


# ---------------------------------------------------------------------------
# Fixture and spec loading
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    """Walk up from start (and from CWD) to find the project root (contains 'fixtures/' dir)."""
    for root_candidate in [start.resolve(), Path.cwd().resolve()]:
        current = root_candidate
        for _ in range(10):
            if (current / "fixtures").is_dir() or (current / "benchmarks").is_dir():
                return current
            current = current.parent
    return start.resolve()


def load_fixture(repo_set_id: str, project_root: Path) -> Optional[Dict]:
    """Load a repo-set fixture by ID."""
    fixture_path = project_root / "fixtures" / "repo_sets" / f"{repo_set_id}.json"
    if not fixture_path.exists():
        logging.error("Fixture not found: %s", fixture_path)
        return None
    with open(fixture_path) as f:
        return json.load(f)


def get_repos_from_fixture(fixture: Dict) -> List[str]:
    """Extract all repo full names from a fixture."""
    return [r.get("full_name", "") for r in fixture.get("repos", []) if r.get("full_name")]


def _repo_sg_name(full_name: str) -> str:
    """Convert org/repo to github.com/org/repo for SG queries."""
    if full_name.startswith("github.com/"):
        return full_name
    return f"github.com/{full_name}"


# ---------------------------------------------------------------------------
# Oracle curation strategies
# ---------------------------------------------------------------------------

def curate_file_set_match(
    client: SourcegraphClient,
    check_params: Dict,
    repos: List[str],
    log: List[Dict],
) -> List[Dict]:
    """Search repos for files matching a pattern. Returns oracle file list."""
    search_pattern = check_params.get("search_pattern", "")
    file_filter = check_params.get("file_filter", "")

    if not search_pattern:
        logging.warning("file_set_match: no search_pattern in params — skipping")
        return []

    oracle_files = []
    seen = set()

    for repo in repos:
        sg_repo = _repo_sg_name(repo)
        query = f"repo:^{sg_repo}$ {search_pattern}"
        if file_filter:
            query += f" file:{file_filter}"

        log.append({"type": "file_set_match", "repo": repo, "query": query})
        results = client.search_files(query)
        logging.info("  %s: %d file matches", repo, len(results))

        for r in results:
            key = (r["repo"], r["path"])
            if key not in seen:
                seen.add(key)
                oracle_files.append({"repo": r["repo"], "path": r["path"]})

    return oracle_files


def curate_symbol_resolution(
    client: SourcegraphClient,
    check_params: Dict,
    repos: List[str],
    log: List[Dict],
) -> List[Dict]:
    """Search repos for symbol definitions. Returns oracle symbol list."""
    symbol_pattern = check_params.get("symbol_name", check_params.get("search_pattern", ""))
    kind_filter = check_params.get("kind_filter", "")  # e.g. "func", "class"

    if not symbol_pattern:
        logging.warning("symbol_resolution: no symbol_name/search_pattern in params — skipping")
        return []

    oracle_symbols = []
    seen = set()

    for repo in repos:
        sg_repo = _repo_sg_name(repo)
        query = f"repo:^{sg_repo}$ {symbol_pattern}"
        if kind_filter:
            query += f" type:symbol"

        log.append({"type": "symbol_resolution", "repo": repo, "query": query})
        results = client.search_symbols(query)
        logging.info("  %s: %d symbol matches", repo, len(results))

        for sym in results:
            key = (sym["repo"], sym["path"], sym["symbol"])
            if key not in seen:
                seen.add(key)
                oracle_symbols.append({
                    "repo": sym["repo"],
                    "path": sym["path"],
                    "symbol": sym["symbol"],
                    "kind": sym.get("kind", ""),
                })

    return oracle_symbols


def curate_dependency_chain(
    client: SourcegraphClient,
    check_params: Dict,
    repos: List[str],
    log: List[Dict],
) -> List[Dict]:
    """Trace an import/call chain across repos. Returns ordered chain steps."""
    chain_steps = check_params.get("chain_steps", [])
    # chain_steps: list of {search_pattern, repo_hint, symbol_hint}

    if not chain_steps:
        logging.warning("dependency_chain: no chain_steps in params — skipping")
        return []

    chain = []

    for step in chain_steps:
        pattern = step.get("search_pattern", "")
        repo_hint = step.get("repo_hint", "")
        symbol_hint = step.get("symbol_hint", "")

        search_repos = [repo_hint] if repo_hint else repos
        for repo in search_repos:
            sg_repo = _repo_sg_name(repo)
            query = f"repo:^{sg_repo}$ {pattern}"

            log.append({"type": "dependency_chain_step", "repo": repo, "query": query, "symbol_hint": symbol_hint})
            results = client.search_files(query)

            if results:
                r = results[0]  # take first match per step
                chain.append({
                    "repo": r["repo"],
                    "path": r["path"],
                    "symbol": symbol_hint or pattern,
                })
                break  # found this step

    return chain


def curate_provenance(
    check_params: Dict,
    repos: List[str],
    oracle_files: List[Dict],
) -> Dict:
    """Build provenance oracle from must_cite_paths/repos."""
    must_cite_paths = check_params.get("must_cite_paths", [])
    must_cite_repos = check_params.get("must_cite_repos", [])

    # Auto-populate from oracle_files if not specified
    if not must_cite_paths and oracle_files:
        must_cite_paths = [f["path"] for f in oracle_files[:5]]
    if not must_cite_repos and repos:
        must_cite_repos = repos[:3]

    return {
        "must_cite_paths": must_cite_paths,
        "must_cite_repos": must_cite_repos,
    }


def curate_keyword_presence(
    check_params: Dict,
) -> List[str]:
    """Return required keywords from params (already the oracle)."""
    return check_params.get("required_keywords", [])


# ---------------------------------------------------------------------------
# Main curation orchestrator
# ---------------------------------------------------------------------------

def curate_oracle(
    task_spec: Dict,
    client: SourcegraphClient,
    fixture: Optional[Dict],
    project_root: Path,
    verbose: bool = False,
) -> Tuple[Dict, List[Dict]]:
    """Curate oracle_answer.json content by searching SG for each check type.

    Returns (oracle_answer, curation_log_entries).
    """
    log: List[Dict] = []
    oracle_answer: Dict[str, Any] = {}

    oracle_def = task_spec.get("artifacts", {}).get("oracle", {})
    eval_checks = task_spec.get("evaluation", {}).get("checks", [])

    # Get repos from fixture
    repos: List[str] = []
    if fixture:
        repos = get_repos_from_fixture(fixture)
        log.append({"event": "repos_from_fixture", "repos": repos})
    else:
        logging.warning("No fixture loaded — using repos from oracle definition if any")

    # If oracle already has required_files, include them as starting point
    existing_files = oracle_def.get("required_files", [])
    existing_symbols = oracle_def.get("required_symbols", [])
    existing_chains = oracle_def.get("dependency_chains", [])

    # Track oracle items across checks (for cross-check reuse)
    all_oracle_files: List[Dict] = list(existing_files)
    all_oracle_symbols: List[Dict] = list(existing_symbols)
    all_chains: List[Dict] = list(existing_chains)

    for check in eval_checks:
        check_type = check.get("type", "")
        params = check.get("params", {})

        logging.info("Curating check: %s", check_type)

        if check_type == "file_set_match" and repos:
            new_files = curate_file_set_match(client, params, repos, log)
            # Merge with existing
            seen = {(f["repo"], f["path"]) for f in all_oracle_files}
            for f in new_files:
                key = (f["repo"], f["path"])
                if key not in seen:
                    all_oracle_files.append(f)
                    seen.add(key)
            log.append({
                "event": "file_set_match_complete",
                "new_items": len(new_files),
                "total_items": len(all_oracle_files),
            })

        elif check_type == "symbol_resolution" and repos:
            new_syms = curate_symbol_resolution(client, params, repos, log)
            seen = {(s["repo"], s["path"], s["symbol"]) for s in all_oracle_symbols}
            for s in new_syms:
                key = (s["repo"], s["path"], s["symbol"])
                if key not in seen:
                    all_oracle_symbols.append(s)
                    seen.add(key)
            log.append({
                "event": "symbol_resolution_complete",
                "new_items": len(new_syms),
                "total_items": len(all_oracle_symbols),
            })

        elif check_type == "dependency_chain" and repos:
            chain_steps = curate_dependency_chain(client, params, repos, log)
            if chain_steps:
                chain_id = params.get("chain_id", f"chain_{len(all_chains)}")
                all_chains.append({"chain_id": chain_id, "steps": chain_steps})
            log.append({
                "event": "dependency_chain_complete",
                "steps_found": len(chain_steps),
            })

        elif check_type == "provenance":
            prov = curate_provenance(params, repos, all_oracle_files)
            oracle_answer["provenance"] = prov
            log.append({"event": "provenance_oracle", "result": prov})

        elif check_type == "keyword_presence":
            kws = curate_keyword_presence(params)
            oracle_answer["required_keywords"] = kws
            log.append({"event": "keyword_presence_oracle", "keywords": kws})

        elif check_type in ("json_schema_match", "test_ratio"):
            # These checks don't require oracle curation
            log.append({"event": f"{check_type}_no_curation_needed"})

        else:
            logging.warning("Unknown or uncuratable check type: %s", check_type)

    # Build oracle_answer structure compatible with oracle_checks.py
    if all_oracle_files:
        oracle_answer["files"] = all_oracle_files
    if all_oracle_symbols:
        oracle_answer["symbols"] = all_oracle_symbols
    if all_chains:
        oracle_answer["chains"] = all_chains
        # Also flatten to "chain" for compatibility with check_dependency_chain
        if len(all_chains) == 1:
            oracle_answer["chain"] = all_chains[0]["steps"]

    # Build a narrative text for provenance/keyword checks
    text_parts = []
    for f in all_oracle_files[:10]:
        text_parts.append(f"{f['repo']} at {f['path']}")
    for s in all_oracle_symbols[:5]:
        text_parts.append(f"{s['symbol']} in {s['repo']}/{s['path']}")
    if text_parts:
        oracle_answer["text"] = " | ".join(text_parts)

    # Metadata
    oracle_answer["_metadata"] = {
        "discovery_method": "sourcegraph_api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repos_searched": repos,
        "sg_queries_made": client.queries_made,
    }

    return oracle_answer, log


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def find_task_spec(task_dir: Path) -> Optional[Path]:
    for p in [task_dir / "task_spec.json", task_dir / "tests" / "task_spec.json"]:
        if p.exists():
            return p
    return None


def find_oracle_answer(task_dir: Path) -> Optional[Path]:
    for p in [task_dir / "tests" / "oracle_answer.json", task_dir / "oracle_answer.json"]:
        if p.exists():
            return p
    return None


def oracle_answer_path(task_dir: Path) -> Path:
    """Return canonical path for writing oracle_answer.json."""
    tests_dir = task_dir / "tests"
    if tests_dir.is_dir():
        return tests_dir / "oracle_answer.json"
    return task_dir / "oracle_answer.json"


def oracle_log_path(task_dir: Path) -> Path:
    """Return canonical path for writing oracle_curation_log.json."""
    tests_dir = task_dir / "tests"
    if tests_dir.is_dir():
        return tests_dir / "oracle_curation_log.json"
    return task_dir / "oracle_curation_log.json"


def merge_oracle_answers(existing: Dict, new: Dict) -> Dict:
    """Merge new oracle findings into existing oracle_answer.json."""
    merged = dict(existing)

    # Merge files (dedup by repo+path)
    existing_files = {(f["repo"], f["path"]) for f in merged.get("files", [])}
    for f in new.get("files", []):
        key = (f["repo"], f["path"])
        if key not in existing_files:
            merged.setdefault("files", []).append(f)
            existing_files.add(key)

    # Merge symbols (dedup by repo+path+symbol)
    existing_syms = {(s["repo"], s["path"], s["symbol"]) for s in merged.get("symbols", [])}
    for s in new.get("symbols", []):
        key = (s["repo"], s["path"], s["symbol"])
        if key not in existing_syms:
            merged.setdefault("symbols", []).append(s)
            existing_syms.add(key)

    # Replace chains (new wins)
    if "chains" in new:
        merged["chains"] = new["chains"]
    if "chain" in new:
        merged["chain"] = new["chain"]

    # Merge other fields
    for k in ("provenance", "required_keywords"):
        if k in new:
            merged[k] = new[k]

    # Update text
    if "text" in new:
        merged["text"] = new["text"]

    # Update metadata
    merged["_metadata"] = new.get("_metadata", merged.get("_metadata", {}))

    return merged


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _get_sg_credentials() -> Tuple[str, str]:
    """Read SG URL and token from environment."""
    url = (
        os.environ.get("SOURCEGRAPH_URL")
        or os.environ.get("SRC_ENDPOINT")
        or SourcegraphClient.DEFAULT_URL
    )
    token = (
        os.environ.get("SOURCEGRAPH_ACCESS_TOKEN")
        or os.environ.get("SRC_ACCESS_TOKEN")
        or ""
    )
    return url, token


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate oracle_answer.json for MCP-unique benchmark tasks using Sourcegraph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--task-dir", metavar="DIR",
        help="Task directory (contains task_spec.json or tests/task_spec.json).",
    )
    parser.add_argument(
        "--task-spec", metavar="PATH",
        help="Direct path to task_spec.json (overrides --task-dir discovery).",
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="After curation, run validate_mcp_task_instance.py to confirm validity gate passes.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print detailed progress.",
    )
    parser.add_argument(
        "--max-results", type=int, default=200,
        help="Maximum results per SG search query (default: 200).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse spec and plan queries without calling SG API.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Resolve paths
    if not args.task_dir and not args.task_spec:
        parser.error("One of --task-dir or --task-spec is required.")

    task_dir: Optional[Path] = Path(args.task_dir).resolve() if args.task_dir else None
    spec_path: Optional[Path] = Path(args.task_spec).resolve() if args.task_spec else None

    if task_dir and not spec_path:
        spec_path = find_task_spec(task_dir)
        if not spec_path:
            logging.error("task_spec.json not found in %s", task_dir)
            return 1

    if not task_dir and spec_path:
        task_dir = spec_path.parent

    assert task_dir is not None and spec_path is not None

    # Load task spec
    try:
        with open(spec_path) as f:
            task_spec = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logging.error("Cannot load task_spec.json: %s", exc)
        return 1

    # Determine project root and load fixture
    project_root = _find_project_root(task_dir)
    logging.info("Project root: %s", project_root)

    repo_set_id = task_spec.get("artifacts", {}).get("repo_set_id", "")
    fixture = None
    if repo_set_id:
        fixture = load_fixture(repo_set_id, project_root)
        if fixture:
            logging.info("Loaded fixture: %s (%d repos)", repo_set_id, len(fixture.get("repos", [])))
        else:
            logging.warning("Fixture '%s' not found — curation will use oracle definition only", repo_set_id)
    else:
        logging.warning("No repo_set_id in task_spec — curation will search oracle repos only")

    # Load existing oracle_answer.json for incremental mode
    existing_oracle_path = find_oracle_answer(task_dir)
    existing_oracle: Dict = {}
    if existing_oracle_path:
        try:
            with open(existing_oracle_path) as f:
                existing_oracle = json.load(f)
            logging.info("Loaded existing oracle_answer.json (%d files)", len(existing_oracle.get("files", [])))
        except (json.JSONDecodeError, OSError):
            logging.warning("Could not load existing oracle_answer.json — starting fresh")

    if args.dry_run:
        logging.info("[DRY RUN] Would curate checks: %s",
                     [c.get("type") for c in task_spec.get("evaluation", {}).get("checks", [])])
        logging.info("[DRY RUN] Would search repos: %s",
                     get_repos_from_fixture(fixture) if fixture else [])
        return 0

    # Set up SG client
    sg_url, sg_token = _get_sg_credentials()
    if not sg_token:
        logging.warning("No SOURCEGRAPH_ACCESS_TOKEN set — SG API calls may fail or be rate-limited")

    client = SourcegraphClient(sg_url, sg_token, verbose=args.verbose)
    logging.info("Using SG instance: %s", sg_url)

    # Curate oracle
    logging.info("Curating oracle for task: %s", task_spec.get("id", spec_path.name))
    oracle_answer, curation_log = curate_oracle(task_spec, client, fixture, project_root, args.verbose)

    # Merge with existing
    if existing_oracle:
        oracle_answer = merge_oracle_answers(existing_oracle, oracle_answer)
        logging.info("Merged with existing oracle: %d files, %d symbols",
                     len(oracle_answer.get("files", [])), len(oracle_answer.get("symbols", [])))

    # Write oracle_answer.json
    out_oracle = oracle_answer_path(task_dir)
    out_oracle.parent.mkdir(parents=True, exist_ok=True)
    with open(out_oracle, "w") as f:
        json.dump(oracle_answer, f, indent=2)
    logging.info("Wrote oracle_answer.json -> %s (%d files, %d symbols)",
                 out_oracle, len(oracle_answer.get("files", [])), len(oracle_answer.get("symbols", [])))

    # Write oracle_curation_log.json
    log_data = {
        "task_id": task_spec.get("id", ""),
        "task_spec_path": str(spec_path),
        "curated_at": datetime.now(timezone.utc).isoformat(),
        "sg_url": sg_url,
        "sg_queries_made": client.queries_made,
        "repos_searched": get_repos_from_fixture(fixture) if fixture else [],
        "curation_entries": curation_log,
        "sg_request_log": client.get_request_log(),
    }
    out_log = oracle_log_path(task_dir)
    with open(out_log, "w") as f:
        json.dump(log_data, f, indent=2)
    logging.info("Wrote oracle_curation_log.json -> %s", out_log)

    # Verify
    if args.verify:
        validator = project_root / "scripts" / "validate_mcp_task_instance.py"
        if not validator.exists():
            logging.warning("validate_mcp_task_instance.py not found — skipping verify")
        else:
            logging.info("Running validity gate...")
            result = subprocess.run(
                [sys.executable, str(validator), "--task-dir", str(task_dir), "--verbose"],
                capture_output=True,
                text=True,
            )
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            if result.returncode != 0:
                logging.error("Validity gate FAILED")
                return 1
            logging.info("Validity gate PASSED")

    return 0


if __name__ == "__main__":
    sys.exit(main())

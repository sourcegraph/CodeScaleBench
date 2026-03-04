#!/usr/bin/env python3
"""Oracle-based retrieval quality analysis for MCP-unique haiku runs.

Extracts answer.json from agent trajectories, loads task_spec.json oracle
definitions, runs oracle checks programmatically, and compares baseline vs MCP.

Stdlib only.
"""

import json
import re
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
STAGING_DIR = BASE_DIR / "runs" / "staging"
BENCHMARKS_DIR = BASE_DIR / "benchmarks"
RUN_TIMESTAMP = "20260221_140913"

# Task → suite mapping
TASK_SUITE = {
    "ccx-dep-trace-001": "csb_org_crossrepo_tracing",
    "ccx-dep-trace-004": "csb_org_crossrepo_tracing",
    "ccx-config-trace-010": "csb_org_crossrepo_tracing",
    "ccx-vuln-remed-011": "csb_org_security",
    "ccx-vuln-remed-014": "csb_org_security",
    "ccx-incident-031": "csb_org_incident",
    "ccx-onboard-041": "csb_org_onboarding",
    "ccx-onboard-050-ds": "csb_org_onboarding",
    "ccx-explore-042-ds": "csb_org_onboarding",
    "ccx-crossorg-061": "csb_org_crossorg",
    "ccx-crossorg-066": "csb_org_crossorg",
    "ccx-explore-091-ds": "csb_org_platform",
}

CONFIGS = ["baseline-local-artifact", "mcp-remote-artifact"]

# Hosting prefix normalization (from oracle_checks.py)
_HOSTING_PREFIX_RE = re.compile(r"^(?:github\.com|gitlab\.com|bitbucket\.org)/")


def _normalize_repo(repo):
    return _HOSTING_PREFIX_RE.sub("", repo)


# ── Oracle check functions (inlined from oracle_checks.py) ─────────────────

def check_file_set_match(answer_files, oracle_files):
    def _key(item):
        return (_normalize_repo(item.get("repo", "")), item.get("path", ""))
    oracle_set = {_key(f) for f in oracle_files}
    answer_set = {_key(f) for f in answer_files}
    matched = oracle_set & answer_set
    missing = oracle_set - answer_set
    extra = answer_set - oracle_set
    recall = len(matched) / len(oracle_set) if oracle_set else 1.0
    precision = len(matched) / len(answer_set) if answer_set else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "matched": [{"repo": r, "path": p} for r, p in sorted(matched)],
        "missing": [{"repo": r, "path": p} for r, p in sorted(missing)],
        "extra": [{"repo": r, "path": p} for r, p in sorted(extra)],
    }


def check_symbol_resolution(answer_symbols, oracle_symbols):
    def _key(item):
        return (_normalize_repo(item.get("repo", "")), item.get("path", ""), item.get("symbol", ""))
    oracle_set = {_key(s) for s in oracle_symbols}
    answer_set = {_key(s) for s in answer_symbols}
    matched = oracle_set & answer_set
    missing = oracle_set - answer_set
    extra = answer_set - oracle_set
    recall = len(matched) / len(oracle_set) if oracle_set else 1.0
    precision = len(matched) / len(answer_set) if answer_set else 0.0
    return {
        "matched": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(matched)],
        "missing": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(missing)],
        "extra": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(extra)],
        "recall": round(recall, 4),
        "precision": round(precision, 4),
    }


def check_dependency_chain(answer_chain, oracle_chain):
    def _key(item):
        return (_normalize_repo(item.get("repo", "")), item.get("path", ""), item.get("symbol", ""))
    oracle_keys = [_key(s) for s in oracle_chain]
    answer_keys = [_key(s) for s in answer_chain]
    oracle_set = set(oracle_keys)
    answer_set = set(answer_keys)
    matched = oracle_set & answer_set
    missing = oracle_set - answer_set
    oracle_positions = {k: i for i, k in enumerate(oracle_keys)}
    matched_in_order = [k for k in answer_keys if k in oracle_set]
    positions = [oracle_positions[k] for k in matched_in_order if k in oracle_positions]
    order_correct = positions == sorted(positions) and len(matched) == len(oracle_set)
    chain_recall = len(matched) / len(oracle_set) if oracle_set else 1.0
    return {
        "matched_steps": len(matched),
        "total_oracle_steps": len(oracle_set),
        "missing_steps": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(missing)],
        "order_correct": order_correct,
        "chain_recall": round(chain_recall, 4),
    }


def check_provenance(answer_text, must_cite_paths=None, must_cite_repos=None):
    must_cite_paths = must_cite_paths or []
    must_cite_repos = must_cite_repos or []
    all_citations = must_cite_paths + must_cite_repos
    found = [c for c in all_citations if c in answer_text]
    missing = [c for c in all_citations if c not in answer_text]
    total = len(all_citations)
    score = len(found) / total if total > 0 else 1.0
    return {
        "citations_found": found,
        "citations_missing": missing,
        "provenance_score": round(score, 4),
    }


def check_keyword_presence(answer_text, required_keywords):
    answer_lower = answer_text.lower()
    found = [kw for kw in required_keywords if kw.lower() in answer_lower]
    missing = [kw for kw in required_keywords if kw.lower() not in answer_lower]
    total = len(required_keywords)
    recall = len(found) / total if total > 0 else 1.0
    return {
        "found": found,
        "missing": missing,
        "total": total,
        "keyword_recall": round(recall, 4),
    }


def _get_primary_score(check_result, check_type):
    score_keys = {
        "file_set_match": "f1",
        "symbol_resolution": "recall",
        "dependency_chain": "chain_recall",
        "provenance": "provenance_score",
        "keyword_presence": "keyword_recall",
    }
    key = score_keys.get(check_type, "")
    value = check_result.get(key, 0)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


# ── Answer extraction ──────────────────────────────────────────────────────

def extract_answer_from_trajectory(trajectory_path):
    """Extract answer.json content from trajectory.json by finding Write tool calls."""
    try:
        with open(trajectory_path) as f:
            tj = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    steps = tj.get("steps", [])
    answer_content = None

    for step in steps:
        tool_calls = step.get("tool_calls", [])
        for tc in tool_calls:
            fn = tc.get("function_name", "")
            args = tc.get("arguments", {})
            if fn == "Write" and "answer.json" in args.get("file_path", ""):
                content_str = args.get("content", "")
                try:
                    answer_content = json.loads(content_str)
                except (json.JSONDecodeError, TypeError):
                    pass

    return answer_content


def extract_answer_from_claude_code_txt(claude_code_path):
    """Fallback: extract answer.json from claude-code.txt JSONL transcript."""
    if not claude_code_path.exists():
        return None

    answer_content = None
    try:
        with open(claude_code_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "answer.json" not in str(entry):
                    continue

                # Look in content blocks for tool_use with Write
                if isinstance(entry, dict):
                    content_blocks = entry.get("content", [])
                    if isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                inp = block.get("input", {})
                                if isinstance(inp, dict) and "answer.json" in inp.get("file_path", ""):
                                    try:
                                        answer_content = json.loads(inp.get("content", ""))
                                    except (json.JSONDecodeError, TypeError):
                                        pass
    except OSError:
        pass

    return answer_content


def find_task_dir(suite_run_dir, config, task_id):
    """Find the task directory for a given task under a config."""
    config_dir = suite_run_dir / config
    if not config_dir.exists():
        return None

    for batch_dir in sorted(config_dir.iterdir()):
        if not batch_dir.is_dir() or not batch_dir.name.startswith("2026-"):
            continue
        for task_dir in batch_dir.iterdir():
            if task_dir.is_dir() and task_dir.name.startswith(task_id + "__"):
                return task_dir
    return None


def get_answer(task_dir):
    """Get answer.json content for a task, trying trajectory then claude-code.txt."""
    trajectory = task_dir / "agent" / "trajectory.json"
    if trajectory.exists():
        answer = extract_answer_from_trajectory(trajectory)
        if answer is not None:
            return answer

    claude_code = task_dir / "agent" / "claude-code.txt"
    if claude_code.exists():
        answer = extract_answer_from_claude_code_txt(claude_code)
        if answer is not None:
            return answer

    return None


# ── Oracle analysis ────────────────────────────────────────────────────────

def run_oracle_checks(answer, spec):
    """Run all oracle checks defined in the task spec against the answer."""
    oracle = spec.get("artifacts", {}).get("oracle", {})
    eval_checks = spec.get("evaluation", {}).get("checks", [])

    # Extract answer text
    answer_text = ""
    if isinstance(answer, dict):
        answer_text = answer.get("text", answer.get("answer", json.dumps(answer)))
    elif isinstance(answer, str):
        answer_text = answer

    # Extract structured lists
    answer_files = answer.get("files", []) if isinstance(answer, dict) else []
    answer_symbols = answer.get("symbols", []) if isinstance(answer, dict) else []
    answer_chain = answer.get("chain", answer.get("dependency_chain", [])) if isinstance(answer, dict) else []

    results = {}
    scores = []

    for check in eval_checks:
        check_type = check.get("type", "")
        params = check.get("params", {})

        if check_type == "file_set_match":
            oracle_files = oracle.get("required_files", [])
            result = check_file_set_match(answer_files, oracle_files)

        elif check_type == "symbol_resolution":
            oracle_symbols = oracle.get("required_symbols", [])
            result = check_symbol_resolution(answer_symbols, oracle_symbols)

        elif check_type == "dependency_chain":
            oracle_chains = oracle.get("dependency_chains", [])
            if oracle_chains:
                chain_results = []
                for oc in oracle_chains:
                    steps = oc.get("steps", [])
                    cr = check_dependency_chain(answer_chain, steps)
                    chain_results.append(cr)
                avg_recall = sum(cr["chain_recall"] for cr in chain_results) / len(chain_results)
                result = {
                    "chains": chain_results,
                    "chain_recall": round(avg_recall, 4),
                    "order_correct": all(cr["order_correct"] for cr in chain_results),
                    "matched_steps": sum(cr["matched_steps"] for cr in chain_results),
                    "missing_steps": [s for cr in chain_results for s in cr["missing_steps"]],
                }
            else:
                result = {"chain_recall": 1.0, "chains": [], "order_correct": True}

        elif check_type == "provenance":
            result = check_provenance(
                answer_text,
                must_cite_paths=params.get("must_cite_paths", []),
                must_cite_repos=params.get("must_cite_repos", []),
            )

        elif check_type == "keyword_presence":
            result = check_keyword_presence(
                answer_text,
                required_keywords=params.get("required_keywords", []),
            )

        else:
            result = {"error": f"Unknown check type: {check_type}"}

        results[check_type] = result
        scores.append(_get_primary_score(result, check_type))

    composite = sum(scores) / len(scores) if scores else 0.0

    return {
        "checks": results,
        "composite_score": round(composite, 4),
        "num_checks": len(scores),
        "individual_scores": {check["type"]: round(s, 4) for check, s in zip(eval_checks, scores)},
    }


# ── Main analysis ──────────────────────────────────────────────────────────

def main():
    print("=" * 90)
    print("ORACLE-BASED RETRIEVAL QUALITY ANALYSIS -- MCP-Unique Haiku Runs")
    print("=" * 90)
    print()

    # Collect all results
    all_results = {}  # task_id -> {suite, spec, configs: {config -> {answer, oracle_result, reward}}}

    for task_id, suite in sorted(TASK_SUITE.items()):
        suite_run_dir = STAGING_DIR / f"{suite}_haiku_{RUN_TIMESTAMP}"

        # Load task spec
        spec_path = BENCHMARKS_DIR / suite / task_id / "tests" / "task_spec.json"
        if not spec_path.exists():
            print(f"WARNING: task_spec.json not found for {task_id}")
            continue
        with open(spec_path) as f:
            spec = json.load(f)

        task_results = {}

        for config in CONFIGS:
            task_dir = find_task_dir(suite_run_dir, config, task_id)
            if task_dir is None:
                print(f"WARNING: No task dir for {task_id} / {config}")
                continue

            # Get reward from verifier
            reward_path = task_dir / "verifier" / "reward.txt"
            reward = None
            if reward_path.exists():
                try:
                    reward = float(reward_path.read_text().strip())
                except ValueError:
                    pass

            # Get answer
            answer = get_answer(task_dir)

            # Run oracle checks
            oracle_result = None
            if answer is not None:
                oracle_result = run_oracle_checks(answer, spec)

            task_results[config] = {
                "answer": answer,
                "oracle_result": oracle_result,
                "reward": reward,
                "task_dir": str(task_dir),
            }

        all_results[task_id] = {
            "suite": suite,
            "spec": spec,
            "configs": task_results,
        }

    # ── Print per-task detailed results ────────────────────────────────────

    bl_scores = []
    mcp_scores = []
    bl_rewards = []
    mcp_rewards = []

    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        spec = info["spec"]
        suite = info["suite"]
        oracle = spec.get("artifacts", {}).get("oracle", {})
        checks = spec.get("evaluation", {}).get("checks", [])

        print("-" * 90)
        print(f"TASK: {task_id}  (suite: {suite})")
        print(f"  Oracle checks: {[c['type'] for c in checks]}")

        # Print oracle requirements
        req_files = oracle.get("required_files", [])
        req_symbols = oracle.get("required_symbols", [])
        dep_chains = oracle.get("dependency_chains", [])

        if req_files:
            print(f"  Oracle required_files ({len(req_files)}):")
            for f in req_files:
                print(f"    - {f['repo']} :: {f['path']}")

        if req_symbols:
            print(f"  Oracle required_symbols ({len(req_symbols)}):")
            for s in req_symbols:
                print(f"    - {s['repo']} :: {s['path']} :: {s['symbol']}")

        if dep_chains:
            for ci, chain in enumerate(dep_chains):
                steps = chain.get("steps", [])
                chain_name = chain.get("name", f"chain-{ci}")
                print(f"  Oracle dependency_chain '{chain_name}' ({len(steps)} steps):")
                for step in steps:
                    print(f"    - {step.get('repo','')} :: {step.get('path','')} :: {step.get('symbol','')}")

        # Print check-specific oracle params
        for check in checks:
            params = check.get("params", {})
            if check["type"] == "keyword_presence" and "required_keywords" in params:
                kws = params["required_keywords"]
                print(f"  Oracle required_keywords ({len(kws)}): {kws}")
            if check["type"] == "provenance":
                cite_paths = params.get("must_cite_paths", [])
                cite_repos = params.get("must_cite_repos", [])
                if cite_paths:
                    print(f"  Oracle must_cite_paths ({len(cite_paths)}): {cite_paths}")
                if cite_repos:
                    print(f"  Oracle must_cite_repos ({len(cite_repos)}): {cite_repos}")

        print()

        for config in CONFIGS:
            config_label = "BASELINE" if "baseline" in config else "MCP"
            cdata = info["configs"].get(config)
            if cdata is None:
                print(f"  [{config_label}] NO DATA")
                continue

            reward = cdata["reward"]
            answer = cdata["answer"]
            oracle_result = cdata["oracle_result"]

            if config_label == "BASELINE":
                if reward is not None:
                    bl_rewards.append(reward)
            else:
                if reward is not None:
                    mcp_rewards.append(reward)

            print(f"  [{config_label}] Verifier reward: {reward}")

            if answer is None:
                print(f"  [{config_label}] Could not extract answer.json from trajectory")
                if config_label == "BASELINE":
                    bl_scores.append(0.0)
                else:
                    mcp_scores.append(0.0)
                print()
                continue

            if oracle_result is None:
                print(f"  [{config_label}] Oracle check failed to run")
                if config_label == "BASELINE":
                    bl_scores.append(0.0)
                else:
                    mcp_scores.append(0.0)
                print()
                continue

            composite = oracle_result["composite_score"]
            if config_label == "BASELINE":
                bl_scores.append(composite)
            else:
                mcp_scores.append(composite)

            print(f"  [{config_label}] Recomputed composite: {composite}")
            print(f"  [{config_label}] Per-check scores: {oracle_result['individual_scores']}")

            # Detailed per-check results
            for check_type, check_result in oracle_result["checks"].items():
                if check_type == "file_set_match":
                    print(f"    file_set_match: recall={check_result['recall']} precision={check_result['precision']} f1={check_result['f1']}")
                    if check_result.get("matched"):
                        print(f"      FOUND ({len(check_result['matched'])}):")
                        for m in check_result["matched"]:
                            print(f"        + {m['repo']} :: {m['path']}")
                    if check_result.get("missing"):
                        print(f"      MISSED ({len(check_result['missing'])}):")
                        for m in check_result["missing"]:
                            print(f"        - {m['repo']} :: {m['path']}")
                    if check_result.get("extra"):
                        print(f"      EXTRA ({len(check_result['extra'])}):")
                        for m in check_result["extra"]:
                            print(f"        ~ {m['repo']} :: {m['path']}")

                elif check_type == "symbol_resolution":
                    print(f"    symbol_resolution: recall={check_result['recall']} precision={check_result['precision']}")
                    if check_result.get("matched"):
                        print(f"      FOUND ({len(check_result['matched'])}):")
                        for m in check_result["matched"]:
                            print(f"        + {m['repo']} :: {m['path']} :: {m['symbol']}")
                    if check_result.get("missing"):
                        print(f"      MISSED ({len(check_result['missing'])}):")
                        for m in check_result["missing"]:
                            print(f"        - {m['repo']} :: {m['path']} :: {m['symbol']}")
                    if check_result.get("extra"):
                        print(f"      EXTRA ({len(check_result['extra'])}):")
                        for m in check_result["extra"]:
                            print(f"        ~ {m['repo']} :: {m['path']} :: {m['symbol']}")

                elif check_type == "dependency_chain":
                    print(f"    dependency_chain: recall={check_result.get('chain_recall', 'N/A')} order_correct={check_result.get('order_correct', 'N/A')}")
                    print(f"      matched_steps={check_result.get('matched_steps', 0)}")
                    if check_result.get("missing_steps"):
                        print(f"      MISSING STEPS:")
                        for m in check_result["missing_steps"]:
                            print(f"        - {m['repo']} :: {m['path']} :: {m['symbol']}")
                    if "chains" in check_result:
                        for ci, cr in enumerate(check_result["chains"]):
                            print(f"      Chain {ci}: recall={cr.get('chain_recall','?')} matched={cr.get('matched_steps',0)}/{cr.get('total_oracle_steps','?')}")

                elif check_type == "provenance":
                    print(f"    provenance: score={check_result['provenance_score']}")
                    if check_result.get("citations_found"):
                        print(f"      CITED: {check_result['citations_found']}")
                    if check_result.get("citations_missing"):
                        print(f"      MISSING: {check_result['citations_missing']}")

                elif check_type == "keyword_presence":
                    print(f"    keyword_presence: recall={check_result['keyword_recall']}")
                    if check_result.get("found"):
                        print(f"      FOUND: {check_result['found']}")
                    if check_result.get("missing"):
                        print(f"      MISSING: {check_result['missing']}")

            # Show answer summary
            if isinstance(answer, dict):
                n_files = len(answer.get("files", []))
                n_symbols = len(answer.get("symbols", []))
                n_chain = len(answer.get("chain", answer.get("dependency_chain", [])))
                text_len = len(answer.get("text", answer.get("answer", "")))
                print(f"    Answer shape: files={n_files}, symbols={n_symbols}, chain={n_chain}, text_len={text_len}")

            print()

    # ── Summary table ──────────────────────────────────────────────────────

    print()
    print("=" * 90)
    print("SUMMARY TABLE")
    print("=" * 90)
    print()
    print(f"{'Task ID':<25} {'Check Types':<35} {'BL reward':>10} {'MCP reward':>10} {'BL oracle':>10} {'MCP oracle':>10} {'Delta':>8}")
    print("-" * 110)

    task_deltas = []
    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        checks = [c["type"] for c in info["spec"].get("evaluation", {}).get("checks", [])]
        checks_str = ", ".join(checks)

        bl_data = info["configs"].get("baseline-local-artifact", {})
        mcp_data = info["configs"].get("mcp-remote-artifact", {})

        bl_reward = bl_data.get("reward")
        mcp_reward = mcp_data.get("reward")

        bl_composite = bl_data.get("oracle_result", {}).get("composite_score") if bl_data.get("oracle_result") else None
        mcp_composite = mcp_data.get("oracle_result", {}).get("composite_score") if mcp_data.get("oracle_result") else None

        bl_r_str = f"{bl_reward:.4f}" if bl_reward is not None else "N/A"
        mcp_r_str = f"{mcp_reward:.4f}" if mcp_reward is not None else "N/A"
        bl_o_str = f"{bl_composite:.4f}" if bl_composite is not None else "N/A"
        mcp_o_str = f"{mcp_composite:.4f}" if mcp_composite is not None else "N/A"

        delta = None
        delta_str = "N/A"
        if bl_composite is not None and mcp_composite is not None:
            delta = mcp_composite - bl_composite
            delta_str = f"{delta:+.4f}"
            task_deltas.append(delta)

        print(f"{task_id:<25} {checks_str:<35} {bl_r_str:>10} {mcp_r_str:>10} {bl_o_str:>10} {mcp_o_str:>10} {delta_str:>8}")

    print("-" * 110)

    # Aggregate stats
    if bl_rewards and mcp_rewards:
        avg_bl_reward = sum(bl_rewards) / len(bl_rewards)
        avg_mcp_reward = sum(mcp_rewards) / len(mcp_rewards)
        print(f"{'MEAN (verifier reward)':<25} {'':<35} {avg_bl_reward:>10.4f} {avg_mcp_reward:>10.4f}")

    if bl_scores and mcp_scores:
        avg_bl_score = sum(bl_scores) / len(bl_scores)
        avg_mcp_score = sum(mcp_scores) / len(mcp_scores)
        avg_delta = avg_mcp_score - avg_bl_score
        print(f"{'MEAN (oracle composite)':<25} {'':<35} {'':>10} {'':>10} {avg_bl_score:>10.4f} {avg_mcp_score:>10.4f} {avg_delta:>+8.4f}")

    # ── Check-type breakdown ───────────────────────────────────────────────

    print()
    print("=" * 90)
    print("PER-CHECK-TYPE BREAKDOWN")
    print("=" * 90)

    check_type_scores = {}  # check_type -> {"baseline": [scores], "mcp": [scores]}

    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        for config in CONFIGS:
            config_label = "baseline" if "baseline" in config else "mcp"
            cdata = info["configs"].get(config, {})
            oracle_result = cdata.get("oracle_result")
            if oracle_result is None:
                continue
            for check_type, score in oracle_result["individual_scores"].items():
                if check_type not in check_type_scores:
                    check_type_scores[check_type] = {"baseline": [], "mcp": []}
                check_type_scores[check_type][config_label].append(score)

    print()
    print(f"{'Check Type':<25} {'BL mean':>10} {'MCP mean':>10} {'BL n':>6} {'MCP n':>6} {'Delta':>8}")
    print("-" * 70)

    for ct in sorted(check_type_scores.keys()):
        bl_vals = check_type_scores[ct]["baseline"]
        mcp_vals = check_type_scores[ct]["mcp"]
        bl_mean = sum(bl_vals) / len(bl_vals) if bl_vals else 0
        mcp_mean = sum(mcp_vals) / len(mcp_vals) if mcp_vals else 0
        delta = mcp_mean - bl_mean
        print(f"{ct:<25} {bl_mean:>10.4f} {mcp_mean:>10.4f} {len(bl_vals):>6} {len(mcp_vals):>6} {delta:>+8.4f}")

    # ── Win/Loss/Tie analysis ──────────────────────────────────────────────

    print()
    print("=" * 90)
    print("WIN / LOSS / TIE ANALYSIS (per task, based on recomputed oracle composite)")
    print("=" * 90)

    wins = []
    losses = []
    ties = []

    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        bl_data = info["configs"].get("baseline-local-artifact", {})
        mcp_data = info["configs"].get("mcp-remote-artifact", {})
        bl_c = bl_data.get("oracle_result", {}).get("composite_score") if bl_data.get("oracle_result") else None
        mcp_c = mcp_data.get("oracle_result", {}).get("composite_score") if mcp_data.get("oracle_result") else None

        if bl_c is None or mcp_c is None:
            continue

        if mcp_c > bl_c + 0.001:
            wins.append((task_id, bl_c, mcp_c))
        elif bl_c > mcp_c + 0.001:
            losses.append((task_id, bl_c, mcp_c))
        else:
            ties.append((task_id, bl_c, mcp_c))

    print()
    print(f"MCP WINS ({len(wins)}):")
    for t, b, m in wins:
        print(f"  {t:<25} BL={b:.4f}  MCP={m:.4f}  delta={m-b:+.4f}")

    print(f"\nMCP LOSSES ({len(losses)}):")
    for t, b, m in losses:
        print(f"  {t:<25} BL={b:.4f}  MCP={m:.4f}  delta={m-b:+.4f}")

    print(f"\nTIES ({len(ties)}):")
    for t, b, m in ties:
        print(f"  {t:<25} BL={b:.4f}  MCP={m:.4f}")

    # ── Verifier vs Oracle agreement ───────────────────────────────────────

    print()
    print("=" * 90)
    print("VERIFIER REWARD vs RECOMPUTED ORACLE SCORE AGREEMENT")
    print("=" * 90)
    print()
    print(f"{'Task ID':<25} {'Config':<12} {'Verifier':>10} {'Oracle':>10} {'Match':>8}")
    print("-" * 70)

    mismatches = 0
    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        for config in CONFIGS:
            config_label = "BL" if "baseline" in config else "MCP"
            cdata = info["configs"].get(config, {})
            reward = cdata.get("reward")
            oracle_result = cdata.get("oracle_result")
            if reward is None or oracle_result is None:
                continue
            oracle_score = oracle_result["composite_score"]
            match = abs(reward - oracle_score) < 0.01
            match_str = "OK" if match else "MISMATCH"
            if not match:
                mismatches += 1
            print(f"{task_id:<25} {config_label:<12} {reward:>10.4f} {oracle_score:>10.4f} {match_str:>8}")

    print(f"\nTotal mismatches: {mismatches}")
    if mismatches > 0:
        print("NOTE: Mismatches may indicate the trajectory-extracted answer.json differs from")
        print("      what the agent actually wrote (e.g., subsequent edits not captured, or")
        print("      answer was written via Bash 'cat <<EOF' instead of Write tool).")

    # ── DS task analysis ───────────────────────────────────────────────────

    print()
    print("=" * 90)
    print("DEEP SEARCH (-ds) TASK FOCUS")
    print("=" * 90)
    print()

    ds_tasks = [t for t in sorted(all_results.keys()) if "-ds" in t]
    non_ds_tasks = [t for t in sorted(all_results.keys()) if "-ds" not in t]

    for label, task_list in [("DS tasks", ds_tasks), ("Non-DS tasks", non_ds_tasks)]:
        bl_vals = []
        mcp_vals = []
        for t in task_list:
            info = all_results[t]
            bl_c = info["configs"].get("baseline-local-artifact", {}).get("oracle_result", {}).get("composite_score") if info["configs"].get("baseline-local-artifact", {}).get("oracle_result") else None
            mcp_c = info["configs"].get("mcp-remote-artifact", {}).get("oracle_result", {}).get("composite_score") if info["configs"].get("mcp-remote-artifact", {}).get("oracle_result") else None
            if bl_c is not None:
                bl_vals.append(bl_c)
            if mcp_c is not None:
                mcp_vals.append(mcp_c)

        bl_mean = sum(bl_vals) / len(bl_vals) if bl_vals else 0
        mcp_mean = sum(mcp_vals) / len(mcp_vals) if mcp_vals else 0
        delta = mcp_mean - bl_mean
        print(f"{label} ({len(task_list)} tasks): BL mean={bl_mean:.4f}, MCP mean={mcp_mean:.4f}, delta={delta:+.4f}")

    # ── Suite-level summary ────────────────────────────────────────────────

    print()
    print("=" * 90)
    print("SUITE-LEVEL SUMMARY")
    print("=" * 90)
    print()

    suite_scores = {}  # suite -> {"baseline": [scores], "mcp": [scores]}
    for task_id in sorted(all_results.keys()):
        info = all_results[task_id]
        suite = info["suite"]
        if suite not in suite_scores:
            suite_scores[suite] = {"baseline": [], "mcp": []}
        for config in CONFIGS:
            config_label = "baseline" if "baseline" in config else "mcp"
            cdata = info["configs"].get(config, {})
            if cdata.get("oracle_result"):
                suite_scores[suite][config_label].append(cdata["oracle_result"]["composite_score"])

    print(f"{'Suite':<35} {'BL mean':>10} {'MCP mean':>10} {'N tasks':>8} {'Delta':>8}")
    print("-" * 75)

    for suite in sorted(suite_scores.keys()):
        bl_vals = suite_scores[suite]["baseline"]
        mcp_vals = suite_scores[suite]["mcp"]
        bl_mean = sum(bl_vals) / len(bl_vals) if bl_vals else 0
        mcp_mean = sum(mcp_vals) / len(mcp_vals) if mcp_vals else 0
        delta = mcp_mean - bl_mean
        n = max(len(bl_vals), len(mcp_vals))
        print(f"{suite:<35} {bl_mean:>10.4f} {mcp_mean:>10.4f} {n:>8} {delta:>+8.4f}")

    print()


if __name__ == "__main__":
    main()

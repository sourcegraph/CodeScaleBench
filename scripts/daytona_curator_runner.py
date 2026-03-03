#!/usr/bin/env python3
"""Run ContextBench calibration at high throughput via Daytona sandboxes.

Each sandbox gets its own Claude CLI + MCP server, eliminating the local
MCP connection bottleneck that caps --parallel at 5 in local mode.

Architecture:
  - Loads ContextBench tasks (from validate_on_contextbench.py sampling)
  - Clones repos locally (shared cache)
  - For each task: creates a Daytona sandbox → installs Claude CLI →
    uploads context_retrieval_agent.py + repo → runs curator → collects results
  - Runs up to 30 sandboxes concurrently (conservative — Daytona Tier 3
    allows 125 but curator tasks are long-running and memory-hungry)

Usage:
    # Quick pilot (5 tasks)
    python3 scripts/daytona_curator_runner.py --sample 5 --verbose

    # Full calibration (50 tasks)
    python3 scripts/daytona_curator_runner.py --sample 50 --parallel 20

    # Verified subset with CCB-weighted sampling
    python3 scripts/daytona_curator_runner.py --phase verify --parallel 20

    # Dry run
    python3 scripts/daytona_curator_runner.py --sample 10 --dry-run

Environment:
    source .env.local  (sets DAYTONA_API_KEY, SRC_ACCESS_TOKEN, OAuth creds)
"""

import argparse
import base64
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("daytona_curator")

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
RESULTS_DIR = REPO_ROOT / "results" / "contextbench"

# Files to upload to each sandbox for the curator agent
CURATOR_FILES = [
    SCRIPTS_DIR / "context_retrieval_agent.py",
    SCRIPTS_DIR / "ds_wrapper.sh",
]

# Sandbox resource allocation (curator is IO-heavy, not compute-heavy)
SANDBOX_CPUS = 2
SANDBOX_MEMORY_GB = 4
SANDBOX_DISK_GB = 10  # Daytona Tier 3 max is 10GB per sandbox
SANDBOX_TIMEOUT_SEC = 900  # 15 min per task

# Max concurrent sandboxes (Tier 3 = 125, but be conservative for long tasks)
DEFAULT_PARALLEL = 20


def load_credentials() -> Dict[str, Any]:
    """Load all required credentials from environment/.claude."""
    creds: Dict[str, Any] = {}

    # Daytona API key
    creds["daytona_api_key"] = os.environ.get("DAYTONA_API_KEY", "")
    if not creds["daytona_api_key"]:
        config_path = Path.home() / ".config" / "daytona" / "env.sh"
        if config_path.exists():
            for line in config_path.read_text().splitlines():
                if "DAYTONA_API_KEY" in line and "=" in line:
                    creds["daytona_api_key"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    # Sourcegraph token
    creds["src_token"] = os.environ.get(
        "SRC_ACCESS_TOKEN",
        os.environ.get("SOURCEGRAPH_ACCESS_TOKEN", ""),
    )

    # OAuth credentials (for Claude CLI in sandbox)
    creds["oauth_creds"] = None
    account_num = int(os.environ.get("CCB_ACCOUNT", "1"))
    creds_path = Path.home() / ".claude-homes" / f"account{account_num}" / ".claude" / ".credentials.json"
    if not creds_path.exists():
        creds_path = creds_path.parent / "credentials.json"
    if creds_path.exists():
        try:
            creds_data = json.loads(creds_path.read_text())
            oauth = creds_data.get("claudeAiOauth", {})
            if oauth.get("accessToken"):
                creds["oauth_creds"] = {
                    "access_token": oauth["accessToken"],
                    "creds_json": creds_path.read_text(),
                }
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load OAuth creds from %s: %s", creds_path, e)

    return creds


def exec_cmd(sandbox, cmd: str, description: str = "", timeout: int = 120) -> str:
    """Execute a command in a Daytona sandbox."""
    label = f"[{sandbox.id[:8]}]"
    if description:
        log.debug("  %s %s", label, description)
    try:
        response = sandbox.process.exec(cmd, timeout=timeout)
        if hasattr(response, "exit_code") and response.exit_code != 0:
            stderr = getattr(response, "stderr", "") or ""
            stdout = getattr(response, "result", "") or getattr(response, "stdout", "") or ""
            log.debug("  %s exit code %d", label, response.exit_code)
            if stderr:
                log.debug("  %s stderr: %s", label, stderr[:500])
            return stdout
        return getattr(response, "result", "") or getattr(response, "stdout", "") or ""
    except Exception as e:
        log.warning("  %s exec error: %s", label, e)
        return ""


def setup_curator_sandbox(
    daytona_client,
    creds: Dict[str, Any],
    repo_url: str,
    commit: str,
    model: str = "claude-opus-4-6",
    backend: str = "hybrid",
) -> Any:
    """Create and set up a Daytona sandbox for curator work.

    Returns the sandbox object, ready to run the curator agent.
    """
    from daytona_sdk import CreateSandboxFromImageParams, Resources

    # Build image with all dependencies baked in
    from daytona_sdk import Image
    image = (
        Image.debian_slim("3.11")
        .run_commands(
            "apt-get update -qq && apt-get install -y -qq git ripgrep curl jq >/dev/null 2>&1",
            # Create non-root user (Claude CLI >=2.1.37 rejects root)
            "useradd -m -s /bin/bash claude",
            # Node.js 22 for Claude CLI
            "curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.gz "
            "| tar -xz -C /usr/local --strip-components=1",
            # Claude Code CLI
            "npm install -g @anthropic-ai/claude-code@latest 2>&1 | tail -3",
            # Pre-create directories for claude user
            "mkdir -p /home/claude/.claude /home/claude/.config/claude /workspace",
            "chown -R claude:claude /home/claude /workspace",
        )
        .add_local_file(str(SCRIPTS_DIR / "context_retrieval_agent.py"), "/tmp/context_retrieval_agent.py")
        .add_local_file(str(SCRIPTS_DIR / "ds_wrapper.sh"), "/tmp/ds_wrapper.sh")
    )

    params = CreateSandboxFromImageParams(
        image=image,
        language="python",
        env_vars={"DEBIAN_FRONTEND": "noninteractive"},
        labels={"purpose": "curator", "repo": repo_url[:50]},
        resources=Resources(
            cpu=SANDBOX_CPUS,
            memory=SANDBOX_MEMORY_GB,
            disk=SANDBOX_DISK_GB,
        ),
        auto_stop_interval=0,
    )

    sandbox = daytona_client.create(params, timeout=600)
    log.info("[%s] Sandbox created (image built)", sandbox.id[:8])

    # Write OAuth credentials
    if creds.get("oauth_creds"):
        creds_content = creds["oauth_creds"]["creds_json"]
        exec_cmd(sandbox,
            f"mkdir -p /home/claude/.claude "
            f"&& cat > /home/claude/.claude/.credentials.json << 'CREDEOF'\n{creds_content}\nCREDEOF",
            "Writing OAuth credentials")
        exec_cmd(sandbox, "rm -f /home/claude/.claude/credentials.json")

    # Write MCP config for Sourcegraph (HTTP mode — no local process needed)
    src_token = creds.get("src_token", "")
    sg_url = os.environ.get("SOURCEGRAPH_URL", "https://sourcegraph.sourcegraph.com").rstrip("/")
    if src_token and backend in ("deepsearch", "hybrid"):
        mcp_config = {
            "mcpServers": {
                "sourcegraph": {
                    "type": "http",
                    "url": f"{sg_url}/.api/mcp/v1",
                    "headers": {"Authorization": f"token {src_token}"},
                }
            }
        }
        mcp_json = json.dumps(mcp_config)
        exec_cmd(sandbox,
            f"mkdir -p /home/claude/.config/claude /home/claude/.claude "
            f"&& echo '{mcp_json}' > /home/claude/.config/claude/mcp.json "
            f"&& echo '{mcp_json}' > /tmp/.mcp.json "
            f"&& chown -R claude:claude /home/claude/.config",
            "Writing MCP config")

    exec_cmd(sandbox, "chmod +x /tmp/ds_wrapper.sh 2>/dev/null || true")

    # Clone the target repo
    log.info("[%s] Cloning %s @ %s", sandbox.id[:8], repo_url, commit[:8])
    exec_cmd(sandbox,
        f"git clone --no-checkout {repo_url} /workspace/repo 2>&1 | tail -3",
        "Cloning repo", timeout=300)
    exec_cmd(sandbox,
        f"cd /workspace/repo && git checkout {commit} 2>&1 | tail -3",
        "Checking out commit", timeout=60)

    # Set ownership
    exec_cmd(sandbox,
        "chown -R claude:claude /workspace /home/claude /tmp/context_retrieval_agent.py "
        "/tmp/ds_wrapper.sh 2>/dev/null || true",
        "Setting ownership")

    return sandbox


def _build_python_runner() -> str:
    """Build a Python wrapper script that calls Claude CLI via subprocess.

    Using Python (subprocess.run with list args) avoids all shell quoting
    issues with the system prompt, which contains $, backticks, braces, etc.
    """
    return '''#!/usr/bin/env python3
"""Run claude CLI for curator agent (avoids shell quoting issues)."""
import json, os, subprocess, sys

# Read inputs
sys_prompt = open("/tmp/system_prompt.txt").read()
user_msg = open("/tmp/user_msg.txt").read()
config = json.load(open("/tmp/curator_config.json"))

# Environment: unset CLAUDECODE to prevent nesting detection
env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
env["PATH"] = "/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
env["HOME"] = "/home/claude"
for key in ("CLAUDE_CODE_OAUTH_TOKEN", "SRC_ACCESS_TOKEN", "SOURCEGRAPH_ACCESS_TOKEN"):
    val = config.get(key, "")
    if val:
        env[key] = val

# Build CLI command (list args — no shell expansion)
cmd = [
    "claude",
    "-p", user_msg,
    "--output-format", "json",
    "--model", config["model"],
    "--append-system-prompt", sys_prompt,
    "--allowedTools", config["allowed_tools"],
    "--dangerously-skip-permissions",
]
if config.get("mcp_config"):
    cmd.extend(["--mcp-config", config["mcp_config"]])

os.chdir(config.get("workdir", "/workspace/repo"))

result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=840)

# Output: print stdout (JSON from claude), stderr to stderr for debugging
if result.stderr:
    print(result.stderr, file=sys.stderr)
if result.stdout:
    print(result.stdout)
sys.exit(result.returncode)
'''


def run_curator_in_sandbox(
    sandbox,
    problem_statement: str,
    repo_name: str,
    creds: Dict[str, Any],
    model: str = "claude-opus-4-6",
    backend: str = "hybrid",
    verbose: bool = False,
    suite_name: str = "",
) -> Dict[str, Any]:
    """Run the curator agent inside a Daytona sandbox.

    Uses claude CLI mode (subscription billing) with a Python wrapper script
    that calls subprocess.run() to avoid shell quoting issues with the
    system prompt (which contains $, backticks, braces, etc.).

    Returns the oracle result dict.
    """
    src_token = creds.get("src_token", "")
    access_token = ""
    if creds.get("oauth_creds"):
        access_token = creds["oauth_creds"]["access_token"]

    # Build curator prompt from the template
    from context_retrieval_agent import (
        CURATOR_SYSTEM_PROMPT,
        _tool_description_for_backend,
        get_task_type_guidance,
    )
    system_prompt = CURATOR_SYSTEM_PROMPT.format(
        tool_description=_tool_description_for_backend(backend, cli_mode=True),
        task_type_guidance=get_task_type_guidance(suite_name),
    )

    user_msg = (
        f"## Task\n{problem_statement[:4000]}\n\n"
        f"## Repositories\n"
        f"- **{repo_name}**: `/workspace/repo`\n\n"
        f"**Use these repo names in Deep Search queries**: {repo_name}\n\n"
        f"**IMPORTANT**: Search the local repository thoroughly using Bash, Read, Glob, Grep tools."
    )

    # Write system prompt and user message via base64 to avoid heredoc issues
    sys_b64 = base64.b64encode(system_prompt.encode()).decode()
    msg_b64 = base64.b64encode(user_msg.encode()).decode()

    exec_cmd(sandbox,
        f"echo '{sys_b64}' | base64 -d > /tmp/system_prompt.txt",
        "Writing system prompt")
    exec_cmd(sandbox,
        f"echo '{msg_b64}' | base64 -d > /tmp/user_msg.txt",
        "Writing user message")

    # Build allowed tools based on backend
    # V6: Deep Search banned. All backends use read-only Bash + keyword search.
    if backend == "local":
        allowed = "Bash(read-only:true),Read,Glob,Grep"
    elif backend == "deepsearch":
        allowed = "Bash(read-only:true),Read,Glob,Grep,mcp__sourcegraph__sg_keyword_search"
    else:  # hybrid
        allowed = "Bash(read-only:true),Read,Glob,Grep,mcp__sourcegraph__sg_keyword_search"

    # Write config for the Python runner
    config = {
        "model": model,
        "allowed_tools": allowed,
        "workdir": "/workspace/repo",
    }
    if access_token:
        config["CLAUDE_CODE_OAUTH_TOKEN"] = access_token
    if src_token:
        config["SRC_ACCESS_TOKEN"] = src_token
        config["SOURCEGRAPH_ACCESS_TOKEN"] = src_token
    if backend in ("deepsearch", "hybrid") and src_token:
        config["mcp_config"] = "/tmp/.mcp.json"

    config_json = json.dumps(config)
    cfg_delim = f"CFG_{hash(repo_name) & 0xFFFFFF:06x}"
    exec_cmd(sandbox,
        f"cat > /tmp/curator_config.json << '{cfg_delim}'\n{config_json}\n{cfg_delim}",
        "Writing curator config")

    # Write the Python runner script
    runner_code = _build_python_runner()
    runner_b64 = base64.b64encode(runner_code.encode()).decode()
    exec_cmd(sandbox,
        f"echo '{runner_b64}' | base64 -d > /tmp/run_curator.py && chmod +x /tmp/run_curator.py",
        "Writing Python runner")

    # Set ownership
    exec_cmd(sandbox,
        "chown -R claude:claude /tmp/system_prompt.txt /tmp/user_msg.txt "
        "/tmp/curator_config.json /tmp/run_curator.py 2>/dev/null || true")

    # Execute via Python (avoids all shell quoting issues)
    start = time.time()
    raw_output = exec_cmd(sandbox,
        "su - claude -c 'python3 /tmp/run_curator.py 2>/tmp/curator_stderr.txt'",
        "Running curator agent", timeout=SANDBOX_TIMEOUT_SEC)
    elapsed = time.time() - start

    # Collect stderr for debugging
    stderr = exec_cmd(sandbox, "cat /tmp/curator_stderr.txt 2>/dev/null || true")
    if stderr and verbose:
        log.debug("[%s] stderr: %s", sandbox.id[:8], stderr[:500])
    if not raw_output and stderr:
        log.warning("[%s] No stdout, stderr: %s", sandbox.id[:8], stderr[:300])

    # Parse output
    result = {"files": [], "text": ""}
    metadata = {
        "elapsed_sec": round(elapsed, 1),
        "cost_usd": 0.0,
        "error": False,
    }

    try:
        parsed = json.loads(raw_output)
        result_text = parsed.get("result", "")
        metadata["cost_usd"] = parsed.get("total_cost_usd", 0.0)
        metadata["num_turns"] = parsed.get("num_turns", 0)

        # Extract oracle JSON from result text
        from context_retrieval_agent import _extract_json_from_text
        oracle = _extract_json_from_text(result_text)
        if oracle:
            result = oracle
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("[%s] Failed to parse output: %s", sandbox.id[:8], e)
        if raw_output:
            log.debug("[%s] Raw output (first 500): %s", sandbox.id[:8], raw_output[:500])
        metadata["error"] = True

    return {"oracle": result, "metadata": metadata}


def process_task(
    task: Dict[str, Any],
    idx: int,
    total: int,
    daytona_client,
    creds: Dict[str, Any],
    model: str,
    backend: str,
    verbose: bool,
    prune: bool = False,
    suite_name: str = "",
) -> Optional[Dict[str, Any]]:
    """Process a single ContextBench task in a Daytona sandbox."""
    instance_id = task.get("instance_id", f"task_{idx}")

    # Resolve repo URL
    repo_url = task.get("repo_url", "")
    if not repo_url:
        repo_slug = task.get("repo", "")
        if repo_slug and "/" in repo_slug:
            repo_url = f"https://github.com/{repo_slug}"
    if not repo_url:
        parts = instance_id.rsplit("-", 1)
        org_repo = parts[0].replace("__", "/") if parts else ""
        repo_url = f"https://github.com/{org_repo}" if org_repo else ""
    if not repo_url:
        log.warning("[%d/%d] No repo URL for %s, skipping", idx + 1, total, instance_id)
        return None

    commit = task.get("base_commit", task.get("commit", "HEAD"))
    repo_name = repo_url.rstrip("/").split("github.com/")[-1]

    log.info("[%d/%d] %s (%s @ %s)", idx + 1, total, instance_id, repo_name, commit[:8])

    sandbox = None
    try:
        sandbox = setup_curator_sandbox(
            daytona_client, creds, repo_url, commit,
            model=model, backend=backend,
        )

        result = run_curator_in_sandbox(
            sandbox,
            problem_statement=task.get("problem_statement", ""),
            repo_name=repo_name,
            creds=creds,
            model=model,
            backend=backend,
            verbose=verbose,
            suite_name=suite_name,
        )

        # Optional haiku pruning pass (runs locally, not in sandbox)
        if prune and result["oracle"].get("files"):
            from context_retrieval_agent import prune_with_haiku
            problem = task.get("problem_statement", "")
            result["oracle"] = prune_with_haiku(
                result["oracle"], problem,
                use_cli=True, verbose=verbose,
            )
            result["metadata"]["pruned"] = True

        n_files = len(result["oracle"].get("files", []))
        cost = result["metadata"].get("cost_usd", 0)
        log.info("[%d/%d] %s -> %d files, $%.4f, %.1fs",
                 idx + 1, total, instance_id, n_files, cost,
                 result["metadata"]["elapsed_sec"])

        # Convert to trajectory format
        from validate_on_contextbench import convert_to_trajectory
        traj = convert_to_trajectory(
            instance_id, result["oracle"],
            model_patch=task.get("patch", ""),
        )

        return {"task": task, "traj": traj, "result": result}

    except Exception as e:
        log.error("[%d/%d] %s failed: %s", idx + 1, total, instance_id, e)
        return None
    finally:
        if sandbox:
            try:
                daytona_client.delete(sandbox)
                log.debug("[%s] Sandbox deleted", sandbox.id[:8])
            except Exception as e:
                log.warning("Failed to delete sandbox: %s", e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ContextBench calibration at high throughput via Daytona"
    )
    parser.add_argument("--sample", type=int, default=0, help="Number of tasks to sample")
    parser.add_argument("--verified", action="store_true", help="Use verified subset (500)")
    parser.add_argument("--phase", type=str, default="", choices=("", "test", "verify"),
                        help="Calibration phase: 'test' (10) or 'verify' (50)")
    parser.add_argument("--model", type=str, default="claude-opus-4-6")
    parser.add_argument("--backend", type=str, default="hybrid",
                        choices=("local", "deepsearch", "hybrid"))
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                        help=f"Concurrent sandboxes (default: {DEFAULT_PARALLEL})")
    parser.add_argument("--max-cost", type=float, default=0, help="Cost limit in USD")
    parser.add_argument("--max-tasks", type=int, default=0, help="Max tasks to process")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default="", help="Output directory")
    parser.add_argument("--prune", action="store_true",
                        help="Run haiku pruning pass to improve precision")
    parser.add_argument("--instance-ids", type=str, default="",
                        help="Comma-separated instance ID suffixes to filter tasks")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Add scripts dir to path for imports
    sys.path.insert(0, str(SCRIPTS_DIR))

    from validate_on_contextbench import (
        load_tasks, ccb_weighted_sample, stratified_sample,
        compute_simple_file_metrics, compute_chunk_metrics,
        build_calibration_report,
    )

    # Load credentials
    creds = load_credentials()
    if not creds["daytona_api_key"]:
        log.error("DAYTONA_API_KEY required. Set in env or ~/.config/daytona/env.sh")
        return 1
    if not creds.get("oauth_creds"):
        log.error("OAuth credentials required. Check ~/.claude-homes/account1/.claude/.credentials.json")
        return 1

    # Load tasks
    if args.instance_ids:
        # Filter to specific instance IDs (match by suffix)
        suffixes = [s.strip() for s in args.instance_ids.split(",") if s.strip()]
        all_tasks = load_tasks(sample=0, seed=args.seed)
        tasks = [t for t in all_tasks
                 if any(t.get("instance_id", "").endswith(s) for s in suffixes)]
        log.info("Filtered to %d tasks by instance ID suffixes", len(tasks))
    elif args.phase:
        phase_size = 10 if args.phase == "test" else 50
        all_tasks = load_tasks(verified=args.verified or (args.phase == "test"), sample=0, seed=args.seed)
        tasks = ccb_weighted_sample(all_tasks, phase_size, seed=args.seed)
        log.info("Phase '%s': %d tasks (CCB-weighted)", args.phase, len(tasks))
    else:
        tasks = load_tasks(verified=args.verified, sample=args.sample, seed=args.seed)

    if not tasks:
        log.error("No tasks loaded")
        return 1

    if args.max_tasks > 0:
        tasks = tasks[:args.max_tasks]

    log.info("Loaded %d tasks (model=%s, backend=%s, parallel=%d)",
             len(tasks), args.model, args.backend, args.parallel)

    if args.dry_run:
        for i, t in enumerate(tasks):
            iid = t.get("instance_id", f"task_{i}")
            repo = t.get("repo", t.get("repo_url", "?"))
            print(f"  [{i+1}] {iid} ({repo})")
        print(f"\nTotal: {len(tasks)} tasks, {args.parallel} concurrent sandboxes")
        return 0

    # Initialize Daytona client
    try:
        from daytona_sdk import Daytona, DaytonaConfig
        daytona = Daytona(DaytonaConfig(
            api_key=creds["daytona_api_key"],
            target=os.environ.get("DAYTONA_TARGET", "us"),
        ))
    except ImportError:
        log.error("daytona_sdk not installed: pip install daytona-sdk")
        return 1

    # Output directory
    out_dir = Path(args.out) if args.out else RESULTS_DIR / f"daytona_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run tasks in parallel
    total_cost = 0.0
    trajectories = []
    evaluated_tasks = []

    task_args = [
        (task, i, len(tasks), daytona, creds, args.model, args.backend,
         args.verbose, args.prune)
        for i, task in enumerate(tasks)
    ]

    # Per-future timeout: SANDBOX_TIMEOUT_SEC + 120s buffer for setup/cleanup
    future_timeout = SANDBOX_TIMEOUT_SEC + 120

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = {
            executor.submit(process_task, *ta): ta[1]  # idx
            for ta in task_args
        }
        for future in as_completed(futures, timeout=future_timeout + 60):
            try:
                outcome = future.result(timeout=future_timeout)
            except TimeoutError:
                idx = futures.get(future, "?")
                log.warning("Task %s timed out (>%ds), skipping", idx, future_timeout)
                continue
            except Exception as e:
                idx = futures.get(future, "?")
                log.warning("Task %s raised %s: %s", idx, type(e).__name__, e)
                continue
            if outcome is None:
                continue
            cost = outcome["result"]["metadata"].get("cost_usd", 0)
            total_cost += cost
            trajectories.append(outcome["traj"])
            evaluated_tasks.append(outcome["task"])

            if args.max_cost > 0 and total_cost >= args.max_cost:
                log.warning("Cost limit $%.2f reached, cancelling remaining", total_cost)
                for f in futures:
                    f.cancel()
                break

    if not trajectories:
        log.error("No tasks completed")
        return 1

    # Write trajectories
    traj_path = out_dir / "trajectories.traj.json"
    with open(traj_path, "w") as f:
        for traj in trajectories:
            f.write(json.dumps(traj) + "\n")
    log.info("Wrote %d trajectories: %s", len(trajectories), traj_path)

    # Compute metrics
    simple_metrics = compute_simple_file_metrics(evaluated_tasks, trajectories)
    chunk_metrics = compute_chunk_metrics(evaluated_tasks, trajectories)

    report = build_calibration_report(
        evaluated_tasks, trajectories, simple_metrics,
        model=args.model, backend=args.backend,
        total_cost=total_cost, n_attempted=len(tasks),
    )
    report["chunk_metrics"] = chunk_metrics
    report["execution"] = {
        "platform": "daytona",
        "parallel": args.parallel,
        "sandbox_timeout_sec": SANDBOX_TIMEOUT_SEC,
    }

    report_path = out_dir / "calibration_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    # Print summary
    sm = report["file_metrics"]
    print(f"\n{'=' * 70}")
    print("Oracle Agent Calibration Report (ContextBench via Daytona)")
    print(f"{'=' * 70}")
    print(f"Model: {args.model} | Backend: {args.backend} | Platform: Daytona")
    print(f"Tasks: {len(trajectories)}/{len(tasks)} | Parallel: {args.parallel} | Cost: ${total_cost:.2f}")
    print(f"\nFile-Level Performance:")
    print(f"  Recall:    {sm['recall']:.4f}")
    print(f"  Precision: {sm['precision']:.4f}")
    print(f"  F1:        {sm['f1']:.4f}")

    cm = report.get("chunk_metrics", {})
    if cm.get("n_chunk_evaluated", 0) > 0:
        print(f"\nChunk-Level:")
        print(f"  Recall:    {cm['chunk_recall']:.4f}")
        print(f"  Precision: {cm['chunk_precision']:.4f}")
        print(f"  F1:        {cm['chunk_f1']:.4f}")

    threshold = report["go_no_go"]
    status = "PASS" if threshold["pass"] else "FAIL"
    print(f"\nGo/No-Go: {status}")
    print(f"  Composite: {report.get('composite_score', 0):.4f}")

    if report.get("bias_analysis", {}).get("by_language"):
        print(f"\nBy Language:")
        for lang, m in sorted(report["bias_analysis"]["by_language"].items()):
            print(f"  {lang:12s}: recall={m['recall']:.3f} precision={m['precision']:.3f} "
                  f"f1={m['f1']:.3f} (n={m['n']})")

    print(f"\nReport: {report_path}")
    print(f"{'=' * 70}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

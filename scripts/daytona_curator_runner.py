#!/usr/bin/env python3
"""Run curator ground truth generation at high throughput via Daytona sandboxes.

Supports two modes:
  1. SDLC mode (--sdlc-all / --suite / --task-dir): Generate ground_truth.json
     for CodeScaleBench SDLC tasks from benchmarks/csb_sdlc_*/ directories.
  2. ContextBench mode (--sample / --phase): Calibrate against ContextBench
     (HuggingFace parquet) tasks with trajectory + metrics output.

Each sandbox gets its own Claude CLI + MCP server, eliminating the local
MCP connection bottleneck that caps --parallel at 5 in local mode.

Usage:
    # SDLC: generate ground truth for all missing tasks
    python3 scripts/daytona_curator_runner.py --sdlc-all --missing-only --parallel 20

    # SDLC: dry run to see what would be processed
    python3 scripts/daytona_curator_runner.py --sdlc-all --missing-only --dry-run

    # SDLC: single suite
    python3 scripts/daytona_curator_runner.py --suite csb_sdlc_debug --missing-only

    # ContextBench: calibration (existing behavior)
    python3 scripts/daytona_curator_runner.py --sample 50 --parallel 20

Environment:
    source .env.local  (sets DAYTONA_API_KEY, SRC_ACCESS_TOKEN, OAuth creds)
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Dict, List, Optional

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
SANDBOX_TIMEOUT_SEC = 1500  # 25 min per task (large repos need more time)

# Max concurrent sandboxes (Tier 3 = 250 vCPU / 2 CPU per sandbox = 125 max)
# Leave headroom for sandbox creation overlap and other users
DEFAULT_PARALLEL = 55

# TAC image tasks → known GitHub repos (no clone URL in Dockerfile)
TAC_REPO_MAP = {
    "bustub": {"slug": "cmu-db/bustub", "commit": "HEAD"},
    "openhands": {"slug": "All-Hands-AI/OpenHands", "commit": "HEAD"},
}

# SWEAP base image patterns — tasks using these must run on local Docker
SWEAP_IMAGE_PATTERNS = ("sweap-images:", "swebench/")

LOCAL_DOCKER_PARALLEL = 12
DAYTONA_PARALLEL = 62


def classify_task_environment(task_dir: Path) -> str:
    """Classify whether a task should run on 'daytona' or 'local' Docker.

    Tasks with SWEAP base images route to local Docker;
    all others route to Daytona.
    """
    env_dir = task_dir / "environment"
    if not env_dir.is_dir():
        return "daytona"

    for dockerfile in env_dir.iterdir():
        if not dockerfile.name.startswith("Dockerfile"):
            continue
        try:
            content = dockerfile.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("FROM "):
                for pattern in SWEAP_IMAGE_PATTERNS:
                    if pattern in stripped:
                        log.info("Task %s routes to LOCAL (SWEAP image: %s)",
                                 task_dir.name, stripped.split()[1])
                        return "local"

    return "daytona"


def _resolve_task_env(task_dir: Path, args) -> str:
    """Resolve the execution environment for a task based on CLI flags."""
    if args.local_only:
        return "local"
    if args.daytona_only:
        return "daytona"
    return classify_task_environment(task_dir)


def load_manifest_tasks(manifest_path: str) -> List[Path]:
    """Load task directories from a manifest JSON (output of audit_gt_coverage.py).

    Filters to tasks with status 'missing', 'empty', or 'invalid-schema'.
    Skips tasks that already have valid GT (idempotent re-runs).
    """
    data = json.loads(Path(manifest_path).read_text())
    processable_statuses = {"missing", "empty", "invalid-schema"}
    tasks = []

    benchmarks_dir = REPO_ROOT / "benchmarks"
    for entry in data:
        if entry.get("status") not in processable_statuses:
            continue
        task_dir = benchmarks_dir / entry["suite"] / entry["task_id"]
        if not task_dir.is_dir():
            log.warning("Manifest task dir not found: %s/%s", entry["suite"], entry["task_id"])
            continue
        # Skip if already has valid GT (idempotent)
        tests_dir = task_dir / "tests"
        if tests_dir.is_dir():
            for gt_name in ("ground_truth.json", "oracle_answer.json", "ground_truth_agent.json"):
                gt = tests_dir / gt_name
                if gt.exists():
                    try:
                        gt_data = json.loads(gt.read_text())
                        if isinstance(gt_data, dict) and gt_data.get("files"):
                            log.debug("Skipping %s — already has valid GT (%s)",
                                      entry["task_id"], gt_name)
                            break
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
            else:
                tasks.append(task_dir)
        else:
            tasks.append(task_dir)

    return tasks


def cleanup_orphaned_sandboxes(daytona_client, label_filter: str = "curator") -> int:
    """Delete all sandboxes with purpose=curator label left from previous runs.

    Called at startup to reclaim CPU quota from crashed/killed runs.
    Returns count of sandboxes deleted.
    """
    try:
        sandboxes = []
        for item in daytona_client.list():
            if isinstance(item, tuple) and item[0] == "items":
                sandboxes = item[1]
                break

        if not sandboxes:
            return 0

        deleted = 0
        for s in sandboxes:
            labels = getattr(s, "labels", {}) or {}
            if labels.get("purpose") != label_filter:
                continue
            try:
                daytona_client.delete(s)
                deleted += 1
            except Exception:
                pass  # Sandbox in transitional state, will be caught by auto-stop

        if deleted:
            log.info("Cleaned up %d orphaned curator sandboxes (of %d total)",
                     deleted, len(sandboxes))
        return deleted
    except Exception as e:
        log.warning("Orphan cleanup failed: %s", e)
        return 0


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
    """Execute a command in a Daytona sandbox with enforced Python-level timeout."""
    label = f"[{sandbox.id[:8]}]"
    if description:
        log.debug("  %s %s", label, description)

    def _run():
        return sandbox.process.exec(cmd, timeout=timeout)

    try:
        # Use a daemon thread to enforce timeout since SDK timeout is unreliable.
        # Avoid context manager — shutdown(wait=True) would block on hung threads.
        from concurrent.futures import ThreadPoolExecutor as _TPE, TimeoutError as _TE
        pool = _TPE(max_workers=1)
        future = pool.submit(_run)
        try:
            response = future.result(timeout=timeout + 15)
        except _TE:
            log.warning("  %s Python-level timeout after %ds: %s", label, timeout, description or cmd[:80])
            pool.shutdown(wait=False, cancel_futures=True)
            return ""
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
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


# ---------------------------------------------------------------------------
# Repo info extraction for SDLC tasks
# ---------------------------------------------------------------------------


def _extract_repo_info_for_sandbox(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract repo cloning info from task context for Daytona sandbox.

    Tries strategies in order:
      1. Dockerfile git clone URLs (sg-evals mirrors, already at right commit)
      2. Dockerfile # Repo: comment (SWEAP images)
      3. Dockerfile # Source: org/repo (commit) (SWEAP debug tasks)
      4. TAC_REPO_MAP for known TAC image tasks

    Returns list of {url, commit, name, slug} dicts.
    """
    repos = []

    # Strategy 1: Dockerfile git clone URLs (sg-evals mirrors)
    clone_urls = ctx.get("repo_urls", [])
    for entry in clone_urls:
        url = entry.get("url", "")
        slug = entry.get("slug", "")
        target = entry.get("target", "repo")
        if url:
            # Only normalize GitHub URLs to ".git"; other hosts (e.g.
            # go.googlesource.com) often work best with the original URL.
            # Substitute kernel.org with faster GitHub mirror for curator clones.
            if "kernel.org" in url:
                clone_url = "https://github.com/torvalds/linux.git"
            elif url.endswith(".git"):
                clone_url = url
            elif "github.com/" in url:
                clone_url = url + ".git"
            else:
                clone_url = url

            # Extract dir name from target path. If Dockerfile uses "." as the
            # target, derive a stable repo name from slug/URL.
            target_name = target.rstrip("/").split("/")[-1] if target else ""
            if target_name in {"", "."}:
                fallback = slug or url
                target_name = fallback.rstrip("/").split("/")[-1].replace(".git", "")
            name = target_name or "repo"
            repos.append({
                "url": clone_url,
                "commit": "HEAD",  # mirrors are at the right commit
                "name": name,
                "slug": slug,
            })
    if repos:
        return repos

    # Parse Dockerfile for comment-based strategies
    task_dir = Path(ctx.get("task_dir", ""))
    dockerfile = task_dir / "environment" / "Dockerfile"
    if dockerfile.exists():
        text = dockerfile.read_text()

        # Strategy 2: # Repo: comment (SWEAP images)
        m = re.search(r"#\s*Repo:\s*(\S+)", text)
        if m:
            slug = m.group(1).strip()
            return [{
                "url": f"https://github.com/{slug}.git",
                "commit": "HEAD",
                "name": slug.split("/")[-1],
                "slug": slug,
            }]

        # Strategy 3: # Source: org/repo (commit) (SWEAP debug tasks)
        m = re.search(r"#\s*Source:\s*(\S+)\s+\(([a-f0-9]+)\)", text)
        if m:
            slug = m.group(1).strip()
            commit = m.group(2).strip()
            return [{
                "url": f"https://github.com/{slug}.git",
                "commit": commit,
                "name": slug.split("/")[-1],
                "slug": slug,
            }]

        # Strategy 3b: Parse SWEAP FROM tag when # Source: uses instance ID format
        # Tag format: jefzda/sweap-images:org.repo-org__repo-commitHash-version
        m = re.search(
            r"jefzda/sweap-images:([\w-]+)\.([\w-]+)-[\w_]+-([a-f0-9]{10,})",
            text,
        )
        if m:
            org = m.group(1)
            repo = m.group(2)
            commit = m.group(3)
            slug = f"{org}/{repo}"
            return [{
                "url": f"https://github.com/{slug}.git",
                "commit": commit,
                "name": repo,
                "slug": slug,
            }]

    # Strategy 4: TAC image mapping
    task_name = ctx.get("task_name", "")
    for key, info in TAC_REPO_MAP.items():
        if key in task_name.lower():
            slug = info["slug"]
            return [{
                "url": f"https://github.com/{slug}.git",
                "commit": info["commit"],
                "name": slug.split("/")[-1],
                "slug": slug,
            }]

    # Strategy 5: repo_fixture local_checkout_repos (Org tasks with MCP-only access)
    # These tasks have no Dockerfile clones — agent accesses repos via MCP at benchmark
    # time. For curator ground truth generation, clone local_checkout_repos so the
    # curator can do thorough local exploration alongside MCP search.
    repo_fixture = ctx.get("repo_fixture", {})
    if repo_fixture:
        local_checkout = repo_fixture.get("local_checkout_repos", [])
        if local_checkout:
            # Disk guard: skip if estimated LOC exceeds sandbox disk capacity
            LOC_DISK_THRESHOLD = 15_000_000  # ~10GB rough approximation
            total_loc = 0
            for full_name in local_checkout:
                for r in repo_fixture.get("repos", []):
                    if r.get("full_name") == full_name:
                        total_loc += r.get("loc_estimate", 0)

            if total_loc > LOC_DISK_THRESHOLD:
                log.warning("[strategy5] %s: skipping local clone (total LOC %d > threshold %d)",
                            ctx.get("task_name", "?"), total_loc, LOC_DISK_THRESHOLD)
                return []

            for full_name in local_checkout:
                name = full_name.split("/")[-1] if "/" in full_name else full_name
                repos.append({
                    "url": f"https://github.com/{full_name}.git",
                    "commit": "HEAD",
                    "name": name,
                    "slug": full_name,
                })
            if repos:
                return repos

    return []


# ---------------------------------------------------------------------------
# Sandbox setup and execution
# ---------------------------------------------------------------------------


def setup_curator_sandbox(
    daytona_client,
    creds: Dict[str, Any],
    repos: List[Dict[str, str]],
    model: str = "claude-opus-4-6",
    backend: str = "hybrid",
) -> Any:
    """Create and set up a Daytona sandbox for curator work.

    Args:
        repos: List of {url, commit, name, slug} dicts for repos to clone.

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

    label_task = repos[0].get("slug", "unknown")[:50] if repos else "unknown"
    params = CreateSandboxFromImageParams(
        image=image,
        language="python",
        env_vars={"DEBIAN_FRONTEND": "noninteractive"},
        labels={"purpose": "curator", "task": label_task},
        resources=Resources(
            cpu=SANDBOX_CPUS,
            memory=SANDBOX_MEMORY_GB,
            disk=SANDBOX_DISK_GB,
        ),
        auto_stop_interval=20,  # Auto-stop after 20 min idle (prevents orphans)
        auto_archive_interval=60,  # Auto-archive after 1 hour
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

    # Clone repos (with retry for transient GitHub rate limits)
    for repo in repos:
        url = repo["url"]
        commit = repo.get("commit", "HEAD")
        name = repo.get("name", "repo")
        target_dir = f"/workspace/{name}"
        log.info("[%s] Cloning %s -> %s (commit: %s)",
                 sandbox.id[:8], url, target_dir, commit[:8] if commit != "HEAD" else "HEAD")
        for attempt in range(3):
            clone_timeout = 540 if "kernel.org" in url else 280
            exec_cmd(sandbox,
                f"timeout {clone_timeout} git clone --no-checkout {url} {target_dir} 2>&1 | tail -3",
                f"Cloning {name} (attempt {attempt+1})", timeout=clone_timeout + 20)
            # Verify clone succeeded
            check = exec_cmd(sandbox, f"test -d {target_dir}/.git && echo OK || echo FAIL")
            if "OK" in check:
                break
            log.warning("[%s] Clone attempt %d failed for %s, retrying...",
                        sandbox.id[:8], attempt + 1, name)
            exec_cmd(sandbox, f"rm -rf {target_dir} 2>/dev/null || true")
            if attempt < 2:
                import time as _time; _time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed to clone {url} after 3 attempts")
        if commit != "HEAD":
            exec_cmd(sandbox,
                f"cd {target_dir} && git checkout {commit} 2>&1 | tail -3",
                f"Checking out {commit[:8]}", timeout=60)
        else:
            # For mirrors/HEAD, just checkout the default branch
            exec_cmd(sandbox,
                f"cd {target_dir} && git checkout 2>&1 | tail -3",
                f"Checking out HEAD", timeout=60)

    # Set ownership
    exec_cmd(sandbox,
        "chown -R claude:claude /workspace /home/claude /tmp/context_retrieval_agent.py "
        "/tmp/ds_wrapper.sh 2>/dev/null || true",
        "Setting ownership")

    return sandbox


def _build_json_rescue_runner() -> str:
    """Build a lightweight Python script that extracts JSON from prose via haiku.

    When the main curator agent outputs prose analysis instead of the required
    JSON format, this rescue runner sends the prose to haiku asking it to
    extract file paths into the expected JSON structure. Costs ~$0.01-0.02
    and takes ~5-10 seconds.
    """
    return '''#!/usr/bin/env python3
"""Extract JSON file list from prose curator output using haiku."""
import json, os, subprocess, sys

prose = open("/tmp/rescue_input.txt").read()
config = json.load(open("/tmp/curator_config.json"))

prompt = """Extract ALL source code file paths mentioned in this analysis output.
Output ONLY a JSON object with a "files" array of repo-relative paths.
Do NOT include test files unless the analysis explicitly says tests need modification.
Do NOT include directories, only files.

Example output:
```json
{"files": ["src/main.py", "pkg/handler/server.go", "internal/config.go"]}
```

Analysis output:
""" + prose[:12000]

env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
env["PATH"] = "/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
env["HOME"] = "/home/claude"
for key in ("CLAUDE_CODE_OAUTH_TOKEN",):
    val = config.get(key, "")
    if val:
        env[key] = val

cmd = [
    "claude", "-p", prompt,
    "--output-format", "json",
    "--model", "claude-haiku-4-5-20251001",
    "--dangerously-skip-permissions",
]

result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
if result.stdout:
    print(result.stdout)
sys.exit(result.returncode)
'''


def _build_python_runner() -> str:
    """Build a Python wrapper script that calls Claude CLI via subprocess.

    Using Python (subprocess.run with list args) avoids all shell quoting
    issues with the system prompt, which contains $, backticks, braces, etc.
    """
    return '''#!/usr/bin/env python3
"""Run claude CLI for curator agent (avoids shell quoting issues)."""
import json, os, signal, subprocess, sys

# OS-level timeout: signal.alarm fires SIGALRM after 840s regardless of
# whether subprocess.run(timeout=...) fires correctly. This prevents the
# Daytona sandbox from hanging indefinitely when the SDK timeout fails.
def _sigalrm_handler(signum, frame):
    print("ERROR: OS-level timeout (SIGALRM) fired after 1440s", file=sys.stderr)
    sys.exit(124)  # Standard timeout exit code

signal.signal(signal.SIGALRM, _sigalrm_handler)

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

signal.alarm(1440)  # Start OS-level timeout (24 min)
try:
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1440)
finally:
    signal.alarm(0)  # Cancel alarm if subprocess completes normally

# Output: print stdout (JSON from claude), stderr to stderr for debugging
if result.stderr:
    print(result.stderr, file=sys.stderr)
if result.stdout:
    print(result.stdout)
sys.exit(result.returncode)
'''


def _run_json_rescue(
    sandbox,
    prose_text: str,
    creds: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Run a haiku rescue call to extract JSON from prose curator output.

    When the main curator agent produces prose analysis instead of the required
    JSON format, this sends the prose to haiku to extract file paths.
    Costs ~$0.01-0.02 and takes ~5-10 seconds.

    Returns parsed oracle dict or None on failure.
    """
    try:
        # Write prose text to sandbox
        prose_b64 = base64.b64encode(prose_text[:12000].encode()).decode()
        exec_cmd(sandbox,
            f"echo '{prose_b64}' | base64 -d > /tmp/rescue_input.txt",
            "Writing rescue input")

        # Write rescue runner script
        rescue_code = _build_json_rescue_runner()
        rescue_b64 = base64.b64encode(rescue_code.encode()).decode()
        exec_cmd(sandbox,
            f"echo '{rescue_b64}' | base64 -d > /tmp/run_rescue.py && chmod +x /tmp/run_rescue.py",
            "Writing rescue runner")

        exec_cmd(sandbox,
            "chown claude:claude /tmp/rescue_input.txt /tmp/run_rescue.py 2>/dev/null || true")

        # Execute rescue
        rescue_output = exec_cmd(sandbox,
            "su - claude -c 'python3 /tmp/run_rescue.py 2>/dev/null'",
            "Haiku JSON rescue", timeout=120)

        if not rescue_output:
            return None

        parsed = json.loads(rescue_output)
        result_text = parsed.get("result", "")

        from context_retrieval_agent import _extract_json_from_text
        return _extract_json_from_text(result_text)

    except Exception as e:
        log.debug("[%s] Rescue error: %s", sandbox.id[:8], e)
        return None


def _regex_extract_files(text: str) -> List[str]:
    """Last-resort extraction of file paths from prose text using regex.

    Looks for patterns like:
      - `path/to/file.ext` (backtick-quoted)
      - path/to/file.ext (bare paths with common extensions)
      - **path/to/file.ext** (bold in markdown)
    """
    files = set()

    # Pattern: backtick-quoted paths with extensions
    for m in re.finditer(r'`([a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10})`', text):
        path = m.group(1)
        if '/' in path and not path.startswith('http') and not path.startswith('.'):
            files.add(path)

    # Pattern: markdown bold paths
    for m in re.finditer(r'\*\*([a-zA-Z0-9_/.-]+\.[a-zA-Z]{1,10})\*\*', text):
        path = m.group(1)
        if '/' in path and not path.startswith('http'):
            files.add(path)

    # Pattern: bare repo-relative paths (at least 2 segments, with extension)
    for m in re.finditer(
        r'(?:^|\s)((?:[a-zA-Z0-9_-]+/){1,10}[a-zA-Z0-9_.-]+\.(?:go|py|java|rs|ts|tsx|js|jsx|c|cc|cpp|h|hpp|rb|ex|exs|swift|kt|scala|sql|proto|yaml|yml|toml|json|xml|sh|bash|md|txt))\b',
        text,
    ):
        path = m.group(1)
        if not path.startswith('http'):
            files.add(path)

    # Filter out obvious non-files
    filtered = []
    skip_prefixes = ('http', 'www.', 'github.com', 'example.', 'test.')
    skip_exact = {'go.sum', 'go.mod', 'package.json', 'package-lock.json',
                  'Cargo.lock', 'yarn.lock', 'pnpm-lock.yaml'}
    for f in sorted(files):
        if any(f.startswith(p) for p in skip_prefixes):
            continue
        if f in skip_exact:
            continue
        if len(f) < 5 or len(f) > 200:
            continue
        filtered.append(f)

    return filtered


def run_curator_in_sandbox(
    sandbox,
    creds: Dict[str, Any],
    model: str = "claude-opus-4-6",
    backend: str = "hybrid",
    verbose: bool = False,
    suite_name: str = "",
    prompt_version: str = "phase1",
    user_msg: str = "",
    workdir: str = "/workspace/repo",
    problem_statement: str = "",
    repo_name: str = "",
) -> Dict[str, Any]:
    """Run the curator agent inside a Daytona sandbox.

    Uses claude CLI mode (subscription billing) with a Python wrapper script
    that calls subprocess.run() to avoid shell quoting issues with the
    system prompt (which contains $, backticks, braces, etc.).

    For SDLC mode, pass user_msg and workdir directly.
    For ContextBench mode, pass problem_statement and repo_name (legacy).

    Returns the oracle result dict.
    """
    src_token = creds.get("src_token", "")
    access_token = ""
    if creds.get("oauth_creds"):
        access_token = creds["oauth_creds"]["access_token"]

    # Build curator prompt based on version
    if prompt_version == "phase1":
        from context_retrieval_agent import get_phase1_system_prompt
        system_prompt = get_phase1_system_prompt(backend)
    else:
        from context_retrieval_agent import (
            CURATOR_SYSTEM_PROMPT,
            _tool_description_for_backend,
            get_task_type_guidance,
        )
        system_prompt = CURATOR_SYSTEM_PROMPT.format(
            tool_description=_tool_description_for_backend(backend, cli_mode=True),
            task_type_guidance=get_task_type_guidance(suite_name),
        )

    # Build user message (SDLC mode provides it; ContextBench builds it here)
    if not user_msg:
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

    # Build allowed tools based on backend and prompt version
    if prompt_version == "phase1":
        from context_retrieval_agent import get_phase1_allowed_tools
        allowed = ",".join(get_phase1_allowed_tools(backend))
    else:
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
        "workdir": workdir,
    }
    if access_token:
        config["CLAUDE_CODE_OAUTH_TOKEN"] = access_token
    if src_token:
        config["SRC_ACCESS_TOKEN"] = src_token
        config["SOURCEGRAPH_ACCESS_TOKEN"] = src_token
    if backend in ("deepsearch", "hybrid") and src_token:
        config["mcp_config"] = "/tmp/.mcp.json"

    config_json = json.dumps(config)
    cfg_delim = f"CFG_{hash(workdir) & 0xFFFFFF:06x}"
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
        f"timeout {SANDBOX_TIMEOUT_SEC} su - claude -c 'python3 /tmp/run_curator.py 2>/tmp/curator_stderr.txt'",
        "Running curator agent", timeout=SANDBOX_TIMEOUT_SEC + 30)
    elapsed = time.time() - start

    # Collect stderr for debugging
    stderr = exec_cmd(sandbox, "cat /tmp/curator_stderr.txt 2>/dev/null || true")
    if stderr and verbose:
        log.debug("[%s] stderr: %s", sandbox.id[:8], stderr[:500])
    if not raw_output and stderr:
        log.warning("[%s] No stdout, stderr: %s", sandbox.id[:8], stderr[:300])
    if raw_output:
        log.debug("[%s] raw output (first 500): %s", sandbox.id[:8], raw_output[:500])

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

        # Detect rate limiting
        if parsed.get("is_error") and "hit your limit" in result_text.lower():
            log.error("[%s] RATE LIMITED: %s", sandbox.id[:8], result_text)
            metadata["error"] = True
            metadata["rate_limited"] = True
            return {"oracle": result, "metadata": metadata}

        # Extract oracle JSON from result text
        from context_retrieval_agent import _extract_json_from_text
        oracle = _extract_json_from_text(result_text)
        if oracle:
            result = oracle
        elif result_text and len(result_text) > 100:
            # JSON extraction failed but we have prose output — try rescue
            log.info("[%s] JSON extraction failed, attempting haiku rescue (%d chars of prose)",
                     sandbox.id[:8], len(result_text))
            rescue_result = _run_json_rescue(sandbox, result_text, creds)
            if rescue_result and rescue_result.get("files"):
                result = rescue_result
                metadata["json_rescued"] = True
                log.info("[%s] Haiku rescue recovered %d files",
                         sandbox.id[:8], len(result["files"]))
            else:
                log.warning("[%s] Haiku rescue also failed", sandbox.id[:8])
                # Last resort: regex extraction of file paths from prose
                regex_files = _regex_extract_files(result_text)
                if regex_files:
                    result = {"files": regex_files, "text": "Extracted via regex from prose output"}
                    metadata["regex_rescued"] = True
                    log.info("[%s] Regex rescue recovered %d files",
                             sandbox.id[:8], len(regex_files))
    except (json.JSONDecodeError, TypeError) as e:
        log.warning("[%s] Failed to parse output: %s", sandbox.id[:8], e)
        if raw_output:
            log.debug("[%s] Raw output (first 500): %s", sandbox.id[:8], raw_output[:500])
        metadata["error"] = True

    return {"oracle": result, "metadata": metadata}


# ---------------------------------------------------------------------------
# SDLC task processing
# ---------------------------------------------------------------------------


def process_sdlc_task(
    task_dir: Path,
    idx: int,
    total: int,
    daytona_client,
    creds: Dict[str, Any],
    model: str,
    backend: str,
    verbose: bool,
    prompt_version: str = "phase1",
    overwrite: bool = False,
) -> Optional[Dict[str, Any]]:
    """Process a single SDLC task for ground truth generation in a Daytona sandbox."""
    from context_retrieval_agent import (
        parse_task_for_curator,
        build_user_message,
        write_curator_outputs,
    )

    task_name = f"{task_dir.parent.name}/{task_dir.name}"
    log.info("[%d/%d] %s", idx + 1, total, task_name)

    # 1. Parse task locally
    ctx = parse_task_for_curator(task_dir)

    # 2. Extract repo info for sandbox cloning
    repos = _extract_repo_info_for_sandbox(ctx)
    if not repos:
        log.warning("[%d/%d] No repo info for %s, skipping", idx + 1, total, task_name)
        return None

    # 3. Build user message with sandbox repo paths
    repo_paths = {}
    for r in repos:
        repo_paths[r["slug"]] = Path(f"/workspace/{r['name']}")
    user_msg = build_user_message(ctx, repo_paths)

    # 4. Determine workdir (first repo)
    workdir = f"/workspace/{repos[0]['name']}"

    sandbox = None
    try:
        # 5. Create sandbox and clone repos
        sandbox = setup_curator_sandbox(
            daytona_client, creds, repos=repos,
            model=model, backend=backend,
        )

        # 6. Run curator in sandbox
        result = run_curator_in_sandbox(
            sandbox,
            creds=creds,
            model=model,
            backend=backend,
            verbose=verbose,
            suite_name=ctx.get("suite_name", ""),
            prompt_version=prompt_version,
            user_msg=user_msg,
            workdir=workdir,
        )

        n_files = len(result["oracle"].get("files", []))
        cost = result["metadata"].get("cost_usd", 0)
        elapsed = result["metadata"].get("elapsed_sec", 0)
        log.info("[%d/%d] %s -> %d files, $%.4f, %.1fs",
                 idx + 1, total, task_name, n_files, cost, elapsed)

        # 7. Write ground truth locally
        if result["oracle"].get("files"):
            metadata = {
                "model": model,
                "backend": backend,
                "prompt_version": prompt_version,
                "cost_usd": cost,
                "elapsed_sec": elapsed,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tool_calls": result["metadata"].get("num_turns", 0),
                "generator": "daytona_curator_runner",
            }
            write_curator_outputs(
                task_dir, result["oracle"], metadata, ctx, overwrite=overwrite,
            )
        else:
            log.warning("[%d/%d] %s: no files found by curator", idx + 1, total, task_name)

        return {"task_name": task_name, "result": result}

    except Exception as e:
        log.error("[%d/%d] %s failed: %s", idx + 1, total, task_name, e)
        traceback.print_exc()
        return None
    finally:
        if sandbox:
            try:
                daytona_client.delete(sandbox)
                log.debug("[%s] Sandbox deleted", sandbox.id[:8])
            except Exception as e:
                log.warning("Failed to delete sandbox: %s", e)


# ---------------------------------------------------------------------------
# ContextBench task processing (existing behavior)
# ---------------------------------------------------------------------------


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
    prompt_version: str = "phase1",
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
        # Wrap single repo in list format for setup_curator_sandbox
        repos = [{"url": repo_url, "commit": commit, "name": "repo", "slug": repo_name}]
        sandbox = setup_curator_sandbox(
            daytona_client, creds, repos=repos,
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
            prompt_version=prompt_version,
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


# ---------------------------------------------------------------------------
# Main: dual-mode entry point
# ---------------------------------------------------------------------------


def _run_sdlc_mode(args, creds: Dict[str, Any]) -> int:
    """SDLC mode: generate ground truth for CodeScaleBench tasks."""
    from context_retrieval_agent import discover_tasks, load_task_context

    # Discover tasks — manifest takes priority over discovery flags
    if args.manifest:
        tasks = load_manifest_tasks(args.manifest)
        log.info("Loaded %d tasks from manifest %s", len(tasks), args.manifest)
    else:
        tasks = discover_tasks(
            suite=args.suite,
            task_dir=args.task_dir,
            sdlc_all=args.sdlc_all,
            mcp_all=args.mcp_all,
        )
    if not tasks:
        log.error("No tasks found")
        return 1

    # Skip tasks whose repos are too large to clone in Daytona (linux kernel ~3.5GB)
    SKIP_TASK_PATTERNS = ()
    SKIP_TASK_NAMES = {
        "linux-acpi-backlight-fault-001",
        "linux-hda-intel-suspend-fault-001",
        "linux-iwlwifi-subdevice-fault-001",
        "linux-nfs-inode-revalidate-fault-001",
    }
    before_skip = len(tasks)
    tasks = [
        t for t in tasks
        if not any(t.name.startswith(pat) for pat in SKIP_TASK_PATTERNS)
        and t.name not in SKIP_TASK_NAMES
    ]
    if len(tasks) < before_skip:
        log.info("Skipped %d unsupported/broken tasks",
                 before_skip - len(tasks))

    # Filter to missing-only if requested
    original_count = len(tasks)
    if args.missing_only:
        filtered = []
        for t in tasks:
            tests_dir = t / "tests"
            has_gt = (
                (tests_dir / "ground_truth.json").exists()
                or (tests_dir / "oracle_answer.json").exists()
            )
            if not has_gt:
                filtered.append(t)
        tasks = filtered
        log.info("Filtered %d -> %d tasks (missing_only=True)", original_count, len(tasks))

    # Skip tasks that already have _agent variant files (for idempotent re-runs)
    if args.skip_agent_variants:
        before_agent = len(tasks)
        filtered2 = []
        for t in tasks:
            tests_dir = t / "tests"
            suite = t.parent.name
            is_org = suite.startswith(("csb_org_", "ccb_mcp_"))
            if is_org:
                agent_file = tests_dir / "oracle_answer_agent.json"
            else:
                agent_file = tests_dir / "ground_truth_agent.json"
            if not agent_file.exists():
                filtered2.append(t)
        tasks = filtered2
        log.info("Filtered %d -> %d tasks (skip_agent_variants=True)",
                 before_agent, len(tasks))

    if args.max_tasks > 0:
        tasks = tasks[:args.max_tasks]

    if not tasks:
        log.info("All tasks already have ground truth. Nothing to do.")
        return 0

    log.info("SDLC mode: %d tasks (model=%s, backend=%s, parallel=%d, prompt=%s)",
             len(tasks), args.model, args.backend, args.parallel, args.prompt_version)

    if args.dry_run:
        route_counts = {"daytona": 0, "local": 0}
        for i, t in enumerate(tasks):
            ctx = load_task_context(t)
            repos = _extract_repo_info_for_sandbox(ctx)
            repo_info = repos[0]["slug"] if repos else "NO_REPO"
            env = _resolve_task_env(t, args)
            route_counts[env] += 1
            print(f"  [{i+1}] {t.parent.name}/{t.name} ({repo_info}) [{env}]")
        print(f"\nTotal: {len(tasks)} tasks, {args.parallel} concurrent sandboxes")
        print(f"Routing: {route_counts['daytona']} daytona, {route_counts['local']} local")
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

    # Clean up orphaned sandboxes from previous crashed/killed runs
    cleanup_orphaned_sandboxes(daytona)

    # Run tasks in parallel
    total_cost = 0.0
    completed = []
    failed = []

    task_args = [
        (task_dir, i, len(tasks), daytona, creds, args.model, args.backend,
         args.verbose, args.prompt_version, args.overwrite_existing)
        for i, task_dir in enumerate(tasks)
    ]

    future_timeout = SANDBOX_TIMEOUT_SEC + 300  # clone (300s) + curator (900s)
    # Scale global timeout by queued "waves" so large batches don't get cut off
    # by a fixed wall-clock limit. Allow explicit override for long/retry runs.
    waves = max(1, (len(tasks) + max(1, args.parallel) - 1) // max(1, args.parallel))
    computed_global_timeout = (future_timeout * waves) + 600  # extra 10 min buffer
    global_timeout = args.global_timeout_sec if args.global_timeout_sec > 0 else computed_global_timeout

    executor = ThreadPoolExecutor(max_workers=args.parallel)
    futures = {
        executor.submit(process_sdlc_task, *ta): ta[0]  # task_dir
        for ta in task_args
    }

    # Signal handler: on SIGTERM/SIGINT, cancel futures and let finally blocks run
    import signal as _signal
    _shutdown_requested = False

    def _graceful_shutdown(signum, frame):
        nonlocal _shutdown_requested
        if _shutdown_requested:
            return  # Avoid re-entry
        _shutdown_requested = True
        sig_name = _signal.Signals(signum).name
        log.warning("Received %s — cancelling pending futures and cleaning up sandboxes", sig_name)
        for f in futures:
            f.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    _signal.signal(_signal.SIGTERM, _graceful_shutdown)
    _signal.signal(_signal.SIGINT, _graceful_shutdown)

    try:
        for future in as_completed(futures, timeout=global_timeout):
            if _shutdown_requested:
                break
            task_dir = futures.get(future, Path("?"))
            try:
                outcome = future.result(timeout=future_timeout)
            except (TimeoutError, FuturesTimeoutError):
                log.warning("Task %s timed out (>%ds), skipping", task_dir, future_timeout)
                failed.append(str(task_dir))
                continue
            except Exception as e:
                log.warning("Task %s raised %s: %s", task_dir, type(e).__name__, e)
                failed.append(str(task_dir))
                continue
            if outcome is None:
                failed.append(str(task_dir))
                continue
            # Abort early on rate limiting
            if outcome["result"]["metadata"].get("rate_limited"):
                log.error("Rate limited — aborting remaining tasks. Wait for limit reset.")
                failed.append(str(task_dir))
                break

            cost = outcome["result"]["metadata"].get("cost_usd", 0)
            total_cost += cost
            completed.append(outcome["task_name"])

            if args.max_cost > 0 and total_cost >= args.max_cost:
                log.warning("Cost limit $%.2f reached, cancelling remaining", total_cost)
                break
    except (TimeoutError, FuturesTimeoutError):
        log.warning("as_completed global timeout expired — %d futures still pending",
                    sum(1 for f in futures if not f.done()))
        for f in futures:
            if not f.done():
                task_dir = futures.get(f, Path("?"))
                failed.append(str(task_dir))
    finally:
        # Non-blocking shutdown — don't wait for stuck Daytona SDK threads
        executor.shutdown(wait=False, cancel_futures=True)
        # Best-effort cleanup of any remaining sandboxes
        cleanup_orphaned_sandboxes(daytona)

    # Summary
    print(f"\n{'=' * 60}")
    print("SDLC Ground Truth Generation (Daytona)")
    print(f"{'=' * 60}")
    print(f"Model: {args.model} | Backend: {args.backend} | Prompt: {args.prompt_version}")
    print(f"Completed: {len(completed)}/{len(tasks)} | Failed: {len(failed)} | Cost: ${total_cost:.2f}")
    if failed:
        print(f"\nFailed tasks:")
        for f in failed[:20]:
            print(f"  - {f}")
    print(f"{'=' * 60}")

    return 0 if completed else 1


def _run_contextbench_mode(args, creds: Dict[str, Any]) -> int:
    """ContextBench mode: calibration with trajectory + metrics output."""
    from validate_on_contextbench import (
        load_tasks, ccb_weighted_sample, compute_simple_file_metrics, compute_chunk_metrics,
        build_calibration_report,
    )

    # Load tasks
    if args.instance_ids:
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

    # Clean up orphaned sandboxes from previous crashed/killed runs
    cleanup_orphaned_sandboxes(daytona)

    # Output directory
    out_dir = Path(args.out) if args.out else RESULTS_DIR / f"daytona_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Run tasks in parallel
    total_cost = 0.0
    trajectories = []
    evaluated_tasks = []

    task_args = [
        (task, i, len(tasks), daytona, creds, args.model, args.backend,
         args.verbose, args.prune, "", args.prompt_version)
        for i, task in enumerate(tasks)
    ]

    future_timeout = SANDBOX_TIMEOUT_SEC + 300
    waves = max(1, (len(tasks) + max(1, args.parallel) - 1) // max(1, args.parallel))
    computed_global_timeout = (future_timeout * waves) + 600
    global_timeout = args.global_timeout_sec if args.global_timeout_sec > 0 else computed_global_timeout

    executor = ThreadPoolExecutor(max_workers=args.parallel)
    futures = {
        executor.submit(process_task, *ta): ta[1]  # idx
        for ta in task_args
    }
    try:
        for future in as_completed(futures, timeout=global_timeout):
            try:
                outcome = future.result(timeout=future_timeout)
            except (TimeoutError, FuturesTimeoutError):
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
                break
    except (TimeoutError, FuturesTimeoutError):
        log.warning("as_completed global timeout expired — %d futures still pending",
                    sum(1 for f in futures if not f.done()))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        cleanup_orphaned_sandboxes(daytona)

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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run curator ground truth generation via Daytona (SDLC or ContextBench)"
    )

    # SDLC mode flags
    sdlc_group = parser.add_argument_group("SDLC mode (ground truth generation)")
    sdlc_group.add_argument("--sdlc-all", action="store_true",
                            help="Process all SDLC tasks")
    sdlc_group.add_argument("--mcp-all", action="store_true",
                            help="Process all MCP-unique tasks")
    sdlc_group.add_argument("--suite", type=str, default="",
                            help="Process tasks in a specific suite (e.g., csb_sdlc_debug)")
    sdlc_group.add_argument("--task-dir", type=str, default="",
                            help="Single task directory to process")
    sdlc_group.add_argument("--missing-only", action="store_true",
                            help="Only process tasks missing ground_truth.json")
    sdlc_group.add_argument("--overwrite-existing", action="store_true",
                            help="Overwrite existing ground_truth.json (default: write to _agent variant)")
    sdlc_group.add_argument("--skip-agent-variants", action="store_true",
                            help="Skip tasks that already have *_agent.json files (idempotent re-runs)")
    sdlc_group.add_argument("--manifest", type=str, default="",
                            help="JSON manifest from audit_gt_coverage.py (filters to missing/empty/invalid tasks)")

    # Environment routing flags
    route_group = parser.add_argument_group("Environment routing")
    route_group.add_argument("--auto-route", action="store_true", default=True,
                             help="Auto-route tasks to Daytona or local Docker (default)")
    route_group.add_argument("--local-only", action="store_true",
                             help="Force all tasks to local Docker (max 12 concurrent)")
    route_group.add_argument("--daytona-only", action="store_true",
                             help="Force all tasks to Daytona (max 62 concurrent)")

    # ContextBench mode flags
    cb_group = parser.add_argument_group("ContextBench mode (calibration)")
    cb_group.add_argument("--sample", type=int, default=0, help="Number of tasks to sample")
    cb_group.add_argument("--verified", action="store_true", help="Use verified subset (500)")
    cb_group.add_argument("--phase", type=str, default="", choices=("", "test", "verify"),
                          help="Calibration phase: 'test' (10) or 'verify' (50)")
    cb_group.add_argument("--seed", type=int, default=42)
    cb_group.add_argument("--out", type=str, default="", help="Output directory")
    cb_group.add_argument("--prune", action="store_true",
                          help="Run haiku pruning pass to improve precision")
    cb_group.add_argument("--instance-ids", type=str, default="",
                          help="Comma-separated instance ID suffixes to filter tasks")

    # Shared flags
    parser.add_argument("--model", type=str, default="claude-opus-4-6")
    parser.add_argument("--prompt-version", type=str, default="phase1",
                        choices=("phase1", "v7"),
                        help="Prompt version: phase1 (recall-focused) or v7 (edit-centric). Default: phase1")
    parser.add_argument("--backend", type=str, default="hybrid",
                        choices=("local", "deepsearch", "hybrid"))
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                        help=f"Concurrent sandboxes (default: {DEFAULT_PARALLEL})")
    parser.add_argument(
        "--global-timeout-sec",
        type=int,
        default=0,
        help=(
            "Override wall-clock timeout for the full batch in seconds. "
            "Default (0) uses a computed timeout based on task count and parallelism."
        ),
    )
    parser.add_argument("--max-cost", type=float, default=0, help="Cost limit in USD")
    parser.add_argument("--max-tasks", type=int, default=0, help="Max tasks to process")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Add scripts dir to path for imports
    sys.path.insert(0, str(SCRIPTS_DIR))

    # Load credentials (skip validation for dry-run)
    creds = load_credentials()
    if not args.dry_run:
        if not creds["daytona_api_key"]:
            log.error("DAYTONA_API_KEY required. Set in env or ~/.config/daytona/env.sh")
            return 1
        if not creds.get("oauth_creds"):
            log.error("OAuth credentials required. Check ~/.claude-homes/accountN/.claude/.credentials.json")
            return 1

    # Dispatch to appropriate mode
    sdlc_mode = args.sdlc_all or args.mcp_all or args.suite or args.task_dir or args.manifest
    if sdlc_mode:
        return _run_sdlc_mode(args, creds)
    else:
        return _run_contextbench_mode(args, creds)


if __name__ == "__main__":
    sys.exit(main())

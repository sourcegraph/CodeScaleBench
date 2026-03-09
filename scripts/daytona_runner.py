#!/usr/bin/env python3
"""General-purpose Daytona benchmark runner for CodeScaleBench.

Runs any combination of benchmark tasks using Daytona sandboxes.
Creates sandboxes dynamically from task Dockerfiles, runs Claude Code,
verifies results, and cleans up.

Usage:
  # Run a single task
  python3 scripts/daytona_runner.py --task cgen-deps-install-001

  # Run a full suite
  python3 scripts/daytona_runner.py --suite ccb_feature --config baseline-local-direct

  # Run all ready tasks in parallel
  python3 scripts/daytona_runner.py --all --parallel 4

  # List suites and tasks
  python3 scripts/daytona_runner.py --list-suites
  python3 scripts/daytona_runner.py --list-tasks --suite ccb_feature

  # Dry run (no sandboxes created)
  python3 scripts/daytona_runner.py --suite ccb_feature --dry-run
"""

import argparse
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
REGISTRY_PATH = REPO_ROOT / "scripts" / "daytona_task_registry.json"
RUNS_DIR = REPO_ROOT / "runs" / "daytona"

DAYTONA_API_URL = os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api")
DAYTONA_TARGET = os.environ.get("DAYTONA_TARGET", "us")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TURNS = 30

CONFIG_DOCKERFILE_MAP = {
    "baseline-local-direct": "Dockerfile",
    "mcp-remote-direct": "Dockerfile.sg_only",
    "baseline-local-artifact": "Dockerfile.artifact_baseline",
    "mcp-remote-artifact": "Dockerfile.artifact_only",
}

CONFIG_INSTRUCTION_MAP = {
    "baseline-local-direct": "instruction.md",
    "mcp-remote-direct": "instruction_mcp.md",
    "baseline-local-artifact": "instruction.md",
    "mcp-remote-artifact": "instruction_mcp.md",
}

MCP_CONFIGS = {"mcp-remote-direct", "mcp-remote-artifact"}
ACCOUNT_NAME_RE = re.compile(r"account(\d+)$")


def resolve_dockerfile_name(task: "TaskSpec", config_name: str) -> str:
    dockerfile_name = CONFIG_DOCKERFILE_MAP[config_name]
    if config_name != "baseline-local-artifact":
        return dockerfile_name

    env_dir = task.task_dir / "environment"
    if (env_dir / dockerfile_name).exists():
        return dockerfile_name
    return dockerfile_name


def baseline_artifact_has_local_repos(task: "TaskSpec") -> bool:
    instruction_path = task.task_dir / "instruction.md"
    if not instruction_path.exists():
        return False
    text = instruction_path.read_text()
    return "No local repositories are pre-checked out." not in text

log = logging.getLogger("daytona_runner")

# ---------------------------------------------------------------------------
# Section 1: Credential Loaders (from PoC)
# ---------------------------------------------------------------------------

def load_daytona_api_key() -> str:
    key = os.environ.get("DAYTONA_API_KEY", "")
    if key:
        return key
    config_path = Path.home() / ".config" / "daytona" / "env.sh"
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            if "DAYTONA_API_KEY" in line and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def load_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    creds_path = Path.home() / ".claude" / "credentials.json"
    if creds_path.exists():
        try:
            return json.loads(creds_path.read_text()).get("apiKey", "")
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def load_src_access_token() -> str:
    return os.environ.get("SRC_ACCESS_TOKEN", "")


# OAuth constants and functions

OAUTH_CLIENT_ID = os.environ.get(
    "CLAUDE_OAUTH_CLIENT_ID", "9d1c250a-e61b-44d9-88ed-5944d1962f5e")
OAUTH_TOKEN_URL = os.environ.get(
    "CLAUDE_OAUTH_TOKEN_URL", "https://console.anthropic.com/api/oauth/token")
REFRESH_MARGIN = 1800


def _account_creds_path(account_num: int) -> Path:
    return Path.home() / ".claude-homes" / f"account{account_num}" / ".claude" / ".credentials.json"


def _discover_account_numbers() -> List[int]:
    homes_dir = Path.home() / ".claude-homes"
    if not homes_dir.is_dir():
        return []

    account_numbers: List[int] = []
    for path in homes_dir.iterdir():
        if not path.is_dir():
            continue
        match = ACCOUNT_NAME_RE.fullmatch(path.name)
        if match:
            account_numbers.append(int(match.group(1)))
    return sorted(account_numbers)


def list_oauth_accounts() -> List[dict]:
    accounts = []
    for num in _discover_account_numbers():
        creds_path = _account_creds_path(num)
        if not creds_path.exists():
            alt_path = creds_path.parent / "credentials.json"
            if alt_path.exists():
                creds_path = alt_path
            else:
                accounts.append({
                    "num": num,
                    "path": str(creds_path),
                    "error": "missing credentials",
                })
                continue
        try:
            creds = json.loads(creds_path.read_text())
            oauth = creds.get("claudeAiOauth", {})
            expires_at_ms = oauth.get("expiresAt", 0)
            now_ms = int(time.time() * 1000)
            remaining_min = int((expires_at_ms - now_ms) / 60000)
            has_refresh = bool(oauth.get("refreshToken"))
            accounts.append({
                "num": num, "path": str(creds_path),
                "remaining_min": remaining_min, "has_refresh": has_refresh,
                "valid": remaining_min > 0 or has_refresh,
            })
        except Exception as e:
            accounts.append({"num": num, "path": str(creds_path), "error": str(e)})
    return accounts


def refresh_oauth_token(account_num: int) -> dict:
    creds_path = _account_creds_path(account_num)
    if not creds_path.exists():
        alt_path = creds_path.parent / "credentials.json"
        if alt_path.exists():
            creds_path = alt_path
        else:
            raise FileNotFoundError(f"No credentials at {creds_path}")

    creds = json.loads(creds_path.read_text())
    oauth = creds.get("claudeAiOauth", {})
    expires_at_ms = oauth.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    remaining_s = (expires_at_ms - now_ms) / 1000

    if remaining_s > REFRESH_MARGIN:
        return creds

    refresh_token = oauth.get("refreshToken")
    if not refresh_token:
        raise ValueError(f"Account {account_num}: no refreshToken")

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        OAUTH_TOKEN_URL, data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ccb-daytona-runner/1.0"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        raise RuntimeError(f"Token refresh failed: HTTP {e.code} - {body}")

    new_access = token_data.get("access_token")
    if not new_access:
        raise RuntimeError("No access_token in refresh response")

    oauth["accessToken"] = new_access
    if token_data.get("refresh_token"):
        oauth["refreshToken"] = token_data["refresh_token"]
    expires_in = token_data.get("expires_in", 28800)
    oauth["expiresAt"] = int(time.time() * 1000) + (expires_in * 1000)
    creds["claudeAiOauth"] = oauth
    creds_path.write_text(json.dumps(creds, indent=2))
    return creds


def load_oauth_credentials(account_num: int) -> dict:
    creds = refresh_oauth_token(account_num)
    oauth = creds.get("claudeAiOauth", {})
    access_token = oauth.get("accessToken", "")
    if not access_token:
        raise ValueError(f"Account {account_num}: no accessToken after refresh")
    return {
        "access_token": access_token,
        "creds_json": json.dumps(creds),
        "creds_dict": creds,
    }


def exec_cmd(sandbox, cmd: str, description: str = "", timeout: int = 120) -> str:
    label = f"[{sandbox.id[:8]}]"
    if description:
        log.debug(f"  {label} {description}")
    try:
        response = sandbox.process.exec(cmd, timeout=timeout)
        if hasattr(response, "exit_code") and response.exit_code != 0:
            stderr = getattr(response, "stderr", "") or ""
            stdout = getattr(response, "result", "") or getattr(response, "stdout", "") or ""
            log.debug(f"  {label} exit code {response.exit_code}")
            if stderr:
                log.debug(f"  {label} stderr: {stderr[:500]}")
            return stdout
        return getattr(response, "result", "") or getattr(response, "stdout", "") or ""
    except Exception as e:
        log.warning(f"  {label} exec error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Section 2: Data Classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    suite: str
    language: str
    category: str
    difficulty: str
    agent_timeout_sec: int
    build_timeout_sec: int
    cpus: int
    memory_mb: int
    storage_mb: int
    reward_type: str
    verify_command: str
    dockerfiles: Dict[str, Any]
    instructions: Dict[str, bool]
    tests: Dict[str, bool]
    task_dir: Path


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    config_name: str
    auth_mode: str
    account_num: int
    model: str
    max_turns: int
    parallel: int
    timeout: int
    retry_count: int
    dry_run: bool


@dataclass
class TaskResult:
    task_id: str
    config: str
    run_id: str
    status: str = "pending"
    reward: Optional[float] = None
    agent_elapsed_sec: float = 0.0
    setup_elapsed_sec: float = 0.0
    verify_elapsed_sec: float = 0.0
    total_elapsed_sec: float = 0.0
    sandbox_id: str = ""
    agent_output: str = ""
    verification_output: str = ""
    error_message: str = ""
    cost_usd: Optional[float] = None
    num_turns: Optional[int] = None
    retry_attempt: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["task_dir"] = None  # Not serializable
        return d


# ---------------------------------------------------------------------------
# Section 3: Task Registry
# ---------------------------------------------------------------------------

class TaskRegistry:
    def __init__(self, registry_path: Path = REGISTRY_PATH):
        data = json.loads(registry_path.read_text())
        self._tasks: Dict[str, dict] = {t["task_id"]: t for t in data["tasks"]}
        self._suites: Dict[str, dict] = data.get("suites", {})

    def get_task(self, task_id: str) -> Optional[TaskSpec]:
        raw = self._tasks.get(task_id)
        if not raw:
            return None
        return self._to_spec(raw)

    def get_suite(self, suite_name: str) -> List[TaskSpec]:
        suite = self._suites.get(suite_name)
        if not suite:
            return []
        return [
            self._to_spec(self._tasks[tid])
            for tid in suite.get("task_ids", [])
            if tid in self._tasks and self._tasks[tid]["daytona_readiness"] == "ready"
        ]

    def get_all_ready(self) -> List[TaskSpec]:
        return [
            self._to_spec(t) for t in self._tasks.values()
            if t["daytona_readiness"] == "ready"
        ]

    def list_suites(self) -> Dict[str, dict]:
        result = {}
        for name, info in self._suites.items():
            ready = sum(
                1 for tid in info.get("task_ids", [])
                if tid in self._tasks and self._tasks[tid]["daytona_readiness"] == "ready"
            )
            result[name] = {"total": info.get("task_count", 0), "ready": ready}
        return result

    def _to_spec(self, raw: dict) -> TaskSpec:
        timeouts = raw.get("timeouts", {})
        resources = raw.get("resources", {})
        return TaskSpec(
            task_id=raw["task_id"],
            suite=raw["suite"],
            language=raw.get("language", ""),
            category=raw.get("category", ""),
            difficulty=raw.get("difficulty", ""),
            agent_timeout_sec=int(timeouts.get("agent_sec", 900)),
            build_timeout_sec=int(timeouts.get("build_sec", 900)),
            cpus=resources.get("cpus", 2),
            memory_mb=resources.get("memory_mb", 4096),
            storage_mb=resources.get("storage_mb", 10240),
            reward_type=raw.get("reward_type", "binary"),
            verify_command=raw.get("verify_command", "bash /tests/test.sh"),
            dockerfiles=raw.get("dockerfiles", {}),
            instructions=raw.get("instructions", {}),
            tests=raw.get("tests", {}),
            task_dir=BENCHMARKS_DIR / raw["suite"] / raw["task_id"],
        )


# ---------------------------------------------------------------------------
# Section 4: Sandbox Manager
# ---------------------------------------------------------------------------

class SandboxManager:
    def __init__(self, daytona_client, run_config: RunConfig, credentials: dict):
        self._daytona = daytona_client
        self._config = run_config
        self._creds = credentials

    def create_sandbox(self, task: TaskSpec):
        from daytona_sdk import CreateSandboxFromImageParams, Image, Resources

        dockerfile_name = resolve_dockerfile_name(task, self._config.config_name)
        dockerfile_path = task.task_dir / "environment" / dockerfile_name

        if not dockerfile_path.exists():
            raise FileNotFoundError(f"Missing {dockerfile_path}")

        dockerfile_text = dockerfile_path.read_text()
        env_dir = task.task_dir / "environment"

        needs_context = "COPY " in dockerfile_text or "ADD " in dockerfile_text
        if needs_context:
            image = Image.from_dockerfile(str(dockerfile_path), context_path=str(env_dir))
        else:
            image = Image.from_dockerfile(str(dockerfile_path))

        timeout_sec = self._config.timeout if self._config.timeout > 0 else task.agent_timeout_sec
        lang = task.language if task.language in ("python", "typescript", "javascript") else "python"

        params = CreateSandboxFromImageParams(
            image=image,
            language=lang,
            env_vars=self._build_env_vars(),
            labels={
                "task": task.task_id,
                "suite": task.suite,
                "config": self._config.config_name,
                "run_id": self._config.run_id,
            },
            resources=Resources(
                cpu=task.cpus,
                memory=max(task.memory_mb // 1024, 1),
                disk=max(task.storage_mb // 1024, 10),
            ),
            auto_stop_interval=0,
        )

        sandbox = self._daytona.create(
            params,
            timeout=max(task.build_timeout_sec, 300),
            on_snapshot_create_logs=lambda msg: log.debug(f"[build] {msg}"),
        )
        return sandbox

    def setup_sandbox(self, sandbox, task: TaskSpec) -> None:
        is_mcp = self._config.config_name in MCP_CONFIGS

        # Install Node.js 22
        exec_cmd(
            sandbox,
            "curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.gz "
            "| tar -xz -C /usr/local --strip-components=1 "
            "&& node --version && npm --version",
            "Installing Node.js 22", timeout=120,
        )

        # Install Claude Code CLI
        exec_cmd(
            sandbox,
            "npm install -g @anthropic-ai/claude-code@latest 2>&1 | tail -5 "
            "&& which claude && claude --version",
            "Installing Claude Code", timeout=180,
        )

        # Create claude user (idempotent)
        exec_cmd(sandbox,
            "id -u claude &>/dev/null || useradd -m -s /bin/bash claude 2>/dev/null || true",
            "Creating claude user")

        # Detect workdir and set ownership
        workdir = self._detect_workdir(sandbox)
        exec_cmd(sandbox,
            f"for d in {workdir} /app /testbed /logs /tests /home/claude; do "
            f"[ -d \"$d\" ] && chown -R claude:claude \"$d\"; done 2>/dev/null || true",
            "Setting ownership")

        # Configure authentication
        self._configure_auth(sandbox)

        # MCP config
        if is_mcp and self._creds.get("src_token"):
            self._configure_mcp(sandbox)

        # Directories
        exec_cmd(sandbox, "mkdir -p /logs/agent /logs/verifier /tests", "Creating directories")

        # Upload test files
        self._upload_test_files(sandbox, task)

    def run_agent(self, sandbox, task: TaskSpec) -> dict:
        is_mcp = self._config.config_name in MCP_CONFIGS
        instruction_name = CONFIG_INSTRUCTION_MAP[self._config.config_name]
        instruction_path = task.task_dir / instruction_name

        if not instruction_path.exists():
            raise FileNotFoundError(f"Missing {instruction_path}")

        instruction = instruction_path.read_text()
        workdir = self._detect_workdir(sandbox)

        # Write instruction to sandbox (unique delimiter to avoid content conflicts)
        instr_delim = f"INSTREOF_{hash(task.task_id) & 0xFFFFFF:06x}"
        exec_cmd(sandbox,
            f"cat > /tmp/task_instruction.md << '{instr_delim}'\n{instruction}\n{instr_delim}",
            "Writing instruction")

        # Build and write wrapper script
        script_lines = self._build_agent_script(is_mcp, workdir)
        wrapper = "\n".join(script_lines) + "\n"
        wrap_delim = f"WRAPEOF_{hash(task.task_id) & 0xFFFFFF:06x}"
        exec_cmd(sandbox, f"cat > /tmp/run_claude.sh << '{wrap_delim}'\n{wrapper}\n{wrap_delim}")
        exec_cmd(sandbox, "chmod +x /tmp/run_claude.sh")

        timeout_sec = self._config.timeout if self._config.timeout > 0 else task.agent_timeout_sec

        start = time.time()
        result = exec_cmd(sandbox, "su - claude -c 'bash /tmp/run_claude.sh'",
                          "Running agent", timeout=timeout_sec)
        elapsed = time.time() - start

        cost_usd = None
        num_turns = None
        try:
            parsed = json.loads(result)
            cost_usd = parsed.get("total_cost_usd")
            num_turns = parsed.get("num_turns")
        except (json.JSONDecodeError, TypeError):
            pass

        return {"elapsed_sec": elapsed, "output": result,
                "cost_usd": cost_usd, "num_turns": num_turns}

    def run_verification(self, sandbox, task: TaskSpec) -> dict:
        workdir = self._detect_workdir(sandbox)
        verify_cmd = task.verify_command or "bash /tests/test.sh"

        start = time.time()
        output = exec_cmd(sandbox, f"cd {workdir} && {verify_cmd} 2>&1",
                          "Running verification", timeout=300)
        elapsed = time.time() - start

        reward_raw = exec_cmd(sandbox,
            "cat /logs/verifier/reward.txt 2>/dev/null || echo 'NO_REWARD'")
        reward_str = reward_raw.strip()

        reward = None
        try:
            reward = float(reward_str)
        except (ValueError, TypeError):
            pass

        return {"elapsed_sec": elapsed, "output": output,
                "reward": reward, "reward_raw": reward_str}

    def delete_sandbox(self, sandbox) -> None:
        try:
            self._daytona.delete(sandbox)
        except Exception as e:
            log.warning(f"Failed to delete sandbox {sandbox.id}: {e}")

    # -- Private helpers --

    def _build_env_vars(self) -> dict:
        env = {"DEBIAN_FRONTEND": "noninteractive"}
        if self._config.auth_mode == "api-key" and self._creds.get("anthropic_key"):
            env["ANTHROPIC_API_KEY"] = self._creds["anthropic_key"]
        return env

    def _configure_auth(self, sandbox) -> None:
        if self._config.auth_mode == "oauth" and self._creds.get("oauth_creds"):
            creds_content = self._creds["oauth_creds"]["creds_json"]
            exec_cmd(sandbox,
                f"mkdir -p /home/claude/.claude "
                f"&& cat > /home/claude/.claude/.credentials.json << 'CREDEOF'\n{creds_content}\nCREDEOF",
                "Writing OAuth credentials")
            exec_cmd(sandbox, "rm -f /home/claude/.claude/credentials.json")
        else:
            key = self._creds.get("anthropic_key", "")
            creds_json = json.dumps({"apiKey": key})
            exec_cmd(sandbox,
                f"mkdir -p /home/claude/.claude "
                f"&& echo '{creds_json}' > /home/claude/.claude/credentials.json",
                "Writing API key credentials")
        exec_cmd(sandbox, "chown -R claude:claude /home/claude")

    def _configure_mcp(self, sandbox) -> None:
        mcp_config = {
            "mcpServers": {
                "sourcegraph": {
                    "command": "npx",
                    "args": ["-y", "@sourcegraph/mcp-server"],
                    "env": {
                        "SRC_ACCESS_TOKEN": self._creds["src_token"],
                        "SOURCEGRAPH_URL": "https://sourcegraph.com",
                    },
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

    def _upload_test_files(self, sandbox, task: TaskSpec) -> None:
        tests_dir = task.task_dir / "tests"
        if not tests_dir.exists():
            return
        for test_file in sorted(tests_dir.iterdir()):
            if not test_file.is_file():
                continue
            text = test_file.read_text()
            # Use a unique delimiter to avoid conflicts with file content
            delim = f"CCBEOF_{hash(test_file.name) & 0xFFFFFF:06x}"
            exec_cmd(sandbox,
                f"cat > /tests/{test_file.name} << '{delim}'\n{text}\n{delim}",
                f"Uploading /tests/{test_file.name}")
        exec_cmd(sandbox, "chmod +x /tests/*.sh 2>/dev/null || true",
                 "Making scripts executable")

    def _detect_workdir(self, sandbox) -> str:
        result = exec_cmd(sandbox, "pwd", timeout=10)
        wd = result.strip()
        if wd and wd.startswith("/") and wd != "/":
            return wd
        for candidate in ["/app/repo", "/workspace", "/testbed"]:
            check = exec_cmd(sandbox, f"test -d {candidate} && echo yes || echo no", timeout=10)
            if check.strip() == "yes":
                return candidate
        return "/workspace"

    def _build_agent_script(self, is_mcp: bool, workdir: str) -> List[str]:
        lines = [
            "#!/bin/bash",
            "set -e",
            "export PATH=/usr/local/bin:/usr/bin:/bin:$PATH",
            "export HOME=/home/claude",
            "export CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000",
        ]
        if self._config.auth_mode == "api-key" and self._creds.get("anthropic_key"):
            lines.append(f"export ANTHROPIC_API_KEY={self._creds['anthropic_key']}")
        if self._config.auth_mode == "oauth" and self._creds.get("oauth_creds"):
            lines.append(
                f"export CLAUDE_CODE_OAUTH_TOKEN={self._creds['oauth_creds']['access_token']}")
        if is_mcp and self._creds.get("src_token"):
            lines.append(f"export SRC_ACCESS_TOKEN={self._creds['src_token']}")

        flags = [
            "--dangerously-skip-permissions",
            f"--max-turns {self._config.max_turns}",
            "--output-format json",
        ]
        if is_mcp:
            flags.append("--mcp-config /tmp/.mcp.json")

        lines.append(f"cd {workdir}")
        lines.append(f'claude {" ".join(flags)} -p "$(cat /tmp/task_instruction.md)"')
        return lines


# ---------------------------------------------------------------------------
# Section 5: Task Runner
# ---------------------------------------------------------------------------

class TaskRunner:
    def __init__(self, sandbox_mgr: SandboxManager, collector: "ResultCollector"):
        self._mgr = sandbox_mgr
        self._collector = collector

    def run_task(self, task: TaskSpec, run_config: RunConfig) -> TaskResult:
        result = TaskResult(
            task_id=task.task_id, config=run_config.config_name, run_id=run_config.run_id)

        # Validate Dockerfile exists
        dockerfile_name = resolve_dockerfile_name(task, run_config.config_name)
        if not (task.task_dir / "environment" / dockerfile_name).exists():
            result.status = "skipped"
            result.error_message = f"Missing {dockerfile_name}"
            log.warning(f"[{task.task_id}] Skipped: {result.error_message}")
            self._collector.save_result(result)
            return result

        if run_config.config_name == "baseline-local-artifact" and not baseline_artifact_has_local_repos(task):
            result.status = "skipped"
            result.error_message = "baseline-local-artifact requires local repos, but instruction.md declares none"
            log.warning(f"[{task.task_id}] Skipped: {result.error_message}")
            self._collector.save_result(result)
            return result

        # Validate instruction exists
        instruction_name = CONFIG_INSTRUCTION_MAP[run_config.config_name]
        if not (task.task_dir / instruction_name).exists():
            result.status = "skipped"
            result.error_message = f"Missing {instruction_name}"
            log.warning(f"[{task.task_id}] Skipped: {result.error_message}")
            self._collector.save_result(result)
            return result

        if run_config.dry_run:
            result.status = "dry_run"
            log.info(f"[{task.task_id}] DRY RUN: {dockerfile_name} + {instruction_name}")
            self._collector.save_result(result)
            return result

        sandbox = None
        total_start = time.time()

        try:
            result.status = "running"

            # Phase 1: Create
            log.info(f"[{task.task_id}] Creating sandbox...")
            setup_start = time.time()
            sandbox = self._mgr.create_sandbox(task)
            result.sandbox_id = sandbox.id
            log.info(f"[{task.task_id}] Sandbox: {sandbox.id[:12]}")

            # Phase 2: Setup
            self._mgr.setup_sandbox(sandbox, task)
            result.setup_elapsed_sec = time.time() - setup_start
            log.info(f"[{task.task_id}] Setup done ({result.setup_elapsed_sec:.1f}s)")

            # Phase 3: Agent
            log.info(f"[{task.task_id}] Running agent...")
            agent_result = self._mgr.run_agent(sandbox, task)
            result.agent_elapsed_sec = agent_result["elapsed_sec"]
            result.agent_output = agent_result["output"][:10000]
            result.cost_usd = agent_result.get("cost_usd")
            result.num_turns = agent_result.get("num_turns")
            log.info(f"[{task.task_id}] Agent done ({result.agent_elapsed_sec:.1f}s)")

            # Phase 4: Verify
            log.info(f"[{task.task_id}] Verifying...")
            verify_result = self._mgr.run_verification(sandbox, task)
            result.verify_elapsed_sec = verify_result["elapsed_sec"]
            result.verification_output = verify_result["output"][:5000]
            result.reward = verify_result["reward"]
            result.status = "success" if verify_result["reward"] is not None else "failed"
            log.info(f"[{task.task_id}] Reward: {result.reward}")

        except Exception as e:
            result.status = "error"
            result.error_message = str(e)
            log.error(f"[{task.task_id}] Error: {e}")

        finally:
            result.total_elapsed_sec = time.time() - total_start
            if sandbox:
                log.info(f"[{task.task_id}] Deleting sandbox...")
                self._mgr.delete_sandbox(sandbox)

        self._collector.save_result(result)
        return result

    def run_task_with_retry(self, task: TaskSpec, run_config: RunConfig) -> TaskResult:
        last_result = None
        for attempt in range(run_config.retry_count + 1):
            result = self.run_task(task, run_config)
            result.retry_attempt = attempt
            last_result = result

            if result.status in ("success", "failed", "skipped", "dry_run"):
                return result

            if attempt < run_config.retry_count:
                wait = 10 * (attempt + 1)
                log.warning(f"[{task.task_id}] Attempt {attempt + 1} failed, retry in {wait}s...")
                time.sleep(wait)

        return last_result


# ---------------------------------------------------------------------------
# Section 6: Result Collector
# ---------------------------------------------------------------------------

class ResultCollector:
    def __init__(self, run_dir: Path, run_config: RunConfig):
        self._run_dir = run_dir
        self._run_config = run_config
        self._results: List[TaskResult] = []
        run_dir.mkdir(parents=True, exist_ok=True)

    def save_result(self, result: TaskResult) -> None:
        self._results.append(result)
        task_dir = self._run_dir / result.task_id / result.config
        task_dir.mkdir(parents=True, exist_ok=True)

        (task_dir / "result.json").write_text(
            json.dumps(result.to_dict(), indent=2, default=str))

        if result.agent_output:
            (task_dir / "agent_output.txt").write_text(result.agent_output)
        if result.verification_output:
            (task_dir / "verification_output.txt").write_text(result.verification_output)

    def write_manifest(self, tasks: List[TaskSpec]) -> None:
        rewards = [r.reward for r in self._results if r.reward is not None]
        passed = sum(1 for r in rewards if r > 0)
        mean_reward = sum(rewards) / len(rewards) if rewards else 0.0

        manifest = {
            "run_id": self._run_config.run_id,
            "config": self._run_config.config_name,
            "model": self._run_config.model,
            "auth_mode": self._run_config.auth_mode,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "platform": "daytona",
            "total_tasks": len(tasks),
            "completed": len(self._results),
            "passed": passed,
            "failed": sum(1 for r in rewards if r == 0),
            "errored": sum(1 for r in self._results if r.status == "error"),
            "skipped": sum(1 for r in self._results if r.status == "skipped"),
            "mean_reward": round(mean_reward, 4),
            "total_cost_usd": sum(r.cost_usd for r in self._results if r.cost_usd),
            "tasks": {
                r.task_id: {
                    "status": r.status, "reward": r.reward,
                    "agent_sec": round(r.agent_elapsed_sec, 1),
                    "total_sec": round(r.total_elapsed_sec, 1),
                    "cost_usd": r.cost_usd,
                    "error": r.error_message or None,
                }
                for r in self._results
            },
        }
        (self._run_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str))

    def print_summary(self) -> None:
        print(f"\n{'='*70}")
        print(f"RUN SUMMARY: {self._run_config.run_id}")
        print(f"Config: {self._run_config.config_name} | Model: {self._run_config.model}")
        print(f"{'='*70}\n")

        print(f"{'Task ID':<45} {'Status':<10} {'Reward':<8} {'Time(s)':<10}")
        print(f"{'-'*45} {'-'*10} {'-'*8} {'-'*10}")

        for r in sorted(self._results, key=lambda x: x.task_id):
            reward_str = f"{r.reward:.2f}" if r.reward is not None else "N/A"
            print(f"{r.task_id:<45} {r.status:<10} {reward_str:<8} {r.total_elapsed_sec:<10.1f}")

        rewards = [r.reward for r in self._results if r.reward is not None]
        if rewards:
            print(f"\nMean reward: {sum(rewards) / len(rewards):.4f}")
            print(f"Pass rate:   {sum(1 for r in rewards if r > 0)}/{len(rewards)}")

        errored = sum(1 for r in self._results if r.status == "error")
        skipped = sum(1 for r in self._results if r.status == "skipped")
        if errored:
            print(f"Errors:      {errored}")
        if skipped:
            print(f"Skipped:     {skipped}")


# ---------------------------------------------------------------------------
# Section 7: CLI + main()
# ---------------------------------------------------------------------------

def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="General-purpose Daytona benchmark runner for CodeScaleBench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/daytona_runner.py --task cgen-deps-install-001
  python3 scripts/daytona_runner.py --suite ccb_feature --config mcp-remote-direct
  python3 scripts/daytona_runner.py --all --parallel 4
  python3 scripts/daytona_runner.py --suite ccb_feature --dry-run
  python3 scripts/daytona_runner.py --list-suites
""",
    )

    sel = parser.add_mutually_exclusive_group()
    sel.add_argument("--task", "-t", type=str, help="Run a single task by ID")
    sel.add_argument("--tasks", type=str, help="Comma-separated task IDs")
    sel.add_argument("--suite", "-s", type=str, help="Run all ready tasks in a suite")
    sel.add_argument("--all", action="store_true", help="Run ALL Daytona-ready tasks")
    sel.add_argument("--tasks-file", type=str, help="JSON file with task ID list")

    parser.add_argument("--config", "-c", type=str, default="baseline-local-direct",
        choices=list(CONFIG_DOCKERFILE_MAP.keys()),
        help="Config mode (default: baseline-local-direct)")

    parser.add_argument("--auth", choices=["api-key", "oauth"], default="api-key",
        help="Auth mode (default: api-key)")
    parser.add_argument("--account", type=int, default=1,
        help="OAuth account number (default: 1)")

    parser.add_argument("--parallel", "-p", type=int, default=1,
        help="Max concurrent sandboxes (default: 1)")
    parser.add_argument("--timeout", type=int, default=0,
        help="Override agent timeout seconds (0=task default)")
    parser.add_argument("--retries", type=int, default=1,
        help="Retry count for failed tasks (default: 1)")
    parser.add_argument("--model", type=str, default=CLAUDE_MODEL,
        help=f"Claude model (default: {CLAUDE_MODEL})")
    parser.add_argument("--max-turns", type=int, default=CLAUDE_MAX_TURNS,
        help=f"Max agent turns (default: {CLAUDE_MAX_TURNS})")

    parser.add_argument("--run-id", type=str, default="",
        help="Custom run ID (default: auto-generated)")
    parser.add_argument("--output-dir", type=str, default="",
        help="Custom output directory")

    parser.add_argument("--dry-run", action="store_true",
        help="Validate without creating sandboxes")
    parser.add_argument("--list-suites", action="store_true",
        help="List available suites and exit")
    parser.add_argument("--list-tasks", action="store_true",
        help="List tasks (filter with --suite)")
    parser.add_argument("--list-accounts", action="store_true",
        help="List OAuth accounts and exit")
    parser.add_argument("--verbose", "-v", action="store_true",
        help="Enable debug logging")

    return parser


def main():
    parser = build_cli()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    registry = TaskRegistry()

    # -- Informational modes --

    if args.list_suites:
        suites = registry.list_suites()
        print(f"\n{'Suite':<40} {'Total':>6} {'Ready':>6}")
        print(f"{'-'*40} {'-'*6} {'-'*6}")
        for name in sorted(suites):
            info = suites[name]
            print(f"{name:<40} {info['total']:>6} {info['ready']:>6}")
        total = sum(i["total"] for i in suites.values())
        ready = sum(i["ready"] for i in suites.values())
        print(f"\n{len(suites)} suites, {total} total tasks, {ready} Daytona-ready")
        return

    if args.list_tasks:
        tasks = registry.get_suite(args.suite) if args.suite else registry.get_all_ready()
        print(f"\n{'Task ID':<50} {'Suite':<25} {'Lang':<12} {'Difficulty'}")
        print(f"{'-'*50} {'-'*25} {'-'*12} {'-'*10}")
        for t in sorted(tasks, key=lambda x: x.task_id):
            print(f"{t.task_id:<50} {t.suite:<25} {t.language:<12} {t.difficulty}")
        print(f"\n{len(tasks)} tasks")
        return

    if args.list_accounts:
        accounts = list_oauth_accounts()
        if not accounts:
            print("No OAuth accounts found at ~/.claude-homes/accountN/.claude/.credentials.json")
        else:
            for a in accounts:
                if "error" in a:
                    print(f"  account{a['num']}: ERROR - {a['error']}")
                else:
                    status = f"{a['remaining_min']} min remaining" if a['remaining_min'] > 0 else "EXPIRED"
                    refresh = "has refresh token" if a['has_refresh'] else "NO refresh token"
                    print(f"  account{a['num']}: {status} ({refresh})")
        return

    # -- Resolve tasks --

    tasks: List[TaskSpec] = []
    if args.task:
        spec = registry.get_task(args.task)
        if not spec:
            print(f"ERROR: Task not found: {args.task}")
            sys.exit(1)
        tasks = [spec]
    elif args.tasks:
        for tid in args.tasks.split(","):
            spec = registry.get_task(tid.strip())
            if spec:
                tasks.append(spec)
            else:
                log.warning(f"Task not found: {tid.strip()}")
    elif args.suite:
        tasks = registry.get_suite(args.suite)
    elif getattr(args, "all", False):
        tasks = registry.get_all_ready()
    elif args.tasks_file:
        task_ids = json.loads(Path(args.tasks_file).read_text())
        for tid in task_ids:
            spec = registry.get_task(tid)
            if spec:
                tasks.append(spec)
    else:
        parser.print_help()
        return

    if not tasks:
        print("ERROR: No tasks resolved.")
        sys.exit(1)

    # -- Build run config --

    run_id = args.run_id or f"daytona_{args.config}_{time.strftime('%Y%m%d_%H%M%S')}"
    output_dir = Path(args.output_dir) if args.output_dir else RUNS_DIR / run_id

    run_config = RunConfig(
        run_id=run_id, config_name=args.config, auth_mode=args.auth,
        account_num=args.account, model=args.model, max_turns=args.max_turns,
        parallel=args.parallel, timeout=args.timeout,
        retry_count=args.retries, dry_run=args.dry_run,
    )

    # -- Load credentials --

    credentials: Dict[str, Any] = {
        "anthropic_key": "", "oauth_creds": None,
        "src_token": load_src_access_token(),
    }

    if not args.dry_run:
        daytona_key = load_daytona_api_key()
        if not daytona_key:
            print("ERROR: No Daytona API key. Set DAYTONA_API_KEY or check ~/.config/daytona/env.sh")
            sys.exit(1)

        if args.auth == "oauth":
            try:
                credentials["oauth_creds"] = load_oauth_credentials(args.account)
            except Exception as e:
                print(f"ERROR: OAuth credentials failed: {e}")
                sys.exit(1)
        else:
            credentials["anthropic_key"] = load_anthropic_api_key()
            if not credentials["anthropic_key"]:
                print("ERROR: No Anthropic API key found.")
                sys.exit(1)
    else:
        daytona_key = ""

    # -- Pre-flight summary --

    print(f"\n{'='*60}")
    print(f"DAYTONA RUNNER: {run_id}")
    print(f"{'='*60}")
    print(f"  Config:     {args.config}")
    print(f"  Tasks:      {len(tasks)}")
    print(f"  Parallel:   {args.parallel}")
    auth_info = f"{args.auth}" + (f" (account {args.account})" if args.auth == "oauth" else "")
    print(f"  Auth:       {auth_info}")
    print(f"  Model:      {args.model}")
    print(f"  Retries:    {args.retries}")
    print(f"  Output:     {output_dir}")
    if args.dry_run:
        print(f"  Mode:       DRY RUN")
    print(f"{'='*60}\n")

    # Confirmation gate (per CLAUDE.md policy)
    if not args.dry_run:
        try:
            input("Press Enter to proceed, Ctrl+C to abort... ")
        except KeyboardInterrupt:
            print("\nAborted.")
            return

    # -- Initialize --

    daytona_client = None
    if not args.dry_run:
        from daytona_sdk import Daytona, DaytonaConfig
        daytona_client = Daytona(DaytonaConfig(
            api_key=daytona_key, api_url=DAYTONA_API_URL, target=DAYTONA_TARGET))

    sandbox_mgr = SandboxManager(daytona_client, run_config, credentials)
    collector = ResultCollector(output_dir, run_config)
    runner = TaskRunner(sandbox_mgr, collector)

    # -- Execute --

    try:
        if args.parallel <= 1:
            for task in tasks:
                runner.run_task_with_retry(task, run_config)
        else:
            with ThreadPoolExecutor(max_workers=args.parallel) as executor:
                futures = {
                    executor.submit(runner.run_task_with_retry, task, run_config): task
                    for task in tasks
                }
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        future.result()
                    except Exception as e:
                        log.error(f"[{task.task_id}] Unhandled: {e}")
    except KeyboardInterrupt:
        log.warning("Interrupted - writing partial results...")

    # -- Finalize --

    collector.write_manifest(tasks)
    collector.print_summary()
    print(f"\nResults: {output_dir}")
    print(f"Manifest: {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()

"""OpenHands harness agent wired to Harbor's OpenHands CLI with shared baseline tooling."""

import base64
import json
import logging
import os
import sys
from pathlib import Path

from harbor.agents import utils as harbor_utils
from harbor.agents.installed.base import ExecInput
from harbor.environments.base import BaseEnvironment
from harbor.agents.installed.openhands import OpenHands

from ..base import BaselineHarnessMixin

logger = logging.getLogger(__name__)

# Codex model names (LiteLLM/Harbor don't know these); we map them to OPENAI_API_KEY
# so Harbor's get_api_key_var_names_from_model_name can resolve the key.
_CODEX_MODEL_PREFIXES = ("gpt-5.3-codex", "gpt53codex", "codex")


def _get_api_key_var_names_from_model_name(model_name: str) -> list[str]:
    """Wrap Harbor's resolver so Codex models map to OPENAI_API_KEY or CODEX_API_KEY."""
    lower = (model_name or "").strip().lower()
    if lower in _CODEX_MODEL_PREFIXES or (lower and "codex" in lower and "gpt" in lower):
        if os.environ.get("CODEX_API_KEY"):
            return ["CODEX_API_KEY"]
        if os.environ.get("OPENAI_API_KEY"):
            return ["OPENAI_API_KEY"]
        # Harbor will raise "Unset API variable"; prefer telling user to set CODEX_API_KEY
        return ["CODEX_API_KEY"]
    return _original_get_api_key_var_names(model_name)


# Apply once at import so Harbor's OpenHands sees it. Harbor's openhands.py does
# "from harbor.agents.utils import get_api_key_var_names_from_model_name", so we
# must patch the openhands module's reference too (utils patch alone is not seen there).
_original_get_api_key_var_names = harbor_utils.get_api_key_var_names_from_model_name
harbor_utils.get_api_key_var_names_from_model_name = _get_api_key_var_names_from_model_name
_openhands_mod = sys.modules.get("harbor.agents.installed.openhands")
if _openhands_mod is not None:
    _openhands_mod.get_api_key_var_names_from_model_name = _get_api_key_var_names_from_model_name


def _litellm_codex_model(model_name: str) -> str:
    """Return LiteLLM model string for Codex so the container uses the OpenAI provider."""
    if not model_name or not model_name.strip():
        return model_name
    s = model_name.strip()
    lower = s.lower()
    if lower in _CODEX_MODEL_PREFIXES or ("codex" in lower and "gpt" in lower):
        return f"openai/{s}" if not s.startswith("openai/") else s
    return model_name


class OpenHandsHarnessAgent(BaselineHarnessMixin, OpenHands):
    """OpenHands CLI agent extended with evaluation context and MCP wiring."""

    OPENHANDS_WORKSPACE_PREAMBLE = """## OpenHands Workspace Rules

- The provided working directory is the only submission surface for this evaluation.
- Do not `git clone`, `git init`, or fetch the target repository into the working directory or any of its subdirectories.
- Use MCP to inspect remote code, then create or edit only the files you need directly in the working directory using repository-relative paths.
- The verifier only reads changes from the provided working directory, not from any self-cloned checkout.
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # LiteLLM inside the container needs a provider prefix (e.g. openai/gpt-5.3-codex)
        # or it raises "LLM Provider NOT provided". Normalize Codex models so env LLM_MODEL works.
        if self.model_name:
            self.model_name = _litellm_codex_model(self.model_name)

    # OpenHands spawns persistent background daemons (tmux, jupyter kernel
    # gateway, action execution server) that outlive the main process.  These
    # orphans prevent Daytona's session-command from ever reporting an exit
    # code, which causes Harbor's _poll_response loop to hang indefinitely.
    # We wrap the upstream command so that once the main pipeline exits we
    # kill the leftovers, letting the session terminate cleanly.
    _CLEANUP_SUFFIX = (
        "; _oh_rc=$?; "
        # Kill known OpenHands daemons that outlive the main process
        "pkill -f 'jupyter-kernelgateway' 2>/dev/null; "
        "pkill -f 'ipykernel_launcher' 2>/dev/null; "
        "pkill -f 'openhands.runtime.action_execution_server' 2>/dev/null; "
        "pkill -f 'tmux' 2>/dev/null; "
        "exit $_oh_rc"
    )

    # Path inside the container where the instruction file is written.
    _TASK_FILE = "/tmp/oh_task_instruction.txt"

    @property
    def _install_agent_template_path(self):
        return Path(__file__).with_name("install-openhands.sh.j2")

    def create_run_agent_commands(self, instruction: str):
        instruction = self._resolve_instruction_text(instruction)
        instruction = self._prepare_instruction(instruction)
        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        if (
            mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated")
            and "## OpenHands Workspace Rules" not in instruction
        ):
            instruction = f"{self.OPENHANDS_WORKSPACE_PREAMBLE}\n\n{instruction}"
        self._save_instruction_artifact(instruction)

        # --- Work around Harbor bug: shlex.quote() breaks on instructions
        # containing single quotes, backticks, etc.  Instead of passing the
        # instruction as a shell-quoted CLI argument, we base64-encode it and
        # decode it inside the container to a temp file, then read it back
        # with $(cat ...).  Base64 is shell-safe (no quotes to break). ---
        b64_instruction = base64.b64encode(instruction.encode()).decode()

        # Build env dict the same way upstream OpenHands does, but skip the
        # broken --task= quoting.  We call the parent's method to get env
        # setup, then replace the command that uses shlex.quote.
        upstream_inputs = OpenHands.create_run_agent_commands(self, instruction)

        # The upstream returns 1-2 ExecInputs:
        #   [0] (optional): MCP config.toml write
        #   [-1]: the actual openhands.core.main command (the broken one)
        # We keep everything except the last command and rebuild it.
        env = dict(upstream_inputs[-1].env or {})
        pythonpath = env.get("PYTHONPATH", "")
        if pythonpath:
            filtered = [
                entry
                for entry in pythonpath.split(os.pathsep)
                if entry and os.path.realpath(entry) != os.path.realpath("/workspace")
            ]
            if filtered:
                env["PYTHONPATH"] = os.pathsep.join(filtered)
            else:
                env.pop("PYTHONPATH", None)
        env["PYTHONSAFEPATH"] = "1"
        # Hint to OpenHands config to disable jupyter/browsing.
        # The real fix is the monkey-patch in oh_main_wrapper.py that
        # removes JupyterRequirement from CodeActAgent.sandbox_plugins.
        env["ENABLE_JUPYTER"] = "false"
        env["ENABLE_BROWSING"] = "false"
        env["AGENT_ENABLE_JUPYTER"] = "false"
        env["AGENT_ENABLE_BROWSING"] = "false"

        exec_inputs = upstream_inputs[:-1]  # keep MCP config setup if present

        # Write instruction file via base64 decode (shell-safe, no quoting)
        exec_inputs.append(ExecInput(
            command=f"echo '{b64_instruction}' | base64 -d > {self._TASK_FILE}",
            env=env,
        ))

        # Build a Python launcher script that reads the task from file,
        # runs openhands.core.main, pipes output to a log file, and cleans up
        # orphan daemons. Everything stays in Python — no shell quoting at all.
        runtime_config = self._build_config_toml()
        config_b64 = base64.b64encode(runtime_config.encode()).decode()
        wrapper_source = "\n".join([
            "import importlib.machinery",
            "import importlib.util",
            "import os",
            "import runpy",
            "import sys",
            "",
            "workspace = os.path.realpath('/workspace')",
            "",
            "class _PathGuard(list):",
            "    def _allow(self, value):",
            "        if value is None:",
            "            return False",
            "        candidate = os.getcwd() if value == '' else value",
            "        real = os.path.realpath(candidate)",
            "        return not (real == workspace or real.startswith(workspace + os.sep))",
            "",
            "    def append(self, value):",
            "        if self._allow(value):",
            "            super().append(value)",
            "",
            "    def insert(self, index, value):",
            "        if self._allow(value):",
            "            super().insert(index, value)",
            "",
            "    def extend(self, values):",
            "        super().extend([value for value in values if self._allow(value)])",
            "",
            "_path_guard = _PathGuard()",
            "sys.path = _PathGuard([value for value in sys.path if _path_guard._allow(value)])",
            "",
            "class _WorkspaceSafeFinder(importlib.machinery.PathFinder):",
            "    @classmethod",
            "    def find_spec(cls, fullname, path=None, target=None):",
            "        search = sys.path if path is None else path",
            "        safe_search = [value for value in search if _path_guard._allow(value)]",
            "        return importlib.machinery.PathFinder.find_spec(fullname, safe_search, target)",
            "",
            "def _preload_site_package(name):",
            "    safe_search = [value for value in sys.path if _path_guard._allow(value)]",
            "    spec = importlib.machinery.PathFinder.find_spec(name, safe_search)",
            "    if spec is None or spec.loader is None:",
            "        return",
            "    module = sys.modules.get(name)",
            "    if module is None or getattr(module, '__file__', '').startswith(workspace):",
            "        module = importlib.util.module_from_spec(spec)",
            "        sys.modules[name] = module",
            "        spec.loader.exec_module(module)",
            "",
            "sys.meta_path = [",
            "    _WorkspaceSafeFinder if finder is importlib.machinery.PathFinder else finder",
            "    for finder in sys.meta_path",
            "]",
            "if _WorkspaceSafeFinder not in sys.meta_path:",
            "    sys.meta_path.insert(0, _WorkspaceSafeFinder)",
            "",
            "_preload_site_package('pandas')",
            "",
            "# Strip all sandbox plugins (jupyter, agent_skills).",
            "# jupyter-kernelgateway can't bind in Daytona sandboxes, and",
            "# agent_skills indexes /workspace at startup which times out on large repos.",
            "# We use a preamble for task instructions, so skills aren't needed.",
            "import openhands.agenthub.codeact_agent.codeact_agent as _ca_mod",
            "_ca_mod.CodeActAgent.sandbox_plugins = []",
            "",
            "# Skip init_user_and_working_directory's chown -R on /workspace.",
            "# We already run as root (uid 0) inside Harbor containers, so the",
            "# recursive chown is a no-op that takes >120s on large repos (firefox,",
            "# linux, etc.), causing the action_execution_server to miss its startup",
            "# deadline and the OH client to throw ConnectError.",
            "# The server runs as a SEPARATE subprocess, so we patch the installed",
            "# source file to replace 'chown -R' with a no-op 'true' command.",
            "import glob as _glob",
            "for _ri_path in _glob.glob('/opt/openhands-venv/lib/python*/site-packages/openhands/runtime/utils/runtime_init.py'):",
            "    _ri_src = open(_ri_path).read()",
            "    if 'chown -R' in _ri_src:",
            "        _ri_src = _ri_src.replace('chown -R', 'true #chown -R')",
            "        with open(_ri_path, 'w') as _f: _f.write(_ri_src)",
            "",
            "runpy.run_module('openhands.core.main', run_name='__main__')",
        ])

        launcher_lines = [
            "import base64, os, subprocess, sys",
            "host_workdir = os.getcwd()",
            "os.environ['SANDBOX_VOLUMES'] = host_workdir + ':/workspace:rw'",
            f"task = open('{self._TASK_FILE}').read()",
            "wrapper_path = '/tmp/oh_main_wrapper.py'",
            "with open(wrapper_path, 'w', encoding='utf-8') as f:",
            f"    f.write({wrapper_source!r})",
            "cmd = [sys.executable, '-P', wrapper_path, '--task=' + task]",
        ]
        launcher_lines.extend([
            "config_path = os.path.join(host_workdir, '.openhands-config.toml')",
            f"config_content = base64.b64decode('{config_b64}').decode()",
            "with open(config_path, 'w', encoding='utf-8') as f:",
            "    f.write(config_content)",
            "cmd.append('--config-file=' + config_path)",
        ])
        launcher_lines.extend([
            # Running OpenHands from /workspace lets repo-local top-level packages
            # (for example a task repo named pandas/) shadow installed deps during
            # OpenHands startup. Launch from /tmp and rely on SANDBOX_VOLUMES.
            "os.chdir('/tmp')",
            "log = open('/logs/agent/openhands.txt', 'wb')",
            "proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)",
            "for line in proc.stdout:",
            "    sys.stdout.buffer.write(line)",
            "    sys.stdout.buffer.flush()",
            "    log.write(line)",
            "log.close()",
            "rc = proc.wait()",
            # Kill known OpenHands daemons that outlive the main process
            "import shutil",
            "if shutil.which('pkill'):",
            "    for pat in ['jupyter-kernelgateway', 'ipykernel_launcher', 'openhands.runtime.action_execution_server', 'tmux']:",
            "        subprocess.run(['pkill', '-f', pat], capture_output=True)",
            "else:",
            "    os.system(\"kill $(ps aux | grep -E 'jupyter-kernelgateway|ipykernel_launcher|action_execution_server|tmux' | grep -v grep | awk '{print $2}') 2>/dev/null\")",
            "sys.exit(rc)",
        ])

        launcher_script = "\n".join(launcher_lines)
        launcher_b64 = base64.b64encode(launcher_script.encode()).decode()

        # Write launcher, then execute it — two separate commands to avoid
        # any shell interpretation of the task content.
        launcher_path = "/tmp/oh_launcher.py"
        exec_inputs.append(ExecInput(
            command=f"echo '{launcher_b64}' | base64 -d > {launcher_path}",
            env=env,
        ))

        exec_inputs.append(ExecInput(
            command=f"/opt/openhands-venv/bin/python {launcher_path}",
            env=env,
        ))

        return exec_inputs

    def _build_workspace_guidance(self, workdir: str) -> str:
        guidance = [
            self.OPENHANDS_WORKSPACE_PREAMBLE,
            "",
            "## Working Directory",
            "",
            f"- Create and edit submission files directly under `{workdir}`.",
            "- Keep the final answer artifacts in the provided workspace so the verifier can find them.",
        ]

        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        if mcp_type != "none":
            repo_list = self._get_repo_list()
            if not repo_list:
                repo_list = [self._get_repo_display()]
            repo_lines = "\n".join(f"- `github.com/{repo}`" for repo in repo_list)
            guidance.extend([
                "",
                "## Sourcegraph MCP",
                "",
                "- Use the provided MCP tools before local edits.",
                f"- Scope remote discovery to:\n{repo_lines}",
            ])

        return "\n".join(guidance) + "\n"

    def _build_config_toml(self, mcp_url: str | None = None) -> str:
        lines = [
            "[core]",
            "enable_jupyter = false",
            "enable_browsing = false",
            "",
            "[agent]",
            f"enable_mcp = {'true' if mcp_url else 'false'}",
            "enable_jupyter = false",
            "enable_browsing = false",
        ]
        if mcp_url:
            lines.extend([
                "",
                "[mcp]",
                "shttp_servers = [",
                f'    {{ url = "{mcp_url}", timeout = 300 }}',
                "]",
            ])
        return "\n".join(lines) + "\n"

    async def _upload_workspace_artifacts(
        self,
        environment: BaseEnvironment,
        workdir: str,
        config_toml: str,
    ) -> None:
        config_toml_path = self.logs_dir / "config.toml"
        config_toml_path.write_text(config_toml)
        await environment.upload_file(
            source_path=str(config_toml_path),
            target_path=f"{workdir}/config.toml",
        )

        guidance = self._build_workspace_guidance(workdir)
        guidance_path = self.logs_dir / ".openhands_instructions"
        guidance_path.write_text(guidance)
        await environment.upload_file(
            source_path=str(guidance_path),
            target_path=f"{workdir}/.openhands_instructions",
        )

    # Port for the in-container auth proxy (Sourcegraph needs "token" auth,
    # but OpenHands hardcodes "Bearer").
    _SG_PROXY_PORT = 18973

    async def _configure_mcp(self, environment: BaseEnvironment) -> None:
        """Configure MCP for OpenHands with Sourcegraph auth proxy.

        OpenHands hardcodes 'Authorization: Bearer <token>' for SHTTP, but
        Sourcegraph requires 'Authorization: token <token>'. We solve this by:
        1. Uploading a small HTTP auth proxy (sg_auth_proxy.py) into the container
        2. Starting it as a background daemon on localhost
        3. Pointing OpenHands' config.toml at http://localhost:<port>
        """
        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        workdir = await self._detect_workdir(environment)
        if mcp_type == "none":
            await self._upload_workspace_artifacts(
                environment,
                workdir,
                self._build_config_toml(),
            )
            return

        sg_url = (
            os.environ.get("SOURCEGRAPH_URL")
            or os.environ.get("SRC_ENDPOINT")
            or "https://sourcegraph.sourcegraph.com"
        )
        sg_token = (
            os.environ.get("SOURCEGRAPH_ACCESS_TOKEN")
            or os.environ.get("SRC_ACCESS_TOKEN")
            or ""
        )
        if not sg_token:
            logger.warning("SOURCEGRAPH_ACCESS_TOKEN not set; skipping OpenHands MCP")
            return
        if not sg_url.startswith(("http://", "https://")):
            sg_url = f"https://{sg_url}"
        sg_url = sg_url.rstrip("/")

        mcp_endpoint = f"{sg_url}/.api/mcp"

        # --- Upload and start the auth proxy ---
        proxy_src = os.path.join(os.path.dirname(__file__), "sg_auth_proxy.py")
        await environment.upload_file(
            source_path=proxy_src,
            target_path="/tmp/sg_auth_proxy.py",
        )
        # Ensure python3 is available (Java/Go images may not have it)
        ensure_python = (
            "command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || { "
            "(apt-get update && apt-get install -y --no-install-recommends python3) 2>/dev/null || "
            "(apk add --no-cache python3) 2>/dev/null || "
            "(yum install -y python3) 2>/dev/null || true; }"
        )
        await environment.exec(ensure_python)

        # Start proxy as background daemon (try python3, fall back to python)
        start_cmd = (
            f"SG_MCP_URL={mcp_endpoint} "
            f"SG_MCP_TOKEN={sg_token} "
            f"nohup $(command -v python3 || command -v python) /tmp/sg_auth_proxy.py --port {self._SG_PROXY_PORT} "
            f"> /tmp/sg_proxy.log 2>&1 &"
        )
        await environment.exec(start_cmd)
        # Wait briefly for proxy to start
        await environment.exec("sleep 1")
        result = await environment.exec(
            f"curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{self._SG_PROXY_PORT}/ || echo 'proxy_down'"
        )
        proxy_status = (result.stdout or "").strip()
        if "proxy_down" in proxy_status:
            logger.error("Auth proxy failed to start. Log: %s",
                        (await environment.exec("cat /tmp/sg_proxy.log")).stdout)
            return
        logger.info("Auth proxy running on port %d (status: %s)", self._SG_PROXY_PORT, proxy_status)

        # --- config.toml pointing at local proxy (no api_key needed) ---
        local_url = f"http://127.0.0.1:{self._SG_PROXY_PORT}"
        await self._upload_workspace_artifacts(
            environment,
            workdir,
            self._build_config_toml(mcp_url=local_url),
        )

        # Also set env vars as backup
        servers = [{"url": local_url, "timeout": 300}]
        os.environ["OPENHANDS_MCP_SHTTP_SERVERS"] = repr(servers)
        os.environ["OPENHANDS_AGENT_ENABLE_MCP"] = "true"

        # Save debug artifacts
        mcp_json = {
            "mcpServers": {
                "sourcegraph": {
                    "type": "http",
                    "url": f"{sg_url}/.api/mcp/v1",
                    "headers": {"Authorization": f"token {sg_token}"},
                }
            }
        }
        artifact_path = self.logs_dir / ".mcp.json"
        artifact_path.write_text(json.dumps(mcp_json, indent=2))
        logger.info("OpenHands MCP configured via auth proxy -> %s", mcp_endpoint)

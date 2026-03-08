"""OpenHands harness agent wired to Harbor's OpenHands CLI with shared baseline tooling."""

import base64
import json
import logging
import os
import shlex

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
import sys
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
        env = upstream_inputs[-1].env or {}

        exec_inputs = upstream_inputs[:-1]  # keep MCP config setup if present

        # Write instruction file via base64 decode (shell-safe, no quoting)
        exec_inputs.append(ExecInput(
            command=f"echo '{b64_instruction}' | base64 -d > {self._TASK_FILE}",
            env=env,
        ))

        # Build the openhands command reading task from file
        mcp_config = self._build_mcp_config_toml()
        config_file_path = "~/.openhands/config.toml"

        commands = [
            "SANDBOX_VOLUMES=${PWD}:/workspace:rw",
            "/opt/openhands-venv/bin/python -m openhands.core.main",
            f'--task="$(cat {self._TASK_FILE})"',
        ]
        if mcp_config:
            commands.append(f"--config-file={config_file_path}")

        main_cmd = (
            " ".join(commands)
            + " 2>&1 </dev/null | stdbuf -oL tee /logs/agent/openhands.txt"
        )

        exec_inputs.append(ExecInput(
            command=f"{{ {main_cmd} }}{self._CLEANUP_SUFFIX}",
            env=env,
        ))

        return exec_inputs

    def _build_workspace_guidance(self, workdir: str) -> str:
        repo_list = self._get_repo_list()
        if not repo_list:
            repo_list = [self._get_repo_display()]
        repo_lines = "\n".join(f"- `github.com/{repo}`" for repo in repo_list)
        return (
            f"{self.OPENHANDS_WORKSPACE_PREAMBLE}\n\n"
            "## Sourcegraph MCP\n\n"
            "- Use the provided MCP tools before local edits.\n"
            f"- Scope remote discovery to:\n{repo_lines}\n"
            f"- Write your final file edits directly under `{workdir}` using repository-relative paths.\n"
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
        if mcp_type == "none":
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
        workdir = await self._detect_workdir(environment)

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
        config_toml = (
            "[agent]\n"
            "enable_mcp = true\n"
            "\n"
            "[mcp]\n"
            "shttp_servers = [\n"
            f'    {{ url = "{local_url}", timeout = 300 }}\n'
            "]\n"
        )
        config_toml_path = self.logs_dir / "config.toml"
        config_toml_path.write_text(config_toml)
        await environment.upload_file(
            source_path=str(config_toml_path),
            target_path=f"{workdir}/config.toml",
        )

        # Also set env vars as backup
        servers = [{"url": local_url, "timeout": 300}]
        os.environ["OPENHANDS_MCP_SHTTP_SERVERS"] = repr(servers)
        os.environ["OPENHANDS_AGENT_ENABLE_MCP"] = "true"

        # Upload guidance through OpenHands' native workspace instruction file.
        guidance = self._build_workspace_guidance(workdir)
        guidance_path = self.logs_dir / ".openhands_instructions"
        guidance_path.write_text(guidance)
        await environment.upload_file(
            source_path=str(guidance_path),
            target_path=f"{workdir}/.openhands_instructions",
        )

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

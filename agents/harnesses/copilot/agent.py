"""Copilot harness agent that runs the GitHub Copilot CLI with our baseline guidance."""

import logging
import os
import shlex
from pathlib import Path

import yaml
from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

from ..base import BaselineHarnessMixin


logger = logging.getLogger(__name__)


class CopilotCliAgent(BaseInstalledAgent):
    """Minimal Copilot CLI wrapper that surfaces the CLI output path."""

    SUPPORTS_ATIF = False
    _OUTPUT_FILENAME = "copilot.log"

    @staticmethod
    def name() -> str:
        return "copilot-cli"

    def version(self) -> str | None:
        return os.environ.get("COPILOT_CLI_VERSION") or "custom"

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-copilot.sh.j2"

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        token = self._resolve_token()
        if not token:
            raise RuntimeError(
                "Copilot CLI requires COPILOT_GITHUB_TOKEN, GH_TOKEN, GITHUB_TOKEN, "
                "or a valid token in ~/.config/gh/hosts.yml"
            )

        env = {
            "COPILOT_GITHUB_TOKEN": token,
            "GH_TOKEN": token,
            "GITHUB_TOKEN": token,
        }
        env.update(
            {
                k: v
                for k, v in os.environ.items()
                if k.startswith("COPILOT_") and k not in env
            }
        )

        if model := os.environ.get("COPILOT_MODEL"):
            model_flag = f"--model {shlex.quote(model)} "
        else:
            model_flag = ""

        escaped_instruction = shlex.quote(instruction.strip())
        log_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME

        command = (
            f"set -euo pipefail && "
            f"copilot --prompt {escaped_instruction} "
            f"{model_flag}"
            f"--format markdown "
            f"--log-level info "
            f"--log {log_path} "
            "| tee "
            f"{log_path}"
        )

        return [
            ExecInput(command=command, env=env),
        ]

    def _resolve_token(self) -> str | None:
        """Return the first available Copilot token from env vars or GH hosts file."""
        for key in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            if value := os.environ.get(key):
                return value

        hosts_path = Path(
            os.environ.get("GH_HOSTS_FILE", Path.home() / ".config/gh/hosts.yml")
        )
        if not hosts_path.exists():
            return None

        try:
            data = yaml.safe_load(hosts_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read GH hosts file %s: %s", hosts_path, exc)
            return None

        if not isinstance(data, dict):
            return None

        host_entry = data.get("github.com") or {}
        if isinstance(host_entry, dict):
            oauth_token = host_entry.get("oauth_token")
            if isinstance(oauth_token, str):
                return oauth_token

        return None

    def populate_context_post_run(self, context: AgentContext) -> None:
        log_path = EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME
        if log_path.exists():
            context.metadata.setdefault("copilot", {})["log_path"] = str(log_path)


class CopilotHarnessAgent(BaselineHarnessMixin, CopilotCliAgent):
    """Copilot CLI agent wired to the baseline MCP and evaluation guidance."""

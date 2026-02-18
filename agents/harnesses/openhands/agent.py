"""OpenHands harness agent wired to Harbor's OpenHands CLI with shared baseline tooling."""

import os

from harbor.agents import utils as harbor_utils
from harbor.agents.installed.openhands import OpenHands

from ..base import BaselineHarnessMixin

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


class OpenHandsHarnessAgent(BaselineHarnessMixin, OpenHands):
    """OpenHands CLI agent extended with evaluation context and MCP wiring."""

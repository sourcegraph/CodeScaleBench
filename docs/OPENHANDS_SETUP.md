# OpenHands Harness Setup

This document covers installing and configuring the OpenHands harness so you can run it with a Gemini-backed model (or other providers). It addresses the `openhands-tools` dependency resolution and how to confirm which Gemini models your API key supports.

## Dependency: openhands-tools

The OpenHands main package ([All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands)) pins:

- `openhands-tools==1.11.4`
- `openhands-sdk==1.11.4`
- `openhands-agent-server==1.11.4`

**openhands-tools 1.11.4 is published on PyPI** (see [pypi.org/project/openhands-tools](https://pypi.org/project/openhands-tools/)). If `pip install git+https://github.com/All-Hands-AI/OpenHands.git` fails with "No matching distribution found for openhands-tools==1.11.4", the usual cause is:

1. **Python version** — OpenHands and openhands-tools require **Python >=3.12**. Use `python3 --version` and ensure you are on 3.12 or 3.13 (OpenHands also constrains &lt;3.14).
2. **Install order** — Resolving from the git repo in one step can hit resolution order issues. Install the pinned SDK/tools first, then OpenHands:
   ```bash
   pip install "openhands-tools==1.11.4" "openhands-sdk==1.11.4" "openhands-agent-server==1.11.4"
   pip install "openhands-ai @ git+https://github.com/All-Hands-AI/OpenHands.git"
   ```
   Or use a constraints file so pip satisfies the pins before building OpenHands from source.
3. **Venv / isolated env** — Prefer a dedicated virtualenv with Python 3.12+ so system or other-project packages do not conflict.

### Alternative: install from OpenHands clone with Poetry

OpenHands uses Poetry. If you clone the repo and have Poetry available:

```bash
git clone https://github.com/All-Hands-AI/OpenHands.git
cd OpenHands
poetry install
```

Then run the CodeContextBench harness with the agent path pointing at your in-repo agent; the Harbor OpenHands agent expects the `openhands` package to be importable in the same environment where Harbor runs.

### Vendoring openhands-tools

We do not vendor openhands-tools in CodeContextBench. The harness imports `harbor.agents.installed.openhands.OpenHands`; Harbor and OpenHands must be installed in the environment that runs the benchmark (e.g. the host or the image that runs `harbor run`). If you need a fully offline or vendored setup, you would:

- Clone [OpenHands/software-agent-sdk](https://github.com/OpenHands/software-agent-sdk) (the upstream for openhands-tools on PyPI), check out the tag that corresponds to 1.11.4, and install from that clone, or
- Use a private PyPI mirror that has openhands-tools 1.11.4.

## Gemini model availability

OpenHands (via LiteLLM) and the CodeContextBench Gemini harness use **GEMINI_API_KEY** or **GOOGLE_API_KEY** for the Gemini API. Not every key has access to every model; requesting a model your key cannot use yields a 404-style "Model not found" error.

To see which models your key can use and to verify a specific model:

1. **List models** (uses the same env vars as the harness):
   ```bash
   export GEMINI_API_KEY='your-key'   # or GOOGLE_API_KEY
   python3 scripts/list_gemini_models.py
   ```
   Or JSON: `python3 scripts/list_gemini_models.py --json`

2. **Test a specific model** before running the harness:
   ```bash
   python3 scripts/list_gemini_models.py --test-model gemini-2.0-flash
   ```
   Use the short name (e.g. `gemini-2.0-flash`, `gemini-1.5-pro`). If the key does not have access, you get a clear failure message.

3. **Run OpenHands with Gemini** — Once you know a working model id, pass it to the OpenHands 2-config runner:
   ```bash
   MODEL=gemini-2.0-flash ./configs/openhands_2config.sh [OPTIONS]
   ```
   The harness registry default for OpenHands is `anthropic/claude-opus-4-6`; override with `MODEL` for Gemini (e.g. `gemini-2.0-flash` or the litellm-style name your OpenHands/LiteLLM expects).

**Note:** The Gemini *list* API may return all public models; access still depends on your key and quota. Use `--test-model` to confirm a given model works before running a full benchmark.

## OpenHands with Codex (gpt-5.3-codex)

The OpenHands harness supports the Codex model. Harbor’s built-in resolver does not know `gpt-5.3-codex`, so we patch it in `agents/harnesses/openhands/agent.py`: Codex model names resolve to **CODEX_API_KEY** or **OPENAI_API_KEY** (whichever is set). Set one of them before running:

```bash
export CODEX_API_KEY='your-codex-key'   # or OPENAI_API_KEY
MODEL=gpt-5.3-codex ./configs/openhands_2config.sh --benchmark ccb_test --task openhands-search-file-test-001 --baseline-only
```

## References

- OpenHands pyproject: [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) (main branch)
- openhands-tools on PyPI: [openhands-tools](https://pypi.org/project/openhands-tools/) (source: OpenHands/software-agent-sdk)
- Harness config: `configs/openhands_2config.sh`, `configs/harness_registry.json`
- Agent: `agents/harnesses/openhands/agent.py` (wires BaselineHarnessMixin + Harbor OpenHands)

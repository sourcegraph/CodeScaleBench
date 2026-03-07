import json
import logging
import os
import re
from pathlib import Path

from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)


class BaselineHarnessMixin:
    """Shared evaluation context, MCP wiring, and instruction handling."""

    # Path used by the Claude-specific template; remains available for fallback content.
    LOCOBENCH_CLAUDE_MD_TEMPLATE = Path(
        "/home/stephanie_jarmak/CodeScaleBench/benchmarks/locobench_agent/templates/CLAUDE.md"
    )

    EVALUATION_CONTEXT_PROMPT = """## EVALUATION CONTEXT

You are being evaluated on a software engineering task. Your performance will be measured by:
- Whether the existing test suite COMPILES without errors
- Whether the failing tests PASS after your implementation
- Whether you implement the EXACT interface that the tests expect

**CRITICAL: You MUST run the test suite BEFORE making any code changes.**

The test compilation errors and failures tell you exactly what interfaces, method names, and types to implement. If you implement code before running tests, you will guess wrong about method names and fail the evaluation.

**Required workflow:**
1. FIRST: Run the full test suite to see compilation errors and failures
2. THEN: Read the test files to understand exact interface requirements
3. THEN: Implement the fix matching the exact interface from tests
4. FINALLY: Run tests again to verify they pass
"""

    SG_TOOL_REFERENCE = """# Sourcegraph MCP Tools

Available tools for searching the remote repository:

- `keyword_search` — exact keyword/pattern search across files. Use `repo:^<repo>$` filter.
- `nls_search` — semantic/fuzzy search (broader matching, good for exploratory queries)
- `read_file` — read file contents from the indexed repository
- `list_files` — list directory contents
- `list_repos` — search and list available repositories
- `go_to_definition` — jump to a symbol's definition
- `find_references` — find all usages of a symbol
- `commit_search` — search commit history by message, author, or content
- `diff_search` — search code changes (added/removed lines)
- `compare_revisions` — compare two branches/commits/tags
- `deepsearch` — AI-powered deep analysis (async: returns a polling link)
- `deepsearch_read` — read Deep Search results (call 60+ seconds after deepsearch)
"""

    V4_PREAMBLE_TEMPLATE = """# Searching Sourcegraph

{repo_scope}

## Tool Selection Logic

**Start here:**

1. **Know the exact symbol or pattern?** → `sg_keyword_search`
2. **Know the concept, not the code?** → `sg_nls_search`
3. **Need to understand how/why?** → `sg_deepsearch_read`
4. **Tracing a symbol's usage?** → `sg_find_references`
5. **Need the implementation?** → `sg_go_to_definition`

Use repo/file filters to keep results focused. Start narrow and widen only when needed.
"""

    def __init__(self, *args, **kwargs):
        self._container_env_cache: dict[str, str] = {}
        super().__init__(*args, **kwargs)

    def create_run_agent_commands(self, instruction: str):
        instruction = self._resolve_instruction_text(instruction)
        instruction = self._prepare_instruction(instruction)
        self._save_instruction_artifact(instruction)
        return super().create_run_agent_commands(instruction)

    async def setup(self, environment: BaseEnvironment) -> None:
        await self._propagate_container_env(environment)
        await self._configure_mcp(environment)
        await super().setup(environment)

    def _save_instruction_artifact(self, instruction: str) -> None:
        try:
            path = self.logs_dir / "instruction.txt"
            path.write_text(instruction)
        except Exception as exc:
            logger.warning("Could not save instruction artifact: %s", exc)

    def _prepare_instruction(self, instruction: str) -> str:
        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        repo = self._get_repo_display()
        repo_list = self._get_repo_list()

        if mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated") and (
            instruction.lstrip().startswith("# IMPORTANT: Source Code Access")
            or instruction.lstrip().startswith("## EVALUATION CONTEXT")
        ):
            return instruction

        parts = [self.EVALUATION_CONTEXT_PROMPT.strip()]

        if mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated"):
            if repo_list:
                scope_lines = ["**Target Repositories (version-pinned mirrors):**\n"]
                for repo_name in repo_list:
                    sg_full = f"github.com/{repo_name}"
                    scope_lines.append(f"- `{sg_full}` — use `repo:^{sg_full}$` filter")
                scope_lines.append("")
                scope_lines.append("Scope all search queries to these repos.")
                scope = "\n".join(scope_lines)
            else:
                scope = (
                    f"**Target Repository:** `github.com/{repo}`\n"
                    f"- Include `repo:^github.com/{repo}$` filters in keyword_search"
                )
            parts.append(self.V4_PREAMBLE_TEMPLATE.format(repo_scope=scope))
        elif mcp_type == "sourcegraph":
            parts.append("## Sourcegraph MCP Guidance")
            parts.append(f"Working repo: `{repo}`")
            parts.append(self.SG_TOOL_REFERENCE)
        elif mcp_type == "deepsearch":
            parts.append("## Deep Search Guidance")
            parts.append(f"Search `sg-evals/{repo}` with Deep Search when you need cross-file understanding")
        elif mcp_type == "deepsearch_hybrid":
            parts.append("## Deep Search Hybrid Guidance")
            parts.append("Use Deep Search for semantic exploration and local tools for verification.")

        return "\n\n".join(parts) + "\n\n" + instruction

    def _get_repo_display(self) -> str:
        cache = self._container_env_cache
        sg_repo = os.environ.get("SOURCEGRAPH_REPO_NAME", "") or cache.get("SOURCEGRAPH_REPO_NAME", "")
        if sg_repo:
            if sg_repo.startswith("github.com/"):
                return sg_repo[len("github.com/") :]
            return sg_repo

        repo_list = self._get_repo_list()
        if repo_list:
            return repo_list[0]

        locobench = cache.get("LOCOBENCH_PROJECT_ID") or os.environ.get("LOCOBENCH_PROJECT_ID", "")
        if locobench:
            return f"sg-evals/locobench-{locobench}"

        swebench = cache.get("SWEBENCH_REPO_COMMIT") or os.environ.get("SWEBENCH_REPO_COMMIT", "")
        if swebench:
            return f"sg-evals/{swebench}"

        return "the codebase"

    def _get_repo_list(self) -> list[str]:
        cache = self._container_env_cache
        repos_str = os.environ.get("SOURCEGRAPH_REPOS", "") or cache.get("SOURCEGRAPH_REPOS", "")
        if not repos_str:
            repos_str = self._parse_sourcegraph_repos_from_dockerfile()
        if not repos_str:
            return []
        return [r.strip() for r in repos_str.split(",") if r.strip()]

    def _parse_sourcegraph_repos_from_dockerfile(self) -> str:
        task_source_dir = os.environ.get("TASK_SOURCE_DIR", "")
        if not task_source_dir:
            return ""

        env_dir = Path(task_source_dir) / "environment"
        if not env_dir.is_dir():
            return ""

        for df_name in ("Dockerfile.artifact_only", "Dockerfile.sg_only", "Dockerfile"):
            df_path = env_dir / df_name
            if not df_path.is_file():
                continue
            try:
                for line in df_path.read_text().splitlines():
                    match = re.match(r'^ENV\s+SOURCEGRAPH_REPOS\s*=\s*"([^"]+)"', line)
                    if match:
                        logger.info("Dockerfile fallback: SOURCEGRAPH_REPOS=%s from %s", match.group(1), df_name)
                        return match.group(1)
            except OSError:
                continue
        return ""

    def _resolve_instruction_text(self, instruction: str) -> str:
        task_source_dir = os.environ.get("TASK_SOURCE_DIR", "")
        if not task_source_dir:
            return instruction

        task_source_path = Path(task_source_dir)
        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        instruction_variant = os.environ.get("INSTRUCTION_VARIANT", "default").lower()

        if mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated"):
            mcp_instruction = task_source_path / "instruction_mcp.md"
            if mcp_instruction.exists():
                logger.info("Using MCP instruction from %s", mcp_instruction)
                return mcp_instruction.read_text()

        if instruction_variant != "default":
            variant_candidates = [instruction_variant]
            if "_" in instruction_variant:
                base_variant = instruction_variant.split("_", 1)[0]
                if base_variant and base_variant not in variant_candidates:
                    variant_candidates.append(base_variant)

            for candidate in variant_candidates:
                variant_path = task_source_path / f"instruction_{candidate}.md"
                if variant_path.exists():
                    logger.info("Using instruction variant %s from %s", candidate, variant_path)
                    return variant_path.read_text()

            logger.warning(
                "Instruction variant '%s' not found in %s (tried: %s), using provided instruction",
                instruction_variant,
                task_source_dir,
                ", ".join(variant_candidates),
            )

        return instruction

    async def _propagate_container_env(self, environment: BaseEnvironment) -> None:
        if os.environ.get("BASELINE_MCP_TYPE", "none").lower() == "none":
            return
        cache = {}
        for var in ("SOURCEGRAPH_REPO_NAME", "SOURCEGRAPH_REPOS", "LOCOBENCH_PROJECT_ID", "SWEBENCH_REPO_COMMIT"):
            if os.environ.get(var):
                continue
            try:
                result = await environment.exec(f"echo ${{{var}:-}}")
            except Exception:
                continue
            lines = (result.stdout or "").strip().splitlines()
            for line in lines:
                line = line.strip()
                if not line or line.startswith("bash:"):
                    continue
                cache[var] = line
                break
        self._container_env_cache = cache

    async def _configure_mcp(self, environment: BaseEnvironment) -> None:
        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        if mcp_type == "sourcegraph":
            await self._setup_sourcegraph_mcp(environment)
        elif mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated"):
            await self._setup_sourcegraph_full_mcp(environment)
        elif mcp_type == "deepsearch":
            await self._setup_deepsearch_mcp(environment)
        elif mcp_type == "deepsearch_hybrid":
            await self._setup_deepsearch_hybrid_mcp(environment)

    async def _setup_sourcegraph_mcp(self, environment: BaseEnvironment) -> None:
        await environment.exec("mkdir -p /logs/agent/sessions")
        sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
        sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""
        if not sg_token:
            logger.warning("SOURCEGRAPH_ACCESS_TOKEN not set; skipping Sourcegraph MCP configuration")
            return
        if not sg_url.startswith(("http://", "https://")):
            sg_url = f"https://{sg_url}"
        sg_url = sg_url.rstrip("/")

        config = {
            "mcpServers": {
                "sourcegraph": {
                    "type": "http",
                    "url": f"{sg_url}/.api/mcp/v1",
                    "headers": {"Authorization": f"token {sg_token}"},
                }
            }
        }

        path = self.logs_dir / ".mcp.json"
        path.write_text(json.dumps(config, indent=2))
        await environment.upload_file(
            source_path=str(path), target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info("Registered Sourcegraph MCP config")

        workdir = await self._detect_workdir(environment)
        claude_md = "## Sourcegraph MCP\nUse the provided MCP tools before local edits."
        claude_md_path = self.logs_dir / "CLAUDE.md"
        claude_md_path.write_text(claude_md)
        await environment.upload_file(
            source_path=str(claude_md_path), target_path=f"{workdir}/CLAUDE.md"
        )

    async def _setup_sourcegraph_full_mcp(self, environment: BaseEnvironment) -> None:
        await self._setup_sourcegraph_mcp(environment)

    async def _setup_deepsearch_mcp(self, environment: BaseEnvironment) -> None:
        await environment.exec("mkdir -p /logs/agent/sessions")
        deepsearch_url = os.environ.get("DEEPSEARCH_MCP_URL") or ""
        deepsearch_token = os.environ.get("DEEPSEARCH_MCP_TOKEN") or ""
        if not deepsearch_url:
            sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
            sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""
            if sg_token:
                if not sg_url.startswith(("http://", "https://")):
                    sg_url = f"https://{sg_url}"
                deepsearch_url = f"{sg_url.rstrip('/')}/.api/mcp/deepsearch"
                deepsearch_token = sg_token
        if not deepsearch_url or not deepsearch_token:
            logger.warning("Deep Search MCP credentials missing; skipping configuration")
            return
        if not deepsearch_url.startswith(("http://", "https://")):
            deepsearch_url = f"https://{deepsearch_url}"
        deepsearch_url = deepsearch_url.rstrip("/")

        config = {
            "mcpServers": {
                "deepsearch": {
                    "type": "http",
                    "url": deepsearch_url,
                    "headers": {"Authorization": f"token {deepsearch_token}"},
                }
            }
        }

        path = self.logs_dir / ".mcp.json"
        path.write_text(json.dumps(config, indent=2))
        await environment.upload_file(
            source_path=str(path), target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info("Registered Deep Search MCP config")

    async def _setup_deepsearch_hybrid_mcp(self, environment: BaseEnvironment) -> None:
        await self._setup_deepsearch_mcp(environment)

    async def _detect_workdir(self, environment: BaseEnvironment) -> str:
        for candidate in ("/workspace", "/app", "/testbed"):
            result = await environment.exec(f'[ -d {candidate} ] && echo EXISTS')
            if result.stdout and "EXISTS" in result.stdout:
                return candidate
        return "/workspace"

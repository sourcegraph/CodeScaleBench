"""MCP Agent implementations for Sourcegraph integration.

Two variants for testing MCP tool effectiveness:
1. SourcegraphMCPAgent - Full Sourcegraph MCP v1 with all tools
2. DeepSearchMCPAgent - Dedicated Deep Search MCP endpoint

Reference: mcp_variants.py for A/B testing patterns
"""

import json
import logging
import os
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.installed.base import ExecInput
from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hard-coded MCP endpoints
# ---------------------------------------------------------------------------

SOURCEGRAPH_MCP_V1 = "https://sourcegraph.sourcegraph.com/.api/mcp/v1"
SOURCEGRAPH_MCP_DEEPSEARCH = (
    "https://sourcegraph.sourcegraph.com/.api/mcp/deepsearch"
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def require_token() -> str:
    """Get Sourcegraph access token from environment."""
    token = (
        os.environ.get("SOURCEGRAPH_ACCESS_TOKEN")
        or os.environ.get("SRC_ACCESS_TOKEN")
        or ""
    )
    if not token:
        raise RuntimeError(
            "SOURCEGRAPH_ACCESS_TOKEN or SRC_ACCESS_TOKEN must be set"
        )
    return token


def write_mcp_config(
    path: Path,
    name: str,
    url: str,
    token: str,
) -> None:
    """Write MCP configuration file."""
    config = {
        "mcpServers": {
            name: {
                "type": "http",
                "url": url,
                "headers": {
                    "Authorization": f"token {token}"
                },
            }
        }
    }
    path.write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Sourcegraph MCP Agent (standard MCP endpoint)
# ---------------------------------------------------------------------------

class SourcegraphMCPAgent(ClaudeCode):
    """Sourcegraph MCP agent with full tool suite.

    Uses Sourcegraph MCP v1 endpoint with all available tools:
    - sg_keyword_search: Fast exact string matching
    - sg_nls_search: Natural language semantic search
    - sg_read_file: Read file from indexed repo
    - sg_list_repos: List available repositories
    - sg_list_files: Find files by pattern
    - sg_go_to_definition: Navigate to symbol definitions
    - sg_commit_search: Search commit history

    System prompt and CLAUDE.md guide the agent to use MCP tools
    effectively for codebase exploration before making changes.
    """

    SYSTEM_PROMPT = """You MUST complete this coding task by making actual code changes.

## CRITICAL: Use Sourcegraph MCP Tools

You have access to **Sourcegraph MCP** tools for code exploration. These tools search across the entire indexed codebase and understand code relationships.

### Available MCP Tools (use the mcp__ prefix)

- `mcp__sourcegraph__sg_keyword_search` - **Fast exact string matching** across the codebase
- `mcp__sourcegraph__sg_nls_search` - **Natural language semantic search** for conceptual queries
- `mcp__sourcegraph__sg_read_file` - Read file contents from indexed repository
- `mcp__sourcegraph__sg_list_files` - Find files by pattern
- `mcp__sourcegraph__sg_list_repos` - List available repositories
- `mcp__sourcegraph__sg_go_to_definition` - Navigate to symbol definitions
- `mcp__sourcegraph__sg_commit_search` - Search commit history

### WHEN to use MCP Tools

1. **At Task Start**: Use MCP to understand the codebase structure
   - `sg_keyword_search` for function/class names, error messages
   - `sg_nls_search` for conceptual questions ("how does auth work")

2. **For Cross-File Understanding**: MCP sees relationships across files
   - Finding all usages of a function
   - Tracing data flow
   - Understanding component interactions

3. **When Local Search Isn't Enough**: For large codebases, MCP is faster

### WHEN to use Local Tools

- `Read` - For files you've already identified
- `Edit` - For making code changes
- `Bash` - For running commands and tests
- `Grep` - For narrow, single-directory searches

### Recommended Workflow

1. **START**: Use MCP tools to explore and understand the problem
2. **IDENTIFY**: Find the relevant files using MCP search
3. **READ**: Use local Read to examine specific files
4. **IMPLEMENT**: Make targeted code changes with Edit
5. **TEST**: Run tests to verify your changes

## Implementation Requirements

This is not a planning task. You must:
1. Use MCP tools to understand the codebase
2. Locate all relevant code
3. MAKE ACTUAL CODE CHANGES to implement the fix or feature
4. Test your implementation

CRITICAL: You must make actual code modifications. The task is complete only when code files have been changed.
"""

    CLAUDE_MD = """# MANDATORY: Use Sourcegraph MCP Tools

## YOU MUST USE MCP TOOLS FOR CODE EXPLORATION

You have Sourcegraph MCP tools configured. **Use these tools to explore the codebase before making changes.**

## Available MCP Tools (use exactly these names)

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `mcp__sourcegraph__sg_keyword_search` | Exact string matching | Function names, error messages, imports |
| `mcp__sourcegraph__sg_nls_search` | Natural language search | "How does X work?", conceptual queries |
| `mcp__sourcegraph__sg_read_file` | Read indexed file | After finding files via search |
| `mcp__sourcegraph__sg_list_files` | Find files by pattern | Discovering file structure |
| `mcp__sourcegraph__sg_go_to_definition` | Symbol navigation | Finding where functions are defined |
| `mcp__sourcegraph__sg_commit_search` | Search git history | Understanding code evolution |

## Recommended First Actions

Before using Bash, Read, or Grep extensively, consider using MCP:

```
# For exact matches (function names, error messages):
mcp__sourcegraph__sg_keyword_search(query="TypeError combine_vars")

# For conceptual understanding:
mcp__sourcegraph__sg_nls_search(query="how does variable merging work")
```

## Search Strategy

1. **Exact Matches** → `sg_keyword_search`
   - Function/class/variable names
   - Error messages and log strings
   - Import statements

2. **Conceptual Questions** → `sg_nls_search`
   - "Where is authentication handled?"
   - "How does the config system work?"

3. **Narrow Scope** → Local Grep
   - Searching within a known directory
   - Simple pattern matching

## Why MCP?

- Searches the entire indexed codebase efficiently
- Understands semantic code relationships
- Faster than reading files one-by-one for exploration
- Provides context-aware results

## Workflow

1. Use MCP to explore and understand the problem domain
2. Use local Read to examine specific files identified by MCP
3. Make targeted code changes with Edit
4. Test your implementation
"""

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        """Override to enable implementation mode with MCP tools."""
        parent_commands = super().create_run_agent_commands(instruction)

        # Include MCP tools for Sourcegraph integration
        base_tools = "Bash,Read,Edit,Write,Grep,Glob,Skill,TodoWrite,Task,TaskOutput"
        mcp_tools = ",".join([
            "mcp__sourcegraph__sg_keyword_search",
            "mcp__sourcegraph__sg_nls_search",
            "mcp__sourcegraph__sg_read_file",
            "mcp__sourcegraph__sg_list_repos",
            "mcp__sourcegraph__sg_list_files",
            "mcp__sourcegraph__sg_go_to_definition",
            "mcp__sourcegraph__sg_commit_search",
        ])
        allowed_tools = f"{base_tools},{mcp_tools}"

        result = []
        for cmd in parent_commands:
            if cmd.command and "claude " in cmd.command:
                modified_command = cmd.command.replace(
                    "claude ",
                    f"claude --permission-mode acceptEdits --allowedTools {allowed_tools} ",
                )
                env = cmd.env or {}
                env_with_config = {
                    **env,
                    "FORCE_AUTO_BACKGROUND_TASKS": "1",
                    "ENABLE_BACKGROUND_TASKS": "1",
                    "NODE_TLS_REJECT_UNAUTHORIZED": "0",
                }
                logger.info(
                    "SourcegraphMCPAgent: Implementation mode with full MCP toolkit"
                )
                result.append(
                    ExecInput(command=modified_command, env=env_with_config)
                )
            else:
                result.append(cmd)
        return result

    async def setup(self, environment: BaseEnvironment) -> None:
        """Setup with Sourcegraph MCP v1 configuration."""
        token = require_token()

        # Detect working directory
        workdir = "/app"  # default
        for candidate in ["/workspace", "/app", "/testbed"]:
            check = await environment.exec(f'[ -d {candidate} ] && echo EXISTS')
            if check.stdout and "EXISTS" in check.stdout:
                workdir = candidate
                break
        logger.info(f"SourcegraphMCPAgent: Detected workdir: {workdir}")

        # Write MCP config
        mcp_config_path = self.logs_dir / ".mcp.json"
        write_mcp_config(
            mcp_config_path,
            name="sourcegraph",
            url=SOURCEGRAPH_MCP_V1,
            token=token,
        )

        # Upload to working directory
        await environment.upload_file(
            source_path=mcp_config_path, target_path=f"{workdir}/.mcp.json"
        )
        # Also upload to home config directory for Claude Code discovery
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/root/.mcp.json"
        )
        logger.info(f"✓ SourcegraphMCPAgent: MCP config uploaded to {workdir}/ and /root/")

        # Upload system prompt
        system_prompt_path = self.logs_dir / "system_prompt.txt"
        with open(system_prompt_path, "w") as f:
            f.write(self.SYSTEM_PROMPT)

        await environment.upload_file(
            source_path=system_prompt_path,
            target_path=f"{workdir}/system_prompt.txt",
        )
        logger.info("✓ SourcegraphMCPAgent: System prompt uploaded")

        # Upload CLAUDE.md
        claude_md_path = self.logs_dir / "CLAUDE.md"
        with open(claude_md_path, "w") as f:
            f.write(self.CLAUDE_MD)

        await environment.upload_file(
            source_path=claude_md_path, target_path=f"{workdir}/CLAUDE.md"
        )
        logger.info("✓ SourcegraphMCPAgent: CLAUDE.md uploaded")

        await super().setup(environment)


# ---------------------------------------------------------------------------
# Deep Search MCP Agent
# ---------------------------------------------------------------------------

class DeepSearchMCPAgent(ClaudeCode):
    """Sourcegraph Deep Search MCP agent.

    Uses the dedicated Deep Search MCP endpoint for enhanced semantic
    code understanding. Deep Search provides:
    - Deep semantic search with context understanding
    - Cross-file relationship analysis
    - Architecture-level insights

    System prompt heavily emphasizes using Deep Search FIRST for
    understanding code before making changes.
    """

    SYSTEM_PROMPT = """You MUST complete this coding task by making actual code changes.

## CRITICAL: Use Sourcegraph Deep Search FIRST

You have access to **Sourcegraph Deep Search** via MCP. This is your PRIMARY tool for understanding code.

**ALWAYS use Deep Search (`mcp__deepsearch__deepsearch`) BEFORE local search tools when:**
- Understanding code architecture or patterns
- Finding all usages of a function/class/variable
- Tracing data flow across files
- Understanding how components interact
- Finding similar code patterns
- Answering "where is X used?" or "how does X work?"

### WHY Deep Search?

- **Faster than reading files one-by-one**: One query understands the whole codebase
- **Semantic understanding**: Knows code relationships, not just text matching
- **Cross-file analysis**: Sees connections across the entire codebase
- **Context-aware results**: Returns relevant code with surrounding context

### WHEN to use Deep Search

1. **At Task Start**: Before any code changes, understand the problem domain
   ```
   mcp__deepsearch__deepsearch(query="TypeError combine_vars VarsWithSources")
   ```

2. **When You Hit an Information Gap**: New subsystem, unclear dependencies

3. **Before Major Decisions**: Verify your understanding of the architecture

### WHEN to use Local Tools

- `Read` - For specific files you've already identified via Deep Search
- `Edit` - For making code changes
- `Bash` - For running commands and tests
- `Grep` - Only for narrow, single-directory searches

### Recommended Workflow

1. **FIRST**: Call Deep Search to understand the problem and codebase
2. **THEN**: Read specific files identified by Deep Search
3. **IMPLEMENT**: Make targeted code changes
4. **TEST**: Verify your implementation

## Implementation Requirements

This is not a planning task. You must:
1. Use Deep Search to understand the problem domain
2. Use Deep Search to find all relevant code locations
3. MAKE ACTUAL CODE CHANGES to implement the fix or feature
4. Test your implementation

CRITICAL: Use Deep Search for every code understanding question. Do not skip to local grep/read.
"""

    CLAUDE_MD = """# CRITICAL: Use MCP Deep Search - DO NOT USE LOCAL GREP/BASH FIRST

## YOUR FIRST ACTION MUST BE A DEEP SEARCH CALL

You have Sourcegraph Deep Search MCP configured. **You MUST call Deep Search before any local tool.**

## MCP Tool Name (use exactly this name)

- `mcp__deepsearch__deepsearch` - **CALL THIS FIRST** - Deep semantic search

## MANDATORY First Step

Your FIRST tool call must be:
```
mcp__deepsearch__deepsearch(query="<describe the bug or feature>")
```

Example:
```
mcp__deepsearch__deepsearch(query="TypeError combine_vars VarsWithSources dict handling")
```

## Why Deep Search First?

1. **The entire codebase is indexed** - Deep Search sees everything
2. **Semantic understanding** - Knows code relationships, not just text
3. **Saves tokens** - One query vs. reading many files
4. **Faster** - Finds the right code immediately

## FORBIDDEN Actions (DO NOT DO THESE FIRST)

❌ `Bash("grep ...")` - Do not grep before Deep Search
❌ `Bash("find ...")` - Do not find before Deep Search
❌ `Read("some/file.py")` - Do not read random files before Deep Search
❌ `Glob("**/*.py")` - Do not glob before Deep Search

## Correct Workflow

1. **FIRST**: `mcp__deepsearch__deepsearch(query="...")`
2. **THEN**: Read specific files from Deep Search results
3. **THEN**: Make targeted code changes
4. **IF STUCK**: Call Deep Search again with refined query

## Anti-Patterns (DO NOT DO)

❌ Starting with local Bash/Grep without Deep Search first
❌ Reading files one-by-one to "explore"
❌ Skipping Deep Search because "I'll just grep for it"
❌ Using Deep Search once then never again when you hit a wall

## Remember

Deep Search saves tokens by finding the right code faster.
Use it liberally for code understanding questions.
"""

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        """Override to enable implementation mode with Deep Search emphasis."""
        parent_commands = super().create_run_agent_commands(instruction)

        # Include Deep Search MCP tool
        base_tools = "Bash,Read,Edit,Write,Grep,Glob,Skill,TodoWrite,Task,TaskOutput"
        mcp_tools = "mcp__deepsearch__deepsearch"
        allowed_tools = f"{base_tools},{mcp_tools}"

        result = []
        for cmd in parent_commands:
            if cmd.command and "claude " in cmd.command:
                modified_command = cmd.command.replace(
                    "claude ",
                    f"claude --permission-mode acceptEdits --allowedTools {allowed_tools} ",
                )
                env = cmd.env or {}
                env_with_config = {
                    **env,
                    "FORCE_AUTO_BACKGROUND_TASKS": "1",
                    "ENABLE_BACKGROUND_TASKS": "1",
                    "NODE_TLS_REJECT_UNAUTHORIZED": "0",
                }
                logger.info(
                    "DeepSearchMCPAgent: Implementation mode with Deep Search emphasis"
                )
                result.append(
                    ExecInput(command=modified_command, env=env_with_config)
                )
            else:
                result.append(cmd)
        return result

    async def setup(self, environment: BaseEnvironment) -> None:
        """Setup with Deep Search MCP configuration."""
        token = require_token()

        # Detect working directory
        workdir = "/app"  # default
        for candidate in ["/workspace", "/app", "/testbed"]:
            check = await environment.exec(f'[ -d {candidate} ] && echo EXISTS')
            if check.stdout and "EXISTS" in check.stdout:
                workdir = candidate
                break
        logger.info(f"DeepSearchMCPAgent: Detected workdir: {workdir}")

        # Check for dedicated Deep Search endpoint, fall back to standard
        deepsearch_url = os.environ.get("DEEPSEARCH_MCP_URL") or SOURCEGRAPH_MCP_DEEPSEARCH

        if not deepsearch_url.startswith(("http://", "https://")):
            deepsearch_url = f"https://{deepsearch_url}"
        deepsearch_url = deepsearch_url.rstrip("/")

        # Write MCP config
        mcp_config_path = self.logs_dir / ".mcp.json"
        write_mcp_config(
            mcp_config_path,
            name="deepsearch",
            url=deepsearch_url,
            token=token,
        )

        # Upload to working directory
        await environment.upload_file(
            source_path=mcp_config_path, target_path=f"{workdir}/.mcp.json"
        )
        # Also upload to home config directory for Claude Code discovery
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/root/.mcp.json"
        )
        logger.info(f"✓ DeepSearchMCPAgent: MCP config uploaded to {workdir}/ and /root/ ({deepsearch_url})")

        # Upload system prompt
        system_prompt_path = self.logs_dir / "system_prompt.txt"
        with open(system_prompt_path, "w") as f:
            f.write(self.SYSTEM_PROMPT)

        await environment.upload_file(
            source_path=system_prompt_path,
            target_path=f"{workdir}/system_prompt.txt",
        )
        logger.info("✓ DeepSearchMCPAgent: System prompt with Deep Search emphasis uploaded")

        # Upload CLAUDE.md
        claude_md_path = self.logs_dir / "CLAUDE.md"
        with open(claude_md_path, "w") as f:
            f.write(self.CLAUDE_MD)

        await environment.upload_file(
            source_path=claude_md_path, target_path=f"{workdir}/CLAUDE.md"
        )
        logger.info("✓ DeepSearchMCPAgent: CLAUDE.md with Deep Search guidance uploaded")

        await super().setup(environment)

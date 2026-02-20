"""Harbor-compatible Claude Code agent with MCP-first code discovery.

This agent extends Harbor's built-in ClaudeCode to:
1. Force MCP-first code discovery by blocking local search tools (Grep, Glob) and
   shell search commands (grep/rg/ag/ack/find/fd/tree) via --tools + --disallowedTools
2. Append explicit system prompts requiring MCP usage for code discovery
3. Enable autonomous/headless operation via environment variables
4. Support optional MCP configuration (Sourcegraph or Deep Search)

The key mechanism: --tools restricts to only Bash/Read/Edit (for implementation),
--disallowedTools blocks search patterns (forcing MCP discovery), and --append-system-prompt
makes the workflow requirement explicit.

Configuration via environment variable: BASELINE_MCP_TYPE (none|sourcegraph|sourcegraph_full|deepsearch|deepsearch_hybrid)
"""

import base64
import json
import logging
import os
from pathlib import Path

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.agents.installed.base import ExecInput
from harbor.environments.base import BaseEnvironment

logger = logging.getLogger(__name__)

# Path to CLAUDE.md template for Deep Search tasks
LOCOBENCH_CLAUDE_MD_TEMPLATE = Path("/home/stephanie_jarmak/CodeContextBench/benchmarks/locobench_agent/templates/CLAUDE.md")

# System prompt for evaluation context - delivered via --append-system-prompt for ALL modes
# This is the single authoritative source of test-first instructions (US-003)
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

## LARGE CODEBASE RULES

This repository may be very large (hundreds of thousands of files, gigabytes of code).
You MUST follow these rules to avoid wasting time on operations that will hang or time out:

**Build and compile ONLY the specific packages you changed.**
- ✅ `go build ./pkg/apis/core/...` or `go test ./staging/src/k8s.io/endpointslice/...`
- ✅ `cargo check -p specific_crate` or `cargo test -p specific_crate`
- ✅ `npm run build -- --filter=specific-package` or `npx jest path/to/test`
- ❌ NEVER run `go build ./...`, `cargo build`, `make all`, `npm run build` on the whole repo
- ❌ NEVER run `go test ./...`, `cargo test`, `npm test` without scoping to specific packages

**Prefer `check` over `build` for verification.**
- ✅ `cargo check -p crate_name` (type-checks only, much faster)
- ✅ `go vet ./pkg/...` for quick static analysis
- ❌ `cargo build -p crate_name` is slower — only use if you need to run the binary
- If a build requires missing system dependencies (LLVM, cmake, etc.), skip it and use syntax/type checking or `rustfmt --check` instead. Do NOT wait for a doomed build.

**Search and explore surgically.**
- ❌ NEVER run `find . -name "*.go"` or `ls -R` from the repo root
- ❌ NEVER run unscoped `grep -r` from the repo root without path constraints
- ✅ Always scope searches to relevant subdirectories (e.g., `pkg/`, `src/`, `staging/`)

**Never pipe long-running commands through `tail`.**
- ❌ `cargo check -p crate 2>&1 | tail -100` — `tail` blocks until the command finishes, hanging your session
- ✅ `cargo check -p crate 2>&1 | head -100` — `head` returns as soon as it has enough output
- ✅ Run long builds in the background and check output later

**If a command takes more than 60 seconds, it is probably too broad.** Kill it, narrow the scope, and retry."""


# Concise Sourcegraph MCP tool reference for CLAUDE.md injection.
# No workflow mandates, no identity framing — just tool documentation.
SG_TOOL_REFERENCE = """# Sourcegraph MCP Tools

Available tools for searching the remote repository:

- `keyword_search` — exact keyword/pattern search across files. Use `repo:^<repo>$` filter.
- `nls_search` — semantic/fuzzy search (broader matching, good for exploratory queries)
- `read_file` — read file contents from the indexed repository
- `list_files` — list directory contents
- `list_repos` — search and list available repositories
- `go_to_definition` — jump to a symbol's definition (cross-repo support)
- `find_references` — find all usages of a symbol
- `commit_search` — search commit history by message, author, or content
- `diff_search` — search code changes (added/removed lines)
- `compare_revisions` — compare two branches/commits/tags
- `deepsearch` — AI-powered deep analysis (async: returns a polling link)
- `deepsearch_read` — read Deep Search results (call 60+ seconds after deepsearch)

Note: Sourcegraph indexes the remote repository. Local source files may be truncated — use Sourcegraph to read code.
"""

# V4 Preamble template for MCP instruction injection.
# Skill-style guidance: tool selection, scoping, context-aware behavior.
# No mandatory workflow mandates — teaches effective MCP usage by example.
# {repo_scope} is replaced at runtime with the target repository filter.
V4_PREAMBLE_TEMPLATE = """# Searching Sourcegraph

Search before you build. Existing patterns reduce tokens, ensure consistency, and surface tested solutions.

{repo_scope}

## Local File Editing

Local source files may be truncated (empty). Use Sourcegraph to *read and understand* code, then *edit local files* based on what you learn. The verifier restores the full codebase and applies your local edits on top.

- **Search/Read remotely:** Use MCP tools to find files, understand patterns, read implementations
- **Edit locally:** Use Edit, Write, and Bash to modify files in your working directory
- **Don't over-read:** Once you understand the pattern, start implementing. Reading 20+ remote files without writing code wastes time.
- **Verify locally:** Run tests with Bash to check your changes

## Tool Selection Logic

**Start here:**

1. **Know the exact symbol or pattern?** → `sg_keyword_search`
2. **Know the concept, not the code?** → `sg_nls_search`
3. **Need to understand how/why?** → `sg_deepsearch_read`
4. **Tracing a symbol's usage?** → `sg_find_references`
5. **Need full implementation?** → `sg_go_to_definition` → `sg_read_file`

| Goal | Tool |
|------|------|
| Concepts/semantic search | `sg_nls_search` |
| Exact code patterns | `sg_keyword_search` |
| Trace usage | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Understand systems | `sg_deepsearch_read` |
| Read files | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
file:.*\\.test\\.ts$ -file:__mocks__   # Tests, exclude mocks
```

Start narrow. Expand only if results are empty.

Combine filters: `repo:^github.com/myorg/backend$ file:src/handlers lang:typescript`

## Context-Aware Behaviour

**When the user provides a file path or error message:**
- Extract symbols, function names, or error codes
- Search for those exact terms first
- Trace references if the error involves a known symbol

**When the user asks "how does X work":**
- Prefer `sg_deepsearch_read` for architectural understanding
- Follow up with `sg_read_file` on key files mentioned in the response

**When the user is implementing a new feature:**
- Search for similar existing implementations first
- Read tests for usage examples
- Check for shared utilities before creating new ones

**When debugging:**
- Search for the exact error string
- Trace the symbol where the error is thrown
- Check recent changes with `sg_diff_search`

## Workflows

For detailed step-by-step workflows, see:
- `workflows/implementing-feature.md` — when building new features
- `workflows/understanding-code.md` — when exploring unfamiliar systems
- `workflows/debugging-issue.md` — when tracking down bugs

## Efficiency Rules

**Minimise tool calls:**
- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms (faster, more precise)

**Batch your understanding:**
- Read 2-3 related files before synthesising, rather than reading one and asking questions
- Use `sg_deepsearch_read` for "how does X work" instead of multiple keyword searches

**Avoid common token waste:**
- Don't search all repos when you know the target repo
- Don't use `sg_deepsearch_read` for simple "find all" queries
- Don't re-read files you've already seen in this conversation

## Query Patterns

| Intent | Query |
|--------|-------|
| React hooks | `file:.*\\.tsx$ use[A-Z].*= \\(` |
| API routes | `file:src/api app\\.(get\\|post\\|put\\|delete)` |
| Error handling | `catch.*Error\\|\\.catch\\(` |
| Type definitions | `file:types/ export (interface\\|type)` |
| Test setup | `file:.*\\.test\\. beforeEach\\|beforeAll` |
| Config files | `file:(webpack\\|vite\\|rollup)\\.config` |
| CI/CD | `file:\\.github/workflows deploy` |

For more patterns, see `query-patterns.md`.

## Output Formatting

**Search results:**
- Present as a brief summary, not raw tool output
- Highlight the most relevant file and line
- Include a code snippet only if it directly answers the question

**Code explanations:**
- Start with a one-sentence summary
- Use the codebase's own terminology
- Reference specific files and functions

**Recommendations:**
- Present as numbered steps if actionable
- Link to specific patterns found in the codebase
- Note any existing utilities that should be reused

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Searching all repos | Add `repo:^github.com/org/repo$` |
| Too many results | Add `file:` pattern or keywords |
| Missing relevant code | Try `sg_nls_search` for semantic matching |
| Not understanding context | Use `sg_deepsearch_read` |
| Guessing patterns | Read implementations with `sg_read_file` |

## Principles

- Start narrow, expand if needed
- Chain tools: search → read → find references → definition
- Check tests for usage examples
- Read before generating

---

"""


class BaselineClaudeCodeAgent(ClaudeCode):
    """Claude Code with MCP-first code discovery enforcement.

    Extends Harbor's built-in ClaudeCode agent to:
    1. Block local search tools (Grep, Glob) and shell commands (grep/rg/ag/find/fd/tree) via --tools + --disallowedTools
    2. Force code discovery through MCP by appending explicit system prompts
    3. Enable autonomous/headless operation mode
    4. Configure MCP endpoints (Sourcegraph or Deep Search)

    Key mechanism: Uses Claude Code CLI flags to restrict tool availability:
    - --tools "Bash,Read,Edit" - Only these tools for implementation
    - --disallowedTools - Blocks search patterns to prevent workarounds
    - --append-system-prompt - Explicit workflow requirement for MCP-first discovery
    - --debug "api,mcp" - Verification and logging

    MCP Configuration (via BASELINE_MCP_TYPE environment variable):
    - "none" or unset: No MCP, pure baseline (standard tool restrictions still apply)
    - "sourcegraph": Full Sourcegraph MCP (14 tools), local search tools blocked
    - "sourcegraph_full": Full Sourcegraph MCP (14 tools) + all local tools (recommended)
    - "deepsearch": Deep Search-only MCP endpoint for semantic code search
    - "deepsearch_hybrid": Deep Search MCP + strategic local search fallback (deprecated, use sourcegraph_full)
    """

    def _get_repo_display(self) -> str:
        """Return the Sourcegraph repository display name for MCP prompts.

        Resolution order:
        1. SOURCEGRAPH_REPO_NAME env var (explicit override, highest priority)
        2. LOCOBENCH_PROJECT_ID -> sg-benchmarks/locobench-{prefix}
           (checked in host env AND _container_env_cache populated by setup())
        3. SWEBENCH_REPO_COMMIT -> sg-benchmarks/{repo_info}
           (checked in host env AND _container_env_cache populated by setup())
        4. Fallback: "the codebase"
        """
        sg_repo_name = os.environ.get("SOURCEGRAPH_REPO_NAME", "")
        if sg_repo_name:
            # Strip github.com/ prefix if present — templates add it back
            if sg_repo_name.startswith("github.com/"):
                return sg_repo_name[len("github.com/"):]
            return sg_repo_name

        cache = getattr(self, '_container_env_cache', {})

        locobench_prefix = os.environ.get("LOCOBENCH_PROJECT_ID", "") or cache.get("LOCOBENCH_PROJECT_ID", "")
        if locobench_prefix:
            return f"sg-benchmarks/locobench-{locobench_prefix}"

        repo_info = os.environ.get("SWEBENCH_REPO_COMMIT", "") or cache.get("SWEBENCH_REPO_COMMIT", "")
        if repo_info:
            return f"sg-benchmarks/{repo_info}"

        return "the codebase"


    def _get_session_dir(self):
        """Override Harbor's _get_session_dir to handle Claude Code subagent sessions.

        Harbor's built-in _get_session_dir fails when Claude Code spawns subagents
        (via the Task tool). Subagents create additional JSONL files under
        <session-id>/subagents/, causing multiple candidate directories. The original
        code returns None when len(candidate_dirs) > 1, which prevents trajectory.json
        from being generated (the H3 bug).

        Fix: filter out 'subagents' directories and return the top-level session dir
        which always contains the main session JSONL file.
        """
        from pathlib import Path

        sessions_root = self.logs_dir / "sessions"
        if not sessions_root.exists():
            return None

        project_root = sessions_root / "projects"
        candidate_files = []
        if project_root.exists():
            candidate_files = list(project_root.glob("**/*.jsonl"))
        if not candidate_files:
            return None

        # Filter out subagent directories — only consider top-level session dirs
        candidate_dirs = sorted(
            {f.parent for f in candidate_files
             if f.parent.is_dir() and "subagents" not in f.parent.parts}
        )
        if not candidate_dirs:
            return None

        if len(candidate_dirs) == 1:
            return candidate_dirs[0]

        # Still multiple non-subagent dirs — fall back to original behavior
        print(
            "Multiple Claude Code session directories found; "
            "could not identify the correct one"
        )
        return None

    @property
    def _install_agent_template_path(self) -> Path:
        """Use our custom install script that properly handles nvm in Docker."""
        return Path(__file__).parent / "install-claude-code.sh.j2"

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        """
        Override to enable MCP-first code discovery via tool restrictions.

        This modifies the Claude Code command to:
        1. Restrict available tools to base set (Bash, Read, Edit) via --tools
        2. Block local search tools (Grep, Glob) and search commands in Bash via --disallowedTools
        3. Append system prompt requiring MCP for code discovery
        4. Add MCP config if MCP is enabled
        5. Enable autonomous implementation mode (autonomous environment variables)

        The tool restriction forces code discovery through MCP instead of local tools.
        The system prompt makes the workflow requirement explicit.
        """

        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()

        # Support instruction variants (e.g., "blind" for symptom-only instructions).
        # TASK_SOURCE_DIR must be set by the config script to the task's source directory.
        instruction_variant = os.environ.get("INSTRUCTION_VARIANT", "default").lower()
        task_source_dir = os.environ.get("TASK_SOURCE_DIR", "")
        if instruction_variant != "default" and task_source_dir:
            variant_path = Path(task_source_dir) / f"instruction_{instruction_variant}.md"
            if variant_path.exists():
                logger.info(f"Using instruction variant: {instruction_variant} from {variant_path}")
                instruction = variant_path.read_text()
            else:
                logger.warning(f"Instruction variant '{instruction_variant}' not found at {variant_path}, using default")

        # Get repo display name for MCP prompts (centralized resolution)
        repo_display = self._get_repo_display()

        # For hybrid MCP modes, prepend V4 preamble to the instruction text.
        if mcp_type in ("sourcegraph_full", "sourcegraph_base", "artifact_full"):
            # --- V4 Preamble ---
            # Skill-style guidance: tool selection, scoping, context-aware behavior.
            # No mandatory workflow mandates — teaches effective MCP usage by example.
            if repo_display != "the codebase":
                sg_repo_full = f"github.com/{repo_display}"
                repo_scope = (
                    f"**Target Repository:** `{sg_repo_full}`\n"
                    f"- Use `repo:^{sg_repo_full}$` filter in keyword_search\n"
                    f"- Use `{sg_repo_full}` as the `repo` parameter for "
                    f"go_to_definition/find_references/read_file\n"
                )
            else:
                repo_scope = (
                    "Use `sg_list_repos` to discover available repositories "
                    "before searching.\n"
                )

            mcp_preamble = V4_PREAMBLE_TEMPLATE.format(repo_scope=repo_scope)
            instruction = mcp_preamble + instruction

            # Artifact-full: append guidance about expressing changes as diffs
            if mcp_type == "artifact_full":
                artifact_guidance = """

## Artifact-Only Evaluation

You are in **artifact-only mode**. Your workspace is empty — all code discovery
must go through Sourcegraph MCP tools. Express all code changes as **unified
diffs** in your output artifact (e.g., `fix_patch` fields in review.json, or a
standalone `solution.patch` file). Do NOT attempt to edit source files directly
— there are no source files in your workspace.
"""
                instruction = instruction + artifact_guidance

        elif mcp_type == "sourcegraph_isolated":
            # Isolated mode: agent has only the target package locally (via sparse checkout).
            # All cross-package discovery MUST go through Sourcegraph MCP.
            if repo_display != "the codebase":
                sg_repo_full = f"github.com/{repo_display}"
                repo_line = f"Sourcegraph repository: `{sg_repo_full}` (use `repo:^{sg_repo_full}$` filter in keyword_search, and as the `repo` parameter for go_to_definition/find_references)"
            else:
                repo_line = "Use `list_repos` to discover available repositories before searching."

            tool_list = "keyword_search, nls_search, list_files, read_file, go_to_definition, find_references, deepsearch, deepsearch_read"
            mcp_preamble = f"""## CRITICAL: Limited Local Access — Sourcegraph REQUIRED for Cross-Package Context

You have LOCAL ACCESS to ONLY the target package directory. All other packages
in this repository are NOT available locally — they were excluded during setup.

To understand cross-package dependencies, imports, callers, conventions, and
patterns from OTHER packages, you MUST use Sourcegraph MCP tools ({tool_list}):
- `keyword_search` to find code patterns across the full repository
- `go_to_definition` / `find_references` to trace symbols across packages
- `read_file` to read files from packages NOT available locally
- `list_files` to browse directories outside your local scope
- `nls_search` for semantic/conceptual searches

{repo_line}

**WORKFLOW:**
1. Read the task requirements and explore your LOCAL package files
2. Use Sourcegraph to discover how your package relates to others (conventions, patterns, imports)
3. Specifically search for examples of similar work in OTHER packages (e.g., other doc.go files)
4. Implement your changes using local tools (Read, Edit, Bash)

---

"""
            instruction = mcp_preamble + instruction

        # Build the system prompt with MCP-first workflow requirement
        if mcp_type == "sourcegraph":
            mcp_system_prompt = f"""You MUST use Sourcegraph MCP tools for ALL code navigation, discovery, and search.
Do NOT use local repo-search (grep/rg/ag/ack/find/fd/tree, or recursive ls) for discovery.
Local search tools (Grep, Glob) are BLOCKED - use Sourcegraph MCP instead.

## Sourcegraph MCP Tool Selection Guide

| Goal | Tool | Example |
|------|------|---------|
| Find exact symbol/string | mcp__sourcegraph__sg_keyword_search | "func handleAuth", "ErrorCode" |
| Conceptual/semantic search | mcp__sourcegraph__sg_nls_search | "authentication middleware", "error handling" |
| Deep semantic analysis | mcp__sourcegraph__sg_deepsearch | "How does auth flow work end-to-end?" |
| Read indexed file | mcp__sourcegraph__sg_read_file | Read a specific file from the index |
| Jump to definition | mcp__sourcegraph__sg_go_to_definition | Find where a function is defined |
| Find all references | mcp__sourcegraph__sg_find_references | Find all callers of a function |
| List files in path | mcp__sourcegraph__sg_list_files | Browse directory structure |
| Search commits | mcp__sourcegraph__sg_commit_search | Find when a change was introduced |
| Search diffs | mcp__sourcegraph__sg_diff_search | Find what changed in a commit |
| Compare revisions | mcp__sourcegraph__sg_compare_revisions | See differences between versions |

## Decision Logic

BEFORE opening files randomly, ask yourself:
1. "Can sg_keyword_search find this exact string?" → YES → use it
2. "Do I need to understand relationships?" → YES → use sg_nls_search or sg_deepsearch
3. "Do I need the definition of this symbol?" → YES → use sg_go_to_definition
4. "Do I need all callers/references?" → YES → use sg_find_references

🎯 CRITICAL - ALWAYS USE THE CORRECT REPOSITORY FILTER:
**You are working in: {repo_display}**

When making sg_keyword_search queries, you MUST include the repo: filter with the EXACT repository name:
- ✅ CORRECT: `repo:^github.com/{repo_display}$ YourSearchTerm`
- ❌ WRONG: Guessing the repo name or omitting parts (e.g., dropping `--latest` suffix)

Example sg_keyword_search query: `repo:^github.com/{repo_display}$ TaintEffectNoSchedule`

Workflow requirement:
1) Run Sourcegraph MCP search to find candidate files/locations
   Always use `repo:^github.com/{repo_display}$` filter in sg_keyword_search queries
2) Open only the relevant files/regions needed to implement the fix
3) If MCP search returns no results, broaden the search query (synonyms, partial identifiers) before opening more files

CRITICAL WARNING - COMMIT VERSION MISMATCH:
Sourcegraph MCP indexes the LATEST code on the default branch (e.g., main/master), but you are working on a HISTORICAL commit (the base_commit specified in the task).
The code in MCP search results may be DIFFERENT from your local working copy because:
- Fields/types may have been added, removed, or changed
- Function signatures may differ
- The bug you're fixing may already be fixed in the indexed version

MANDATORY VERIFICATION STEPS:
1) After every MCP search query, use Read to verify the actual file contents in your local working directory
2) If MCP shows `*time.Time` but local code shows `time.Time`, TRUST THE LOCAL CODE
3) Check the base_commit in the task description - you are working at that specific point in history
4) When in doubt, read the local file directly before making any changes

IMPORTANT: If your first Sourcegraph search returns empty results, the repository name may differ
from what you expect. Use `mcp__sourcegraph__sg_list_repos` to discover the correct repo name
before retrying."""
            system_prompt_append = EVALUATION_CONTEXT_PROMPT + "\n\n---\n\n" + mcp_system_prompt

        elif mcp_type == "deepsearch":
            mcp_system_prompt = f"""When you need to understand the codebase or locate code across the repo, you MUST use Deep Search MCP first.
Do NOT use local repo-search (grep/rg/ag/ack/find/fd/tree, or recursive ls) for discovery.

Available MCP tool:
- mcp__deepsearch__deepsearch - Deep semantic code search (use this first for understanding)

🎯 CRITICAL - ALWAYS REFERENCE THE CORRECT REPOSITORY:
**You are working in: {repo_display}**

When making Deep Search queries, you MUST explicitly reference this repository name in your query:
- ✅ CORRECT: "In {repo_display}, where is [code]?"
- ✅ CORRECT: "Search {repo_display} for [query]"
- ❌ WRONG: "In the codebase, where..." (too vague, might search wrong repo)
- ❌ WRONG: "In navidrome, where..." (searches original, not sg-benchmarks mirror)

IMPORTANT - SG-BENCHMARKS ORG:
The Deep Search MCP is configured to search in the sg-benchmarks GitHub organization.
This organization contains mirrors of all benchmark repositories with HEAD pinned to match your local working copy's commit.
Do NOT search the original repositories - use sg-benchmarks which has the correct indexed commit.

Workflow requirement:
1) Run Deep Search MCP to find relevant code and understand relationships
   ALWAYS include repository reference: "In {repo_display}, [your query]"
2) Open only the relevant files/regions needed to implement the fix
3) If Deep Search returns no results, broaden the search query before opening more files

Deep Search is configured for sg-benchmarks org with the correct commit, so results should match your local working copy.

IMPORTANT: If your first search returns empty results, the repository name may differ
from what you expect. Use `mcp__sourcegraph__sg_list_repos` (if available) to discover the correct repo name
before retrying."""
            system_prompt_append = EVALUATION_CONTEXT_PROMPT + "\n\n---\n\n" + mcp_system_prompt

        elif mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated", "artifact_full"):
            # V4 system prompt: lightweight reinforcement (detailed guidance is in the instruction preamble).
            if repo_display != "the codebase":
                repo_filter_system = f"Sourcegraph repository: github.com/{repo_display}\nFor keyword_search: repo:^github.com/{repo_display}$ YourSearchTerm"
            else:
                repo_filter_system = "Use list_repos to discover available repositories first."

            mcp_system_prompt = f"""You have Sourcegraph MCP tools available. Use them to search, read, and navigate the codebase before making changes.

Local source files may be truncated or unavailable. Use Sourcegraph to read and understand code, then make edits to local files based on what you learned. Run tests locally to verify your changes.

{repo_filter_system}"""
            system_prompt_append = EVALUATION_CONTEXT_PROMPT + "\n\n---\n\n" + mcp_system_prompt

        elif mcp_type == "deepsearch_hybrid":
            mcp_system_prompt = f"""When exploring this codebase for code discovery, use a hybrid approach:

        Available tools:
        - Deep Search MCP (mcp__deepsearch__deepsearch) - Deep semantic code search
        - Local search tools (Grep, Glob, Bash) - For quick pattern matching and file discovery

        🎯 CRITICAL - ALWAYS REFERENCE THE CORRECT REPOSITORY:
        **You are working in: {repo_display}**

        When making Deep Search queries, you MUST explicitly reference this repository name:
        - ✅ CORRECT: "In {repo_display}, where is [code]?"
        - ✅ CORRECT: "Search {repo_display} for [query]"
        - ❌ WRONG: "In the codebase, where..." (too vague, might search wrong repo)
        - ❌ WRONG: "In navidrome, where..." (searches original, not sg-benchmarks mirror)

        IMPORTANT - SG-BENCHMARKS ORG:
        The Deep Search MCP is configured to search in the sg-benchmarks GitHub organization.
        This organization contains mirrors of all benchmark repositories with HEAD pinned to match your local working copy's commit.
        Deep Search results should now match your local working copy without version mismatches.

        Strategic workflow:
        1) START with Deep Search MCP for:
        - Understanding code relationships and dependencies
        - Finding implementations of key concepts
        - Locating where specific functionality is defined
        - Understanding how features interact across modules
        - ALWAYS include repository reference: "In {repo_display}, [your query]"

        2) Use local search (Grep, Glob, or Bash) as tactical fallback for:
        - Quick file pattern matching (file names, extensions)
        - Verification of specific locations found by Deep Search
        - Finding exact occurrences of identifiers
        - Rapid exploration of local file structure

        3) Decision logic:
        - "Where is the XYZ functionality?" → Use Deep Search first (with repo reference)
        - "Does this file contain pattern ABC?" → Use local search
        - "What files match *.test.ts?" → Use Glob or Bash find
        - Complex relationship/architecture questions → Deep Search (with repo reference)
        - Simple pattern/location verification → Local search

        This hybrid approach gives you the semantic understanding of Deep Search plus the speed of local tools.
        With sg-benchmarks org configured, Deep Search results should accurately reflect your working copy.

        IMPORTANT: If your first search returns empty results, the repository name may differ
        from what you expect. Use `mcp__sourcegraph__sg_list_repos` (if available) to discover the correct repo name
        before retrying."""
            system_prompt_append = EVALUATION_CONTEXT_PROMPT + "\n\n---\n\n" + mcp_system_prompt

        else:
            # Pure baseline mode - system prompt is just the evaluation context
            system_prompt_append = EVALUATION_CONTEXT_PROMPT

        # EVALUATION CONTEXT is now delivered via --append-system-prompt (US-003)
        logger.info("=" * 80)
        logger.info("INSTRUCTION DELIVERY")
        logger.info(f"MCP Type: {mcp_type}")
        logger.info(f"Instruction length: {len(instruction)} chars")
        logger.info(f"EVALUATION CONTEXT delivered via --append-system-prompt (system prompt)")
        logger.info("=" * 80)

        # Persist the final instruction as an artifact for post-run analysis.
        # This captures exactly what the agent receives, including any MCP preamble.
        try:
            instruction_path = self.logs_dir / "instruction.txt"
            with open(instruction_path, "w") as f:
                f.write(instruction)
            logger.info(f"Saved instruction artifact to {instruction_path} ({len(instruction)} chars)")
        except Exception as e:
            logger.warning(f"Could not save instruction artifact: {e}")

        # Get parent's commands with instruction (unchanged)
        parent_commands = super().create_run_agent_commands(instruction)
        
        # MCP configuration flag
        mcp_config_flag = ""
        if mcp_type in ["sourcegraph", "sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated", "deepsearch", "deepsearch_hybrid"]:
            mcp_config_flag = "--mcp-config /logs/agent/sessions/.mcp.json "

        # Build disallowed tools list (blocks local search to force MCP usage)
        # For hybrid mode, we DON'T apply tool restrictions - agent decides strategically
        disallowed_tools = [
            "Grep",                  # Block Grep tool
            "Glob",                  # Block Glob tool
            "Bash(grep:*)",          # Block grep command in Bash
            "Bash(rg:*)",            # Block ripgrep command
            "Bash(ag:*)",            # Block ag (the_silver_searcher) command
            "Bash(ack:*)",           # Block ack command
            "Bash(find:*)",          # Block find command
            "Bash(fd:*)",            # Block fd command
            "Bash(tree:*)",          # Block tree command
            "Bash(ls -R:*)",         # Block recursive ls
        ]

        # Modify the Claude command to force MCP-first discovery
        result = []
        for cmd in parent_commands:
            if cmd.command and "claude " in cmd.command:
                # Start with the base command
                modified_command = cmd.command
                
                # Insert flags after "claude " - build them up incrementally
                flags_to_insert = []
                
                # CRITICAL: Add --dangerously-skip-permissions for autonomous operation
                # Without this, Claude will prompt for user confirmation on tool usage
                flags_to_insert.append('--dangerously-skip-permissions')
                
                # Add MCP config flag if needed
                if mcp_config_flag:
                    flags_to_insert.append(mcp_config_flag)
                
                # For hybrid mode and pure baseline: no tool restrictions
                # For forced MCP modes (sourcegraph, deepsearch): apply tool restrictions
                if mcp_type in ["sourcegraph_full", "sourcegraph_isolated", "artifact_full", "deepsearch_hybrid", "none"]:
                    # Hybrid mode and pure baseline: No tool restrictions
                    # Don't add --tools flag at all - let Claude use all available tools
                    # Skip debug flag - it causes massive bundled JS output to stdout
                    pass
                elif mcp_type == "sourcegraph_base":
                    # Hybrid with all local tools, but block deep search MCP tools
                    deepsearch_blocked = [
                        "mcp__sourcegraph__sg_deepsearch",
                        "mcp__sourcegraph__sg_deepsearch_read",
                    ]
                    blocked_str = " ".join([f'"{tool}"' for tool in deepsearch_blocked])
                    flags_to_insert.append(f'--disallowedTools {blocked_str}')
                elif mcp_type in ["sourcegraph", "deepsearch"]:
                    # Forced MCP modes: Apply full tool restrictions
                    # Add tool restriction flags
                    disallowed_str = " ".join([f'"{tool}"' for tool in disallowed_tools])
                    
                    # Build allowed tools list - base tools plus MCP tools if enabled
                    allowed_tools = ["Bash", "Read", "Edit"]
                    if mcp_type == "sourcegraph":
                        # Add all Sourcegraph MCP tools to allowed list
                        allowed_tools.extend([
                            "mcp__sourcegraph__sg_keyword_search",
                            "mcp__sourcegraph__sg_nls_search",
                            "mcp__sourcegraph__sg_read_file",
                            "mcp__sourcegraph__sg_list_files",
                            "mcp__sourcegraph__sg_list_repos",
                            "mcp__sourcegraph__sg_go_to_definition",
                            "mcp__sourcegraph__sg_find_references",
                            "mcp__sourcegraph__sg_commit_search",
                            "mcp__sourcegraph__sg_diff_search",
                            "mcp__sourcegraph__sg_deepsearch",
                            "mcp__sourcegraph__sg_deepsearch_read",
                            "mcp__sourcegraph__sg_compare_revisions",
                            "mcp__sourcegraph__sg_get_contributor_repos",
                        ])
                    elif mcp_type == "deepsearch":
                        allowed_tools.extend([
                            "mcp__deepsearch__deepsearch",
                        ])
                    
                    allowed_str = ",".join(allowed_tools)
                    flags_to_insert.append(f'--tools "{allowed_str}"')
                    flags_to_insert.append(f'--disallowedTools {disallowed_str}')
                    
                    # Add debug flag for MCP verification
                    flags_to_insert.append('--debug api,mcp')
                
                # Add system prompt via file to avoid "Argument list too long" errors.
                # The system prompt (EVALUATION_CONTEXT + MCP instructions) can exceed
                # Linux ARG_MAX when passed as a CLI argument. Instead, we:
                # 1. Store the prompt content to be written to a file at runtime
                # 2. Have the claude command read it from the file
                _system_prompt_content = system_prompt_append if system_prompt_append else ""

                # Insert all flags after "claude "
                if flags_to_insert:
                    flags_str = " ".join(flags_to_insert)
                    modified_command = modified_command.replace(
                        "claude ",
                        f"claude {flags_str} ",
                        1  # Only replace the first occurrence
                    )

                # CRITICAL: Wrap command to run as non-root user
                # --dangerously-skip-permissions fails when running as root
                # Use adduser/su which are available in Alpine/Debian containers
                # Only chown /logs (small) - /app is read-only and huge
                # Claude is installed globally via npm at /usr/local/bin
                # After running, chmod session files so Harbor can read them
                #
                # We generate a wrapper script at runtime rather than inlining the
                # full command in `su -c '...'`. This avoids:
                # 1. "Argument list too long" when system prompts are large
                # 2. Complex single-quote escaping inside su -c
                #
                # Workdir detection: dynamically detect at runtime since the
                # container filesystem isn't available at command-generation time.
                # Priority: /workspace > /app > /testbed > / (matches setup() logic)

                # Build the wrapper script content
                script_lines = [
                    '#!/bin/bash',
                    'export PATH=/usr/local/bin:/usr/bin:/bin:$PATH',
                    '# Detect working directory',
                    'if [ -d /workspace ]; then WORKDIR=/workspace',
                    'elif [ -d /app ]; then WORKDIR=/app',
                    'elif [ -d /testbed ]; then WORKDIR=/testbed',
                    'else WORKDIR=/; fi',
                    'cd "$WORKDIR"',
                ]

                # If system prompt exists, read it from file and pass via --append-system-prompt
                if _system_prompt_content:
                    script_lines.append('SYSPROMPT=$(cat /tmp/claude_system_prompt.txt)')
                    modified_command = modified_command.replace(
                        "claude ",
                        'claude --append-system-prompt "$SYSPROMPT" ',
                        1
                    )

                script_lines.append(modified_command)

                wrapper_script = "\n".join(script_lines) + "\n"

                # Encode system prompt and wrapper script as base64 to avoid
                # shell escaping issues when embedding in the outer command.
                prompt_b64 = base64.b64encode(_system_prompt_content.encode()).decode() if _system_prompt_content else ""
                script_b64 = base64.b64encode(wrapper_script.encode()).decode()

                # The outer command:
                # 1. Creates claude user
                # 2. Writes system prompt and wrapper script from base64
                # 3. Runs wrapper script as claude user (or root in hybrid SG modes)
                # 4. Fixes permissions after run
                setup_cmds = (
                    "id -u claude &>/dev/null || adduser -D -s /bin/bash claude 2>/dev/null || adduser --disabled-password --gecos '' claude 2>/dev/null || true && "
                    "chown -R claude:claude /logs 2>/dev/null || true && "
                    "chown -R claude:claude /workspace /app /testbed 2>/dev/null || true"
                )

                file_cmds = ""
                if prompt_b64:
                    file_cmds += f" && echo '{prompt_b64}' | base64 -d > /tmp/claude_system_prompt.txt"
                file_cmds += f" && echo '{script_b64}' | base64 -d > /tmp/claude_run.sh && chmod +x /tmp/claude_run.sh"

                # Always run as non-root 'claude' user. Claude Code >=2.1.37 rejects
                # --dangerously-skip-permissions under root/sudo. The chown above ensures
                # the claude user can write to workspace dirs in all benchmark images.
                run_cmd = "su claude -s /bin/bash /tmp/claude_run.sh"

                modified_command = (
                    f"{setup_cmds}{file_cmds} && "
                    f"{run_cmd} ; "
                    "chmod -R a+rX /logs 2>/dev/null || true"
                )
                
                # CRITICAL: Add autonomous environment variables
                # These enable headless/autonomous operation mode
                env = cmd.env or {}
                env_with_autonomous = {
                    **env,
                    'FORCE_AUTO_BACKGROUND_TASKS': '1',
                    'ENABLE_BACKGROUND_TASKS': '1'
                }

                # Add SSL workaround for MCP HTTP transport
                if mcp_type in ["sourcegraph", "sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated", "deepsearch", "deepsearch_hybrid"]:
                    env_with_autonomous['NODE_TLS_REJECT_UNAUTHORIZED'] = '0'

                if mcp_type == "sourcegraph_base":
                    logger.info(f"Modified command for Sourcegraph (12 tools, no Deep Search) + local search approach")
                    logger.info(f"All local tools available: Bash, Read, Edit, Grep, Glob + 12 Sourcegraph MCP tools")
                    logger.info(f"Blocked MCP tools: sg_deepsearch, sg_deepsearch_read")
                    logger.info(f"Strategy: Sourcegraph MCP as PRIMARY (without Deep Search) + local search for verification")
                    logger.info(f"System prompt appended with MANDATORY MCP usage guidance")
                elif mcp_type == "sourcegraph_full":
                    logger.info(f"Modified command for HYBRID Sourcegraph (14 tools) + local search approach")
                    logger.info(f"All tools available: Bash, Read, Edit, Grep, Glob + 14 Sourcegraph MCP tools")
                    logger.info(f"Strategy: Sourcegraph MCP as PRIMARY for code discovery + local search for verification only")
                    logger.info(f"System prompt appended with MANDATORY MCP usage guidance")
                elif mcp_type == "deepsearch_hybrid":
                    logger.info(f"Modified command for HYBRID Deep Search + local search approach")
                    logger.info(f"All tools available: Bash, Read, Edit, Grep, Glob, mcp__deepsearch__deepsearch")
                    logger.info(f"Strategy: Deep Search for semantic understanding + local search as tactical fallback")
                    logger.info(f"System prompt appended with hybrid workflow guidance")
                elif mcp_type == "none":
                    logger.info(f"Pure baseline mode - all standard Claude Code tools available")
                    logger.info(f"No MCP configured, no tool restrictions applied")
                elif mcp_type in ["sourcegraph", "deepsearch"]:
                    logger.info(f"Modified command for MCP-first code discovery")
                    logger.info(f"Base tools available: Bash, Read, Edit")
                    logger.info(f"Blocked local search tools: Grep, Glob, and search commands (grep/rg/ag/ack/find/fd/tree)")
                    logger.info(f"MCP type: {mcp_type}")
                    logger.info(f"System prompt appended with MCP-first workflow requirement")
                    logger.info(f"Debug mode enabled: api,mcp")
                
                logger.info(f"Autonomous mode enabled: FORCE_AUTO_BACKGROUND_TASKS=1, ENABLE_BACKGROUND_TASKS=1")
                
                result.append(
                    ExecInput(command=modified_command, env=env_with_autonomous)
                )
            else:
                result.append(cmd)

        return result

    async def setup(self, environment: BaseEnvironment) -> None:
        """Setup agent environment with optional MCP configuration."""
        # FIX: Make /app writable for the claude user created by the non-root wrapper
        # Pre-built Docker images have /app owned by root, causing permission denied errors
        # when the agent tries to edit files. Fix this at runtime.
        # Note: Harbor exec now runs as root (via patch_harbor_docker.sh), so sudo is unnecessary.
        # The non-root wrapper (create_run_agent_commands) creates a 'claude' user via adduser,
        # which gets uid 1000. We must chown to claude:claude (not hardcoded 1001) to match.
        logger.info("=" * 80)
        logger.info("FIXING WORKDIR PERMISSIONS FOR AGENT")
        try:
            # Detect the correct working directory
            # Priority: /workspace > /app > /testbed (matches create_run_agent_commands)
            workdir = "/app"  # default
            for candidate in ["/workspace", "/app", "/testbed"]:
                check = await environment.exec(f'[ -d {candidate} ] && echo EXISTS')
                if check.stdout and "EXISTS" in check.stdout:
                    workdir = candidate
                    break
            logger.info(f"Detected workdir for permission fix: {workdir}")

            # Create the claude user first (same as the non-root wrapper does later)
            # so we can chown to it. adduser is idempotent if user already exists.
            await environment.exec("id -u claude &>/dev/null || adduser -D -s /bin/bash claude 2>/dev/null || adduser --disabled-password --gecos '' claude 2>/dev/null || true")

            # Fast writability probe. Avoid recursive chown/chmod here because it can hang
            # on large repositories (e.g., Linux trees) and consume the full setup timeout.
            probe = await environment.exec(
                f"touch {workdir}/.claude_write_probe.$$ 2>/dev/null && "
                f"rm -f {workdir}/.claude_write_probe.$$ 2>/dev/null && echo WRITABLE || echo NOT_WRITABLE"
            )
            if probe.stdout and "WRITABLE" in probe.stdout:
                logger.info(f"{workdir} is already writable; skipping ownership recursion")
            else:
                # Fallback to non-recursive top-level fixes only (bounded runtime).
                await environment.exec(
                    f"chown claude:claude {workdir} 2>/dev/null || "
                    f"chown $(id -u):$(id -g) {workdir} 2>/dev/null || true"
                )
                await environment.exec(f"chmod u+rwx {workdir} 2>/dev/null || true")
                logger.info(f"Applied non-recursive permission fix to {workdir}")

            # Some benchmarks (notably k8s docs) mount nested source trees as root-owned,
            # so top-level writability is not sufficient. Fix only immediate package dirs
            # under staging/src/k8s.io to keep runtime bounded.
            k8s_root = f"{workdir}/staging/src/k8s.io"
            k8s_check = await environment.exec(f'[ -d "{k8s_root}" ] && echo EXISTS || true')
            if k8s_check.stdout and "EXISTS" in k8s_check.stdout:
                await environment.exec(
                    f'for d in "{k8s_root}"/*; do '
                    '  [ -d "$d" ] || continue; '
                    '  [ -w "$d" ] && continue; '
                    '  timeout 45 chown -R claude:claude "$d" 2>/dev/null || '
                    '  timeout 45 chown -R $(id -u):$(id -g) "$d" 2>/dev/null || true; '
                    "done"
                )
                logger.info(f"Applied bounded recursive permission fix under {k8s_root}")

            # Allow git-based fallbacks that may touch index.lock.
            await environment.exec(
                f'[ -d "{workdir}/.git" ] && '
                f'chown claude:claude "{workdir}/.git" "{workdir}/.git/index" 2>/dev/null || true'
            )
            # Verify permission state for debugging
            result = await environment.exec(f'stat -c "%U:%G %a" {workdir} 2>/dev/null || echo "stat unavailable"')
            if result.stdout:
                logger.info(f"{workdir} permissions after fix: {result.stdout.strip()}")
        except Exception as e:
            logger.warning(f"Could not fix workdir permissions (may already be writable): {e}")
        logger.info("=" * 80)

        # Propagate container env vars for _get_repo_display()
        # These are set in docker-compose.yaml but not available on the host.
        # We read them from the container and cache them for later use.
        mcp_type_setup = os.environ.get("BASELINE_MCP_TYPE", "none").lower()
        if mcp_type_setup != "none":
            self._container_env_cache = {}
            for var_name in ("LOCOBENCH_PROJECT_ID", "SWEBENCH_REPO_COMMIT"):
                if not os.environ.get("SOURCEGRAPH_REPO_NAME") and not os.environ.get(var_name):
                    try:
                        result = await environment.exec(f'echo ${{{var_name}:-}}')
                        # Filter out bash warning messages (e.g., "bash: cannot set terminal process group")
                        # that appear in stdout when container shell starts
                        lines = (result.stdout or "").strip().split('\n')
                        val = ""
                        for line in lines:
                            line = line.strip()
                            # Skip bash warnings and empty lines
                            if line and not line.startswith("bash:") and "no job control" not in line:
                                val = line
                                break
                        if val:
                            self._container_env_cache[var_name] = val
                            logger.info(f"Propagated container env {var_name}={val}")
                    except Exception as e:
                        logger.warning(f"Could not read container env {var_name}: {e}")

        # Check if using subscription mode
        use_subscription = os.environ.get("USE_SUBSCRIPTION", "false").lower() == "true"
        if use_subscription:
            await self._setup_subscription_auth(environment)

        mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()

        if mcp_type == "sourcegraph":
            await self._setup_sourcegraph_mcp(environment)
        elif mcp_type in ("sourcegraph_full", "sourcegraph_base", "sourcegraph_isolated", "artifact_full"):
            await self._setup_sourcegraph_full_mcp(environment, mcp_type=mcp_type)
        elif mcp_type == "deepsearch":
            await self._setup_deepsearch_mcp(environment)
        elif mcp_type == "deepsearch_hybrid":
            await self._setup_deepsearch_hybrid_mcp(environment)
        else:
            # Pure baseline - no MCP
            logger.info("BaselineClaudeCodeAgent: Pure baseline (no MCP)")

        await super().setup(environment)

    async def _setup_subscription_auth(self, environment: BaseEnvironment) -> None:
        """Setup Claude Code subscription authentication in container.

        Extracts the OAuth access token from ~/.claude/.credentials.json and
        makes it available as ANTHROPIC_API_KEY in the container. This allows
        Claude Code to use subscription credentials for API calls.

        If the token is expired or about to expire (within 30 min), attempts
        to refresh it using the refresh_token and the Anthropic OAuth endpoint.
        """
        logger.info("BaselineClaudeCodeAgent: Setting up subscription authentication...")

        local_auth_file = Path.home() / ".claude" / ".credentials.json"

        if not local_auth_file.exists():
            raise FileNotFoundError(
                f"Claude Code credentials file not found at {local_auth_file}"
            )

        import json
        import time

        # Read credentials as late as possible to minimize staleness window
        # (another process like _common.sh may have refreshed the token)
        with open(local_auth_file) as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        access_token = oauth.get("accessToken")
        if not access_token:
            raise ValueError("No accessToken found in credentials file")

        # Check if token needs refresh (expired or <30 min remaining)
        expires_at_ms = oauth.get("expiresAt", 0)
        now_ms = int(time.time() * 1000)
        remaining_s = (expires_at_ms - now_ms) / 1000
        refresh_margin_s = 1800  # 30 minutes

        if remaining_s < refresh_margin_s:
            logger.info(f"BaselineClaudeCodeAgent: Token expires in {int(remaining_s / 60)} min — attempting refresh...")
            access_token = self._refresh_subscription_token(local_auth_file, creds)

        subscription_type = oauth.get("subscriptionType", "unknown")
        logger.info(f"BaselineClaudeCodeAgent: Subscription auth ready (type: {subscription_type})")

        # Set CLAUDE_CODE_OAUTH_TOKEN so Harbor's create_run_agent_commands()
        # passes the OAuth access token to the container. Claude Code >=2.1.37
        # rejects OAuth tokens (sk-ant-oat01-...) set via ANTHROPIC_API_KEY,
        # requiring CLAUDE_CODE_OAUTH_TOKEN instead.
        # Harbor reads os.environ["CLAUDE_CODE_OAUTH_TOKEN"] at line 763 of claude_code.py.
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = access_token
        # Also clear any stale ANTHROPIC_API_KEY to avoid conflicts
        os.environ.pop("ANTHROPIC_API_KEY", None)

    @staticmethod
    def _refresh_subscription_token(creds_file: Path, creds: dict) -> str:
        """Refresh the OAuth access token using the refresh token.

        Re-reads the credentials file from disk before refreshing to avoid
        using a stale refresh_token (OAuth refresh tokens are single-use).
        If refresh fails with HTTP 403, re-reads the file again in case
        another process (e.g. _common.sh) already refreshed successfully,
        and returns that token if it is still valid.

        Updates the credentials file in place and returns the new access token.
        """
        import json
        import time
        import urllib.request
        import urllib.error

        refresh_margin_s = 1800  # 30 minutes

        # Always re-read from disk to get the latest refresh_token,
        # since another process may have written a new one.
        with open(creds_file) as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        refresh_token = oauth.get("refreshToken")
        if not refresh_token:
            raise ValueError("No refreshToken in credentials — cannot refresh")

        # Before refreshing, check if the on-disk token is already fresh
        # (another process may have refreshed between our caller's check and now)
        expires_at_ms = oauth.get("expiresAt", 0)
        now_ms = int(time.time() * 1000)
        remaining_s = (expires_at_ms - now_ms) / 1000
        if remaining_s >= refresh_margin_s:
            access_token = oauth.get("accessToken")
            if access_token:
                logger.info(
                    f"BaselineClaudeCodeAgent: On-disk token already fresh "
                    f"({int(remaining_s / 60)} min remaining) — skipping refresh"
                )
                return access_token

        payload = json.dumps({
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
        }).encode()

        req = urllib.request.Request(
            "https://console.anthropic.com/api/oauth/token",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                token_data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""

            if e.code == 403:
                # 403 likely means our refresh_token was already consumed by
                # another process. Re-read the creds file — if that process
                # wrote a valid token, just use it.
                logger.warning(
                    "BaselineClaudeCodeAgent: Token refresh got HTTP 403 "
                    "(refresh_token likely consumed by another process). "
                    "Re-reading credentials file..."
                )
                with open(creds_file) as f:
                    creds = json.load(f)
                oauth = creds.get("claudeAiOauth", {})
                expires_at_ms = oauth.get("expiresAt", 0)
                now_ms = int(time.time() * 1000)
                remaining_s = (expires_at_ms - now_ms) / 1000

                access_token = oauth.get("accessToken")
                if access_token and remaining_s > 0:
                    logger.info(
                        f"BaselineClaudeCodeAgent: Using token refreshed by "
                        f"another process ({int(remaining_s / 60)} min remaining)"
                    )
                    return access_token

                # The on-disk token is also expired — nothing we can do
                raise RuntimeError(
                    f"Token refresh failed with HTTP 403 and on-disk token "
                    f"is also expired. Original error: {body}"
                )

            raise RuntimeError(f"Token refresh failed: HTTP {e.code} — {body}")

        new_access = token_data.get("access_token")
        if not new_access:
            raise RuntimeError("No access_token in refresh response")

        new_refresh = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 28800)

        oauth["accessToken"] = new_access
        if new_refresh:
            oauth["refreshToken"] = new_refresh
        oauth["expiresAt"] = int(time.time() * 1000) + (expires_in * 1000)
        creds["claudeAiOauth"] = oauth

        with open(creds_file, "w") as f:
            json.dump(creds, f, indent=2)

        logger.info(f"BaselineClaudeCodeAgent: Token refreshed, valid for {expires_in // 60} min")
        return new_access

    async def _install_sourcegraph_skill(self, environment: BaseEnvironment) -> None:
        """Install the Sourcegraph MCP skill to teach the agent how to use MCP tools effectively.
        
        This skill provides:
        - Tool selection guidance (which Sourcegraph tool to use for each goal)
        - Query scoping with repo: and file: filters
        - Search type guidance (semantic vs keyword vs Deep Search)
        - Step-by-step workflows for implementing features
        - Common query patterns and mistake avoidance
        
        See: https://medium.com/@ajaynz/teaching-ai-to-navigate-your-codebase-agent-skills-sourcegraph-mcp-710b75ab2943
        """
        logger.info("BaselineClaudeCodeAgent: Installing Sourcegraph MCP skill...")
        
        # Install the skill using npx (Node.js should already be installed)
        # The skill provides guidance on how to effectively use Sourcegraph MCP tools
        result = await environment.exec('npx -y skills add ajaynz/sourcegraph-skill')
        
        # Check if installation succeeded by looking at output
        if result.stdout and ("added" in result.stdout.lower() or "skill" in result.stdout.lower()):
            logger.info(f"BaselineClaudeCodeAgent: Sourcegraph skill installed: {result.stdout[:200] if result.stdout else ''}")
        elif result.stderr:
            # Log warning but don't fail - skill is optional enhancement
            logger.warning(f"BaselineClaudeCodeAgent: Sourcegraph skill install warning: {result.stderr[:200]}")
        else:
            logger.info(f"BaselineClaudeCodeAgent: Sourcegraph skill install output: {result.stdout[:200] if result.stdout else 'no output'}")

    async def _setup_sourcegraph_mcp(self, environment: BaseEnvironment) -> None:
        """Configure Sourcegraph MCP with all tools (keyword, NLS, Deep Search)."""
        # Set NODE_TLS_REJECT_UNAUTHORIZED globally in container for MCP subprocess
        # This works around Node.js fetch() SSL certificate validation issues in Docker
        await environment.exec('export NODE_TLS_REJECT_UNAUTHORIZED=0')
        logger.info("BaselineClaudeCodeAgent: Set NODE_TLS_REJECT_UNAUTHORIZED=0 globally for MCP")
        
        # Install the Sourcegraph skill to teach the agent how to use MCP tools effectively
        await self._install_sourcegraph_skill(environment)
        
        # Detect the correct working directory
        # - swebench-verified uses /testbed
        # - swebenchpro uses /app
        # - big_code_mcp uses /workspace
        # Use simple file existence check that avoids bash startup noise
        workspace_check = await environment.exec('[ -d /workspace ] && echo EXISTS')
        app_check = await environment.exec('[ -d /app ] && echo EXISTS')
        testbed_check = await environment.exec('[ -d /testbed ] && echo EXISTS')

        # Check for "EXISTS" in output (may contain bash startup noise)
        if workspace_check.stdout and "EXISTS" in workspace_check.stdout:
            workdir = "/workspace"
        elif app_check.stdout and "EXISTS" in app_check.stdout:
            workdir = "/app"
        elif testbed_check.stdout and "EXISTS" in testbed_check.stdout:
            workdir = "/testbed"
        else:
            workdir = "/workspace"  # Default fallback (most common)
        logger.info(f"BaselineClaudeCodeAgent: Detected working directory: {workdir}")

        # Default to public Sourcegraph instance
        sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
        sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""

        if not sg_token:
            logger.warning("SOURCEGRAPH_ACCESS_TOKEN not found. Skipping MCP setup.")
            return

        if not sg_url.startswith(("http://", "https://")):
            sg_url = f"https://{sg_url}"
        sg_url = sg_url.rstrip("/")

        # Sourcegraph HTTP MCP config
        # Note: SSL workaround (NODE_TLS_REJECT_UNAUTHORIZED=0) is set in command environment
        mcp_config = {
            "mcpServers": {
                "sourcegraph": {
                    "type": "http",
                    "url": f"{sg_url}/.api/mcp/v1",
                    "headers": {"Authorization": f"token {sg_token}"}
                }
            }
        }

        mcp_config_path = self.logs_dir / ".mcp.json"
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

        # Create the config directory in the container first
        await environment.exec("mkdir -p /logs/agent/sessions")

        # Upload to CLAUDE_CONFIG_DIR (where Claude Code looks for MCP config)
        # Harbor sets CLAUDE_CONFIG_DIR=/logs/agent/sessions
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info(f"BaselineClaudeCodeAgent: Sourcegraph MCP configured at /logs/agent/sessions/ ({sg_url})")

        # Get repo display name for CLAUDE.md
        repo_display = self._get_repo_display()

        # Upload CLAUDE.md with Sourcegraph instructions
        claude_md_content = f"""## Task Execution
Follow the test-first workflow from your system instructions.

# Sourcegraph MCP: Code Discovery Workflow

        ## Available Tools

        You have **only** these tools available for this task:
        - `Bash` - For running commands (tests, compilation)
        - `Read` - For reading files
        - `Edit` - For editing files

        **Note:** Grep, Glob, and shell search commands (grep/rg/ag/find/fd) are NOT available.

        ## MCP Tools (use these for code discovery)

        - `mcp__sourcegraph__sg_keyword_search` - Find code by exact string/regex matching
        - `mcp__sourcegraph__sg_nls_search` - Find code by natural language description
        - `mcp__sourcegraph__sg_read_file` - Read indexed files from Sourcegraph

        ## 🎯 CRITICAL - ALWAYS USE THE CORRECT REPOSITORY FILTER

        **You are working in: {repo_display}**

        When making sg_keyword_search queries, ALWAYS include the repo: filter with the EXACT name:
        - ✅ CORRECT: `repo:^github.com/{repo_display}$ YourSearchTerm`
        - ❌ WRONG: Guessing the repo name or omitting parts (e.g., dropping `--latest` suffix)

        ## Recommended Workflow

        1. **Start with MCP search** to locate relevant files and understand code structure
        - Use `mcp__sourcegraph__sg_keyword_search()` for specific symbols/strings
        - Use `mcp__sourcegraph__sg_nls_search()` for conceptual queries
        - Always use `repo:^github.com/{repo_display}$` filter in keyword searches

        2. **Read relevant files** using the `Read` tool
        - Only open files identified by MCP search
        - Avoid random exploration (search tools are blocked)

        3. **Make changes** using the `Edit` tool

        4. **Verify** using the `Bash` tool (tests, compilation)

        ## ⚠️ CRITICAL WARNING: COMMIT VERSION MISMATCH ⚠️

        **Sourcegraph MCP indexes the LATEST code on the default branch (main/master), but you are working on a HISTORICAL commit (the base_commit in the task description).**

        This means MCP search results may show:
        - Fields/types that don't exist yet in your working copy
        - Function signatures that have changed
        - Code that already has the bug fixed (in the newer version)

        ### MANDATORY VERIFICATION STEPS:
        1. After EVERY MCP search query, use `Read` to verify the actual file contents
        2. If MCP shows `*time.Time` but local code has `time.Time` - TRUST LOCAL CODE
        3. Check the `base_commit` in your task - you are working at that specific point in history
        4. NEVER trust MCP code snippets for exact syntax - always verify locally with Read

        ### Example of the problem:
        - MCP might say: `CreatedAt *time.Time` (from the fixed version)
        - Your local code actually has: `CreatedAt time.Time` (the unfixed version you're working on)
        - If you don't verify, you'll write incorrect code!
        """

        claude_md_path = self.logs_dir / "CLAUDE.md"
        with open(claude_md_path, "w") as f:
            f.write(claude_md_content)

        await environment.upload_file(
            source_path=claude_md_path, target_path=f"{workdir}/CLAUDE.md"
        )
        logger.info("=" * 80)
        logger.info("CLAUDE.MD UPLOADED - SOURCEGRAPH MODE")
        logger.info(f"Target path: {workdir}/CLAUDE.md")
        logger.info(f"Content size: {len(claude_md_content)} chars")
        logger.info("Instructions include: MCP workflow guidance (test-first via system prompt)")
        logger.info("=" * 80)

    async def _setup_sourcegraph_full_mcp(self, environment: BaseEnvironment, mcp_type: str = "sourcegraph_full") -> None:
        """Configure Sourcegraph MCP with all local tools available (hybrid approach).

        Uses the same /.api/mcp/v1 endpoint as sourcegraph mode but does NOT block
        local search tools. The system prompt enforces MCP-first usage through
        strong mandatory instructions rather than tool restrictions.

        For sourcegraph_base, the CLAUDE.md omits deep search tools from
        guidance (the actual blocking is done via --disallowedTools in create_run_agent_commands).
        """
        # Set NODE_TLS_REJECT_UNAUTHORIZED globally in container for MCP subprocess
        await environment.exec('export NODE_TLS_REJECT_UNAUTHORIZED=0')
        logger.info("BaselineClaudeCodeAgent: Set NODE_TLS_REJECT_UNAUTHORIZED=0 globally for MCP")

        # Install the Sourcegraph skill to teach the agent how to use MCP tools effectively
        await self._install_sourcegraph_skill(environment)

        # Detect the correct working directory
        workspace_check = await environment.exec('[ -d /workspace ] && echo EXISTS')
        app_check = await environment.exec('[ -d /app ] && echo EXISTS')
        testbed_check = await environment.exec('[ -d /testbed ] && echo EXISTS')

        if workspace_check.stdout and "EXISTS" in workspace_check.stdout:
            workdir = "/workspace"
        elif app_check.stdout and "EXISTS" in app_check.stdout:
            workdir = "/app"
        elif testbed_check.stdout and "EXISTS" in testbed_check.stdout:
            workdir = "/testbed"
        else:
            workdir = "/workspace"
        logger.info(f"BaselineClaudeCodeAgent: Detected working directory for Sourcegraph Hybrid: {workdir}")

        # Default to public Sourcegraph instance
        sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
        sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""

        if not sg_token:
            logger.warning("SOURCEGRAPH_ACCESS_TOKEN not found. Skipping MCP setup.")
            return

        if not sg_url.startswith(("http://", "https://")):
            sg_url = f"https://{sg_url}"
        sg_url = sg_url.rstrip("/")

        # Full Sourcegraph MCP config (same endpoint as sourcegraph mode)
        mcp_config = {
            "mcpServers": {
                "sourcegraph": {
                    "type": "http",
                    "url": f"{sg_url}/.api/mcp/v1",
                    "headers": {"Authorization": f"token {sg_token}"}
                }
            }
        }

        mcp_config_path = self.logs_dir / ".mcp.json"
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

        # Create the config directory in the container first
        await environment.exec("mkdir -p /logs/agent/sessions")

        # Upload to CLAUDE_CONFIG_DIR
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info(f"BaselineClaudeCodeAgent: Sourcegraph Hybrid MCP configured at /logs/agent/sessions/ ({sg_url})")
        # No CLAUDE.md uploaded — V4 preamble in instruction text provides all MCP guidance.

    async def _setup_deepsearch_mcp(self, environment: BaseEnvironment) -> None:
        """Configure Deep Search-only MCP endpoint."""
        # Install the Sourcegraph skill to teach the agent how to use MCP tools effectively
        await self._install_sourcegraph_skill(environment)
        
        # Detect the correct working directory
        # - swebench-verified uses /testbed
        # - swebenchpro uses /app
        # - big_code_mcp uses /workspace
        workspace_check = await environment.exec('[ -d /workspace ] && echo EXISTS')
        app_check = await environment.exec('[ -d /app ] && echo EXISTS')
        testbed_check = await environment.exec('[ -d /testbed ] && echo EXISTS')

        if workspace_check.stdout and "EXISTS" in workspace_check.stdout:
            workdir = "/workspace"
        elif app_check.stdout and "EXISTS" in app_check.stdout:
            workdir = "/app"
        elif testbed_check.stdout and "EXISTS" in testbed_check.stdout:
            workdir = "/testbed"
        else:
            workdir = "/workspace"  # Default fallback (most common)
        logger.info(f"BaselineClaudeCodeAgent: Detected working directory for DeepSearch: {workdir}")

        # Check for dedicated Deep Search endpoint first
        deepsearch_url = os.environ.get("DEEPSEARCH_MCP_URL") or ""
        deepsearch_token = os.environ.get("DEEPSEARCH_MCP_TOKEN") or ""

        # Fall back to Sourcegraph with Deep Search path
        if not deepsearch_url:
            sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
            sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""

            if sg_token:
                if not sg_url.startswith(("http://", "https://")):
                    sg_url = f"https://{sg_url}"
                deepsearch_url = sg_url.rstrip("/") + "/.api/mcp/deepsearch"
                deepsearch_token = sg_token

        if not deepsearch_url or not deepsearch_token:
            logger.warning("Deep Search credentials not found. Skipping MCP setup.")
            return

        if not deepsearch_url.startswith(("http://", "https://")):
            deepsearch_url = f"https://{deepsearch_url}"
        deepsearch_url = deepsearch_url.rstrip("/")

        # Extract repo and commit info from environment (set by task runner)
        # Format: repo--commit (e.g., NodeBB--f1a80d48)
        repo_info = os.environ.get("SWEBENCH_REPO_COMMIT", "")
        repo_name = ""
        commit = ""
        sg_benchmarks_org = "sg-benchmarks"
        if repo_info and "--" in repo_info:
            repo_name, commit = repo_info.split("--", 1)
            logger.info(f"BaselineClaudeCodeAgent: Deep Search MCP will use sg-benchmarks repo={repo_name}, commit={commit}")

        # Deep Search MCP config - add sg-benchmarks org and repo info if available
        deepsearch_config = {
            "type": "http",
            "url": deepsearch_url,
            "headers": {"Authorization": f"token {deepsearch_token}"},
        }
        
        # Add sg-benchmarks org and repo hint to the config if we have repo info
        if repo_name:
            deepsearch_config["org"] = sg_benchmarks_org
            deepsearch_config["repo"] = repo_name
            deepsearch_config["commit"] = commit
        
        mcp_config = {
            "mcpServers": {
                "deepsearch": deepsearch_config
            }
        }

        mcp_config_path = self.logs_dir / ".mcp.json"
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

        # Create the config directory in the container first
        await environment.exec("mkdir -p /logs/agent/sessions")

        # Upload to CLAUDE_CONFIG_DIR (where Claude Code looks for MCP config)
        # Harbor sets CLAUDE_CONFIG_DIR=/logs/agent/sessions
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info(f"BaselineClaudeCodeAgent: Deep Search MCP configured at /logs/agent/sessions/ ({deepsearch_url})")

        # Get repo display name for CLAUDE.md
        repo_display = self._get_repo_display()

        # Upload CLAUDE.md using template
        if LOCOBENCH_CLAUDE_MD_TEMPLATE.exists():
            # Read template and perform placeholder substitution
            template_content = LOCOBENCH_CLAUDE_MD_TEMPLATE.read_text()
            claude_md_content = template_content.replace("[repo-name]", repo_display)
            logger.info(f"BaselineClaudeCodeAgent: Using CLAUDE.md template with repo: {repo_display}")
        else:
            # Fallback to inline content if template doesn't exist
            logger.warning(f"BaselineClaudeCodeAgent: CLAUDE.md template not found at {LOCOBENCH_CLAUDE_MD_TEMPLATE}, using fallback")
            claude_md_content = f"""## Task Execution
Follow the test-first workflow from your system instructions.

# Deep Search MCP: Code Discovery Workflow

## Available Tools

You have **only** these tools available for this task:
- `Bash` - For running commands (tests, compilation)
- `Read` - For reading files
- `Edit` - For editing files

**Note:** Grep, Glob, and shell search commands (grep/rg/ag/find/fd) are NOT available.

## MCP Tool (use this for code discovery)

- `mcp__deepsearch__deepsearch` - Deep semantic code search (understands relationships and context)

## 🎯 CRITICAL - ALWAYS REFERENCE THE CORRECT REPOSITORY

**You are working in: {repo_display}**

When making Deep Search queries, you MUST explicitly reference this repository name:
- ✅ CORRECT: "In {repo_display}, where is [code]?"
- ✅ CORRECT: "Search {repo_display} for [query]"
- ❌ WRONG: "In the codebase, where..." (too vague)
"""

        claude_md_path = self.logs_dir / "CLAUDE.md"
        with open(claude_md_path, "w") as f:
            f.write(claude_md_content)

        await environment.upload_file(
            source_path=claude_md_path, target_path=f"{workdir}/CLAUDE.md"
        )
        logger.info("=" * 80)
        logger.info("CLAUDE.MD UPLOADED - DEEPSEARCH MODE")
        logger.info(f"Target path: {workdir}/CLAUDE.md")
        logger.info(f"Content size: {len(claude_md_content)} chars")
        logger.info("Instructions include: MCP workflow guidance (test-first via system prompt)")
        logger.info("=" * 80)

    async def _setup_deepsearch_hybrid_mcp(self, environment: BaseEnvironment) -> None:
        """Configure Deep Search MCP with strategic local search fallback (hybrid approach)."""
        # Install the Sourcegraph skill to teach the agent how to use MCP tools effectively
        await self._install_sourcegraph_skill(environment)
        
        # Detect the correct working directory
        # - swebench-verified uses /testbed
        # - swebenchpro uses /app
        # - big_code_mcp uses /workspace
        workspace_check = await environment.exec('[ -d /workspace ] && echo EXISTS')
        app_check = await environment.exec('[ -d /app ] && echo EXISTS')
        testbed_check = await environment.exec('[ -d /testbed ] && echo EXISTS')

        if workspace_check.stdout and "EXISTS" in workspace_check.stdout:
            workdir = "/workspace"
        elif app_check.stdout and "EXISTS" in app_check.stdout:
            workdir = "/app"
        elif testbed_check.stdout and "EXISTS" in testbed_check.stdout:
            workdir = "/testbed"
        else:
            workdir = "/workspace"  # Default fallback (most common)
        logger.info(f"BaselineClaudeCodeAgent: Detected working directory for Deep Search Hybrid: {workdir}")

        # Check for dedicated Deep Search endpoint first
        deepsearch_url = os.environ.get("DEEPSEARCH_MCP_URL") or ""
        deepsearch_token = os.environ.get("DEEPSEARCH_MCP_TOKEN") or ""

        # Fall back to Sourcegraph with Deep Search path
        if not deepsearch_url:
            sg_url = os.environ.get("SOURCEGRAPH_URL") or os.environ.get("SRC_ENDPOINT") or "https://sourcegraph.sourcegraph.com"
            sg_token = os.environ.get("SOURCEGRAPH_ACCESS_TOKEN") or os.environ.get("SRC_ACCESS_TOKEN") or ""

            if sg_token:
                if not sg_url.startswith(("http://", "https://")):
                    sg_url = f"https://{sg_url}"
                deepsearch_url = sg_url.rstrip("/") + "/.api/mcp/deepsearch"
                deepsearch_token = sg_token

        if not deepsearch_url or not deepsearch_token:
            logger.warning("Deep Search credentials not found. Skipping MCP setup.")
            return

        if not deepsearch_url.startswith(("http://", "https://")):
            deepsearch_url = f"https://{deepsearch_url}"
        deepsearch_url = deepsearch_url.rstrip("/")

        # Extract repo and commit info from environment (set by task runner)
        # Format: repo--commit (e.g., NodeBB--f1a80d48)
        repo_info = os.environ.get("SWEBENCH_REPO_COMMIT", "")
        repo_name = ""
        commit = ""
        sg_benchmarks_org = "sg-benchmarks"
        if repo_info and "--" in repo_info:
            repo_name, commit = repo_info.split("--", 1)
            logger.info(f"BaselineClaudeCodeAgent: Hybrid Deep Search MCP will use sg-benchmarks repo={repo_name}, commit={commit}")

        # Deep Search MCP config (same as deepsearch mode) - add sg-benchmarks org and repo info if available
        deepsearch_config = {
            "type": "http",
            "url": deepsearch_url,
            "headers": {"Authorization": f"token {deepsearch_token}"},
        }
        
        # Add sg-benchmarks org and repo hint to the config if we have repo info
        if repo_name:
            deepsearch_config["org"] = sg_benchmarks_org
            deepsearch_config["repo"] = repo_name
            deepsearch_config["commit"] = commit
        
        mcp_config = {
            "mcpServers": {
                "deepsearch": deepsearch_config
            }
        }

        mcp_config_path = self.logs_dir / ".mcp.json"
        with open(mcp_config_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

        # Create the config directory in the container first
        await environment.exec("mkdir -p /logs/agent/sessions")

        # Upload to CLAUDE_CONFIG_DIR (where Claude Code looks for MCP config)
        await environment.upload_file(
            source_path=mcp_config_path, target_path="/logs/agent/sessions/.mcp.json"
        )
        logger.info(f"BaselineClaudeCodeAgent: Hybrid Deep Search MCP configured at /logs/agent/sessions/ ({deepsearch_url}) with sg-benchmarks org")

        # Get repo display name for CLAUDE.md
        repo_display = self._get_repo_display()

        # Upload CLAUDE.md with hybrid strategy instructions
        claude_md_content = f"""## Task Execution
Follow the test-first workflow from your system instructions.

# Deep Search MCP with Hybrid Strategy: Code Discovery Workflow

        ## Available Tools

        You have **ALL** of these tools available:
        - `Bash` - For running commands (tests, compilation, local search)
        - `Read` - For reading files
        - `Edit` - For editing files
        - `Grep` - For local pattern matching
        - `Glob` - For local file pattern matching
        - `mcp__deepsearch__deepsearch` - For deep semantic code search

        ## 🎯 CRITICAL - ALWAYS REFERENCE THE CORRECT REPOSITORY

        **You are working in: {repo_display}**

        When making Deep Search queries, you MUST explicitly reference this repository name:
        - ✅ CORRECT: "In {repo_display}, where is [code]?"
        - ✅ CORRECT: "Search {repo_display} for [query]"
        - ❌ WRONG: "In the codebase, where..." (too vague)
        - ❌ WRONG: "In navidrome, where..." (searches original, not sg-benchmarks mirror)

        ## SG-BENCHMARKS ORG - COMMIT-MATCHED SEARCH

        🎯 **Deep Search is configured to search within the **sg-benchmarks** GitHub organization.**

        This organization contains mirrors of all benchmark repositories with:
        - HEAD pinned to the exact same commit as your local working copy
        - Full indexing for Deep Search semantic understanding
        - Results that match your actual local code (NO version mismatches!)

        ## Strategic Hybrid Approach

        Use this decision logic to pick the right tool:

        ### When to Use Deep Search MCP First (sg-benchmarks org):
        1. **Bug localization** - "In {repo_display}, where in the code does [error/behavior] occur?"
        2. **Error path discovery** - "In {repo_display}, what code handles [specific error condition]?"
        3. **Data flow tracing** - "In {repo_display}, how does data flow from [source] to [destination]?"
        4. **Feature implementation** - "In {repo_display}, what files implement [feature/functionality]?"
        5. **Failure analysis** - "In {repo_display}, what code could cause [test failure/error message]?"

        ### When to Use Local Search (Grep/Glob/Bash):
        1. **Quick file existence** - "Does `src/handler.ts` exist?"
        2. **Pattern verification** - "Is the exact string 'NULL' in this file?"
        3. **File type filtering** - "Find all `*_test.go` files"
        4. **Rapid exploration** - Quickly scan files to understand context
        5. **Verification** - Confirm Deep Search findings in actual code

        ## Effective Deep Search Query Patterns for Bug Fixing

        ### Pattern 1: Error-Focused Discovery
        **Problem:** You see an error message or exception
        **Query:** "In {repo_display}, where is the code that handles/throws [specific error]?"
        **Example:** "In {repo_display}, where do we handle NULL values from the database?"
        **Why:** Leads directly to the bug manifestation point

        ### Pattern 2: Data Flow Tracing
        **Problem:** Data is corrupted or missing at a certain point
        **Query:** "In {repo_display}, how does [field/variable] flow from [source] to [location]?"
        **Example:** "In {repo_display}, how does the external_info_updated_at field get populated from the database?"
        **Why:** Identifies where the bug enters the system

        ### Pattern 3: Test-Guided Discovery
        **Problem:** Tests are failing but you don't know why
        **Query:** "In {repo_display}, what code would cause [test expectation] to fail?"
        **Example:** "In {repo_display}, what code fails when timestamp fields are NULL?"
        **Why:** Test failures pinpoint the actual bug location

        ### Pattern 4: Handler/Processor Discovery
        **Problem:** You need to understand how a specific type of data is processed
        **Query:** "In {repo_display}, what code processes/handles [data type/scenario]?"
        **Example:** "In {repo_display}, what code processes NULL values when reading from the database?"
        **Why:** Finds the critical path where the bug lives

        ## Recommended Bug-Fixing Workflow

        1. **Understand the failure**
           - Read error messages, stack traces, test output
           - Use Bash to run failing tests (get full context)
           - Identify what's broken: data, logic, handling?

        2. **Use Deep Search to locate the bug**
           - **Start with error-focused queries:** "In {repo_display}, where do we handle this error?"
           - **Trace data flow:** "In {repo_display}, how does this field get processed?"
           - **Find handlers:** "In {repo_display}, what code deals with this scenario?"
           - **ALWAYS include repository reference in queries**
           - Don't ask architecture questions - ask bug-finding questions

        3. **Verify with local tools**
           - Use `Read` to examine files Deep Search identified
           - Use `Bash` to verify the error occurs in that exact location
           - Use `Grep` to find related code patterns nearby

        4. **Implement the fix**
           - Make targeted edits to the identified location
           - Run tests to verify (use `Bash`)
           - If tests still fail, iterate: use Deep Search again with better queries

        5. **Iterate if first attempt fails**
           - First Deep Search didn't help? Try different query:
              - Instead of: "In {repo_display}, where is the Album struct?"
              - Try: "In {repo_display}, what code fails when Album.ExternalInfoUpdatedAt is NULL?"
            - Use local Bash exploration to gather clues for better Deep Search queries

        ## Deep Search Query Anti-Patterns (Don't Do These)

        ❌ **Too architectural:** "Where are the model structs defined?"
           → Answers: "They're in model/ directory" (not helpful for bugs)
           → Better: "What code fails when these struct fields are NULL?"

        ❌ **Too vague:** "Tell me about the Album model"
           → Answers: Huge amount of unfocused context
           → Better: "What happens when Album.ExternalInfoUpdatedAt is NULL?"

        ❌ **Assumes you know the location:** "How should I fix this in album.go?"
           → Problem: You haven't found the actual bug location yet
           → Better: Start with "Where does this error occur?"

        ❌ **No error context:** "Where should I add NULL handling?"
           → Problem: You don't know what to handle yet
           → Better: "What code currently breaks when values are NULL?"

        ## Example: From Error to Fix

        **Scenario:** Tests fail with "panic: time.Time cannot be nil"

        1. Read the test failure and error message ✓
        2. **Deep Search Query:** "What code panics when a time.Time field is NULL from the database?"
           → Returns: Folder.go, line 42, ImagesUpdatedAt field handling
        3. **Read** Folder.go to see the problem (non-pointer time.Time) ✓
        4. **Deep Search (if needed):** "Where else do we have non-nullable timestamp fields?"
           → Find other similar issues
        5. **Edit** to change non-pointer to pointer time.Time ✓
        6. **Bash** to run tests and verify ✓

        ## Critical: Iterate on Queries

        If Deep Search results don't help:
        1. ❌ Don't give up and use only local search
        2. ✅ Refine your query with more context:
           - Add error messages: "Where does the error '[exact message]' occur?"
           - Add data context: "What handles [specific field] when it's NULL?"
           - Add test context: "What code makes [test name] fail?"

        ## Why This Matters

        With sg-benchmarks org correctly configured:
        - Deep Search results are **accurate** (same commit as your code)
        - Deep Search understands **relationships** (not just text matching)
        - You have **full tool access** (hybrid: MCP + local tools)
        - The combination is **more powerful than either alone**

        Use these patterns to leverage Deep Search's semantic understanding for faster bug discovery.
        """

        claude_md_path = self.logs_dir / "CLAUDE.md"
        with open(claude_md_path, "w") as f:
            f.write(claude_md_content)

        await environment.upload_file(
            source_path=claude_md_path, target_path=f"{workdir}/CLAUDE.md"
        )
        logger.info("=" * 80)
        logger.info("CLAUDE.MD UPLOADED - DEEPSEARCH HYBRID MODE")
        logger.info(f"Target path: {workdir}/CLAUDE.md")
        logger.info(f"Content size: {len(claude_md_content)} chars")
        logger.info("Instructions include: MCP workflow guidance (test-first via system prompt)")
        logger.info("=" * 80)

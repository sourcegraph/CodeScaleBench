"""
Kubernetes Documentation Benchmark Agent Variants.

These agents are specialized for the documentation generation benchmark,
which requires filtering out documentation files from Sourcegraph search results.

The key difference from standard MCP agents is that these agents:
1. Add query filters to exclude README.md, KEP, and design doc files
2. Include prompt constraints about not using the target package's doc.go
3. Focus on code-based inference rather than finding existing docs
"""

from typing import Any, Dict, Optional

# Import base agents
try:
    from agents.mcp_variants import DeepSearchFocusedAgent, MCPNonDeepSearchAgent
    from agents.claude_baseline_agent import BaselineClaudeCodeAgent
except ImportError:
    # Fallback for testing
    DeepSearchFocusedAgent = object
    MCPNonDeepSearchAgent = object
    BaselineClaudeCodeAgent = object


# Query filter suffix for excluding documentation.
# NOTE: We only exclude the target doc.go via CLAUDE.md constraints, NOT all doc.go files.
# Agents CAN and SHOULD find other packages' doc.go to understand conventions.
DOC_FILTER_SUFFIX = (
    "repo:^github\\.com/.*kubernetes-stripped$ "
    "-file:README.md -file:README -file:DESIGN.md "
    "-file:CONTRIBUTING.md -file:CHANGELOG "
    "-repo:kubernetes/enhancements -repo:kubernetes/website "
    "-repo:kubernetes/community -path:docs/ -path:examples/"
)


# System prompt additions for documentation benchmark
DOC_BENCHMARK_CONSTRAINTS = """
## Documentation Benchmark Constraints

You are participating in a documentation generation benchmark. The goal is to
test your ability to understand code and generate accurate documentation.

### STRICT RULES - You MUST follow these:

1. **ONLY search the kubernetes-stripped repository** - This repository has been
   specially prepared for this benchmark.
2. **DO NOT find or use the doc.go for the TARGET package** - The specific target
   package's documentation has been removed and is the ground truth you must recreate.
   Check CLAUDE.md for which package is the target.
3. **DO NOT USE README.md files** - These may contain answers.
4. **DO NOT CITE KEPs** - Enhancement proposals are off-limits.
5. **DO NOT USE kubernetes/enhancements repository** - Contains design docs.

### What you CAN use:

- Source code files (*.go)
- Test files (*_test.go) - these show expected behavior
- API type definitions in staging/src/k8s.io/api/
- Configuration and utility files
- doc.go files from OTHER packages (not the target) - to understand conventions
  and cross-package relationships

### Query Filtering

When using Sourcegraph search tools, your queries will be automatically filtered
to target ONLY the `kubernetes-stripped` repository and exclude certain documentation files.
This is enforced at the query level.
"""


class DocBenchmarkDeepSearchAgent(DeepSearchFocusedAgent):
    """
    Deep Search agent variant for documentation benchmarks.

    This agent adds documentation filters to all Sourcegraph queries
    and includes constraints in the system prompt.
    """

    @classmethod
    def get_system_prompt_additions(cls) -> str:
        """Add documentation benchmark constraints to system prompt."""
        base_additions = super().get_system_prompt_additions()
        return f"{base_additions}\n\n{DOC_BENCHMARK_CONSTRAINTS}"

    def _filter_query(self, query: str) -> str:
        """Add documentation exclusion filters to a query."""
        # Don't add filters if they're already present
        if "-file:README.md" in query:
            return query
        return f"{query} {DOC_FILTER_SUFFIX}"

    async def deep_search(self, question: str, **kwargs) -> Dict[str, Any]:
        """Execute Deep Search with documentation filtering."""
        # Add context to the question about what to exclude
        filtered_question = f"""
{question}

IMPORTANT: Focus on source code files. Do NOT include or reference:
- README.md files
- KEP documents
- Design documents

You may reference doc.go files from packages OTHER than the target package
to understand conventions and cross-package relationships.
Base your analysis primarily on implementation code.
"""
        return await super().deep_search(filtered_question, **kwargs)

    async def keyword_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Execute keyword search with documentation filters."""
        filtered_query = self._filter_query(query)
        return await super().keyword_search(filtered_query, **kwargs)


class DocBenchmarkKeywordOnlyAgent(MCPNonDeepSearchAgent):
    """
    Keyword-only search agent for documentation benchmarks.

    Uses only keyword and NLS search (no Deep Search) with documentation filters.
    """

    @classmethod
    def get_system_prompt_additions(cls) -> str:
        """Add documentation benchmark constraints to system prompt."""
        base_additions = super().get_system_prompt_additions()
        return f"{base_additions}\n\n{DOC_BENCHMARK_CONSTRAINTS}"

    def _filter_query(self, query: str) -> str:
        """Add documentation exclusion filters to a query."""
        if "-file:README.md" in query:
            return query
        return f"{query} {DOC_FILTER_SUFFIX}"

    async def keyword_search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Execute keyword search with documentation filters."""
        filtered_query = self._filter_query(query)
        return await super().keyword_search(filtered_query, **kwargs)


class DocBenchmarkBaselineAgent(BaselineClaudeCodeAgent):
    """
    Baseline agent for documentation benchmarks.

    This agent has NO MCP tools - it can only work with local files.
    Included for comparison against MCP-enabled agents.
    """

    @classmethod
    def get_system_prompt_additions(cls) -> str:
        """Add documentation benchmark context to system prompt."""
        base_additions = super().get_system_prompt_additions()
        return f"""{base_additions}

## Documentation Generation Task

You are generating documentation for a Kubernetes package. You only have access
to the local source code files provided in the workspace.

Your task is to:
1. Read and understand the code implementation
2. Generate comprehensive documentation (doc.go or README.md format)
3. Cover: purpose, architecture, key concepts, usage, and edge cases

You do NOT have access to:
- Sourcegraph search tools
- External documentation
- KEPs or design documents

Demonstrate your ability to understand code and infer documentation from
implementation details alone.
"""


# Agent mapping for benchmark runner
DOC_BENCHMARK_AGENTS = {
    "baseline": DocBenchmarkBaselineAgent,
    "deep-search": DocBenchmarkDeepSearchAgent,
    "keyword-only": DocBenchmarkKeywordOnlyAgent,
}


def get_agent_class(agent_name: str):
    """Get agent class by name for benchmark runner."""
    if agent_name not in DOC_BENCHMARK_AGENTS:
        raise ValueError(
            f"Unknown agent: {agent_name}. "
            f"Available: {list(DOC_BENCHMARK_AGENTS.keys())}"
        )
    return DOC_BENCHMARK_AGENTS[agent_name]


if __name__ == "__main__":
    print("Documentation Benchmark Agent Variants")
    print("=" * 50)
    print()
    print("Available agents:")
    for name, cls in DOC_BENCHMARK_AGENTS.items():
        print(f"  {name}: {cls.__name__}")
    print()
    print("Query filter suffix:")
    print(f"  {DOC_FILTER_SUFFIX}")
    print()
    print("These agents are designed to work with Sourcegraph's cloud index")
    print("while ensuring documentation files are filtered from search results.")

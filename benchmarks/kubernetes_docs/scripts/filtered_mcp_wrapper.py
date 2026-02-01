#!/usr/bin/env python3
"""
Filtered MCP Wrapper for Documentation Benchmark.

This wrapper intercepts Sourcegraph MCP tool responses and filters out
documentation files to ensure agents can't directly find the ground truth.

The wrapper:
1. Intercepts Deep Search and search results
2. Removes content from doc.go, README.md, and KEP files
3. Allows code-only results to pass through

Usage:
    This module provides a FilteredMCPClient that wraps the standard MCP client
    and can be used in place of the regular client for benchmark runs.

Design Rationale:
    Sourcegraph's cloud index contains all Kubernetes documentation. For a fair
    benchmark comparing baseline vs MCP-enabled agents, we need to ensure MCP
    tools can find related CODE patterns but not the documentation itself.
"""

import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class FilterConfig:
    """Configuration for what to filter from MCP responses."""

    # File patterns to completely exclude from results
    excluded_file_patterns: List[str] = field(
        default_factory=lambda: [
            r"doc\.go$",
            r"README\.md$",
            r"README$",
            r"DESIGN\.md$",
            r"CONTRIBUTING\.md$",
            r"CHANGELOG.*\.md$",
        ]
    )

    # Path patterns to exclude (e.g., KEPs directory)
    excluded_path_patterns: List[str] = field(
        default_factory=lambda: [
            r"keps/",
            r"docs/",
            r"examples/",
            r"website/",
            r"community/contributors/devel/",
        ]
    )

    # Repositories to exclude entirely
    excluded_repositories: List[str] = field(
        default_factory=lambda: [
            "kubernetes/enhancements",
            "kubernetes/website",
            "kubernetes/community",
        ]
    )

    # Allow specific paths even if they match exclusion patterns
    # (e.g., allow code in docs/ if it's actual implementation)
    allowed_overrides: List[str] = field(default_factory=list)


class MCPResponseFilter:
    """Filters MCP tool responses to remove documentation content."""

    def __init__(self, config: Optional[FilterConfig] = None):
        self.config = config or FilterConfig()
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        self._file_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.config.excluded_file_patterns
        ]
        self._path_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.config.excluded_path_patterns
        ]

    def should_exclude_file(self, filepath: str) -> bool:
        """Check if a file should be excluded from results."""
        # Check allowed overrides first
        for override in self.config.allowed_overrides:
            if override in filepath:
                return False

        # Check file patterns
        for pattern in self._file_patterns:
            if pattern.search(filepath):
                return True

        # Check path patterns
        for pattern in self._path_patterns:
            if pattern.search(filepath):
                return True

        return False

    def should_exclude_repository(self, repo: str) -> bool:
        """Check if an entire repository should be excluded."""
        return repo in self.config.excluded_repositories

    def filter_search_results(
        self, results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter a list of search results, removing documentation files."""
        filtered = []
        for result in results:
            repo = result.get("repository", "")
            filepath = result.get("path", result.get("file", ""))

            if self.should_exclude_repository(repo):
                continue

            if self.should_exclude_file(filepath):
                continue

            filtered.append(result)

        return filtered

    def filter_deep_search_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter a Deep Search response, removing documentation from context.

        Deep Search returns conversational responses with embedded code snippets
        and file references. We need to:
        1. Remove references to doc files from the response text
        2. Filter code snippets that are from doc files
        3. Preserve code-only context
        """
        filtered = response.copy()

        # Filter any 'sources' or 'references' lists
        if "sources" in filtered:
            filtered["sources"] = self.filter_search_results(filtered["sources"])

        if "references" in filtered:
            filtered["references"] = self.filter_search_results(filtered["references"])

        if "context" in filtered and isinstance(filtered["context"], list):
            filtered["context"] = self.filter_search_results(filtered["context"])

        # Filter the main response text to remove doc file mentions
        if "response" in filtered:
            filtered["response"] = self._redact_doc_references(filtered["response"])

        if "answer" in filtered:
            filtered["answer"] = self._redact_doc_references(filtered["answer"])

        return filtered

    def _redact_doc_references(self, text: str) -> str:
        """
        Redact references to documentation files from response text.

        This is a best-effort filter - it removes obvious doc file references
        but can't guarantee complete removal of documentation content that
        was already incorporated into the response.
        """
        # Remove file path references to doc files
        doc_file_pattern = r"`[^`]*(?:doc\.go|README\.md|README)[^`]*`"
        text = re.sub(doc_file_pattern, "[documentation file reference removed]", text)

        # Remove KEP references
        kep_pattern = r"(?:KEP-?\d+|keps/[^\s]+)"
        text = re.sub(kep_pattern, "[KEP reference removed]", text, flags=re.IGNORECASE)

        return text


def create_query_filter_suffix() -> str:
    """
    Generate a query suffix to exclude documentation files at the search level.

    This can be appended to Sourcegraph queries to filter results server-side,
    which is more efficient than post-filtering.

    Returns a string like: -file:README.md -repo:kubernetes/enhancements

    NOTE: We do NOT exclude doc.go globally. Agents CAN and SHOULD find other
    packages' doc.go to understand conventions. The target package's doc.go is
    excluded via task-specific constraints in CLAUDE.md.
    """
    exclusions = [
        "-file:README.md",
        "-file:README",
        "-file:DESIGN.md",
        "-file:CONTRIBUTING.md",
        "-file:CHANGELOG",
        "-repo:kubernetes/enhancements",
        "-repo:kubernetes/website",
        "-repo:kubernetes/community",
        "-path:docs/",
        "-path:examples/",
    ]
    return " ".join(exclusions)


# Example usage in agent system prompt
FILTERED_SEARCH_INSTRUCTIONS = """
## Documentation Benchmark Constraints

For this documentation generation task, you must NOT use the following types of
sources when searching:

1. **The target package's doc.go** - This is the documentation you're being asked to generate
2. **README.md files** - These may contain ground truth documentation
3. **KEPs (Kubernetes Enhancement Proposals)** - Design documents we're testing if you can infer
4. **kubernetes/enhancements repository** - Contains KEPs
5. **kubernetes/website repository** - Contains user documentation

You MAY use:
- Source code files (*.go)
- doc.go files from OTHER packages (not the target package) to understand conventions
- Test files (for understanding behavior)
- API type definitions
- Configuration files

When using Deep Search or keyword search, add these filters to your queries:
-file:README.md -repo:kubernetes/enhancements

Your task is to demonstrate understanding of the code itself, not to find
existing documentation.
"""


class FilteredDeepSearchWrapper:
    """
    Wrapper for Deep Search that applies documentation filtering.

    This can be used in place of the standard Deep Search tool to ensure
    documentation files are not returned in results.
    """

    def __init__(self, base_client, filter_config: Optional[FilterConfig] = None):
        self.base_client = base_client
        self.filter = MCPResponseFilter(filter_config)
        self.query_suffix = create_query_filter_suffix()

    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Execute a filtered search."""
        # Append exclusion filters to query
        filtered_query = f"{query} {self.query_suffix}"

        # Execute search
        response = self.base_client.search(filtered_query, **kwargs)

        # Post-filter results
        return self.filter.filter_deep_search_response(response)

    def deep_search(self, question: str, **kwargs) -> Dict[str, Any]:
        """Execute a filtered Deep Search."""
        # For Deep Search, we add context about what to exclude
        filtered_question = f"""
        {question}

        Note: Exclude doc.go files, README files, and KEP documents from your analysis.
        Focus only on source code implementation.
        """

        # Execute Deep Search
        response = self.base_client.deep_search(filtered_question, **kwargs)

        # Post-filter results
        return self.filter.filter_deep_search_response(response)


if __name__ == "__main__":
    # Test the filter
    filter = MCPResponseFilter()

    test_files = [
        "pkg/scheduler/framework/plugins/podtopologyspread/plugin.go",
        "pkg/scheduler/framework/plugins/podtopologyspread/doc.go",
        "pkg/kubelet/cm/README.md",
        "keps/sig-scheduling/895-pod-topology-spread/README.md",
        "staging/src/k8s.io/api/core/v1/types.go",
    ]

    print("File filtering test:")
    for f in test_files:
        excluded = filter.should_exclude_file(f)
        status = "EXCLUDED" if excluded else "ALLOWED"
        print(f"  {status}: {f}")

    print("\nQuery filter suffix:")
    print(f"  {create_query_filter_suffix()}")

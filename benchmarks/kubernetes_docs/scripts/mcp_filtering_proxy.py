#!/usr/bin/env python3
"""
Deterministic MCP Filtering Proxy Server.

This proxy sits between the agent and Sourcegraph MCP server, intercepting
ALL requests and responses to ensure documentation files are filtered out.

Architecture:
    Agent  →  FilteringProxy  →  Sourcegraph MCP Server
              (we control)        (cloud)

The agent CANNOT bypass this filtering because:
1. The proxy is the only MCP endpoint the agent sees
2. All queries are modified before reaching Sourcegraph
3. All responses are filtered before reaching the agent

Usage:
    # Start the proxy server
    python mcp_filtering_proxy.py --port 8080 --upstream-url $SOURCEGRAPH_URL

    # Configure agent to use proxy instead of Sourcegraph directly
    export MCP_SERVER_URL=http://localhost:8080
"""

import asyncio
import json
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from aiohttp import web, ClientSession

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """Configuration for deterministic filtering.

    When target_file is set, only that specific file path is excluded from
    doc.go results. Other packages' doc.go files are allowed through so agents
    can learn conventions and cross-package relationships.
    """

    # Target file to exclude (task-specific, e.g. "staging/src/k8s.io/client-go/doc.go")
    target_file: Optional[str] = None

    # Sourcegraph query filters (appended to ALL queries)
    # NOTE: doc.go is NOT globally excluded — only the target_file is filtered from responses
    query_exclusions: List[str] = field(
        default_factory=lambda: [
            "-file:README\\.md$",
            "-file:README$",
            "-file:DESIGN\\.md$",
            "-file:CONTRIBUTING\\.md$",
            "-file:CHANGELOG",
            "-repo:kubernetes/enhancements",
            "-repo:kubernetes/website",
            "-repo:kubernetes/community",
            "-file:keps/",
            "-path:docs/",
            "-path:examples/",
        ]
    )

    # File patterns to remove from responses
    # NOTE: doc.go is NOT globally excluded — only the target_file is filtered
    excluded_file_patterns: List[str] = field(
        default_factory=lambda: [
            r"README\.md$",
            r"README$",
            r"DESIGN\.md$",
            r"CONTRIBUTING\.md$",
            r"CHANGELOG.*\.md$",
            r"/keps/",
            r"/docs/",
        ]
    )

    # Repositories to completely exclude
    excluded_repos: Set[str] = field(
        default_factory=lambda: {
            "kubernetes/enhancements",
            "kubernetes/website",
            "kubernetes/community",
        }
    )


class DeterministicFilter:
    """
    Deterministic filter that modifies queries and responses.

    This is the core filtering logic that ensures NO documentation
    content reaches the agent.
    """

    def __init__(self, config: Optional[FilterConfig] = None):
        self.config = config or FilterConfig()
        self._compile_patterns()
        self.stats = {
            "queries_modified": 0,
            "results_filtered": 0,
            "files_excluded": 0,
        }

    def _compile_patterns(self):
        """Pre-compile regex patterns."""
        self._file_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.config.excluded_file_patterns
        ]

    def get_query_suffix(self) -> str:
        """Get the filter suffix to append to queries."""
        return " " + " ".join(self.config.query_exclusions)

    def filter_query(self, query: str) -> str:
        """
        DETERMINISTICALLY modify a query to exclude documentation.

        This is called for EVERY query before it reaches Sourcegraph.
        """
        suffix = self.get_query_suffix()

        # Always append, even if query already has some filters
        # This ensures we can't be bypassed by clever query construction
        filtered = query + suffix

        self.stats["queries_modified"] += 1
        logger.debug(f"Filtered query: {query[:50]}... → added {len(suffix)} chars")

        return filtered

    def should_exclude_file(self, filepath: str) -> bool:
        """Check if a file should be excluded from results."""
        # Check target file (task-specific ground truth exclusion)
        if self.config.target_file and filepath.endswith(self.config.target_file):
            return True
        for pattern in self._file_patterns:
            if pattern.search(filepath):
                return True
        return False

    def should_exclude_repo(self, repo: str) -> bool:
        """Check if a repository should be excluded."""
        return repo in self.config.excluded_repos

    def filter_search_results(self, results: List[Dict]) -> List[Dict]:
        """
        DETERMINISTICALLY filter search results.

        Removes any results that reference documentation files.
        """
        filtered = []

        for result in results:
            repo = result.get("repository", result.get("repo", ""))
            filepath = result.get("path", result.get("file", result.get("name", "")))

            if self.should_exclude_repo(repo):
                self.stats["files_excluded"] += 1
                logger.debug(f"Excluded repo: {repo}")
                continue

            if self.should_exclude_file(filepath):
                self.stats["files_excluded"] += 1
                logger.debug(f"Excluded file: {filepath}")
                continue

            filtered.append(result)

        self.stats["results_filtered"] += 1
        return filtered

    def filter_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        DETERMINISTICALLY filter an MCP response.

        This handles various response formats from Sourcegraph MCP.
        """
        filtered = response.copy()

        # Filter result lists
        for key in ["results", "matches", "files", "references", "sources", "context"]:
            if key in filtered and isinstance(filtered[key], list):
                filtered[key] = self.filter_search_results(filtered[key])

        # Filter embedded file content in text responses
        if "text" in filtered:
            filtered["text"] = self._redact_doc_content(filtered["text"])

        if "content" in filtered:
            if isinstance(filtered["content"], str):
                filtered["content"] = self._redact_doc_content(filtered["content"])
            elif isinstance(filtered["content"], list):
                filtered["content"] = [
                    self._redact_doc_content(c) if isinstance(c, str) else c
                    for c in filtered["content"]
                ]

        # Filter Deep Search answer/response
        for key in ["answer", "response", "message"]:
            if key in filtered and isinstance(filtered[key], str):
                filtered[key] = self._redact_doc_content(filtered[key])

        return filtered

    def _redact_doc_content(self, text: str) -> str:
        """
        Redact documentation file content from text.

        This handles cases where Deep Search quotes from doc files.
        """
        # Remove file path references
        for pattern in self._file_patterns:
            # Match file paths in backticks or quotes
            text = re.sub(
                rf"`[^`]*{pattern.pattern}[^`]*`",
                "[FILTERED: documentation file]",
                text,
                flags=re.IGNORECASE,
            )

        # Remove code blocks that appear to be from doc files
        # This is heuristic but catches common patterns
        doc_block_patterns = [
            r"```go\s*//\s*Package\s+\w+\s+provides[^`]*```",  # doc.go style
            r"```markdown\s*#[^`]*KEP[^`]*```",  # KEP content
        ]
        for pattern in doc_block_patterns:
            text = re.sub(
                pattern, "[FILTERED: documentation content]", text, flags=re.IGNORECASE
            )

        return text


class MCPFilteringProxy:
    """
    HTTP/JSON-RPC proxy server that filters MCP requests/responses.

    This provides a deterministic filtering layer that the agent cannot bypass.
    """

    def __init__(
        self,
        upstream_url: str,
        access_token: str,
        filter_config: Optional[FilterConfig] = None,
        port: int = 8080,
    ):
        self.upstream_url = upstream_url.rstrip("/")
        self.access_token = access_token
        self.filter = DeterministicFilter(filter_config)
        self.port = port
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        """Set up proxy routes."""
        self.app.router.add_post("/mcp", self.handle_mcp_request)
        self.app.router.add_post("/.api/mcp", self.handle_mcp_request)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/stats", self.handle_stats)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({"status": "healthy", "filtering": "enabled"})

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Return filtering statistics."""
        return web.json_response(self.filter.stats)

    async def handle_mcp_request(self, request: web.Request) -> web.Response:
        """
        Handle an MCP request with deterministic filtering.

        1. Parse the incoming request
        2. Modify any queries to add exclusion filters
        3. Forward to upstream Sourcegraph
        4. Filter the response
        5. Return filtered response to agent
        """
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        logger.info(f"MCP request: method={body.get('method', 'unknown')}")

        # Filter the request (modify queries)
        filtered_request = self._filter_request(body)

        # Forward to upstream
        async with ClientSession() as session:
            headers = {
                "Authorization": f"token {self.access_token}",
                "Content-Type": "application/json",
            }

            async with session.post(
                f"{self.upstream_url}/.api/mcp", json=filtered_request, headers=headers
            ) as upstream_response:
                upstream_body = await upstream_response.json()

        # Filter the response
        filtered_response = self._filter_response(upstream_body)

        return web.json_response(filtered_response)

    def _filter_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Filter an outgoing MCP request."""
        filtered = request.copy()

        # Handle different MCP methods
        method = request.get("method", "")
        params = request.get("params", {})

        if "query" in params:
            params["query"] = self.filter.filter_query(params["query"])

        if "question" in params:
            # For Deep Search, we can't easily filter the question
            # but we'll filter the response
            pass

        if "search" in params:
            params["search"] = self.filter.filter_query(params["search"])

        filtered["params"] = params
        return filtered

    def _filter_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Filter an incoming MCP response."""
        if "result" in response:
            response["result"] = self.filter.filter_response(response["result"])

        if "error" in response:
            # Don't filter errors
            pass

        return response

    def run(self):
        """Start the proxy server."""
        logger.info(f"Starting MCP filtering proxy on port {self.port}")
        logger.info(f"Upstream: {self.upstream_url}")
        logger.info(f"Query filters: {self.filter.get_query_suffix()[:80]}...")
        web.run_app(self.app, port=self.port)


def main():
    import argparse
    import os

    parser = argparse.ArgumentParser(description="MCP Filtering Proxy")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument(
        "--upstream-url",
        default=os.environ.get("SOURCEGRAPH_URL", ""),
        help="Sourcegraph URL",
    )
    parser.add_argument(
        "--access-token",
        default=os.environ.get("SOURCEGRAPH_ACCESS_TOKEN", ""),
        help="Sourcegraph access token",
    )
    parser.add_argument(
        "--target-file",
        default=os.environ.get("TARGET_FILE", ""),
        help="Specific ground truth file path to exclude (e.g. staging/src/k8s.io/client-go/doc.go)",
    )
    args = parser.parse_args()

    if not args.upstream_url:
        print("Error: --upstream-url or SOURCEGRAPH_URL required")
        return 1

    if not args.access_token:
        print("Error: --access-token or SOURCEGRAPH_ACCESS_TOKEN required")
        return 1

    filter_config = None
    if args.target_file:
        filter_config = FilterConfig(target_file=args.target_file)

    proxy = MCPFilteringProxy(
        upstream_url=args.upstream_url,
        access_token=args.access_token,
        filter_config=filter_config,
        port=args.port,
    )
    proxy.run()
    return 0


if __name__ == "__main__":
    exit(main())

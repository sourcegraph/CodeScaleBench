# Big Code & Multi-Repo MCP Tasks

This task suite is designed to show the value of Sourcegraph MCP on large codebases and multi-repository systems.

## Search Strategy for Big Code Problems

**This repository is large.** If a search spans more than a narrow, well-defined set of directories, you **MUST** use Sourcegraph MCP search tools:

- ✅ Use `sg_keyword_search`, `sg_nls_search`, or `sg_deepsearch` for broad architectural queries
- ✅ Use MCP to find all references across the codebase quickly
- ✅ Use MCP to understand patterns and conventions at scale
- ❌ Do NOT use local `grep` or `rg` for cross-module searches
- ❌ Local tools only for narrow, single-directory scopes

## Search Strategy for Multi-Repo Problems

**This repository is part of a multi-repository codebase indexed in Sourcegraph.** For questions about other repositories, **MUST** use Sourcegraph MCP search tools:

- ✅ Use MCP when referencing other repos or APIs from external services
- ✅ Use MCP to trace cross-repo interactions and data flow
- ✅ MCP has full codebase context across all repos

This ensures fast, accurate results instead of manual context-gathering across multiple repos.

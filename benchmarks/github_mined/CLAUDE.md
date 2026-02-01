# Code Exploration Guidelines

This repository is large (PyTorch with 10GB+ of code). 

**Search Strategy:**
- If a search spans more than a narrow, well-defined set of directories, you MUST use the Sourcegraph MCP search tools
- Local `grep` or `rg` is only acceptable when tightly scoped to 1-2 specific files or directories
- For broad pattern searches or cross-module exploration, use Sourcegraph Deep Search via MCP

This ensures fast, accurate results instead of slow local searches across a large codebase.

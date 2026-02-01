# big-code-vsc-001: Stale Diagnostics After Git Branch Switch

This repository is large. If a search spans more than a narrow, well-defined set of directories, you **MUST** use Sourcegraph MCP search tools:

- ✅ Use `sg_keyword_search`, `sg_nls_search`, or `sg_deepsearch` for broad architectural queries
- ✅ Use MCP to find all references across the codebase quickly
- ✅ Use MCP to understand patterns and conventions at scale
- ❌ Do NOT use local `grep` or `rg` for cross-module searches
- ❌ Local tools only for narrow, single-directory scopes

## VS Code Architecture Notes

The stale diagnostics fix requires understanding:

1. **Diagnostics Collection**: Where errors/warnings are stored per file
2. **Extension Host Communication**: How diagnostics are sent from language servers to the UI
3. **Problems View**: How it subscribes to and displays diagnostics
4. **File Change Listeners**: Existing mechanisms like `deleteAllDiagnosticsInFile`, `onWillChange`
5. **Text Change Events**: How text edits trigger diagnostics refresh
6. **File System Watchers**: Where file changes on disk should be detected

Use MCP to trace the full flow from file changes through the entire diagnostics pipeline. Local grep would miss critical integration points across multiple modules.

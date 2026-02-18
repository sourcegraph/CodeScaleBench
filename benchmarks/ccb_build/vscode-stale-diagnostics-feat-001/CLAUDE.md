# big-code-vsc-001: Stale Diagnostics After Git Branch Switch

This repository is large. Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## VS Code Architecture Notes

The stale diagnostics fix requires understanding:

1. **Diagnostics Collection**: Where errors/warnings are stored per file
2. **Extension Host Communication**: How diagnostics are sent from language servers to the UI
3. **Problems View**: How it subscribes to and displays diagnostics
4. **File Change Listeners**: Existing mechanisms like `deleteAllDiagnosticsInFile`, `onWillChange`
5. **Text Change Events**: How text edits trigger diagnostics refresh
6. **File System Watchers**: Where file changes on disk should be detected

Trace the full flow from file changes through the entire diagnostics pipeline — critical integration points are spread across multiple modules.

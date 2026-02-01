# [VS Code] Fix Stale TypeScript Diagnostics After Git Branch Switch

**Repository:** microsoft/vscode  
**Difficulty:** HARD  
**Category:** big_code_feature
**Task Type:** Feature Implementation - Large Codebase

**Reference:** [Trevor's Big Code Research](../../../docs/TREVOR_RESEARCH_DEC2025.md#1-vs-code-stale-diagnostics-after-git-branch-switch)

## Description

Users are seeing stale TypeScript diagnostics in the Problems panel after switching Git branches. Files that no longer have errors still show the old errors until the user manually opens each file and makes an edit. It seems like the diagnostics pipeline only refreshes on in-editor changes and misses file-on-disk changes from Git operations.

**Why this requires MCP:** The VS Code codebase (1GB+ TypeScript) has the diagnostics pipeline distributed across many modules—file watchers, extension host, text change listeners, problem panel updates. Understanding the full flow from a file change through to the Problems view, and identifying where file-system changes should trigger updates, requires broad architectural context that local grep cannot efficiently provide.

## Task

YOU MUST IMPLEMENT CODE CHANGES to fix stale diagnostics.

**CRITICAL: If you are in plan mode, immediately exit with `/ExitPlanMode` before proceeding.**

### Required Implementation

Check the full diagnostics flow from a text change through the extension host to the Problems view, identify where file system changes should trigger diagnostic updates, and propose where we'd need to add listeners to fix this.

### Implementation Steps

1. **Understand the diagnostics pipeline** (use Sourcegraph MCP for broad search):
   - Find the main diagnostics collection and how it stores errors per file
   - Locate the extension host communication for sending diagnostics to the client
   - Find the Problems view panel and how it subscribes to diagnostics
   - Look for existing file change listeners (e.g., `deleteAllDiagnosticsInFile`, `onWillChange`)

2. **Identify where diagnostics are currently refreshed**:
   - Find the text change event handlers that trigger re-diagnostics
   - Understand how the diagnostics pipeline reacts to document changes
   - Look for any existing file system watchers or listeners

3. **Add file system change triggers**:
   - Add listener for file changes on disk (e.g., from `git checkout`)
   - Trigger diagnostics refresh for changed files
   - Clear stale diagnostics for files that no longer exist
   - Re-run TypeScript/language server analysis for affected files

4. **Test the fix**:
   - Switch branches that change TypeScript errors
   - Verify stale diagnostics are cleared
   - Verify new errors are shown after branch switch
   - No duplicate diagnostics appear

5. **Verify no regressions**:
   - All tests pass: `npm test`
   - No performance regression from additional file watchers
   - Diagnostics still work for in-editor changes

## Success Criteria

✅ Stale diagnostics are cleared when files change on disk  
✅ New diagnostics appear after Git branch switch  
✅ Diagnostics refresh without requiring manual file edits  
✅ Problems panel reflects current state of files  
✅ All tests pass: `npm test`  
✅ No performance regression  
✅ Code follows VS Code conventions and patterns  

## Critical Requirement

**YOU MUST MAKE ACTUAL CODE CHANGES.** Do not plan or analyze. You must:

- Add file system change listeners to the diagnostics pipeline
- Trigger diagnostics refresh on file changes
- Clear stale diagnostics appropriately
- Commit all changes to git
- Verify tests pass

## Testing

```bash
npm test
```

**Time Limit:** 20 minutes  
**Estimated Context:** 15,000 tokens  
**Why MCP Helps:** Finding all diagnostic refresh points across VS Code's extension host, language servers, and problem panel requires semantic search. Understanding how `deleteAllDiagnosticsInFile` and `onWillChange` listeners work requires tracing through the entire codebase.

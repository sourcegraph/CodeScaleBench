# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/vscode--138f619c` — use `repo:^github.com/sg-evals/vscode--138f619c$` filter

Scope ALL keyword_search/nls_search queries to these repos.
Use the repo name as the `repo` parameter for read_file/go_to_definition/find_references.


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

**Sourcegraph Repositories:** `github.com/sg-evals/vscode--138f619c`

# Task: Implement Custom Named Folding Regions with Navigation in VS Code

## Objective
Add support for custom named folding regions in VS Code that can be navigated via a quick-pick menu. Users mark regions with special comments (e.g., `// #region MySection` / `// #endregion`), and this feature extends the existing folding to allow naming and jumping to regions by name.

## Requirements

1. **Create a Named Region Provider** in the folding subsystem:
   - Create or extend a folding range provider in `src/vs/editor/contrib/folding/browser/`
   - Detect `#region <name>` and `#endregion` comment markers
   - Extract the region name from the marker
   - Register named regions in a data structure that maps name -> line range

2. **Add region decoration** in the editor:
   - Display the region name as a decorative label in the gutter or inline
   - Use VS Code's decoration API (`IModelDecorationOptions`)
   - Collapsed regions should show the name in the fold placeholder text

3. **Register a "Go to Region" command**:
   - Add command `editor.action.goToNamedRegion` in `src/vs/editor/contrib/folding/browser/`
   - Wire it to a keybinding (suggest `Ctrl+Shift+R` / `Cmd+Shift+R`)
   - Register the command via `registerEditorAction` or `registerEditorCommand` pattern

4. **Implement quick-pick navigation**:
   - When the command is invoked, show a quick-pick (`IQuickInputService`) listing all named regions in the current file
   - Each item shows the region name and line number
   - Selecting an item navigates the editor cursor to that region and unfolds it

5. **Add a test file** for the named region provider:
   - Test region detection and name extraction
   - Test navigation to a named region

## Key Reference Files
- `src/vs/editor/contrib/folding/browser/folding.ts` — main folding contribution
- `src/vs/editor/contrib/folding/browser/foldingRanges.ts` — FoldingRanges data structure
- `src/vs/editor/contrib/folding/browser/indentRangeProvider.ts` — reference range provider
- `src/vs/editor/contrib/folding/browser/syntaxRangeProvider.ts` — another range provider pattern
- `src/vs/editor/common/model/textModel.ts` — text model API for line access
- `src/vs/editor/contrib/gotoSymbol/browser/goToCommands.ts` — reference for navigation commands
- `src/vs/platform/quickinput/common/quickInput.ts` — QuickInput service interface

## Success Criteria
- Named region detection code exists in folding contrib
- Region name extraction from `#region` markers implemented
- Command registered for navigating to named regions
- Quick-pick integration with region listing
- Decoration or placeholder text shows region names
- Test file exists for the region provider

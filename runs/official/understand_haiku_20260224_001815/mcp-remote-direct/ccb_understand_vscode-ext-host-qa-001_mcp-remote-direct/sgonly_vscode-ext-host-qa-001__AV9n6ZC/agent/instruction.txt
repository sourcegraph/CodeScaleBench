# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/vscode--17baf841`
- Use `repo:^github.com/sg-evals/vscode--17baf841$` filter in keyword_search
- Use `github.com/sg-evals/vscode--17baf841` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Debug Q&A: VS Code Extension Host Isolation

**Repository:** github.com/sg-evals/vscode--17baf841 (mirror of microsoft/vscode)
**Task Type:** Debug Q&A (investigation only — no code changes)

## Background

VS Code uses a multi-process architecture where extensions run in a separate process called the "extension host." Users have observed that when an extension crashes or encounters a fatal error, the main VS Code window continues to function normally — they can still edit files, open new tabs, and use the UI.

## Behavior Observation

**What happens:** When a VS Code extension crashes (e.g., throws an uncaught exception, segfaults in a native module, or hits a fatal error), the main VS Code window remains responsive and functional. The user may see a notification about the extension host restarting, but the editor UI doesn't freeze or crash.

**Why is this notable?** Many applications that load plugins or extensions crash entirely when a plugin fails. VS Code's architecture prevents extension failures from bringing down the whole application.

## Questions

Answer ALL of the following questions to explain this behavior:

### Q1: Process Isolation Architecture

How is the extension host process isolated from the main VS Code window process?
- What mechanism is used to spawn the extension host as a separate process?
- What is the relationship between the main process and the extension host process at the OS level (parent/child, detached, etc.)?
- How does this isolation prevent a crash in one process from affecting the other?

### Q2: Communication Between Processes

Since the extension host and main window are separate processes, how do they communicate?
- What IPC (inter-process communication) mechanism is used?
- What happens to this communication channel when the extension host crashes?
- How does the main window detect that the extension host has crashed vs. just being slow to respond?

### Q3: Crash Detection and Recovery

What happens when the extension host crashes?
- What component in the main process detects the crash?
- How does VS Code decide whether to automatically restart the extension host vs. showing a user prompt?
- What prevents infinite restart loops if an extension crashes repeatedly?

### Q4: Isolation Mechanisms

What specific architectural features ensure the main window's lifecycle is independent of the extension host?
- Are there any OS-specific isolation techniques (e.g., Windows vs. Linux/macOS)?
- What prevents exceptions or errors in the extension host from propagating to the main process?
- How does the architecture ensure the main window continues functioning even when extensions are unavailable?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# VS Code Extension Host Isolation

## Q1: Process Isolation Architecture
<answer with specific file paths, class names, and function references>

## Q2: Communication Between Processes
<answer with specific file paths, class names, and function references>

## Q3: Crash Detection and Recovery
<answer with specific file paths, class names, and function references>

## Q4: Isolation Mechanisms
<answer with specific file paths, class names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `src/vs/workbench/services/extensions/`, `src/vs/platform/utilityProcess/`, and `src/vs/workbench/api/node/` directories

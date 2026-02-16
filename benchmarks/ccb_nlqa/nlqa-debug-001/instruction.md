# Debug Q&A: VS Code Extension Host Isolation

**Repository:** microsoft/vscode
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
<consolidated list of key file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `src/vs/workbench/services/extensions/`, `src/vs/platform/utilityProcess/`, and `src/vs/workbench/api/node/` directories

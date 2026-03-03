# Chromium Multi-Process Architecture Overview

## Your Task

A new contributor wants to understand Chromium's multi-process architecture. Find the key C++ source files in `chromium/chromium` that define the process model: 1. The file under `content/browser/` that defines `RenderProcessHostImpl` — the browser-side representation of a renderer process. 2. The file that defines `BrowserMainLoop` — the main browser process event loop (`content/browser/browser_main_loop.cc`). 3. The file under `content/renderer/` that defines `RenderThreadImpl` — the main thread of a renderer process. 4. The file that defines `ChildProcessLauncher` — responsible for spawning child processes. 5. The IPC/Mojo file that declares the `content.mojom.Renderer` interface for browser-to-renderer communication. Report each file path and key class name.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/chromium--2d05e315.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/chromium--2d05e315` (chromium/chromium)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

# Chromium Renderer Process Sandbox Audit

## Your Task

Audit the security sandbox implementation for Chromium's renderer processes. Find all C++ source files in `chromium/chromium` that implement the sandbox: 1. The file under `sandbox/linux/` that implements `BPFBasePolicy` — the seccomp-BPF base policy for Linux sandboxing. 2. The file under `sandbox/win/src/` that defines `TargetPolicy` — the Windows sandbox policy configuration. 3. The file under `content/browser/` that configures sandbox parameters for renderer process launch (look for `SetRendererSandboxPolicy` or `GetRendererSandboxType`). 4. The file under `sandbox/policy/` that defines `SandboxType` enum and sandbox profile mappings. Report each file path and key class/function.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/chromium--2d05e315.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/chromium--2d05e315` (chromium/chromium)

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go"}
  ],
  "symbols": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "SymbolName"}
  ],
  "chain": [
    {"repo": "org/repo-name", "path": "relative/path/to/file.go", "symbol": "FunctionName"}
  ],
  "text": "Narrative explanation of your findings, citing repos and file paths."
}
```

Include only the fields relevant to this task. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant files?

# Android Activity Lifecycle Implementation

## Your Task

A new Android framework contributor wants to understand how the Activity lifecycle is implemented. Find the key Java source files in `aosp-mirror/platform_frameworks_base` that implement the Activity lifecycle: 1. The file under `core/java/android/app/` that defines `Activity.java` — the base Activity class with `onCreate`, `onStart`, `onResume` lifecycle methods. 2. The file that implements `ActivityThread.java` — the main thread of an Android application that drives lifecycle transitions. 3. The file under `services/core/java/com/android/server/wm/` that defines `ActivityRecord` — the server-side representation of an Activity. 4. The file that implements `ActivityTaskManagerService` — the system service managing activity stacks and tasks. Report each file path and key class name.

## Context

You are working on a codebase task involving repos from the onboarding domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/android-frameworks-base--d41da232.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/android-frameworks-base--d41da232` (aosp-mirror/platform_frameworks_base)

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

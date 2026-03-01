# Android View Rendering Pipeline

## Your Task

Trace how an Android View is measured, laid out, and drawn. Find the key Java source files in `aosp-mirror/platform_frameworks_base` that implement the rendering pipeline: 1. The file that defines `View.java` under `core/java/android/view/` — specifically the `measure()`, `layout()`, and `draw()` methods. 2. The file that defines `ViewRootImpl.java` — the connection between the window manager and the view hierarchy that schedules traversals. 3. The file that implements `Choreographer.java` — the VSYNC-driven frame scheduling. 4. The file that defines `ThreadedRenderer` or `HardwareRenderer` — the hardware-accelerated rendering bridge to the GPU. 5. The file that implements `DisplayListCanvas` or `RecordingCanvas` — the canvas that records draw operations for GPU replay. Report each file path and key class/method.

## Context

You are working on a codebase task involving repos from the domain domain.

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

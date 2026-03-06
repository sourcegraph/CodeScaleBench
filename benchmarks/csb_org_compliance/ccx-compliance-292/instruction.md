# Godot GDScript Sandbox and Security Boundary Audit

## Your Task

Audit the security boundaries of the GDScript virtual machine in godotengine/godot. Find all C++ source and header files under modules/gdscript/ and core/object/ that implement: the GDScriptVM bytecode interpreter and its opcode dispatch, the GDScriptFunction call frame management, the Object::call and Object::callp method dispatch used by scripts, the ClassDB registration that controls which engine APIs are exposed to scripts, and any EditorScript or ToolScript permission checks. Report each file path and the key class or function it defines.

## Context

You are working on a codebase task involving repos from the compliance domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/godot--4.3-stable.

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

# GCC Stack Clash Protection Implementation Audit

## Your Task

Audit the stack clash protection implementation in GCC. Find all C/C++ source files in `gcc-mirror/gcc` that implement stack clash mitigation. Specifically: 1. The file that implements stack clash probing for x86_64 targets (`gcc/config/i386/i386.cc` — look for `stack_clash_protection`). 2. The file that implements the generic stack clash expansion (`gcc/explow.cc` — look for `anti_adjust_stack_and_probe`). 3. The header where `TARGET_STACK_CLASH_PROTECTION` is declared or defined. 4. The test file under `gcc/testsuite/gcc.target/i386/` that validates stack clash protection (look for `stack-clash-*`). 5. The common options file where `-fstack-clash-protection` is defined (`gcc/common.opt`). Report each file path and the key function or definition.

## Context

You are working on a codebase task involving repos from the security domain.

## Available Resources

The local `/workspace/` directory contains: sg-evals/llvm-project--a8f3c97d, sg-evals/gcc--96dfb333.

**Note:** Additional repositories are accessible via Sourcegraph MCP tools:
- `sg-evals/llvm-project--a8f3c97d` (llvm/llvm-project)
- `sg-evals/gcc--96dfb333` (gcc-mirror/gcc)

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

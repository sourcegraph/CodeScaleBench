# big-code-k8s-bug-001: Missing ResourceSlice Event Handler

This repository is large (~3.5M LOC). Use targeted search to trace the execution path from symptom to root cause.

## Task Type: Bug Investigation

Your goal is to trace a bug from its observed symptom to its root cause. Focus on:

1. **Symptom location**: Start from the entry point where the bug is observed
2. **Call chain tracing**: Follow the execution path through function calls
3. **Root cause identification**: Find the specific file and line where the bug originates
4. **Fix proposal**: Explain WHY the bug occurs and propose a minimal fix

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — examined for [reason]

## Dependency Chain
1. Symptom observed in: path/to/symptom.ext
2. Called from: path/to/caller.ext (function_name)
3. Bug triggered by: path/to/buggy.ext (function_name, line ~N)

## Root Cause
- **File**: path/to/root_cause.ext
- **Function**: function_name()
- **Line**: ~N
- **Explanation**: [Why this code is buggy]

## Proposed Fix
\`\`\`diff
- buggy code
+ fixed code
\`\`\`

## Analysis
[Detailed trace from symptom to root cause]
```

## Search Strategy

- Start from `pkg/scheduler/schedule_one.go` — the `ScheduleOne()` method
- Use `go_to_definition` to follow function calls deeper into the codebase
- Use `find_references` to understand how events flow through the scheduler
- Key subsystems: scheduling queue (`internal/queue/`), event handlers (`eventhandlers.go`), plugin framework (`framework/`), DRA plugin (`framework/plugins/dynamicresources/`)
- Look at how other resource types (Node, PersistentVolumeClaim) register event handlers — then check whether ResourceSlice follows the same pattern

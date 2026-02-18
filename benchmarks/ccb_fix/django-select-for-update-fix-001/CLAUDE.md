# big-code-django-bug-001: Django select_for_update(of) Crash

This repository is large (~350K LOC). Use targeted search to trace the execution path from symptom to root cause.

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

- Start from `django/db/models/sql/compiler.py` — the `get_select_for_update_of_arguments()` method
- Use `go_to_definition` to follow function calls deeper into the codebase
- Use `find_references` to understand how buggy code is called
- Search error messages and exception types to find related handling code
- The bug involves the interaction between `values()`/`values_list()` field ordering and `select_for_update(of=...)`

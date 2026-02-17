Investigate a failed task or analyze agent behavior on any task.

Covers: MCP usage patterns, tool patterns, zero-MCP investigation, error root cause analysis.

## Steps

1. If the user specifies a task, find its result directory:
```bash
find runs/official/ runs/staging/ -name "result.json" -path "*<task_name>*" 2>/dev/null
```

2. Read the result.json to understand the failure:
   - Check `exception_info` for error details
   - Check `verifier_result` for scoring
   - Check `agent_result` for token usage

3. Read the agent transcript (claude-code.txt) for behavior analysis

4. Use error fingerprinting if applicable:
```bash
python3 scripts/aggregate_status.py --failures-only --format table
```

5. Report findings: root cause, whether it's infra vs task difficulty, MCP usage patterns

## Arguments

$ARGUMENTS — task name or run directory to investigate

# DevAI Task

## Overview

**Task ID**: {id}
**Domain**: {domain}
**Requirements**: {requirement_count}

## User Query

{user_query}

## Description

{description}

{requirements}

{preferences}

## Instructions

1. Analyze the user query and understand the requirements
2. Use MCP tools for efficient code navigation and understanding
3. Implement the solution following the requirements hierarchy
4. Your workspace is at `/workspace/project/`
5. Write your trajectory to `/trajectory/trajectory.json`

## Workspace Structure

Your workspace follows DevAI's expected structure:
```
/workspace/
├── project/      # Your implementation goes here
└── ...
```

## Output Format

Your trajectory must be written to `/trajectory/trajectory.json` following this format:

```json
{
    "task_id": "{id}",
    "agent_name": "your-agent-name",
    "steps": [
        {
            "step_number": 1,
            "action": {
                "type": "command|file_write|file_read|code_edit|tool_call|message",
                "content": "action content"
            },
            "observation": {
                "output": "result of the action",
                "success": true
            }
        }
    ],
    "final_state": {
        "completed": true,
        "requirements_met": {
            "R1": true,
            "R2": false
        },
        "artifacts": ["path/to/output/file"]
    }
}
```

The verifier will validate your trajectory format and compute your score based on requirement satisfaction.

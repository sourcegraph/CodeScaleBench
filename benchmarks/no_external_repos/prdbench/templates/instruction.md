# PRDBench Task

## Overview

**Task ID**: {id}
**Title**: {title}
**Difficulty**: {difficulty}
**Evaluation Criteria**: {criteria_count}

---

## Product Requirements Document

{prd_content}

---

{criteria}

## Instructions

1. Read and understand the PRD above carefully
2. Implement the product according to the requirements
3. Use MCP tools for efficient code navigation and development
4. Your workspace is at `/workspace/project/`
5. Write test results to `/workspace/test_results.json` or run the included tests

## Workspace Structure

Your workspace follows PRDBench's expected structure:
```
/workspace/
├── project/      # Your implementation goes here
└── test_results.json  # Write your test results here
```

## Output Format

After implementing the PRD, generate test results in `/workspace/test_results.json`:

```json
{
    "task_id": "{id}",
    "tests_passed": 5,
    "tests_total": 10,
    "criteria_results": {
        "C1": true,
        "C2": false,
        "C3": {
            "passed": true,
            "score": 0.8,
            "notes": "Partial implementation"
        }
    },
    "artifacts": ["path/to/main/file.py"]
}
```

The verifier will evaluate your implementation against the evaluation criteria and compute your score.

## Tips

- Focus on the most heavily weighted criteria first
- Ensure automated criteria can be verified programmatically
- Document any assumptions in your implementation
- Test your implementation thoroughly before submitting

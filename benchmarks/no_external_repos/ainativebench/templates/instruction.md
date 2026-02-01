# AINativeBench Task

## Overview

**Task ID**: {id}
**Benchmark**: {benchmark_name}
**Variant**: {variant}
**Language**: {language}

## Description

{description}

## Scoring

{scoring_metrics}

{test_cases}

{context_files}

## Instructions

1. Explore the codebase in `/app/project/` to understand the existing implementation
2. Use MCP tools for efficient code navigation and understanding
3. Complete the task as described above
4. Your test results should be written to `/test_results/` directory as JSON files

## Output Format

Write your test results to `/test_results/` directory. Each test result should be a JSON file with the following structure:

```json
{
    "test_name": "name_of_test",
    "passed": true,
    "output": "actual output or result",
    "expected": "expected output (optional)"
}
```

The verifier will parse all JSON files in `/test_results/` to compute your final score based on pass rate.

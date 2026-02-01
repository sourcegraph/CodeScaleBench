# Multi-file Editing Task

## Problem Statement



## Task Description

Your task is to make the required code edits across multiple files in the repository according to the specifications. This may involve modifying existing functions, adding new code, or updating cross-file dependencies.

## Repository Information

- **Repository**: Android-DraggableGridViewPager
- **Language**: java

## Output Format

Write your answer to `/workspace/submission.json` as a JSON object containing the modified file contents:

```json
{
  "path/to/file1.py": "# Complete modified file content\\n...",
  "path/to/file2.py": "# Complete modified file content\\n...",
  "path/to/file3.py": "# Complete modified file content\\n..."
}
```

### Requirements:

1. Include **complete file contents** for all modified files
2. Use correct file paths relative to the repository root
3. Ensure all syntax is valid for the target language
4. Maintain code style and formatting consistency
5. Preserve functionality of unchanged code

### Alternative Format (Patches):

You can also submit unified diff patches:

```json
{
  "patches": [
    {
      "file": "path/to/file1.py",
      "diff": "@@ -10,5 +10,7 @@\\n..."
    }
  ]
}
```

## Evaluation

Your submission will be evaluated on:

1. **Function Call Correctness** (25%): Proper function signatures and cross-file dependencies
2. **Feature Alignment** (25%): Code reflects intended requirements
3. **Implementation Accuracy** (20%): Functionally correct, dependencies resolved
4. **Completeness** (20%): All required segments implemented
5. **Code Quality** (10%): Readable, maintainable, efficient

**Note**: This simplified version uses string similarity scoring. The original DependEval uses LLM-based evaluation across these five dimensions.

## Tips

- Read the requirements carefully before making changes
- Test that your changes don't break existing functionality
- Ensure cross-file imports and function calls are correct
- Maintain consistent coding style with the rest of the repository
- Include all necessary imports and dependencies
- Consider edge cases and error handling

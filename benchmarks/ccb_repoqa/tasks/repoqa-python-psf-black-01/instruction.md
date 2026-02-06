# RepoQA: Semantic Retrieval (SR-QA)

## Task: Find the Function

You are searching a large codebase for a specific function based on its behavior.

**Repository**: psf/black  
**Language**: python  
**Commit**: f03ee113c9f3dfeb477f2d4247bfb7de2e5f465c

## Function Description

```

1. **Purpose**: The function is designed to transform specific lines of code that have not been modified into a special comment format that preserves their original formatting during further processing. This is particularly useful in scenarios where selective formatting is required, ensuring that unchanged parts of the code remain visually consistent and untouched.
2. **Input**: The function takes two parameters: a node representing the parsed source code and a collection of line ranges that specify which lines have not been altered.
3. **Output**: There is no direct output from this function as it modifies the input node in place. The changes involve converting specified lines into a format that will not be altered in subsequent formatting steps.
4. **Procedure**: The function operates in two main phases:
   - First, it identifies top-level statements within the unchanged lines and converts these blocks into a special comment type that preserves their formatting.
   - Second, it processes individual unchanged lines within the node, converting them into the same special comment type. This includes normalizing comment prefixes and indentations to ensure consistency, even though the content itself remains unchanged.

```

## Search Strategy

This function **cannot be found by searching for its name** because the name is not provided. You must:

1. **Understand the behavior** described above
2. **Search the codebase** to find functions matching this behavior
3. **Explore the code** using call graphs and references
4. **Narrow down** candidates until you find the exact function


## Output Format

You MUST provide your answer as valid JSON and **SAVE IT TO A FILE**:

```json
{
  "function_path": "path/to/file.py",
  "function_name": "the_function_name",
  "justification": "Why this function matches: describe the behavior you found"
}
```

**CRITICAL**: You MUST save the JSON to `/app/solution.json`. This location is required for Harbor verification.

**Your final step MUST be to run this exact bash command:**

```bash
cat > /app/solution.json << 'JSONEOF'
{
  "function_path": "ACTUAL_PATH",
  "function_name": "ACTUAL_NAME", 
  "justification": "ACTUAL_JUSTIFICATION_TEXT"
}
JSONEOF
```

Replace:
- `ACTUAL_PATH`: The file path you found (e.g., "requests/cookies.py" or "src/requests/cookies.py")
- `ACTUAL_NAME`: The function name (e.g., "extract_cookies_to_jar")
- `ACTUAL_JUSTIFICATION_TEXT`: Your explanation of why this is the right function

**You must run this bash command to complete the task.** Harbor will preserve files in `/app/` for the verification step.

## Notes

- The file path should be relative to repository root
- Function names are case-sensitive
- Provide your best match even if uncertain; explain your reasoning
- The justification is scored on how well it explains the function's behavior

## Scoring

- **Perfect** (1.0): Correct path AND name
- **Good** (0.7-0.9): Correct path, similar name OR vice versa
- **Partial** (0.3-0.6): Close approximation
- **Incorrect** (0.0): Wrong function entirely


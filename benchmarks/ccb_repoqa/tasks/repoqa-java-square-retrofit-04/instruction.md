# RepoQA: Semantic Retrieval (SR-QA)

## Task: Find the Function

You are searching a large codebase for a specific function based on its behavior.

**Repository**: square/retrofit  
**Language**: java  
**Commit**: 10014c2bb7bd5fd24cf6b5b680e6917ab9a7767b

## Function Description

```

1. **Purpose**: To append a query parameter to the URL being constructed, with an option to encode the parameter.
2. **Input**: The method takes three parameters: the name of the query parameter, its value (which can be null), and a boolean indicating whether the parameter should be URL-encoded.
3. **Output**: There is no direct output; however, the method modifies the state of the URL builder by adding a new query parameter.
4. **Procedure**: 
   - First, it checks if the URL has been previously set. If so, it combines the relative URL with the base URL to initialize the URL builder.
   - Depending on whether the parameter should be encoded, it either adds the parameter as-is or encodes it before adding.
   - If the URL builder is not properly initialized (due to a malformed URL), an exception is thrown.

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


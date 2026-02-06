# RepoQA: Semantic Retrieval (SR-QA)

## Task: Find the Function

You are searching a large codebase for a specific function based on its behavior.

**Repository**: xenova/transformers.js  
**Language**: typescript  
**Commit**: 642743136efa3a481b2b96d3c2c550085540d844

## Function Description

```

1. **Purpose**: The function rearranges the elements of a multi-dimensional array based on specified new axis orders, effectively reorienting the data structure.
2. **Input**: The function takes three parameters: a multi-dimensional array, its current dimensions, and the new order of axes.
3. **Output**: It returns a tuple containing the newly arranged array and its new shape.
4. **Procedure**: The function first calculates the new shape and stride for the array based on the new axis order. It then computes an inverse mapping of the stride to facilitate re-indexing. Using this mapping, it iterates over the original array, calculates the new index for each element in the rearranged array, and assigns the values accordingly.

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


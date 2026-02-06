# RepoQA: Semantic Retrieval (SR-QA)

## Task: Find the Function

You are searching a large codebase for a specific function based on its behavior.

**Repository**: rust-bakery/nom  
**Language**: rust  
**Commit**: e87c7da9fa2ddb943306369f6c6d9e914256edbc

## Function Description

```

1. **Purpose**: To verify that the function correctly parses specific bit segments from a byte array and accurately tracks the remaining unconsumed bytes.
2. **Input**: An array of bytes intended to be parsed into segments of 4, 8, and 4 bits respectively.
3. **Output**: A tuple containing the parsed values from the specified bit segments and the array of bytes that were not consumed during the parsing process.
4. **Procedure**: The function processes the input byte array to extract the first 4 bits, then the next 8 bits, and finally another 4 bits. It checks that the remaining bytes in the array are correctly identified and returned, ensuring that bytes fully consumed by the parsing are not included in the output.

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


        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: grafana/grafana
        **Language**: typescript

        ## Function Description

        ```
        1. **Purpose**: Computes a comprehensive set of aggregate statistics (min, max, mean, sum, count, delta, range, diff, first/last, logmin, etc.) for a single data field, serving as the default standard-calculations reducer used by panel visualizations and data transformations.
2. **Input**: A field object (containing a values array and a type enum indicating whether the field is numeric, time, string, etc.), plus two boolean flags: one for whether to skip null values entirely and one for whether to treat null values as zero for calculation purposes.
3. **Output**: A dictionary containing computed statistics: first, last, firstNotNull, lastNotNull, min, max, sum, count, nonNullCount, mean, range, diff (last minus first non-null), percentage change, delta (cumulative positive increments with counter-reset detection), step (minimum interval between consecutive non-null values), smallest positive value, and boolean flags for all-null and all-zero.
4. **Procedure**:
   - Returns defaults immediately if the values array is empty or undefined.
   - Determines whether the field is numeric or time-typed.
   - Iterates over every value: records first/last; handles null values according to the two flags; increments count.
   - For non-null numeric values: tracks running sum, min, max, smallest positive value, non-null count; computes step as the minimum gap between consecutive non-null values; computes delta by accumulating positive increments while detecting counter resets.
   - After the loop: clamps sentinel values back to null if no real values were seen; computes mean, range, diff, and percentage change from the accumulated statistics.
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
          "function_path": "path/to/file.ext",
          "function_name": "the_function_name",
          "justification": "Why this function matches: describe the behavior you found"
        }
        ```

        **CRITICAL**: You MUST save the JSON to `/app/solution.json`. This location is required for verification.

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

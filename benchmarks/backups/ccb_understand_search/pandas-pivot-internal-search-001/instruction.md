        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: pandas-dev/pandas
        **Language**: python

        ## Function Description

        ```
        1. **Purpose**: Implements the core pivot table computation for a single aggregation function. This is the internal workhorse called by the public pivot_table function after it splits list-valued aggregation arguments into individual calls.
2. **Input**: A DataFrame, plus parameters for values (columns to aggregate), index (row grouping keys), columns (column grouping keys), a single aggregation function or callable, fill value, margins (whether to add row/column totals), dropna, margins name, observed (for categorical groupers), sort, and extra keyword arguments.
3. **Output**: Returns a DataFrame representing the pivot table: rows correspond to unique combinations of index keys, columns correspond to unique combinations of column keys, and cell values are the result of applying the aggregation function to matching data subsets.
4. **Procedure**:
   - Validates that value labels exist in the data; filters the DataFrame to only relevant columns.
   - Groups the data by the concatenation of index and column keys, then applies the aggregation function.
   - If dropna is set, drops all-NaN rows from the aggregated result.
   - If the result has a MultiIndex, unstacks the column-key levels to create a 2D pivot layout, using the fill value for missing combinations.
   - If dropna is false, reindexes both axes against the full Cartesian product of level values.
   - Sorts columns if requested, fills remaining NaN values, handles integer downcasting for len aggregations.
   - If margins are requested, appends row/column totals.
   - Cleans up: drops redundant top-level column headers, transposes if no row index was specified.
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

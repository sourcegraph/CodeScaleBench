        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: rust-lang/rust
        **Language**: rust

        ## Function Description

        ```
        1. **Purpose**: Validates whether the type-outlives relationship tests generated during type checking are satisfied by the inferred region values, and collects error reports for those that fail.
2. **Input**: Takes an immutable reference to the region inference context, a reference to the inference context for type manipulation, an optional mutable vector for propagating outlives requirements to enclosing closures, and a mutable buffer for collecting region error reports.
3. **Output**: No return value; populates the errors buffer with type-test failure entries for each unsatisfied test. When processing closures, may instead propagate unsatisfied requirements upward through the optional requirements vector rather than reporting an error directly.
4. **Procedure**:
   - Maintains a deduplication set of (erased generic kind, lower bound region, span) triples to avoid reporting essentially identical errors multiple times.
   - Iterates over each registered type test (encoding constraints like T: 'a).
   - For each test, converts the generic kind to a concrete type, then evaluates its verify bound against the inferred lower-bound region. If the bound is satisfied, the test passes and is skipped.
   - If the bound is not satisfied and this is a closure, attempts to promote the type test into a closure outlives requirement. If promotion succeeds, the test is skipped.
   - If neither verification nor promotion succeeds, erases and anonymizes the generic kind's regions, checks the deduplication set, and if the error is novel, pushes a failure entry into the errors buffer.
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

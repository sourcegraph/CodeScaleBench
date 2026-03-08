        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: kubernetes/kubernetes
        **Language**: go

        ## Function Description

        ```
        1. **Purpose**: Identifies which cluster nodes satisfy all scheduling filter plugins for a given workload, enabling the scheduler to narrow down placement candidates.
2. **Input**: Takes a context, a framework handle providing filter plugins and parallelism settings, cycle state, a pod specification, a diagnosis collector for recording filter failures, and a pre-fetched list of all node information objects.
3. **Output**: Returns a slice of node-info objects representing feasible placement targets, plus an error if any filter plugin returned a fatal error. Also populates the diagnosis object with per-node failure reasons as a side effect.
4. **Procedure**:
   - Computes the target number of feasible nodes to find, reducing to 1 if there are no extender filters and no scoring plugins.
   - If no filter plugins are registered, returns the first N nodes starting from a round-robin offset.
   - Otherwise, defines an inner closure that runs all filter plugins against each node in parallel, starting from the last scheduling cycle's offset to ensure fairness.
   - Uses atomic counters to track how many feasible nodes have been found; cancels the parallel search early once the target count is reached.
   - Records non-feasible node statuses into a result array under the parallel check, then copies them into the diagnosis object after all parallel work completes.
   - Measures and reports the total Filter extension point latency via deferred metrics emission.
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

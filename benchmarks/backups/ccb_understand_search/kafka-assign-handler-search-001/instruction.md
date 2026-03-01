        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: apache/kafka
        **Language**: java

        ## Function Description

        ```
        1. **Purpose**: Reconciles the stream processing task manager's current task ownership with a new assignment of active and standby tasks received after a consumer group rebalance, deciding which tasks to create, recycle, resume, or close.
2. **Input**: Takes two maps: one mapping task IDs to sets of topic partitions for active tasks, and another for standby tasks. These represent the new desired assignment from the partition assignor.
3. **Output**: No return value; as side effects, it updates internal task registries, creates new tasks, closes tasks no longer assigned, recycles tasks that changed between active and standby roles, and resumes suspended tasks. May throw aggregated exceptions for corrupted or migrated tasks.
4. **Procedure**:
   - Logs the delta between existing and new assignments, then registers subscribed topics from the new active partitions.
   - Prepares mutable copies of the assignment maps and empty collections for tasks to recycle and tasks to close.
   - Locks tasks that appear in both old and new assignments to prevent concurrent state modifications.
   - Iterates over all existing tasks: if a task's ID appears in the new active set and is already active, updates its input partitions and resumes it; if it's standby but needs to become active (or vice versa), marks it for recycling. Tasks not in either new map are marked for clean closure.
   - After classification, closes and recycles tasks, unlocks, aggregates any exceptions (prioritizing fatal over migrated over corrupted), and finally creates brand-new tasks for any remaining IDs in the assignment maps.
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

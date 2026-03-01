        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: rust-lang/rust
        **Language**: rust

        ## Function Description

        ```
        1. **Purpose**: Orchestrates the liveness analysis for the borrow checker, determining which local variables need liveness tracking and emitting the corresponding region constraints that encode which types must be live at which program points.
2. **Input**: Takes a mutable reference to the type checker (providing access to inference context, universal regions, constraints, and the MIR body), a dense location map for the control-flow graph, and move data tracking initialization and move status of variables.
3. **Output**: No return value; modifies the type checker's constraint sets by adding liveness constraints. As a side effect, computes and stores boring locals (those whose types contain only free regions) in the Polonius liveness context when the next-generation borrow checker is enabled.
4. **Procedure**:
   - First computes the set of regions known to outlive free regions by building a reverse constraint graph and performing a depth-first search from all universal (free) regions.
   - If the experimental Polonius mode is enabled, partitions locals into relevant (needing liveness computation) and boring (all regions are free), stores the boring locals for later diagnostics, then resets the free-region set.
   - Partitions local variable declarations into relevant and boring based on whether their types contain any non-free regions.
   - Invokes the trace module to perform the actual liveness computation over the relevant locals using move data.
   - Finally, records regular live regions, marking regions that appear in rvalues or call arguments as live at their use points.
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

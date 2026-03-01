        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: kubernetes/kubernetes
        **Language**: go

        ## Function Description

        ```
        1. **Purpose**: Performs a single synchronization cycle of the node eviction manager, evaluating current resource usage against configured thresholds and, if necessary, selecting and terminating one workload to relieve resource pressure.
2. **Input**: Operates as a method on the eviction manager, receiving a context, a list of active workloads (pods), a function to retrieve resource usage statistics, and a function to check if a pod has been cleaned up. It implicitly reads node summary statistics from the summary provider.
3. **Output**: Returns a slice of pods that were evicted during this cycle (at most one) and an error. As side effects, it updates internal state: the set of met thresholds, node condition timestamps, and observation history.
4. **Procedure**:
   - Refreshes memory threshold notifiers from the latest statistics summary.
   - Computes signal observations (e.g., memory available, disk available) and determines which thresholds are currently met, both ignoring and respecting grace periods.
   - Tracks when each threshold was first observed and when each node condition was last observed, applying a transition period before declaring conditions active.
   - Filters thresholds to only those whose grace periods are fully met and whose stats have been updated since the last sync.
   - Checks for local storage eviction violations first (pod-level disk usage); if any pods are evicted there, returns early.
   - Sorts remaining thresholds by eviction priority, identifies the highest-priority reclaimable resource, and first attempts node-level reclamation (e.g., garbage-collecting images or containers).
   - If node-level reclamation is insufficient, ranks all active pods using a signal-specific ranking function, then iterates through ranked pods and evicts the first one that can be killed.
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

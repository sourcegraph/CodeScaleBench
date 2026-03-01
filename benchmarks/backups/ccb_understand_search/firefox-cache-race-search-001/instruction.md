        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: mozilla/gecko-dev
        **Language**: cpp

        ## Function Description

        ```
        1. **Purpose**: Determines whether it is advisable to race a network request against a pending cache lookup for the same resource, and if so, computes an appropriate delay and triggers the network request to run concurrently with cache access.
2. **Input**: Takes no explicit parameters; operates as a method on the HTTP channel, reading channel state (load flags, error status, CORS preflight requirements) and querying system services for network link type and cache performance statistics.
3. **Output**: No return value; as a side effect, may schedule a network request to fire after a computed delay (or immediately if the cache is determined to be slow). Sets the channel's race delay field and triggers network activation via a timer.
4. **Procedure**:
   - Queries the network link service for the current connection type.
   - Returns immediately (no racing) if the link type is metered (e.g., cellular on Android).
   - Returns immediately if load flags prohibit network access (LOAD_ONLY_FROM_CACHE or LOAD_NO_NETWORK_IO).
   - Returns immediately if the channel has a failure status or if a CORS preflight is required but not yet completed.
   - Computes the race delay: if cache performance statistics indicate the cache is slow, sets delay to zero; otherwise, sets the delay to three times the average cache entry open time.
   - Clamps the delay between configurable minimum and maximum bounds from preferences.
   - Triggers the network request with the computed delay.
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

        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: envoyproxy/envoy
        **Language**: cpp

        ## Function Description

        ```
        1. **Purpose**: Initializes an upstream request after its connection pool has successfully provided a connection, setting up stream metadata, timing information, protocol details, watermark callbacks, stream duration limits, and host-rewrite rules before the request is forwarded upstream.
2. **Input**: Takes ownership of a generic upstream connection via move semantics, a shared pointer to the upstream host description, a reference to the connection's address provider (local/remote addresses, SSL info), a reference to the pool's stream info, and an optional HTTP protocol version.
3. **Output**: No return value; as side effects, configures the upstream stream with the downstream account, records connection timing metadata, sets up upstream filter state, populates upstream address information, enables half-close if configured, starts per-try and max-stream-duration timers, rewrites the Host header if auto-host-rewrite is enabled, and notifies all registered upstream callbacks.
4. **Procedure**:
   - Records the connection pool callback latency and takes ownership of the upstream connection.
   - Reports a successful connection to the host's outlier detector.
   - Selects the upstream host and records the protocol in stream info.
   - Copies connection timing data and stream count from the pool's stream info.
   - Sets up filter state and records local/remote addresses, SSL connection info, connection ID.
   - Synchronizes upstream and downstream byte meters.
   - Defers per-try timeout setup until the downstream request completes, or starts it immediately if the downstream has already ended.
   - Registers downstream watermark callbacks for backpressure propagation.
   - Computes and starts the max stream duration timer.
   - If auto-host-rewrite is enabled and the upstream host has a non-empty hostname, updates the Authority/Host header.
   - Emits an upstream pool-ready access log entry and invokes all upstream-connection-established callbacks.
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

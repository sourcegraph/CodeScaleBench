        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: envoyproxy/envoy
        **Language**: cpp

        ## Function Description

        ```
        1. **Purpose**: Evaluates an upstream HTTP response against the configured retry policy to determine whether the request should be retried based on the response status code, headers, or gRPC status, returning a retry decision.
2. **Input**: Takes a constant reference to the upstream response headers, a constant reference to the original downstream request headers, and a mutable boolean reference for signaling whether early data (0-RTT) should be disabled on retry.
3. **Output**: Returns a retry decision enum value: either no retry, retry with backoff, or retry immediately. Sets the disable-early-data output flag when retrying a 425 Too Early response.
4. **Procedure**:
   - First checks if the response contains a rate-limited header; if so, only retries when the rate-limited retry policy is active.
   - Extracts the HTTP response status code and evaluates it against multiple configured retry-on policies in sequence: 5xx errors, gateway errors (502/503/504), retriable 4xx (specifically 409 Conflict), and custom retriable status codes.
   - For custom retriable status codes, has special handling for HTTP 425 (Too Early): only retries if the downstream request was not itself received as early data.
   - Checks for retriable response header matchers, evaluating each configured header matcher against the response.
   - Evaluates gRPC-specific retry conditions by extracting the gRPC status from response headers and matching against configured gRPC retry policies.
   - Returns no-retry if none of the configured policies matched.
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

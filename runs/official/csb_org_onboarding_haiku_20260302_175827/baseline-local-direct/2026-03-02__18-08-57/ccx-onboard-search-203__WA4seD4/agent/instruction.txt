        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: apache/kafka
        **Language**: java

        ## Function Description

        ```
        1. **Purpose**: Collects pending record batches from the accumulator's per-partition queues for a single broker node, respecting a maximum request size, to be sent in a single produce request.
2. **Input**: Takes a metadata snapshot (providing cluster topology and leader epoch information), a broker node object, a maximum request size in bytes, and the current timestamp in milliseconds.
3. **Output**: Returns an ordered list of producer batch objects that are ready to be sent to the specified broker, with their combined serialized size not exceeding the maximum (except when a single batch is larger due to compression).
4. **Procedure**:
   - Retrieves the list of partitions assigned to the given node from the metadata snapshot.
   - Uses a per-node drain index (round-robin offset) to avoid starvation by starting from where the previous drain left off.
   - Iterates through partitions in a circular fashion: skips muted partitions (those with in-flight batches), skips partitions with empty queues or batches still in backoff.
   - For each eligible partition, peeks at the head batch under a synchronized lock: updates its leader epoch, checks if adding it would exceed the max size (allowing one oversized batch when the ready list is empty).
   - Removes the batch from the queue, and if a transaction manager is present and the batch lacks a sequence number, assigns producer ID/epoch and sequence numbers for exactly-once semantics.
   - Outside the lock, closes the batch (finalizing its memory records), records its size, marks it as drained, and continues until all partitions have been visited.
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

        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: microsoft/vscode
        **Language**: typescript

        ## Function Description

        ```
        1. **Purpose**: Implements a three-way merge algorithm that determines which items were added, removed, updated, or conflicting when reconciling local, remote, and base versions of a configuration during Settings Sync.
2. **Input**: Three compare-result objects: one for the direct diff between local and remote, one for the diff from common ancestor to local, and one for the diff from common ancestor to remote. Each contains three sets: added, removed, and updated keys.
3. **Output**: An object with four sets: added (keys to add from remote), removed (keys to remove per remote), updated (keys to update per remote), and conflicts (keys where local and remote diverged and cannot be auto-merged).
4. **Procedure**:
   - Iterates over keys removed locally; if any were updated in the remote, marks them as conflicts.
   - Iterates over keys removed remotely; if updated locally, marks as conflict; otherwise accepts the removal.
   - Iterates over keys added locally; if also added in remote with different values, marks as conflict.
   - Iterates over keys added remotely; if also added locally with different values, marks as conflict; otherwise accepts the addition.
   - Iterates over keys updated locally; if also updated remotely with different values, marks as conflict.
   - Iterates over keys updated remotely; if also updated locally with different values, marks as conflict; otherwise accepts the update.
   - Already-conflicted keys are skipped via guards to avoid duplicate processing.
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

        # RepoQA: Semantic Retrieval (SR-QA)

        ## Task: Find the Function

        You are searching a large codebase for a specific function based on its behavior.

        **Repository**: scikit-learn/scikit-learn
        **Language**: python

        ## Function Description

        ```
        1. **Purpose**: Performs the core fitting procedure for Independent Component Analysis (ICA), computing the unmixing matrix that separates observed signals into statistically independent source signals, with optional whitening as a preprocessing step.
2. **Input**: A 2D array of shape (n_samples, n_features) containing multivariate signal observations, plus a boolean flag that controls whether to materialize the separated source matrix or only compute the rotation matrix (to save memory on large datasets).
3. **Output**: Returns either None (when the flag is off) or an array of shape (n_samples, n_components) containing the estimated independent source signals. As a side effect, sets instance attributes for components, mixing matrix, mean, whitening matrix, unmixing, and iteration count.
4. **Procedure**:
   - Validates and transposes input data; selects the nonlinearity function (logcosh, exp, cube, or user-supplied callable).
   - Determines number of components (clamping to min of samples and features).
   - If whitening is enabled, centers the data by subtracting the mean, then computes a whitening matrix via eigendecomposition or SVD, projecting onto a lower-dimensional space.
   - Initializes the unmixing weight matrix (random normal if not provided).
   - Delegates to either a parallel (symmetric decorrelation) or deflation (one component at a time) algorithm to iteratively refine the unmixing matrix using fixed-point iteration.
   - Computes separated sources if requested.
   - Stores the components, mixing matrix (pseudo-inverse), and whitening matrix on the instance.
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

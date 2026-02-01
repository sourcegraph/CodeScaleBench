#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected outcome is a significant reduction in boilerplate code across multiple files, replaced by a robust, centralized pattern.

**Key changes in the final state:**

*   **`src/constants.txt`:**
    *   Contains two new lines:
        ```csharp
        public const int API_MAX_RETRIES = 5;
        public const int API_INITIAL_BACKOFF_MS = 200;
        ```

*   **`src/utils.txt`:**
    *   Contains a new static class, `ResilienceHelper`, with a method signature similar to this:
        ```csharp
        public static class ResilienceHelper
        {
            public static async Task<T> ExecuteWithRetryAsync<T>(Func<Task<T>> operation)
            {
                int attempt = 0;
                while (true)
                {
                    try
                    {
                        return await operation();
                    }
                    catch (Exception ex) when (IsTransient(ex) && attempt < Constants.API_MAX_RETRIES)
                    {
                        attempt++;
                        var delay = TimeSpan.FromMilliseconds(Constants.API_INITIAL_BACKOFF_MS * Math.Pow(2, attempt - 1));
                        // A real implementation would also include logging the retry attempt.
                        await Task.Delay(delay);
                    }
                }
            }

            private static bool IsTransient(Exception ex)
            {
                // In a real system, this would be more robust.
                return ex is HttpRequestException || ex is TimeoutException;
            }
        }
        ```

*   **`src/module_*.txt` files:**
    *   Multiple files (likely 5-10 or more) will have their code changed.
    *   Code blocks of 10-15 lines (e.g., a `for` loop with `try-catch` and `Task.Delay`) will be replaced by a single, elegant line:
        *   **Before:** A complex, multi-line loop.
        *   **After:** `var processResult = await ResilienceHelper.ExecuteWithRetryAsync(() => someApiService.GetDataAsync(request));`
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

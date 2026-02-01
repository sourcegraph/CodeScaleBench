#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
{
  "root_cause_summary": "The root cause is a classic race condition involving a mismanaged global state used for request context. A legacy component reads user context from a global `Arc<Mutex<Option<UserContext>>>`, which is incorrectly written to by a modern authentication middleware. While the middleware also correctly uses a `tokio::task_local` for most of the application, its write to the global state for backward compatibility creates a window for data corruption. Under concurrent load, one request's context can be overwritten in this global variable by another request before the first request's handler has finished reading from it, leading to data leakage.",
  "culprit_files": [
    {
      "file_path": "src/module_48.txt",
      "description": "This file contains the primary authentication and context-setting middleware. It correctly populates a `task_local` but also incorrectly writes the user context to a globally shared `Arc<Mutex<...>>` for a legacy component.",
      "line_number": 215
    },
    {
      "file_path": "src/module_15.txt",
      "description": "This file contains a legacy data-fetching function for the user dashboard. This function exclusively reads user context from the flawed global `Arc<Mutex<...>>` instead of the modern `task_local`, making it vulnerable to the race condition.",
      "line_number": 98
    },
    {
      "file_path": "src/utils.txt",
      "description": "This utility file contains the definition of the global static variable (`LEGACY_USER_CONTEXT: Arc<Mutex<Option<UserContext>>>`).",
      "line_number": 132
    }
  ],
  "race_condition_explanation": "1. Request A for User 'Alice' arrives on a worker thread.\n2. The middleware in `module_48.txt` authenticates Alice. It locks the global mutex, writes `Some(Alice's Context)`, and unlocks it. It then populates the `task_local` correctly.\n3. An OS or async runtime context switch occurs. Request B for User 'Bob' is scheduled on the *same* worker thread.\n4. The middleware in `module_48.txt` authenticates Bob. It locks the global mutex, writes `Some(Bob's Context)`, overwriting Alice's entry, and unlocks it.\n5. Control returns to Request A's handler, which proceeds to call the legacy dashboard data function in `module_15.txt`.\n6. The function in `module_15.txt` locks the global mutex. It reads the context, but now it reads `Some(Bob's Context)`.\n7. The function then fetches and returns dashboard data for Bob, which is then served in the HTTP response to Alice."
}
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

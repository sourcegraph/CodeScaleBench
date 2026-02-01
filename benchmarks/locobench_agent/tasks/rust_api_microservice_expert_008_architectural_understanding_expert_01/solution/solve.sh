#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The agent's response should contain the following key insights, referencing the correct (obfuscated) files:

*   **Key Component Identification**:
    *   **Caching Service**: The primary caching logic, including `get` and `set` operations, is implemented in `src/module_44.txt`, which appears to be a wrapper around a Redis client. Configuration is pulled from `src/config.txt`.
    *   **Read Handlers**: `src/module_26.txt` and `src/module_52.txt` contain handlers for `GET` requests. These handlers check for a valid cache entry in `module_44` before proceeding to query the database.
    *   **Write Handlers**: `src/module_71.txt` contains the handlers for `PUT` and `POST` requests. These handlers process incoming data, validate it, and persist it to the database.

*   **Architectural Flaw Diagnosis**:
    *   The core flaw is a lack of communication between the write and cache services. The write handlers in `src/module_71.txt` successfully update the state in the primary data store but fail to notify the caching service in `src/module_44.txt` that the data has changed. Consequently, the cache holds a stale version of the resource, which is served by the read handlers in `src/module_26.txt` until its TTL expires.

*   **Proposed Solution & Implementation Plan**:
    *   **Pattern**: The recommended pattern is explicit 'Cache-Aside' invalidation. Upon a successful write operation, the application logic is responsible for deleting the corresponding entry from the cache.
    *   **Module Modifications**:
        1.  **`src/module_44.txt` (Caching Service)**: A new public function, `invalidate(key: &str)`, must be added. This function will execute a `DEL` command on the Redis cache for the given key.
        2.  **`src/module_71.txt` (Write Handlers)**: The functions handling `PUT` and `POST` requests must be modified. After the database transaction is successfully committed, they must call the new `invalidate` function on the caching service instance. They are responsible for constructing the exact cache key that the corresponding `GET` handler in `src/module_26.txt` would use for that resource.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

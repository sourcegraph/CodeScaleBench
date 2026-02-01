#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The core of the problem lies in a flawed interaction between the versioning logic and the caching layer.

-   **Routing Logic (`module_31.txt`):** This module contains the primary request router. It parses the URL and directs traffic. For `/v1/...` requests, it calls functions in modules like `module_15.txt`. For `/v2/...` requests, it calls a specific transformation function in `module_50.txt`.

-   **V2 Transformation Logic (`module_50.txt`):** This module acts as a compatibility/transformation layer. It first calls the same underlying business logic as v1 (e.g., in `module_15.txt`) to get the raw data structure. Then, it performs a series of complex and computationally expensive operations to transform this raw structure into the new v2 API format.

-   **Caching Logic (`module_62.txt`):** This module provides a generic key-value caching service.

-   **The Architectural Flaw:** The request lifecycle for a v2 endpoint is as follows:
    1.  Request arrives and is parsed by the router in `module_31.txt`.
    2.  The router identifies it as a v2 request and calls the transformation function in `module_50.txt`.
    3.  `module_50.txt` calls the core business logic in `module_15.txt` to fetch data.
    4.  `module_50.txt` performs the **expensive data transformation** to create the v2 response body.
    5.  **Only after all this work**, the router logic in `module_31.txt` calls the caching function in `module_62.txt` to get/set the response.

    The root cause of the performance degradation is that the expensive v2 data transformation in `module_50.txt` is executed on **every single request**, regardless of whether the result is already in the cache. The cache check happens too late in the lifecycle. The correct architecture would be to check the cache first, and only if there is a cache miss, proceed with fetching and transforming the data.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

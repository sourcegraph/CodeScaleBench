#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected outcome is a set of changes that centralize the search logic.

**Key Changes:**
-   **New Files:** `src/search/SearchService.h` and `src/search/SearchService.cpp` exist.
-   **`SearchService.h`:** Contains the `SearchService` class definition with the specified `indexDocument` and `query` public methods. It also likely contains private member declarations for the inverted index and helper functions.
-   **`SearchService.cpp`:** Contains the full implementation of the `SearchService` methods, including logic for tokenizing text, updating the inverted index, and searching the index.
-   **`module_18.cpp`:** The original indexing function(s) are removed. The file now includes `search/SearchService.h` and contains a call to `SearchService::getInstance().indexDocument(...)` or a similar mechanism.
-   **`module_41.cpp`:** The original query function(s) are removed. The file now includes `search/SearchService.h` and contains a call to `SearchService::getInstance().query(...)` to fetch search results.
-   **`module_61.cpp`:** The utility functions and data structures related to the search index are removed.
-   The overall functionality of the blog's search feature remains unchanged from an end-user perspective.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

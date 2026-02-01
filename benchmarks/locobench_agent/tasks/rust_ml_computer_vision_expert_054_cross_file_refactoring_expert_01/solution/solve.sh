#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The ideal solution involves changes across 5 files.

1.  **`src/experiment_tracker.txt` (New File):** Contains the `ExperimentTracker` trait definition and the `DefaultTracker` struct which implements the trait by wrapping the `RawMetricClient`.
2.  **`src/utils.txt`:** The `RawMetricClient` struct and its `impl` are no longer `pub`. The file now contains `pub mod experiment_tracker;` at the top.
3.  **`src/module_34.txt` & `src/module_62.txt`:** All functions that previously took `client: &RawMetricClient` now have a signature like `fn some_function<T: ExperimentTracker>(..., tracker: &T, ...)`. All internal calls are updated to `tracker.log_scalar(...)` etc. There should be no remaining references to `RawMetricClient`.
4.  **`src/module_7.txt`:** The line `let client = RawMetricClient::new(...)` is replaced with `let tracker = DefaultTracker::new(...)` (or similar, depending on the constructor for `DefaultTracker`). This `tracker` instance is then passed to the functions in `module_34` and `module_62`.
5.  **`tests/test_main.txt`:** Contains a new `MockTracker` struct that implements `ExperimentTracker`. Test functions are updated to instantiate `MockTracker` and pass it to the functions under test. Assertions are made against the state of the `MockTracker` after the function call.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

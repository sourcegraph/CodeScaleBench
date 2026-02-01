#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The expected outcome is a set of changes across multiple files:

-   **New Files Created:**
    -   `src/validation/core.py`: Contains a class-based validation framework. At a minimum, it should define a base validator class and several concrete implementations (e.g., for not-null, type, regex).
    -   `src/validation/exceptions.py`: Contains a custom `ValidationError` class.

-   **Modified Files:**
    -   `src/module_19.py`: The original validation functions (e.g., `_validate_user_profile`) are removed. The code that calls them is updated to instantiate and use validators from `src/validation/core.py`. An import statement like `from validation.core import SchemaValidator, NotNullValidator` is added.
    -   `src/module_73.py`: Similar to `module_19`, its transaction validation logic is replaced with calls to the new framework. Redundant code is deleted.
    -   `src/module_30.py`: Its event validation logic is replaced with calls to the new framework. Redundant code is deleted.
    -   `src/utils.py`: Any generic validation helper functions that were identified should be removed, and their call sites throughout the project (if any beyond the three target modules) should also be updated.

-   **Code Structure Changes:**
    -   The overall line count of the project should decrease due to the removal of duplicated code.
    -   The cyclomatic complexity of the refactored modules should decrease as complex conditional validation blocks are replaced by clearer, declarative calls to the validation framework.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

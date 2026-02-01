#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The final state of the codebase should reflect a successful consolidation:

*   **File Creation:** The file `flockdesk/core/services/user_service.py` exists and contains the `UserService` class.
*   **File Deletion:** The files `flockdesk/core/services/profile_service.py` and `flockdesk/modules/presence/service.py` have been deleted from the project.
*   **Code Modification:**
    *   The new `UserService` class integrates methods for fetching profile data and managing real-time presence.
    *   Files like `chat_vm.py`, `presence_vm.py`, `presence_widget.py`, and `avatar_widget.py` have been modified to import and use `UserService` exclusively for user data needs.
    *   The service initialization/registration logic in `flockdesk/core/app.py` (or equivalent) has been updated to remove `ProfileService` and `PresenceService` and add `UserService`.
*   **Test Modification:**
    *   A new test file, `tests/unit/core/test_user_service.py` (or similar), exists and provides coverage for the new service.
    *   Existing tests that depended on the old services have been updated or removed. For instance, `tests/integration/test_profile_sync.py` is either deleted or refactored to test the new service.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

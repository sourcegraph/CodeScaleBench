#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The agent's response will be evaluated against this ground truth, which represents the hidden architecture of the system.

1.  **Core Component Identification:**
    *   `src/module_12.cpp`: This module is the core of user management. It contains the `User` class definition, functions for `createUser`, `findUserByUsername`, and critically, `verifyPassword` which involves a password hashing and salting mechanism.
    *   `src/module_35.cpp`: This module handles session management. It contains functions like `createSessionToken` (likely generating a JWT) and `validateSessionToken`, which are used to maintain user state across requests. It depends on `module_12` to get user details.

2.  **Dependency Mapping:**
    *   `src/module_23.cpp` (Request Middleware/Guard): This module inspects incoming request headers for a session token and uses `module_35::validateSessionToken` to protect application routes. It's a primary consumer of the session service.
    *   `src/module_10.cpp` (Post Manager): When creating or editing a post, this module gets the current `userId` from the validated session to assign authorship.
    *   `src/module_61.cpp` (Comment Manager): Similar to the Post Manager, this module requires a valid `userId` from the session to allow users to post comments.
    *   `src/module_7.cpp` (API Endpoint Router): This module defines the `/login` endpoint, which directly calls `module_12::verifyPassword` and `module_35::createSessionToken`.
    *   `src/module_41.cpp` (Search Functionality): The search service may have features for searching only one's own posts, which requires getting the `userId` from the current session.
    *   `src/config.cpp`: While not a module, it's a critical dependency. It holds configuration used by `module_35`, such as the JWT secret key and token expiration duration.

3.  **Decoupling Strategy:**
    *   **Define an Interface:** Propose a new abstract base class, `IAuthenticationService`, with pure virtual functions like:
        ```cpp
        class IAuthenticationService {
        public:
            virtual ~IAuthenticationService() = default;
            virtual std::optional<UserDetails> authenticate(const std::string& username, const std::string& password) = 0;
            virtual std::optional<SessionInfo> validateToken(const std::string& token) = 0;
            virtual void logout(const std::string& token) = 0;
        };
        ```
    *   **Refactor Consumers:** All dependent modules (`23`, `10`, `61`, `7`, `41`) should be refactored to hold a `std::shared_ptr<IAuthenticationService>` and call its methods instead of directly calling functions in `module_12` and `module_35`.
    *   **Implement Concrete Classes:** Create an initial `LocalAuthService` that implements `IAuthenticationService` by wrapping the existing logic from `module_12` and `module_35`. This allows for an incremental refactor. The future `SSOAuthService` would be a separate implementation that makes network calls to the external SSO service.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

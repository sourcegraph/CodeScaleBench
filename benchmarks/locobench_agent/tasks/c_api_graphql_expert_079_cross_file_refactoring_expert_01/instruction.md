# LoCoBench-Agent Task

## Overview

**Task ID**: c_api_graphql_expert_079_cross_file_refactoring_expert_01
**Category**: cross_file_refactoring
**Difficulty**: expert
**Language**: c
**Context Length**: 1000845 tokens
**Files**: 84

## Task Title

Refactor Service-Level Error Handling into a Unified Common Library Abstraction

## Description

The SynestheticCanvas API Suite currently suffers from inconsistent error handling across its various microservices (palette, texture, audio, etc.). Each service defines its own error codes and formats, which are then manually and often incompletely translated into HTTP status codes at the API Gateway. This approach is brittle, hard to maintain, and leads to inconsistent error responses for the end-user. This task involves refactoring the error handling mechanism by creating a robust, unified error abstraction in the `sc_common` library and migrating the services to use it.

## Your Task

Your goal is to centralize and standardize error handling for the entire microservice suite.

**1. Enhance the Common Error Abstraction:**
   - In `libs/sc_common/include/sc_errors.h`, define a new structured error type, `sc_error_t`. This struct should contain:
     - An integer `code` (the service-specific error code).
     - A `char* message` (a detailed, dynamically allocated error message).
     - An enumeration `sc_service_domain_t` to identify the originating service (e.g., `SC_DOMAIN_PALETTE`, `SC_DOMAIN_TEXTURE`, etc.). You will need to define this enum.
     - An integer `http_status_code` (the recommended HTTP status to return, e.g., 404, 500).
   - In `sc_errors.h` and `sc_errors.c`, create and implement factory and destructor functions for this new type:
     - `sc_error_t* sc_error_create(sc_service_domain_t domain, int code, int http_status, const char* format, ...);` (variadic for easy message formatting)
     - `void sc_error_destroy(sc_error_t* err);`

**2. Refactor Core Services:**
   - Select two services for this refactoring: `palette-service` and `texture-service`.
   - Modify the function signatures within the service and repository layers (`palette_service.c`, `palette_repository.c`, `texture_service.c`, `texture_repository.c`) that currently return an integer error code. They should now return `sc_error_t*` on failure and `NULL` on success. You will need to update the function callers accordingly.
   - Replace all instances of ad-hoc error code returns (e.g., `return -1;`) with calls to your new `sc_error_create()` factory.

**3. Update the API Gateway:**
   - Modify the `api-gateway`'s service client (`api-gateway/src/services/service_client.c`) and fallback handlers (`api-gateway/src/rest/fallback_handlers.c`) to correctly interpret the new `sc_error_t*` returned from the services.
   - The gateway should no longer rely on simple integer codes. It must now use the `http_status_code` and `message` from the `sc_error_t` struct to generate the final HTTP response to the client.

**4. Update Tests:**
   - Modify the unit tests for the refactored services (`test_palette_service.c`, `test_texture_service.c`) to reflect the new function signatures and error handling logic. Tests that previously checked for integer return values like `-1` must now check for a non-NULL `sc_error_t*` and validate its contents.

**5. Build and Verify:**
   - Ensure the entire project, including the modified services, common library, and API gateway, compiles without warnings.
   - Ensure all updated tests pass.

## Expected Approach

An expert developer would approach this systematically:

1.  **Analyze and Design (Bottom-Up):**
    - Start by examining the existing error patterns in `palette_service.c` and `texture_service.c`. Note how errors (e.g., 'not found', 'database error') are currently represented.
    - Design the `sc_service_domain_t` enum and the `sc_error_t` struct in `libs/sc_common/include/sc_errors.h`.
    - Implement the `sc_error_create` and `sc_error_destroy` functions in `libs/sc_common/src/sc_errors.c`, paying close attention to dynamic memory allocation for the message string.

2.  **Refactor one service completely (`palette-service`):**
    - Start at the lowest level, likely `palette_repository.c`. Change function signatures from `int func(...)` to `sc_error_t* func(...)` where appropriate. Update the implementation to return `sc_error_create(...)` on failure.
    - Propagate these signature changes upwards into `palette_service.c` and then to `palette_handler.c`.
    - Update `test_palette_service.c` to align with the new error handling. Assert on the fields of the returned `sc_error_t` object in failure-case tests.
    - Compile and run the tests for this service to ensure it's working in isolation before proceeding.

3.  **Refactor the second service (`texture-service`):**
    - Repeat the process for `texture-service`, modifying its repository, service, handler, and test files.

4.  **Refactor the Consumer (`api-gateway`):**
    - Modify the functions in `service_client.c` that call the microservices. They now need to handle an `sc_error_t*` instead of a simple status code.
    - Update the generic error handling logic in `fallback_handlers.c` or `router.c` to unpack the `sc_error_t` object and use its `http_status_code` and `message` to build the final response.

5.  **Final Integration and Cleanup:**
    - Perform a full build of the entire `SynestheticCanvas` project using `scripts/build.sh`.
    - Run all test suites.
    - Review all changes for memory leaks (e.g., ensuring `sc_error_destroy` is called everywhere an error is handled and not propagated further).

## Evaluation Criteria

- **Correctness & Compilation:** The entire project must compile successfully without new warnings. All modified tests must pass, and no existing functionality should be broken.
- **Abstraction Quality:** The new `sc_error_t` abstraction in `sc_common` must be well-defined, and its helper functions must be correctly implemented, especially concerning memory management (e.g., `strdup` for the message, proper `free` in the destructor).
- **Refactoring Completeness:** Both `palette-service` and `texture-service` must be fully refactored to use the new error system, from the repository layer up to the handler.
- **Gateway Integration:** The API Gateway must correctly consume the new `sc_error_t` objects, using their fields to generate appropriate and consistent HTTP responses.
- **Test Adaptation:** Unit tests for the modified services must be updated to reflect the new function signatures and properly assert on the new error struct's contents.
- **Code Consistency:** The new error handling pattern must be applied consistently across all modified files.
- **Memory Safety:** The agent must correctly manage the lifecycle of `sc_error_t` objects, creating them on error and destroying them once handled to prevent memory leaks.

## Instructions

1. Explore the codebase in `/app/project/` to understand the existing implementation
2. Use MCP tools for efficient code navigation and understanding
3. **IMPORTANT**: Write your solution to `/logs/agent/solution.md` (this path is required for verification)

Your response should:
- Be comprehensive and address all aspects of the task
- Reference specific files and code sections where relevant
- Provide concrete recommendations or implementations as requested
- Consider the architectural implications of your solution

## MCP Search Instructions (if using Sourcegraph/Deep Search)

When using MCP tools to search the codebase, you MUST specify the correct repository:

**Repository**: `sg-benchmarks/locobench-c_api_graphql_expert_079`

Example MCP queries:
- "In sg-benchmarks/locobench-c_api_graphql_expert_079, where is the main entry point?"
- "Search sg-benchmarks/locobench-c_api_graphql_expert_079 for error handling code"
- "In sg-benchmarks/locobench-c_api_graphql_expert_079, how does the authentication flow work?"

**IMPORTANT**: Always include the full repository path `sg-benchmarks/locobench-c_api_graphql_expert_079` in your MCP search queries to ensure you're searching the correct codebase.

## Output Format

**CRITICAL**: Write your complete solution to `/logs/agent/solution.md` (NOT `/app/solution.md`). Include:
- Your analysis and reasoning
- Specific file paths and code references
- Any code changes or implementations (as applicable)
- Your final answer or recommendations

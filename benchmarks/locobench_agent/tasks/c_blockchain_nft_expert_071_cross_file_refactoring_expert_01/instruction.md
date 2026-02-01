# LoCoBench-Agent Task

## Overview

**Task ID**: c_blockchain_nft_expert_071_cross_file_refactoring_expert_01
**Category**: cross_file_refactoring
**Difficulty**: expert
**Language**: c
**Context Length**: 1095933 tokens
**Files**: 85

## Task Title

Refactor Disparate Event Handling Logic into a Shared Event Dispatcher Module

## Description

The HoloCanvas system is composed of several microservices that communicate via a Kafka message bus. Currently, multiple services (governance_hall, mint_factory, muse_observer) contain duplicated, boilerplate code for consuming, deserializing, and dispatching these events. This approach is inefficient, error-prone, and makes adding new event types difficult. The goal is to refactor this functionality into a single, generic, and reusable 'Event Dispatcher' module within the `shared` library. This will centralize the event consumption loop and allow each service to simply register its specific event handlers.

## Your Task

Your task is to implement a major architectural refactoring by creating a shared event dispatcher. You must centralize the event handling logic currently duplicated across multiple services.

**Detailed Requirements:**

1.  **Create a New Shared Module:**
    *   In the `HoloCanvas/shared/` directory, create a new subdirectory named `event_dispatcher`.
    *   Inside this new directory, create two new files: `hc_event_dispatcher.h` and `hc_event_dispatcher.c`.

2.  **Define the Dispatcher Interface (`hc_event_dispatcher.h`):**
    *   Define a function pointer type for event handlers: `typedef hc_error_t (*event_handler_func_t)(const ProtobufCMessage* msg, void* user_context);`.
    *   Define an opaque struct for the event dispatcher context: `typedef struct EventDispatcher EventDispatcher;`.
    *   Declare the public API for the dispatcher:
        *   `EventDispatcher* event_dispatcher_create(const char* kafka_brokers, const char* topic, const char* group_id, void* user_context);`
        *   `hc_error_t event_dispatcher_register_handler(EventDispatcher* dispatcher, const char* event_type_key, event_handler_func_t handler);`
        *   `void event_dispatcher_run(EventDispatcher* dispatcher);` (This will contain the main consumption loop).
        *   `void event_dispatcher_destroy(EventDispatcher* dispatcher);`

3.  **Implement the Dispatcher Logic (`hc_event_dispatcher.c`):**
    *   Implement the functions declared in the header.
    *   The implementation should use a hash map or a similar data structure to store the mapping from `event_type_key` strings to `event_handler_func_t` function pointers.
    *   The `event_dispatcher_run` function must encapsulate the logic for connecting to Kafka (using the existing `hc_kafka` client), consuming messages in a loop, deserializing the message (assuming a generic wrapper proto with an `event_type` field), looking up the handler in the registry, and invoking it with the message payload and user context.

4.  **Refactor Consumer Services:**
    *   Modify the following services to use the new event dispatcher: `governance_hall`, `mint_factory`, and `muse_observer`.
    *   **In each service's `main.c`:**
        *   Remove the existing Kafka connection and consumption loop.
        *   Instantiate the new `EventDispatcher` using `event_dispatcher_create()`.
        *   Register all service-specific event handlers using `event_dispatcher_register_handler()`.
        *   Start the event processing by calling `event_dispatcher_run()`.
        *   Ensure `event_dispatcher_destroy()` is called on shutdown.
    *   **In each service's event handling file (`governance_hall/src/event_handler.c`, `mint_factory/src/event_handler.c`, `muse_observer/src/event_listener.c`):**
        *   Remove the main dispatching function (e.g., the large `switch` statement that routes events).
        *   Ensure the individual handler functions (e.g., `handle_proposal_created`, `handle_artifact_minted`) are modified to match the `event_handler_func_t` signature and are made visible to `main.c` (i.e., not `static` if they were before, and declared in a local header if necessary).

5.  **Update Build System:**
    *   Modify `HoloCanvas/shared/CMakeLists.txt` to include the new `event_dispatcher` source files in the `shared_lib` target.
    *   Verify that the `CMakeLists.txt` files for `governance_hall`, `mint_factory`, and `muse_observer` correctly link against the `shared_lib`.

## Expected Approach

An expert developer would approach this systematically:

1.  **Analysis & Interface Design:** First, inspect the event handling logic in `governance_hall/src/event_handler.c`, `mint_factory/src/event_handler.c`, and `muse_observer/src/event_listener.c` to identify the common pattern: a Kafka consumer loop, message deserialization, a large switch/if-else block on an event type field, and delegation to a specific function. Based on this, they would design the clean, generic interface in `hc_event_dispatcher.h`.

2.  **Implement the Core Abstraction:** Implement the `hc_event_dispatcher.c` module. This is the core of the task. They would likely use a robust hash map implementation for the handler registry. The `event_dispatcher_run` function would be carefully crafted to handle the consumer loop, error conditions, and graceful shutdown.

3.  **Incremental Refactoring:** Refactor one service at a time. For example, start with `governance_hall`:
    *   Update `governance_hall/src/main.c` to use the new dispatcher API. This involves creating the dispatcher, registering handlers, and starting the run loop.
    *   Modify `governance_hall/src/event_handler.c`, removing the dispatch logic and adapting the handler function signatures. This might require creating a small internal header file for the service to declare the handler functions for `main.c`.
    *   Update `governance_hall/CMakeLists.txt` to ensure it links correctly.

4.  **Repeat and Verify:** Repeat the refactoring process for `mint_factory` and `muse_observer`.

5.  **Build System Finalization:** Update the `shared/CMakeLists.txt` to include the new `event_dispatcher` source files. This step is crucial for the entire project to compile.

6.  **Review and Cleanup:** After all services are migrated, review the changes for consistency, proper memory management (especially in `event_dispatcher_create/destroy`), and clarity. The developer would ensure that the core business logic inside the individual handler functions remains untouched.

## Evaluation Criteria

- **Correctness of Abstraction:** The created `hc_event_dispatcher` API must be generic, reusable, and correctly designed with an opaque struct and function pointers.
- **Completeness of Refactoring:** All three specified services (`governance_hall`, `mint_factory`, `muse_observer`) must be successfully refactored to use the new dispatcher.
- **Code Removal:** The agent must correctly identify and remove the duplicated Kafka consumption and event dispatching logic from the services' `main.c` and `event_handler.c`/`event_listener.c` files.
- **Build System Integrity:** The `CMakeLists.txt` files for both the `shared` library and the affected services must be updated correctly, allowing the project to compile without errors.
- **Non-Regression of Logic:** The core business logic inside the individual handler functions (e.g., the logic that processes a `PROPOSAL_CREATED` event) must be preserved and correctly integrated with the new handler signature.
- **File System Manipulation:** The agent must correctly create new files and directories and modify existing files across the project structure as required.
- **Resource Management:** The implementation of `hc_event_dispatcher.c` must demonstrate proper memory and resource management (e.g., freeing the dispatcher context, the handler registry, and closing Kafka handles).

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

**Repository**: `sg-benchmarks/locobench-c_blockchain_nft_expert_071`

Example MCP queries:
- "In sg-benchmarks/locobench-c_blockchain_nft_expert_071, where is the main entry point?"
- "Search sg-benchmarks/locobench-c_blockchain_nft_expert_071 for error handling code"
- "In sg-benchmarks/locobench-c_blockchain_nft_expert_071, how does the authentication flow work?"

**IMPORTANT**: Always include the full repository path `sg-benchmarks/locobench-c_blockchain_nft_expert_071` in your MCP search queries to ensure you're searching the correct codebase.

## Output Format

**CRITICAL**: Write your complete solution to `/logs/agent/solution.md` (NOT `/app/solution.md`). Include:
- Your analysis and reasoning
- Specific file paths and code references
- Any code changes or implementations (as applicable)
- Your final answer or recommendations

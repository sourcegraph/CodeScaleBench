#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
The solution is correct if the agent successfully creates the new shared module and refactors the specified services. Key indicators of a correct solution include:

*   **New Files Created:** `HoloCanvas/shared/event_dispatcher/hc_event_dispatcher.h` and `HoloCanvas/shared/event_dispatcher/hc_event_dispatcher.c` exist and are populated.

*   **Key Code Snippet in `hc_event_dispatcher.h`:**
    ```c
    // HoloCanvas/shared/event_dispatcher/hc_event_dispatcher.h
    #include "shared/common/errors.h"
    #include <protobuf-c/protobuf-c.h>

    typedef struct EventDispatcher EventDispatcher;

    typedef hc_error_t (*event_handler_func_t)(const ProtobufCMessage* msg, void* user_context);

    EventDispatcher* event_dispatcher_create(const char* kafka_brokers, const char* topic, const char* group_id, void* user_context);
    hc_error_t event_dispatcher_register_handler(EventDispatcher* dispatcher, const char* event_type_key, event_handler_func_t handler);
    void event_dispatcher_run(EventDispatcher* dispatcher);
    void event_dispatcher_destroy(EventDispatcher* dispatcher);
    ```

*   **Example of Refactored `main.c` (e.g., `governance_hall/src/main.c`):**
    ```c
    // HoloCanvas/services/governance_hall/src/main.c (Conceptual Change)
    #include "shared/event_dispatcher/hc_event_dispatcher.h"
    #include "governance.h" // Assumed to declare handlers like handle_proposal_created, etc.

    int main(int argc, char **argv) {
        // ... initial setup ...
        GovernanceState* state = initialize_governance_state();
        
        EventDispatcher* dispatcher = event_dispatcher_create("kafka:9092", "governance_topic", "governance_group", state);
        if (!dispatcher) { /* handle error */ }

        event_dispatcher_register_handler(dispatcher, "PROPOSAL_CREATED", handle_proposal_created_event);
        event_dispatcher_register_handler(dispatcher, "VOTE_CAST", handle_vote_cast_event);
        // ... register other handlers ...

        printf("Starting Governance Hall event dispatcher...\n");
        event_dispatcher_run(dispatcher);

        printf("Shutting down...\n");
        event_dispatcher_destroy(dispatcher);
        destroy_governance_state(state);
        return 0;
    }
    ```

*   **Removal of Logic:** The large `switch` statement for routing events based on type is no longer present in `governance_hall/src/event_handler.c`, `mint_factory/src/event_handler.c`, etc.

*   **`CMakeLists.txt` Modification:** `HoloCanvas/shared/CMakeLists.txt` should be updated:
    ```cmake
    # In shared/CMakeLists.txt
    set(SHARED_SOURCES
        common/types.c
        common/errors.c
        kafka_client/hc_kafka.c
        crypto_wrapper/hc_crypto.c
        event_dispatcher/hc_event_dispatcher.c # <-- ADDED LINE
    )
    ```
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

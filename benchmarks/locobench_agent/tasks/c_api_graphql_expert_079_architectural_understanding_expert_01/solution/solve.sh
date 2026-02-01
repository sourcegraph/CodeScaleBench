#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Key Component Identification
- **Shared IPC Library:** `libs/sc_ipc/src/sc_ipc.c` and its header.
- **Gateway Client:** `api-gateway/src/services/service_client.c` is the primary consumer of `sc_ipc` for making outbound requests to services.
- **Service Servers:** The `main()` function in each microservice's `main.c` (e.g., `services/texture-service/src/main.c`, `services/palette-service/src/main.c`) is responsible for initializing the `sc_ipc` server and entering a request-handling loop.
- **Configuration:** Service addresses and ports for the IPC are managed via `libs/sc_common/sc_config.c` and the respective `*.toml.example` files.
- **Build System:** `CMakeLists.txt` in the root, gateway, and all services would need modification.

### Migration Strategy Insights
- **Phased Rollout is Critical:** The most viable strategy is to not replace `sc_ipc` in one go. The `texture-service` should be updated to run both the legacy IPC server and a new gRPC server, listening on different ports.
- **Configuration-Driven Switching:** The API Gateway should be updated to support both communication clients. The choice of which client to use for a specific service (e.g., `texture-service`) should be driven by a configuration value loaded via `sc_config`. This allows for flipping the switch in production without a redeployment of the gateway.
- **Contract First:** The first step is to define the service contract in a `.proto` file (e.g., `texture.proto`), which then generates the C++ stubs to be integrated into the C project (often via C-compatible wrapper functions).

### Key Risks
- **Build System Hell:** Integrating gRPC and Protobuf dependencies into a mature C/CMake project is notoriously difficult and a primary risk. It involves managing transitive dependencies and compiler flags correctly.
- **Performance Regression:** The existing `sc_ipc` is likely a highly optimized, raw TCP protocol. gRPC, while very fast, adds layers of abstraction (HTTP/2, Protobuf serialization) that could introduce latency or CPU overhead. Performance testing is mandatory.
- **Operational Complexity:** During the transition, the team must monitor and manage two different communication systems. This increases cognitive load, complicates debugging, and requires more sophisticated monitoring.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### Architectural Analysis of Scan Latency Issue

**1. On-Demand Scan Request Lifecycle**

The lifecycle of an on-demand scan request is as follows:

-   **API Gateway**: A request hits the public endpoint defined in `api/v1/openapi.yaml`. The `api_gateway` service (`src/services/api_gateway/server.cpp`) receives this request.
-   **Orchestration**: The gateway doesn't perform the scan itself. It creates a `ScanCommand` (`lib/domain/commands/scan_command.h`) and passes it to the `CommandHandler` (`lib/orchestration/command_handler.cpp`).
-   **Strategy & Dispatch**: The `CommandHandler` uses a factory or strategy selector to apply the correct logic based on the tenant's subscription type, such as the `PaygScanStrategy`. Following validation, it publishes a `ScanRequested` event to the system's event bus. This is consistent with the event-driven design outlined in `docs/architecture/adr/002-event-driven-architecture.md`.
-   **Consumption & Execution**: The `scanner_svc` is the consumer of this event. Its `EventConsumer` (`lib/infrastructure/event_bus/event_consumer.cpp`) receives the message and forwards the job to the `ScannerEngine` (`src/services/scanner_svc/scanner_engine.cpp`).
-   **Execution**: The `ScannerEngine` is responsible for performing the actual security scan.

**2. Architectural Interference and Root Cause**

The primary architectural weakness is the **lack of Quality of Service (QoS) and workload isolation within the `scanner_svc`**. 

-   **Shared Resource Contention**: The `scanner_svc` handles scans for *all* tenant types. Both high-volume, low-urgency 'Continuous Scans' and low-volume, high-urgency on-demand 'PAYG' scans are processed by the same `ScannerEngine`.
-   **Head-of-Line Blocking**: The implementation in `src/services/scanner_svc/scanner_engine.cpp` reveals that it uses a single, non-prioritized FIFO (First-In, First-Out) work queue to manage scan jobs. When 'Continuous Scan' tenants generate a large backlog of background tasks, new, time-sensitive on-demand requests from 'PAYG' tenants are simply added to the end of this queue. They are forced to wait for all preceding background tasks to complete.

**3. Conclusion**

The reported latency is not due to a fault in a single component but a systemic architectural issue. The system's design fails to differentiate between different classes of work at the execution layer. This creates a "noisy neighbor" problem where the background workload of one class of tenants directly degrades the interactive performance for another. The core flaw is the naive, non-prioritized queuing mechanism in the `ScannerEngine`, making it the architectural bottleneck.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

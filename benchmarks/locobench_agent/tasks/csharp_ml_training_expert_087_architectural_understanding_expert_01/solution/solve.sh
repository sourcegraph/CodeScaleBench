#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
### 1. Analysis of Current State
The current system is a modular monolith. The `ServingController` handles prediction requests and publishes a `ModelPredictionQueriedEvent` to a RabbitMQ message bus. Within the same process, the `CanvasCraft.Monitoring` module runs as a background service, subscribed to this message bus. It uses an internal Observer pattern (`ModelServingSubject` notifying `DataDriftObserver` and `PerformanceFadeObserver`). When these observers detect an issue, they publish a new event (e.g., `RetrainingRequiredEvent`) back to RabbitMQ. The `AutomatedRetrainingTrigger` in the `CanvasCraft.Pipeline` module subscribes to this event to initiate a new training pipeline.

### 2. Proposed Microservice Architecture

a. **Communication Strategy:** The communication will be fully asynchronous using the existing RabbitMQ message bus. This aligns with `ADR-002` and ensures loose coupling and independent scalability. The main application will be the producer of prediction events, and the new `MonitoringService` will be the consumer. The `MonitoringService` will, in turn, become a producer of `RetrainingRequiredEvent`s.

b. **Data Flow:**
   1. `CanvasCraft.Api` receives a prediction request and publishes `ModelPredictionQueriedEvent` to a RabbitMQ topic.
   2. The new standalone `MonitoringService` is the sole subscriber to this topic.
   3. The `MonitoringService` processes the event, updates its internal state, and runs its drift/fade detection logic.
   4. If a significant event is detected, the `MonitoringService` publishes a `RetrainingRequiredEvent` to a different RabbitMQ topic.
   5. The `AutomatedRetrainingTrigger` within the main application's `CanvasCraft.Pipeline` module subscribes to this `RetrainingRequiredEvent` topic and initiates the retraining pipeline.

### 3. Implementation & Refactoring Plan

a. **Code Changes:**
   - **`CanvasCraft.Api/Startup.cs`**: Remove dependency injection registration for all services from the `CanvasCraft.Monitoring` project.
   - **`CanvasCraft.sln` & Project Files**: Remove the `CanvasCraft.Monitoring` project reference from the solution and any project that references it.
   - **`CanvasCraft.Pipeline/Triggers/AutomatedRetrainingTrigger.cs`**: Ensure its message bus subscription logic is robust enough to handle events from an external service. No significant change is likely needed if it's already using `IMessageBus`.
   - **`CanvasCraft.Api/Controllers/MonitoringController.cs`**: This controller, if used for querying monitoring status, must be refactored. Its GET endpoints should be moved to the new microservice. The main API could optionally act as a proxy to the new service's API for a unified front-end experience.

b. **New Components:**
   - A new C# solution and project for `MonitoringService` will be created, containing all the code from the original `CanvasCraft.Monitoring` project.
   - It will have its own `Program.cs`/`Startup.cs` to register its services and configure the RabbitMQ listener.
   - It will expose a minimal REST API for health checks and to allow manual querying of drift/performance status.

c. **Deployment (`docker-compose.yml`):**
   A new service definition must be added:
   ```yaml
   services:
     # ... existing services (api, db, rabbitmq)
     monitoring-service:
       image: canvascraft-monitoring-service
       build:
         context: .
         dockerfile: src/MonitoringService/Dockerfile # New Dockerfile for the service
       depends_on:
         - rabbitmq
         - db
       environment:
         - RabbitMq__HostName=rabbitmq
         - ConnectionStrings__DefaultConnection=...
       networks:
         - canvascraft-net
   ```
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"

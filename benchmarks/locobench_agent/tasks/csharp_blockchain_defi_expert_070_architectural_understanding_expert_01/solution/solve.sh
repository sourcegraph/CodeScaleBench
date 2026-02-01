#!/bin/bash
# Oracle solution script for LoCoBench-Agent tasks
# Outputs the ground truth answer to /app/solution.md

# Read the ground truth from the tests directory
# Harbor uploads tests to /tests at verification time
# For oracle agent, we write the expected answer to solution.md

cat > /app/solution.md << 'GROUND_TRUTH_EOF'
A successful solution will be a well-structured Markdown document (`PROPOSAL.md`) that contains the following key insights:

*   **Affected Components:** `TransactionProcessor`, `StakingService`, `GovernanceService`, `P2PService`, and `ApiGateway` are the primary stakeholders. The proposal should note that every component using `IEventBus` is affected.
*   **Data Consistency Solution:** The proposal MUST identify the loss of atomicity as the primary challenge. The gold-standard solution presented should be the **Transactional Outbox Pattern**. A naive solution that simply replaces the bus implementation without addressing this consistency gap is incorrect.
*   **Configuration Example (`appsettings.json`):**
    ```json
    "MessageBroker": {
      "HostName": "rabbitmq.utilitychain.net",
      "UserName": "user",
      "Password": "password",
      "ExchangeName": "utilitychain_events"
    }
    ```
*   **DI Changes (`Startup.cs`):** The report must show the change from `services.AddSingleton<IEventBus, InMemoryEventBus>();` to something like `services.AddSingleton<IEventBus, RabbitMqEventBus>();` and also show the registration of the outbox poller service: `services.AddHostedService<OutboxProcessorService>();`.
*   **Resilience Strategy:** The proposal must explicitly recommend using **Dead-Letter Queues (DLQs)** to handle messages that repeatedly fail processing, preventing poison messages from halting the system. It should also recommend **configurable retry policies with exponential backoff** for transient errors like network hiccups when connecting to the broker.
*   **Trade-off Analysis:** The analysis must be balanced. It should praise the move for enabling scalability, fault isolation, and independent deployments. Critically, it must also acknowledge the costs: increased operational overhead (managing a message broker cluster), introduction of network latency for inter-service calls, and the added complexity of ensuring eventual consistency.
GROUND_TRUTH_EOF

echo "Oracle solution written to /app/solution.md"
